"""discord-ai-member の runner。

受け口（worker.js）から repository_dispatch で起こされ、Discord の /ai の質問に
Claude Agent SDK（コモンズのプラグイン入り）で答えて、「考え中…」を答えに書き換える。

公開リポジトリでも動かすので、質問・答え・チャンネルの中身は実行ログに出さない。
ログと実行ページの記録には、費用・使ったスキルなどの数字だけを残す。

環境変数
  PAYLOAD            … 受け口から渡された JSON（question, application_id, token, channel_id, user_name など）
  ANTHROPIC_API_KEY  … Claude の API キー（キーの持ち主に請求される）
  MEMBER_DIR         … このコモンズの設定フォルダ（config.json・member.md・memory.md）
  PLUGIN_ROOTS       … プラグインを読む場所。plugins/ を持つフォルダを「:」区切りで。先のものが優先
  DISCORD_BOT_TOKEN  … （任意）あれば、チャンネルの直近のやりとりを読んで文脈にする
  WORK_DIR           … 作業場所（既定は RUNNER_TEMP）
"""

from __future__ import annotations

import asyncio
import json
import os
import re
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
    """答えを書く。/ai なら「考え中…」を書き換え、メンションなら元の発言への返信として書く。"""
    no_ping = {"parse": []}  # @everyone などで人を呼ばない
    chunks = split_text(text)
    if not p.get("token"):
        # メンションから来たとき（中継の discord-mention）。合鍵が無いので、ボットの鍵で返信する
        h = {"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}"}
        for i, c in enumerate(chunks):
            body = {"content": c, "allowed_mentions": no_ping}
            if i == 0 and p.get("message_id"):
                body["message_reference"] = {"message_id": p["message_id"], "fail_if_not_exists": False}
            requests.post(f"{API}/channels/{p['channel_id']}/messages", headers=h, json=body, timeout=30).raise_for_status()
        return
    base = f"{API}/webhooks/{p['application_id']}/{p['token']}"
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


def build_system_prompt(member_md: str, user_name: str, memory_md: str = "") -> str:
    person = f"\n\n## いま話しかけている人\n名前：{user_name}\n" if user_name else ""
    rules = """

## Discord で返事をするときの決まり
- 返事は Discord のメッセージとしてそのまま投稿される。Markdown（太字、箇条書き、リンク）は使える。表は崩れるので使わない
- 結論を1行目に書く。前置き・仕事ぶりの実況（「確認しました」など）は書かない
- 3行を超える返事は、書く前に core:writing-for-humans を読んで従う
- 分からないことは推測で埋めない。調べて分からなければ、そう書く
- ここは複数の事業者が集まる場所。ほかの事業者の事業データ（人名、金額、口座、住所、取引先）は書かない
- 最後の出力が、そのまま返事として投稿される
- コモンズの GitHub（commons-ground/ground・winegrowers）の Issue・プルリクエスト・実行の記録は、`gh issue view 番号 -R commons-ground/ground` のように読める（読むだけ。書くコマンドは使えない）
- スキルや仕組みを「直して」「こうしたい」と頼まれたら、何をどう直すか・なぜかを1〜3行で、返事の最後に「〔提案〕（1行）」として書く。この行は #提案 に回り、篩がプルリクエストにして、門番の点検を通れば入る（おかしければ「取り下げて」で戻る）。自分で直したとは書かない
- 次の自分（GitHub の自分も含む）が知っておくべきこと（人に直されたこと、コモンズで決まったこと、次から気をつけること）が出たら、返事の最後に「〔覚えておく〕（1行）」と書く。この行は Discord には出ず、裏で「覚えておく候補」に入り、人が確かめてから覚えていることに入る。その場かぎりの話、事業データ、推測、「見つからなかった・できなかった」という自分の限界は書かない"""
    memory = f"\n\n{memory_md}" if memory_md.strip() else ""
    return member_md + memory + person + rules


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
        allowed_tools=["Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", *GH_READ],
        disallowed_tools=["Edit", "Write", "NotebookEdit"],
        # allowed_tools に無い道具（Bash など）は聞かずに断る。GitHub は読むコマンドだけ（GH_READ）。
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
    # 覚えていること（GitHub の AI と共通。やりとりから育つ）
    memory_path = member_dir / "memory.md"
    memory_md = memory_path.read_text() if memory_path.exists() else ""
    work = Path(os.environ.get("WORK_DIR") or os.environ.get("RUNNER_TEMP") or "/tmp") / "discord-ai"
    work.mkdir(parents=True, exist_ok=True)

    question = (p.get("question") or "").strip()
    if not question:
        post_answer(p, "聞きたいことを `/ai` のあと（またはメンションのあと）に書いてください。")
        return 0

    roots = [Path(x) for x in os.environ.get("PLUGIN_ROOTS", "").split(":") if x]
    plugins, origins = plugin_dirs(roots, config.get("exclude_plugins", []))
    history = recent_messages(p.get("channel_id", ""), config.get("history_messages", 20))
    prompt = (
        f"Discord のサーバー「{config.get('community', 'コモンズ')}」で、"
        f"{p.get('user_name') or '参加者'}さんが {'メンション' if p.get('command') == 'mention' else '/ai'} で質問しました。{config.get('name', 'AI')}として答えてください。\n\n"
        + (f"参考：このチャンネルの直近のやりとり（古い順）\n---\n{history}\n---\n\n" if history else "")
        + f"質問：{question}"
    )
    system_prompt = build_system_prompt(member_md, p.get("user_name", ""), memory_md)

    answer, info = asyncio.run(run_agent(prompt, system_prompt, config, plugins, work))
    write_summary(info, config, origins)
    answer = keep_memory_quietly(answer, p)
    answer = hand_to_sieve(answer, p)
    # 何への答えかが見えるように、質問を引用で添える（メンションは元の発言への返信になるので要らない）
    header = "" if p.get("command") == "mention" else f"> {question[:300]}\n\n"
    post_answer(p, header + (answer or FAIL_TEXT))
    return 0


