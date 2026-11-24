# discord-ai-member

コモンズの Discord に AI を置く仕組みです。GitHub の `@claude` と同じ AI です（`tools/ai-member/README.md`）。Discord で `/ai 〇〇` と打つと、そのコモンズのスキル（土台の ground と、そのコモンズのプラグイン）を読んだ Claude が、同じチャンネルに答えます。

## コマンド

AI とのやり取りは、すべて Discord のコマンドの形にそろえます。名前は短い英語にし、説明は日本語にします。`/` を打つと候補と説明が出るので、覚えなくても使えます。

| コマンド | すること | どこで動くか |
|:--|:--|:--|
| `/ai 質問` | AI に聞く | GitHub Actions の Claude |
| `/propose 内容` | 提案を〔提案〕として書く。篩の仕組みがあとで拾う | 受け口だけ |
| 発言の「アプリ」→「Propose to Commons」 | その発言を〔提案〕として書き直す | 受け口だけ |
| `/record start`・`/record stop` | 通話を録って、議事録と提案まで作る（`tools/discord-meeting`） | GitHub Actions |
| `/help` | コマンドの一覧（本人にだけ見える） | 受け口だけ |

コマンドを足すとき：

1. `commands.json` に足す（名前は短い英語、説明は日本語）
2. `worker.js` に振り分けを足す。3秒で済むものは受け口でその場に返し、時間がかかるものは repository_dispatch で GitHub Actions に渡す。`HELP` も合わせる
3. 受け口を置き直し、`discord-commands` の workflow で登録し直す

## 流れ

```
Discord で /ai 〇〇
  → 受け口（Cloudflare Worker、worker.js）
      署名を確かめ、すぐ「考え中…」を返し、repository_dispatch で渡す
  → 各コモンズのリポジトリの workflow
  → この ground の workflow（.github/workflows/discord-ai-member.yml）
      run.py が、呼び出し側と ground のプラグインを読み込んだ Claude で答えを作り、
      「考え中…」を答えに書き換える
```

- 返事は Discord から渡される一時的な合鍵（15分有効）で書き戻すので、答えるだけならボットの鍵は要りません
- ボットの鍵があれば、チャンネルの直近のやりとりも読んで、話の流れを踏まえて答えます
- 公開リポジトリでも動かせるよう、質問・答え・チャンネルの中身はログに出しません。実行ページには費用と使ったスキルだけを残します

## 置き場所

| もの | 場所 |
|:--|:--|
| 受け口 | `worker.js` を Cloudflare Worker に置く |
| 返事を作る処理 | `run.py`（ground の workflow から動く） |
| コマンドの登録 | `register.py`（最初に1回） |
| 呼び名・モデル・上限額 | 呼び出し側の `discord/config.json` |
| ふるまい（性格・決まり） | 呼び出し側の `discord/member.md` |
| 覚えていること | 呼び出し側の `discord/memory.md`（GitHub の AI と共通。`tools/ai-member/README.md`） |

## 鍵（リポジトリには置かない）

| 名前 | 置き場 |
|:--|:--|
| `ANTHROPIC_API_KEY` | 呼び出し側のリポジトリの Actions secrets（キーの持ち主に請求される） |
| `DISCORD_BOT_TOKEN` | 呼び出し側のリポジトリの Actions secrets（コマンドの登録と、チャンネルを読むのに使う） |
| `GITHUB_TOKEN`（dispatch 用） | Cloudflare Worker の Secret |
| `DISCORD_PUBLIC_KEY`・`REPO` | Cloudflare Worker の変数（秘密ではない） |

## 呼び出し側の workflow

```yaml
on:
  repository_dispatch:
    types: [discord-interaction]
jobs:
  reply:
    uses: commons-ground/ground/.github/workflows/discord-ai-member.yml@main
    with:
      payload: ${{ toJSON(github.event.client_payload) }}
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
```

## まだ無いもの

- 知識コモンズ（Notion）を読む道具。いまは Web 検索とスキルだけで答える
- 📌 を付けた発言を集めて、知識コモンズや GitHub の提案に移す仕組み
