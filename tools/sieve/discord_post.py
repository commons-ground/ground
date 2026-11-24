"""篩の仕事から、Discord に短く知らせる。

使い方：python3 discord_post.py "知らせる文"
環境変数：DISCORD_BOT_TOKEN（無ければ何もせずに終わる）、SIEVE_CHANNEL（チャンネル名。既定「スキルの相談」。#提案 には書かない。書いたものが提案として拾われるため）
ボットが入っているサーバーのうち、名前が合う最初のテキストチャンネルに書く。人やロールは呼び出さない。
"""
import json
import os
import sys
import urllib.request

API = "https://discord.com/api/v10"


def call(method: str, path: str, token: str, body: dict | None = None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "commons-sieve (https://github.com/commons-ground/ground, 1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


def main() -> int:
    text = " ".join(sys.argv[1:]).strip()
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    name = os.environ.get("SIEVE_CHANNEL", "") or "スキルの相談"
    if not text:
        print("知らせる文が空です")
        return 1
    if not token:
        print("DISCORD_BOT_TOKEN が無いので、Discord には知らせなかった")
        return 0
    for guild in call("GET", "/users/@me/guilds", token):
        for ch in call("GET", f"/guilds/{guild['id']}/channels", token):
            if ch.get("type") == 0 and ch.get("name") == name:
                call("POST", f"/channels/{ch['id']}/messages", token,
                     {"content": text[:1900], "allowed_mentions": {"parse": []}})
                print("知らせた")
                return 0
    print(f"チャンネル「{name}」が見つからなかった")
    return 0


if __name__ == "__main__":
    sys.exit(main())
