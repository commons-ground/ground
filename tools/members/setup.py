#!/usr/bin/env python3
"""見学者とコモンズメンバー（docs/membership.md）を、コモンズの Discord に用意する。何度走らせても同じ形になる。

やること
  1. ロール「コモンズメンバー」が無ければ作る
  2. いまいる人（ボットを除く）全員と、このボット自身にそのロールを付ける（最初のメンバー）
  3. チャンネル #ようこそ が無ければ作り、案内を書いてピン留めする
  4. 書き込みをメンバーに絞る：@everyone（見学者）から「発言する」「スレッドで発言する」「スレッドを作る」を外し、
     メンバーのロールに付ける。#ようこそ だけは @everyone も書ける。スラッシュコマンド（/ai）は誰でも使える

使い方（ボットの鍵がある場所で）
  DISCORD_BOT_TOKEN=… python3 setup.py           … 何をするかを見せるだけ
  DISCORD_BOT_TOKEN=… python3 setup.py --apply   … 実際に変える
ボットに「ロールの管理」「チャンネルの管理」の権限が要る。足りなければ止まって知らせる。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
ROLE = os.environ.get("MEMBER_ROLE_NAME", "コモンズメンバー")
WELCOME = os.environ.get("WELCOME_CHANNEL", "ようこそ")
SEND, SEND_THREADS, CREATE_PUBLIC_THREADS, CREATE_PRIVATE_THREADS = 1 << 11, 1 << 38, 1 << 35, 1 << 36
WRITE = SEND | SEND_THREADS | CREATE_PUBLIC_THREADS | CREATE_PRIVATE_THREADS
MANAGE_ROLES, MANAGE_CHANNELS, ADMIN = 1 << 28, 1 << 4, 1 << 3
WELCOME_TEXT = """👋 ようこそ、Winegrowers Commons へ！

ここに入ったばかりの人は **見学者** です。いろんなチャンネルを読めて、`/ai` でコモンズのAIに話しかけられます。

コモンズに共感したら、**コモンズメンバー** になってください。メンバーは、みんなのスキルを自分の Claude に入れて使い、知識コモンズを読み書きし、#提案 で仕組みを育てられます。

**メンバーになるには**：このチャンネルに自己紹介と「メンバーになりたい」を書いてください。メンバーの誰かが ✅ を付けたら、ロールが付いて、はじめかたが届きます。

くわしく：https://github.com/commons-ground/ground/blob/main/docs/membership.md"""

APPLY = "--apply" in sys.argv


def call(method: str, path: str, body=None, reason: str = ""):
    for _ in range(5):
        req = urllib.request.Request(
            API + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}", "Content-Type": "application/json",
                     "User-Agent": "commons-members (https://github.com/commons-ground/ground, 1.0)",
                     **({"X-Audit-Log-Reason": urllib.request.quote(reason)} if reason else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(json.loads(e.read() or b"{}").get("retry_after", 1)) + 0.2)
                continue
            raise SystemExit(f"Discord が断りました：{method} {path} → {e.code} {e.read()[:300]!r}")
    raise SystemExit("Discord が混んでいて進めませんでした")


def do(what: str, method: str, path: str, body=None):
    print(("やった：" if APPLY else "やる予定：") + what)
    return call(method, path, body, reason="見学者とコモンズメンバー（docs/membership.md）") if APPLY else None


