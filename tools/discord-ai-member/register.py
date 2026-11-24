"""Discord のサーバーに、commands.json のコマンドを登録する（最初に1回、コマンドを変えたときにもう1回）。

環境変数
  DISCORD_BOT_TOKEN … ボットの鍵
  APPLICATION_ID    … Discord 開発者画面「一般情報」のアプリID
  GUILD_ID          … 登録するサーバーのID（サーバーごとの登録はすぐ使えるようになる）
"""

import json
import os
import sys
from pathlib import Path

import requests

COMMANDS = json.loads((Path(__file__).parent / "commands.json").read_text())


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
