"""/propose と、発言のアプリ「コモンズに提案」を、提案のチャンネルに載せる。

受け口（worker.js）が repository_dispatch（discord-propose）で起こす。受け口はボットの鍵を持たないので、
ほかのチャンネルへの書き込みはここ（Actions の DISCORD_BOT_TOKEN）でする。

環境変数
  PAYLOAD            … 受け口から渡された JSON（text, user_name, source_link, source_author, application_id, token, guild_id）
  DISCORD_BOT_TOKEN  … ボットの鍵
  MEMBER_DIR         … このコモンズの設定フォルダ（config.json の proposal_channel を読む）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

API = "https://discord.com/api/v10"


def main() -> int:
    p = json.loads(os.environ["PAYLOAD"])
    print(f"::add-mask::{p.get('token', '')}")
    h = {"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}"}
    config = json.loads((Path(os.environ["MEMBER_DIR"]) / "config.json").read_text())
    name = config.get("proposal_channel", "提案")
    channels = requests.get(f"{API}/guilds/{p['guild_id']}/channels", headers=h, timeout=30).json()
    ch = next((c["id"] for c in channels if c.get("name") == name and c.get("type") in (0, 5)), None)

    who = p.get("user_name") or "参加者"
    if p.get("source_link"):
        foot = f"-# {p.get('source_author') or '参加者'}さんの発言（{p['source_link']}）を、{who}さんが提案にしました"
    else:
        foot = f"-# {who}さんが /propose で出しました"
    body = f"〔提案〕{p.get('text', '').strip()[:1700]}\n{foot}"

    done = "提案を載せられませんでした。少し待って、もう一度出してください。"
    if ch:
        r = requests.post(f"{API}/channels/{ch}/messages", headers=h, timeout=30,
                          json={"content": body, "allowed_mentions": {"parse": []}})
        if r.ok:
            done = f"提案を #{name} に載せました：https://discord.com/channels/{p['guild_id']}/{ch}/{r.json()['id']}"
    else:
        done = f"提案のチャンネル #{name} が見つかりませんでした。世話役に伝えてください。"
    # 受け付けた本人にだけ見える返事を書き換える
    requests.patch(f"{API}/webhooks/{p['application_id']}/{p['token']}/messages/@original", timeout=30,
                   json={"content": done, "allowed_mentions": {"parse": []}})
    print("載せた" if ch else "チャンネルが無い")
    return 0


if __name__ == "__main__":
    sys.exit(main())
