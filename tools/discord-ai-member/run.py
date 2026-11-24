"""discord-ai-member の runner。

受け口（worker.js）から repository_dispatch で起こされ、Discord の /ai の質問に
Claude Agent SDK（コモンズのプラグイン入り）で答えて、「考え中…」を答えに書き換える。

公開リポジトリでも動かすので、質問・答え・チャンネルの中身は実行ログに出さない。
ログと実行ページの記録には、費用・使ったスキルなどの数字だけを残す。

環境変数
  PAYLOAD            … 受け口から渡された JSON（question, application_id, token, channel_id, user_name など）
  ANTHROPIC_API_KEY  … Claude の API キー（キーの持ち主に請求される）
  MEMBER_DIR         … このコモンズの設定フォルダ（config.json と member.md）
  PLUGIN_ROOTS       … プラグインを読む場所。plugins/ を持つフォルダを「:」区切りで。先のものが優先
  DISCORD_BOT_TOKEN  … （任意）あれば、チャンネルの直近のやりとりを読んで文脈にする
  WORK_DIR           … 作業場所（既定は RUNNER_TEMP）
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import requests

API = "https://discord.com/api/v10"
MAX_LEN = 1900  # Discord の1メッセージは2000字まで
FAIL_TEXT = "うまく返事を作れませんでした。少し言い方を変えて、もう一度 /ai で聞いてください。"


def mask(value: str) -> None:
    """GitHub Actions のログで伏せ字にする。"""
    if value:
        print(f"::add-mask::{value}")


def split_text(text: str) -> list[str]:
    """2000字の制限に合わせて、段落の切れ目でなるべく分ける。"""
    chunks, cur = [], ""
    for para in text.split("\n"):
        while len(para) > MAX_LEN:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(para[:MAX_LEN])
            para = para[MAX_LEN:]
        if len(cur) + len(para) + 1 > MAX_LEN:
            chunks.append(cur)
            cur = para
        else:
            cur = f"{cur}\n{para}" if cur else para
    if cur:
        chunks.append(cur)
    return chunks or [""]


def post_answer(p: dict, text: str) -> None:
    """「考え中…」を答えの1つ目に書き換え、続きは追いメッセージにする。"""
    base = f"{API}/webhooks/{p['application_id']}/{p['token']}"
    no_ping = {"parse": []}  # @everyone などで人を呼ばない
    chunks = split_text(text)
    r = requests.patch(f"{base}/messages/@original", json={"content": chunks[0], "allowed_mentions": no_ping}, timeout=30)
    r.raise_for_status()
    for c in chunks[1:]:
        requests.post(base, json={"content": c, "allowed_mentions": no_ping}, timeout=30).raise_for_status()


def recent_messages(channel_id: str, limit: int) -> str:
    """チャンネルの直近のやりとりを、古い順の文字にする（ボットの鍵があるときだけ）。"""
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not (token and channel_id and limit):
        return ""
    try:
        r = requests.get(
            f"{API}/channels/{channel_id}/messages",
            params={"limit": limit},
            headers={"Authorization": f"Bot {token}"},
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"チャンネルを読めなかった: {type(e).__name__}")
        return ""
    lines = []
    for m in reversed(r.json()):
        a = m.get("author", {})
        who = (m.get("member") or {}).get("nick") or a.get("global_name") or a.get("username") or "?"
        if m.get("content"):
            lines.append(f"{who}：{m['content']}")
    return "\n".join(lines)


def plugin_dirs(roots: list[Path], exclude: list[str]) -> tuple[list[dict], dict]:
    """plugins/ の下のプラグインを集める。同じ名前は先の場所のものを使う。"""
    seen, dirs, origins = set(), [], {}
    for root in roots:
        pdir = root / "plugins"
        if not pdir.is_dir():
            print(f"プラグインの場所が見つからない: {root.name}")
            continue
        for p in sorted(pdir.iterdir()):
            if not (p / "skills").is_dir() or p.name in seen or p.name in exclude:
                continue
            seen.add(p.name)
            dirs.append({"type": "local", "path": str(p)})
            for sk in (p / "skills").glob("*/SKILL.md"):
                origins[f"{p.name}:{sk.parent.name}"] = root.name
    return dirs, origins


def build_system_prompt(member_md: str, user_name: str) -> str:
    person = f"\n\n## いま話しかけている人\n名前：{user_name}\n" if user_name else ""
    rules = """

