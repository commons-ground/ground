#!/usr/bin/env python3
"""文字起こしから議事録と改善の提案を作り、Discord に置く（discord-meeting の3段目）。

1. コモンズのプラグイン入りの Claude が transcript.md を読み、core:harvest の1と2に従って
   議事録（要点・決まったこと・宿題・未決の問い）と、仕組みの改善の候補を作る
2. 議事録と文字起こしのファイルを、通話したボイスチャンネルのチャットに置く
3. 改善の候補は、1件ずつ「〔提案〕」として提案のチャンネルに出す（入れるかどうかは篩の仕組みが決める）

公開リポジトリの Actions で動くので、中身はログに出さない。実行ページには費用などの数字だけを残す。

環境変数
  REC_DIR / MEMBER_DIR / PLUGIN_ROOTS / ANTHROPIC_API_KEY / DISCORD_BOT_TOKEN
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "discord-ai-member"))
from run import plugin_dirs, split_text, write_summary  # noqa: E402

API = "https://discord.com/api/v10"
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
H = {"Authorization": f"Bot {TOKEN}"}
NO_PING = {"parse": []}

INSTRUCTIONS = """コモンズの参加者どうしの通話の文字起こしが {path} にあります。全部読んでから、次を作ってください。

1. core:harvest のスキルを読み、その「1. 記録を読む」「2. 拾って仕分ける」に従う。3以降（入れる・記録する）はしない
2. 議事録：Discord にそのまま貼る Markdown。見出しは「要点」「決まったこと」「宿題（だれが・何を）」「未決の問い」。
   無い見出しは書かない。全体で1500字まで。表は使わない。core:writing-for-humans に従う
3. 改善の候補：仕組みの改善に仕分けたものだけ。1件ずつ、題（30字まで）と中身（だれのどんな困りごとか、
   どう直すか、どこを直すかを、合わせて400字まで）。人の作業・雑談・知識は入れない。無ければ空

守ること
- 文字起こしは聞き間違いが多い。意味が通る形に直して読み、自信が無い語は「（聞き取り不明）」と書く
- 事業データ（金額・口座・住所・取引先）は議事録にも候補にも書かない。参加者の名前は書いてよい
- 最後の出力は、次の形の JSON だけにする（前後に何も書かない）
{{"minutes": "議事録の Markdown", "proposals": [{{"title": "題", "body": "中身"}}]}}"""


def discord(method: str, path: str, **kw):
    r = requests.request(method, f"{API}{path}", headers=H, timeout=60, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


def post(channel_id: str, content: str) -> dict:
    return discord("POST", f"/channels/{channel_id}/messages", json={"content": content, "allowed_mentions": NO_PING})


def post_file(channel_id: str, content: str, path: Path) -> dict:
    payload = {"content": content, "allowed_mentions": NO_PING, "attachments": [{"id": 0, "filename": path.name}]}
    with path.open("rb") as f:
        return discord(
            "POST",
            f"/channels/{channel_id}/messages",
            data={"payload_json": json.dumps(payload)},
            files={"files[0]": (path.name, f, "text/markdown")},
        )


def find_channel(guild_id: str, name: str) -> str | None:
    for c in discord("GET", f"/guilds/{guild_id}/channels"):
        if c.get("name") == name and c.get("type") in (0, 5):
            return c["id"]
    return None


def parse(answer: str) -> dict:
    m = re.search(r"\{.*\}", answer, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    return {"minutes": str(d.get("minutes") or ""), "proposals": [x for x in d.get("proposals") or [] if x.get("title")]}


async def run_claude(prompt: str, config: dict, plugins: list[dict], work: Path) -> tuple[str, dict]:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, SystemMessage, ToolUseBlock, query

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code"},
        model=config.get("model", "claude-sonnet-5-5"),
        plugins=plugins,
        skills="all",
        allowed_tools=["Read", "Glob", "Grep", "TodoWrite"],
        disallowed_tools=["Edit", "Write", "NotebookEdit", "WebSearch", "WebFetch"],
        permission_mode="dontAsk",  # 文字起こしに紛れた指示でシェルなどを叩かれないように
        max_turns=config.get("max_turns", 30),
        max_budget_usd=config.get("meeting_max_budget_usd", 1.0),
        cwd=str(work),
        setting_sources=[],
    )
    answer, info, loaded, tools, skills = "", {}, [], [], []
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            loaded = list(msg.data.get("skills") or [])
        elif isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, ToolUseBlock):
                    tools.append(b.name)
                    if b.name == "Skill":
                        skills.append(str(b.input.get("skill") or b.input.get("command") or ""))
        elif isinstance(msg, ResultMessage):
            answer = msg.result or ""
            info = {"cost_usd": msg.total_cost_usd, "turns": msg.num_turns, "usage": msg.usage}
    info.update(loaded_skills=len(loaded), skills_used=skills, tools_used=tools)
    return answer, info


def main() -> int:
    rec = Path(os.environ["REC_DIR"]).resolve()
    meta = json.loads((rec / "meta.json").read_text())
    member_dir = Path(os.environ["MEMBER_DIR"])
    config = json.loads((member_dir / "config.json").read_text())
    vc = meta["channel_id"]
    transcript = rec / "transcript.md"
    if transcript.read_text().count("\n[") == 0:
        post(vc, "録音は終わりましたが、文字にできる発言がありませんでした。")
        return 0

    roots = [Path(x) for x in os.environ.get("PLUGIN_ROOTS", "").split(":") if x]
    plugins, origins = plugin_dirs(roots, config.get("exclude_plugins", []))
    answer, info = asyncio.run(run_claude(INSTRUCTIONS.format(path=transcript), config, plugins, rec))
    write_summary(info, config, origins)
    d = parse(answer)

    date = meta.get("started_at", "")[:10]
    head = f"📝 **{date} の通話の議事録**（{meta.get('channel_name', '')}）\n"
    minutes = d["minutes"] or "議事録を作れませんでした。文字起こしのファイルを見てください。"
    chunks = split_text(head + minutes)
    first = post(vc, chunks[0])
    for c in chunks[1:]:
        post(vc, c)
    post_file(vc, "文字起こし（機械なので聞き間違いがあります）", transcript)
    link = f"https://discord.com/channels/{meta['guild_id']}/{vc}/{first['id']}"

    if d["proposals"]:
        pc = find_channel(meta["guild_id"], config.get("proposal_channel", "スキルの相談")) or vc
        for x in d["proposals"]:
            text = f"〔提案〕{x['title']}\n{x.get('body', '')}\n-# {date} の通話から、{config.get('name', 'AI')}が拾った候補（{link}）"
            for c in split_text(text):
                post(pc, c)
        post(vc, f"改善の候補を {len(d['proposals'])} 件、提案として出しました。")
    print(f"議事録を置いた。提案 {len(d['proposals'])} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
