#!/usr/bin/env python3
"""使われた記録を、スキルごとに数える。試行の見直し（棚卸しの会）の材料にする。

Issue「📊 使われた記録 YYYY-MM」の行（日付・呼ばれ方・スキル・印）を読み、Discord のボットの発言を
さかのぼって印（発言IDの短いハッシュ）と照らし、返事に付いた 👍・👎 の数をスキルごとに足す。
発言のIDも中身も外に出さない。数は判断の材料の1つで、これだけで定着・取り下げを決めない。

使い方（Discord のボットの鍵と gh が使える場所で）
  DISCORD_BOT_TOKEN=… python3 count.py commons-ground/winegrowers 2026-11
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict

API = "https://discord.com/api/v10"
ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([0-9a-f]{12}|-)\s*\|$")


def discord(path: str):
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}",
        "User-Agent": "commons-usage (https://github.com/commons-ground/ground, 1.0)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def rows(repo: str, month: str) -> list[tuple[str, str, list[str], str]]:
    out = subprocess.run(["gh", "issue", "list", "-R", repo, "--label", "使われた記録", "--state", "all",
                          "--search", f'"使われた記録 {month}" in:title', "--json", "number", "-q", ".[].number"],
                         capture_output=True, text=True, check=True).stdout.split()
    found = []
    for n in out:
        data = json.loads(subprocess.run(["gh", "issue", "view", n, "-R", repo, "--json", "comments"],
                                         capture_output=True, text=True, check=True).stdout)
        for c in data["comments"]:
            for line in c["body"].splitlines():
                m = ROW.match(line.strip())
                if m:
                    found.append((m[1], m[2], [s for s in m[3].split("、") if s != "なし"], m[4]))
    return found


def reactions(month: str) -> dict[str, tuple[int, int]]:
    """その月のボットの発言の 印 → (👍, 👎)。"""
    me = discord("/users/@me")["id"]
    got: dict[str, tuple[int, int]] = {}
    for g in discord("/users/@me/guilds"):
        for ch in discord(f"/guilds/{g['id']}/channels"):
            if ch.get("type") not in (0, 5):
                continue
            before = ""
            for _ in range(20):  # 1チャンネル 2,000 件まで
                try:
                    msgs = discord(f"/channels/{ch['id']}/messages?limit=100{before}")
                except Exception:  # noqa: BLE001  読めないチャンネルは飛ばす
                    break
                if not msgs:
                    break
                for m in msgs:
                    if m["author"]["id"] == me and m["timestamp"][:7] == month:
                        r = {x["emoji"].get("name"): x["count"] for x in m.get("reactions", [])}
                        got[hashlib.sha256(m["id"].encode()).hexdigest()[:12]] = (r.get("👍", 0), r.get("👎", 0))
                if msgs[-1]["timestamp"][:7] < month:
                    break
                before = f"&before={msgs[-1]['id']}"
    return got


def main() -> int:
    repo, month = sys.argv[1], sys.argv[2]
    table: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    rx = reactions(month)
    for _day, _kind, skills, ref in rows(repo, month):
        up, down = rx.get(ref, (0, 0))
        for s in skills or ["（スキルなし）"]:
            t = table[s]
            t[0] += 1
            t[1] += up
            t[2] += down
    print(f"### 使われた記録 {month}（{repo}）\n\n| スキル | 回数 | 👍 | 👎 |\n|:--|--:|--:|--:|")
    for s, (n, up, down) in sorted(table.items(), key=lambda x: -x[1][0]):
        print(f"| {s} | {n} | {up} | {down} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
