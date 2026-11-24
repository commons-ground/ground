"""篩（tools/sieve）の3つの段で共通に使うもの。"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import requests

API = "https://discord.com/api/v10"
MARK_DONE = "🧺"  # 篩に入った（ボットが付ける）
MARK_HOLD = "⏸️"  # 公開の前の点検で止めた（ボットが付ける）
KINDS = ("〔提案〕", "〔覚えておく〕")

# 公開の場所に書く前の機械の点検。validate の点検に、金額らしき文字を足したもの
PRIVATE = re.compile(
    r"[0-9]{3,4}-[0-9]{2,4}-[0-9]{4}"  # 電話番号
    r"|notion\.so/[0-9a-f]{32}|app\.notion\.com/p/[0-9a-f]{32}"  # 各自の Notion
    r"|docs\.google\.com/|drive\.google\.com/"  # 各自の Drive
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}"  # メールアドレス
    r"|[¥￥][0-9,]{3,}|[0-9][0-9,]{2,}\s?円|[0-9]+\s?万円"  # 金額
)


def out_dir() -> Path:
    """作業の置き場。既定は実行環境の一時フォルダ（ログにもリポジトリにも残らない）。"""
    return Path(os.environ.get("OUT_DIR") or Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "sieve")


def private_hits(text: str) -> list[str]:
    return sorted({m.group(0) for m in PRIVATE.finditer(text or "")})


def load_config(member_dir: str | None) -> dict:
    if member_dir:
        p = Path(member_dir) / "config.json"
        if p.exists():
            return json.loads(p.read_text())
    return {}


def discord(method: str, path: str, **kw):
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    r = requests.request(method, f"{API}{path}", headers={"Authorization": f"Bot {token}"}, timeout=60, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


def gh(*args: str, input_text: str | None = None, check: bool = True) -> str:
    """gh を動かす。中身はログに出さない（公開リポジトリのため）。"""
    r = subprocess.run(["gh", *args], input=input_text or "", capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''} が失敗（{r.returncode}）")
    return r.stdout


def summary(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")