## Discord で返事をするときの決まり
- 返事は Discord のメッセージとしてそのまま投稿される。Markdown（太字、箇条書き、リンク）は使える。表は崩れるので使わない
- 結論を1行目に書く。前置き・仕事ぶりの実況（「確認しました」など）は書かない
- 3行を超える返事は、書く前に core:writing-for-humans を読んで従う
- 分からないことは推測で埋めない。調べて分からなければ、そう書く
- ここは複数の事業者が集まる場所。ほかの事業者の事業データ（人名、金額、口座、住所、取引先）は書かない
- 最後の出力が、そのまま返事として投稿される"""
    return member_md + person + rules


async def run_agent(prompt: str, system_prompt: str, config: dict, plugins: list[dict], work: Path) -> tuple[str, dict]:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        SystemMessage,
        ToolUseBlock,
        query,
    )

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": system_prompt},
        model=config.get("model", "claude-sonnet-5-5"),
        plugins=plugins,
        skills="all",
        allowed_tools=["Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite"],
        disallowed_tools=["Edit", "Write", "NotebookEdit"],
        # allowed_tools に無い道具（Bash など）は聞かずに断る。
        # 環境変数に鍵があるので、メッセージに紛れた指示でシェルを叩かれないようにする
        permission_mode="dontAsk",
        max_turns=config.get("max_turns", 30),
        max_budget_usd=config.get("max_budget_usd", 0.5),
        cwd=str(work),
        setting_sources=[],
    )
    answer, info = "", {}
    loaded, tools, skills = [], [], []
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            loaded = list(msg.data.get("skills") or [])
        elif isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, ToolUseBlock):
                    tools.append(block.name)
                    if block.name == "Skill":
                        skills.append(str(block.input.get("skill") or block.input.get("command") or ""))
        elif isinstance(msg, ResultMessage):
            answer = msg.result or ""
            info = {"cost_usd": msg.total_cost_usd, "turns": msg.num_turns, "usage": msg.usage,
                    "is_error": msg.is_error, "subtype": msg.subtype}
    info.update(loaded_skills=len(loaded), skills_used=skills, tools_used=tools)
    return answer.strip(), info


def write_summary(info: dict, config: dict, origins: dict) -> None:
    """実行ページに、数字だけの記録を残す（質問・答えの中身は残さない）。"""
    tools: dict[str, int] = {}
    for t in info.get("tools_used", []):
        tools[t] = tools.get(t, 0) + 1
    usage = info.get("usage") or {}
    skills = "、".join(f"{s}（{origins.get(s, '?')}）" for s in info.get("skills_used") or []) or "なし"
    lines = [
        f"### {config.get('name', 'AI')} の返事（Discord）",
        "",
        "| 項目 | 値 |",
        "|:--|:--|",
        f"| 費用 | {info.get('cost_usd') or 0:.4f} ドル |",
        f"| 往復 | {info.get('turns')} 回 |",
        f"| 出力 | {usage.get('output_tokens', 0)} |",
        f"| 読み込んだスキル数 | {info.get('loaded_skills', 0)} |",
        f"| 使ったスキル | {skills} |",
        f"| 使った道具 | {'、'.join(f'{k}×{v}' for k, v in tools.items()) or 'なし'} |",
        "",
    ]
    print("\n".join(lines))
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")


def main() -> int:
    p = json.loads(os.environ["PAYLOAD"])
    mask(p.get("token", ""))
    member_dir = Path(os.environ["MEMBER_DIR"])
    config = json.loads((member_dir / "config.json").read_text())
    member_md = (member_dir / "member.md").read_text()
    work = Path(os.environ.get("WORK_DIR") or os.environ.get("RUNNER_TEMP") or "/tmp") / "discord-ai"
    work.mkdir(parents=True, exist_ok=True)

    question = (p.get("question") or "").strip()
    if not question:
        post_answer(p, "聞きたいことを `/ai` のあとに書いてください。")
        return 0

    roots = [Path(x) for x in os.environ.get("PLUGIN_ROOTS", "").split(":") if x]
    plugins, origins = plugin_dirs(roots, config.get("exclude_plugins", []))
    history = recent_messages(p.get("channel_id", ""), config.get("history_messages", 20))
    prompt = (
        f"Discord のサーバー「{config.get('community', 'コモンズ')}」で、"
        f"{p.get('user_name') or '参加者'}さんが /ai で質問しました。{config.get('name', 'AI')}として答えてください。\n\n"
        + (f"参考：このチャンネルの直近のやりとり（古い順）\n---\n{history}\n---\n\n" if history else "")
        + f"質問：{question}"
    )
    system_prompt = build_system_prompt(member_md, p.get("user_name", ""))

    answer, info = asyncio.run(run_agent(prompt, system_prompt, config, plugins, work))
    write_summary(info, config, origins)
    header = f"> {question[:300]}\n\n"  # 何への答えかが見えるように、質問を引用で添える
    post_answer(p, header + (answer or FAIL_TEXT))
    return 0


def fail() -> int:
    """runner が途中で落ちたとき、「考え中…」のまま残らないようにする。"""
    p = json.loads(os.environ["PAYLOAD"])
    mask(p.get("token", ""))
    try:
        post_answer(p, FAIL_TEXT)
    except requests.RequestException as e:
        print(f"失敗の知らせを書けなかった: {type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(fail() if "--fail" in sys.argv else main())
