#!/usr/bin/env python3
"""篩の係が、公開の場所に書くときに必ず通る門。

篩の係（Claude）は、GitHub への書き込み・ブランチの push・Discord への書き込みを、この門を通してしかできない
（sieve.yml の allowedTools で、gh と git は読むだけ・手元の操作だけに絞ってある）。門は書く前に機械で点検し、
個人や事業の情報らしき文字（電話番号・メール・各自の Notion や Drive の URL・金額）か、鍵の値が入っていたら書かない。
AI が自分で書いた文を AI が点検するだけでは抜けが残るため（docs/sieve.md の「公開の前の点検」）。

使い方
  python3 safe.py gh issue create --title "…" --body-file card.md --label 篩   … gh の書き込み（issue・pr・label）
  python3 safe.py push <ブランチ>                    … main との差分の、足した行を点検してから push
  python3 safe.py discord "<文>"                      … 知らせのチャンネル（既定 #スキルの相談）に書き、投稿のリンクを出す
  python3 safe.py reply <チャンネルID> <発言ID> "<文>"   … Discord の元の発言に返事する
  python3 safe.py reactions <Discord の発言のリンク>   … その発言の 👍・👎 の数を読む（読むだけ）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request

API = "https://discord.com/api/v10"
PRIVATE = re.compile(
    r"[0-9]{3,4}-[0-9]{2,4}-[0-9]{4}"  # 電話番号
    r"|notion\.so/[0-9a-f]{32}|app\.notion\.com/p/[0-9a-f]{32}"  # 各自の Notion
    r"|docs\.google\.com/|drive\.google\.com/"  # 各自の Drive
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}"  # メールアドレス
    r"|[¥￥][0-9,]{3,}|[0-9][0-9,]{2,}\s?円|[0-9]+\s?万円"  # 金額
)
# 書き込みを許す gh のコマンド（読むだけのものは、門を通さず gh で直接使える）
WRITE = {
    "issue": {"create", "edit", "comment", "close", "reopen"},
    "pr": {"create", "edit", "comment", "ready", "close"},
    "label": {"create", "edit"},
}
TEXT_FLAGS = {"--title", "-t", "--body", "-b", "--comment", "-c", "--description", "-d"}
FILE_FLAGS = {"--body-file", "-F"}


def secrets() -> list[str]:
    """鍵らしき環境変数の値。これが文に入っていたら書かない。"""
    return [v for k, v in os.environ.items()
            if len(v) >= 16 and any(w in k.upper() for w in ("TOKEN", "KEY", "SECRET", "PASSWORD"))]


def check(text: str, where: str) -> None:
    hits = sorted({m.group(0) for m in PRIVATE.finditer(text or "")})
    if any(s in (text or "") for s in secrets()):
        hits.append("（鍵の値）")
    if hits:
        print(f"書きませんでした：{where} に、個人や事業の情報・鍵らしき文字があります（{len(hits)}か所）。"
              "一般化して書き直すか、公開しないでカードを「篩:保留」にしてください。")
        sys.exit(2)


def run_gh(args: list[str]) -> int:
    if len(args) < 2 or args[1] not in WRITE.get(args[0], set()):
        print(f"この門で使える gh の書き込みは {', '.join(f'{k} {sorted(v)}' for k, v in WRITE.items())} だけです。"
              "読むだけなら gh を直接使ってください。")
        return 2
    if any(a.startswith("--remove-label") for a in args) and "人の確認" in " ".join(args):
        print("ラベル「人の確認」は外せません。外すのは人です。")
        return 2
    texts, i = [], 2
    while i < len(args):
        a = args[i]
        key, _, val = a.partition("=")
        if key in TEXT_FLAGS | FILE_FLAGS and not val and i + 1 < len(args):
            val, i = args[i + 1], i + 1
        if key in TEXT_FLAGS:
            texts.append(val)
        elif key in FILE_FLAGS:
            if val == "-":
                print("本文はファイルで渡してください（--body-file <ファイル>）")
                return 2
            with open(val, encoding="utf-8") as f:
                texts.append(f.read())
        elif not a.startswith("-") and i >= 2:
            texts.append(a)  # gh issue comment 12 --body … の番号や、位置で渡した文も点検する
        i += 1
    check("\n".join(texts), f"gh {args[0]} {args[1]}")
    return subprocess.run(["gh", *args]).returncode


def run_push(branch: str) -> int:
    if branch in ("main", "master") or branch.startswith("-"):
        print("main には push しません。ブランチを切ってください。")
        return 2
    subprocess.run(["git", "fetch", "-q", "origin", "main"], check=False)
    diff = subprocess.run(["git", "diff", "origin/main...HEAD"], capture_output=True, text=True).stdout
    added = "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    check(added, f"ブランチ {branch} の変更")
    return subprocess.run(["git", "push", "-u", "origin", f"HEAD:refs/heads/{branch}"]).returncode


def discord(method: str, path: str, body: dict | None = None):
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        return None
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                 "User-Agent": "commons-sieve (https://github.com/commons-ground/ground, 1.0)"},
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        raw = res.read()
        return json.loads(raw) if raw else {}


def post(channel_id: str, text: str, reply_to: str | None = None) -> dict | None:
    # 篩の書き込みが、次の篩で提案として拾われないように、印の括弧を外す
    text = text.replace("〔提案〕", "提案：").replace("〔覚えておく〕", "覚えておく：")
    body = {"content": text[:1900], "allowed_mentions": {"parse": []}}
    if reply_to:
        body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
    return discord("POST", f"/channels/{channel_id}/messages", body)


def run_discord(text: str) -> int:
    check(text, "Discord への知らせ")
    if not os.environ.get("DISCORD_BOT_TOKEN"):
        print("DISCORD_BOT_TOKEN が無いので、Discord には知らせなかった")
        return 0
    name = os.environ.get("SIEVE_CHANNEL") or "スキルの相談"
    for guild in discord("GET", "/users/@me/guilds"):
        for ch in discord("GET", f"/guilds/{guild['id']}/channels"):
            if ch.get("type") == 0 and ch.get("name") == name:
                m = post(ch["id"], text)
                print(f"知らせた：https://discord.com/channels/{guild['id']}/{ch['id']}/{m['id']}")
                return 0
    print(f"チャンネル「{name}」が見つからなかった")
    return 0


def run_reply(channel_id: str, message_id: str, text: str) -> int:
    check(text, "Discord への返事")
    if not (channel_id.isdigit() and message_id.isdigit()):
        print("チャンネルIDと発言IDは数字で渡してください")
        return 2
    m = post(channel_id, text, reply_to=message_id)
    print("返事した" if m else "DISCORD_BOT_TOKEN が無いので、返事しなかった")
    return 0


def run_reactions(link: str) -> int:
    m = re.search(r"discord\.com/channels/\d+/(\d+)/(\d+)", link)
    if not m:
        print("Discord の発言のリンクを渡してください")
        return 2
    msg = discord("GET", f"/channels/{m.group(1)}/messages/{m.group(2)}")
    if msg is None:
        print("DISCORD_BOT_TOKEN が無いので、読めなかった")
        return 0
    counts = {r["emoji"]["name"]: r["count"] - (1 if r.get("me") else 0) for r in msg.get("reactions") or []}
    print(json.dumps({"👍": counts.get("👍", 0), "👎": counts.get("👎", 0)}, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "gh":
        return run_gh(rest)
    if cmd == "push" and len(rest) == 1:
        return run_push(rest[0])
    if cmd == "discord" and rest:
        return run_discord(" ".join(rest))
    if cmd == "reply" and len(rest) >= 3:
        return run_reply(rest[0], rest[1], " ".join(rest[2:]))
    if cmd == "reactions" and len(rest) == 1:
        return run_reactions(rest[0])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
