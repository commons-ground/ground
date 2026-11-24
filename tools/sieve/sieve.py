#!/usr/bin/env python3
"""篩の2段目：振り分ける（Claude）。

collect.py が集めた items.json を、core:sieve のルールで振り分け、直すものは写しのリポジトリを直し、
やることを plan.json に書く。GitHub や Discord には何も書かない（書くのは apply.py）。

Claude に渡すのは、Read・Glob・Grep・Edit・Write だけ。シェルも、GitHub や Discord の鍵も渡さない。
提案の文に紛れた指示で、外に書き込まれないようにするため。

環境変数
  OUT_DIR / MEMBER_DIR / PLUGIN_ROOTS / SELF_DIR / GROUND_DIR / ANTHROPIC_API_KEY / GITHUB_REPOSITORY
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import load_config, out_dir

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "discord-ai-member"))
from run import plugin_dirs, write_summary  # noqa: E402

EMPTY = {"issues": [], "comments": [], "labels": [], "edits": [], "closes": [], "prs": [],
         "replies": [], "announce": [], "polls": [], "held": []}


async def run_claude(prompt: str, config: dict, plugins: list[dict], work: Path) -> tuple[str, dict]:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, SystemMessage, ToolUseBlock, query

    options = ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code"},
        model=config.get("sieve_model") or config.get("model", "claude-sonnet-5-5"),
        plugins=plugins,
        skills="all",
        allowed_tools=["Read", "Glob", "Grep", "Edit", "Write", "TodoWrite"],
        disallowed_tools=["Bash", "NotebookEdit", "WebSearch", "WebFetch"],
        permission_mode="dontAsk",
        max_turns=config.get("sieve_max_turns", 60),
        max_budget_usd=config.get("sieve_max_budget_usd", 1.0),
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


def parse(answer: str) -> dict:
    m = re.search(r"\{.*\}", answer, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    return {k: d.get(k) or v for k, v in EMPTY.items()}


def main() -> int:
    out = out_dir().resolve()
    self_dir = Path(os.environ["SELF_DIR"]).resolve()
    ground = Path(os.environ["GROUND_DIR"]).resolve()
    config = load_config(os.environ.get("MEMBER_DIR"))

    edit = out / "edit"
    if edit.exists():
        shutil.rmtree(edit)
    shutil.copytree(self_dir, edit, ignore=shutil.ignore_patterns(".git", "node_modules"))

    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    prompt = (HERE / "agent.md").read_text().format(
        community=config.get("community", "コモンズ"),
        repo=os.environ.get("GITHUB_REPOSITORY", ""),
        out=out, ground=ground, today=today,
    )
    roots = [Path(x) for x in os.environ.get("PLUGIN_ROOTS", "").split(":") if x]
    plugins, origins = plugin_dirs(roots, config.get("exclude_plugins", []))
    answer, info = asyncio.run(run_claude(prompt, config, plugins, out))
    write_summary(info, {"name": "篩"}, origins)
    plan = parse(answer)
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    print("plan: " + "、".join(f"{k} {len(v)}" for k, v in plan.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
