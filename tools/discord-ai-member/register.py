"""Discord のサーバーに /ai コマンドを登録する（最初に1回、コマンドを変えたときにもう1回）。

環境変数
  DISCORD_BOT_TOKEN … ボットの鍵
  APPLICATION_ID    … Discord 開発者画面「一般情報」のアプリID
  GUILD_ID          … 登録するサーバーのID（サーバーごとの登録はすぐ使えるようになる）
"""

import os
import sys

import requests

COMMANDS = [
    {
        "name": "ai",
        "description": "コモンズのAIに聞く",
        "type": 1,
        "options": [
            {"type": 3, "name": "question", "name_localizations": {"ja": "質問"},
             "description": "聞きたいこと", "required": True, "max_length": 2000},
        ],
    }
]


def main() -> int:
    app, guild = os.environ["APPLICATION_ID"], os.environ["GUILD_ID"]
    r = requests.put(
        f"https://discord.com/api/v10/applications/{app}/guilds/{guild}/commands",
        headers={"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}"},
        json=COMMANDS,
        timeout=30,
    )
    print(r.status_code, [c.get("name") for c in r.json()] if r.ok else r.text[:500])
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