# GitHub を読むコマンドだけ許す（書くのは篩に任せる。Discord の発言から直接リポジトリを書き換えない）
GH_READ = [f"Bash(gh {c}:*)" for c in (
    "issue list", "issue view", "pr list", "pr view", "pr diff", "pr checks",
    "search issues", "search prs", "search code", "run list", "run view", "release list",
)]
PROPOSAL_MARK = re.compile(r"^\s*[〔\[]提案[〕\]]\s*(.+)$")


def hand_to_sieve(answer: str, p: dict) -> str:
    """返事の「〔提案〕」の行を外し、#提案 に「拾った候補」として流す（中継が見つけて篩に渡す）。
    返事には、回したことだけを1行で残す。"""
    keep, props = [], []
    for line in answer.splitlines():
        m = PROPOSAL_MARK.match(line)
        if m:
            props.append(m.group(1).strip())
        else:
            keep.append(line)
    if not props:
        return answer
    token, guild = os.environ.get("DISCORD_BOT_TOKEN", ""), p.get("guild_id", "")
    posted = False
    if token and guild:
        h = {"Authorization": f"Bot {token}"}
        try:
            chans = requests.get(f"{API}/guilds/{guild}/channels", headers=h, timeout=30).json()
            ch = next((c for c in chans if c.get("name") == os.environ.get("PROPOSAL_CHANNEL", "提案")), None)
            if ch:
                link = ""
                if p.get("channel_id") and p.get("message_id"):
                    link = f"\n元の発言：https://discord.com/channels/{guild}/{p['channel_id']}/{p['message_id']}"
                body = "〔提案〕（コモンズのAIが会話から拾った候補）\n" + "\n".join(f"- {x}" for x in props) + link
                requests.post(f"{API}/channels/{ch['id']}/messages", headers=h,
                              json={"content": body[:1900], "allowed_mentions": {"parse": []}}, timeout=30).raise_for_status()
                posted = True
        except requests.RequestException as e:
            print(f"提案を流せなかった: {type(e).__name__}")
    note = "🧺 直す案を #提案 に回したよ。ふるいにかけてプルリクエストになるはず" if posted else "（直す案を #提案 に回せなかったので、`/propose` で出してね）"
    return ("\n".join(keep).strip() + "\n\n" + note).strip()


MEMORY_MARK = re.compile(r"^\s*[〔\[]覚えておく[〕\]]\s*(.+)$")


def keep_memory_quietly(answer: str, p: dict) -> str:
    """返事から「〔覚えておく〕」の行を外し、候補のファイルに書く（Discord には出さない）。
    候補は workflow の次の段で、リポジトリの Issue「覚えておく候補」にたまる。"""
    keep, notes = [], []
    for line in answer.splitlines():
        m = MEMORY_MARK.match(line)
        if m:
            if m.group(1).strip() not in notes:
                notes.append(m.group(1).strip())
        else:
            keep.append(line)
    path = os.environ.get("MEMORY_CANDIDATES")
    if notes and path:
        link = ""
        if p.get("guild_id") and p.get("channel_id") and p.get("message_id"):
            link = f"https://discord.com/channels/{p['guild_id']}/{p['channel_id']}/{p['message_id']}"
        with open(path, "a") as f:
            for n in notes:
                f.write(f"- {n}" + (f"（[元の発言]({link})）" if link else "") + "\n")
    return "\n".join(keep).strip()


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