def main() -> int:
    me = call("GET", "/users/@me")
    guilds = call("GET", "/users/@me/guilds")
    gid = os.environ.get("DISCORD_GUILD_ID") or (guilds[0]["id"] if len(guilds) == 1 else "")
    if not gid:
        raise SystemExit("サーバーが1つに決まりません。DISCORD_GUILD_ID を渡してください")
    roles = call("GET", f"/guilds/{gid}/roles")
    everyone = next(r for r in roles if r["id"] == gid)
    mine = call("GET", f"/guilds/{gid}/members/{me['id']}")
    perms = 0
    for r in roles:
        if r["id"] in mine["roles"] or r["id"] == gid:
            perms |= int(r["permissions"])
    if not perms & ADMIN and (not perms & MANAGE_ROLES or not perms & MANAGE_CHANNELS):
        raise SystemExit("ボットに「ロールの管理」と「チャンネルの管理」の権限がありません。サーバー設定 → ロール → ボットのロールで付けてください")

    # 1. ロール
    role = next((r for r in roles if r["name"] == ROLE), None)
    if role:
        print(f"ある：ロール「{ROLE}」")
    else:
        role = do(f"ロール「{ROLE}」を作る", "POST", f"/guilds/{gid}/roles",
                  {"name": ROLE, "permissions": str(WRITE), "hoist": True, "mentionable": False}) or {"id": "(新しいロール)", "permissions": "0"}
    if role and int(role.get("permissions", "0")) & WRITE != WRITE and role["id"].isdigit():
        do(f"ロール「{ROLE}」に書き込みの権限を付ける", "PATCH", f"/guilds/{gid}/roles/{role['id']}",
           {"permissions": str(int(role["permissions"]) | WRITE)})

    # 2. 最初のメンバー：いまいる人全員とこのボット
    people = []
    try:
        after = "0"
        while True:
            page = call("GET", f"/guilds/{gid}/members?limit=1000&after={after}")
            if not page:
                break
            people += page
            after = page[-1]["user"]["id"]
            if len(page) < 1000:
                break
    except SystemExit:
        # 名簿を読む許可（SERVER MEMBERS INTENT）が無いときは、チャンネルで発言したことのある人を「いまいる人」とみなす
        print("名簿は読めないので、発言したことのある人から集める")
        seen = {}
        for c in call("GET", f"/guilds/{gid}/channels"):
            if c["type"] != 0:
                continue
            try:
                for msg in call("GET", f"/channels/{c['id']}/messages?limit=100"):
                    seen[msg["author"]["id"]] = msg["author"]
            except SystemExit:
                continue
        for uid in list(seen) + [me["id"]]:
            try:
                people.append(call("GET", f"/guilds/{gid}/members/{uid}"))
            except SystemExit:
                pass  # もう抜けた人
    for m in people:
        u = m["user"]
        if u.get("bot") and u["id"] != me["id"]:
            continue
        if role["id"] in m["roles"]:
            print(f"ある：{u.get('global_name') or u['username']} はメンバー")
            continue
        do(f"{u.get('global_name') or u['username']} をメンバーにする", "PUT", f"/guilds/{gid}/members/{u['id']}/roles/{role['id']}")

    # 3. #ようこそ
    channels = call("GET", f"/guilds/{gid}/channels")
    welcome = next((c for c in channels if c["type"] == 0 and c["name"] == WELCOME), None)
    overwrite = {"id": gid, "type": 0, "allow": str(SEND), "deny": "0"}
    if welcome:
        print(f"ある：#{WELCOME}")
        if not any(o["id"] == gid and int(o["allow"]) & SEND for o in welcome.get("permission_overwrites", [])):
            do(f"#{WELCOME} は見学者も書けるようにする", "PUT", f"/channels/{welcome['id']}/permissions/{gid}",
               {"type": 0, "allow": str(SEND), "deny": "0"})
    else:
        welcome = do(f"#{WELCOME} を作る（見学者も書ける）", "POST", f"/guilds/{gid}/channels",
                     {"name": WELCOME, "type": 0, "position": 0,
                      "topic": "はじめての人はここへ。自己紹介と「メンバーになりたい」を書くと、メンバーの誰かが ✅ で迎えます",
                      "permission_overwrites": [overwrite]})
        if welcome:
            msg = do(f"#{WELCOME} に案内を書く", "POST", f"/channels/{welcome['id']}/messages",
                     {"content": WELCOME_TEXT, "allowed_mentions": {"parse": []}})
            do("案内をピン留めする", "PUT", f"/channels/{welcome['id']}/pins/{msg['id']}")
        else:
            print(f"やる予定：#{WELCOME} に案内を書いてピン留めする")

    # 4. 見学者は読むだけにする（ロールと #ようこそ ができてから）
    base = int(everyone["permissions"])
    if base & WRITE:
        do("@everyone（見学者）から、発言・スレッドの権限を外す（/ai は使える）", "PATCH", f"/guilds/{gid}/roles/{gid}",
           {"permissions": str(base & ~WRITE)})
    else:
        print("済み：見学者は読むだけ")
    if not APPLY:
        print("\n見せただけです。変えるときは --apply を付けて走らせてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
