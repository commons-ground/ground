# sieve（篩）

コモンズに入ってくる提案を、提案箱（GitHub の Issue）に集めて振り分ける仕組みです。設計と理由は [docs/sieve.md](../../docs/sieve.md)、AI が守るルールは core の [sieve スキル](../../plugins/core/skills/sieve/SKILL.md) にあります。

## 3段の中身

| 段 | ファイル | Claude | 持つ鍵 |
|:--|:--|:--|:--|
| 1 集める | `collect.py` | 使わない | Discord のボット、GitHub（読む） |
| 2 振り分ける | `sieve.py`（指示は `agent.md`） | 使う。道具は Read・Glob・Grep・Edit・Write だけ | Anthropic の API キーだけ |
| 3 書き出す | `apply.py` | 使わない | Discord のボット、GitHub（書く） |

Claude にシェルも GitHub や Discord の鍵も渡さないのは、提案の文に紛れた指示で外に書き込まれないようにするためです。Claude は「何をするか」を `plan.json` に書くだけで、書き出すのは `apply.py` です。`apply.py` は書く前に個人や事業の情報らしき文字を点検し、マージはせず、ラベル「人の確認」を外すこともしません。

Discord の発言には、篩に通したら 🧺、点検で止めたら ⏸️ をボットが付けます。この印が「通したかどうか」の記録なので、篩は何度起きても同じ発言を二度通しません。

## コモンズにつなぐ

呼び出し側のリポジトリに、`.github/workflows/sieve.yml` を置きます。

```yaml
name: sieve
on:
  issues:
    types: [opened]
  workflow_dispatch:
concurrency:
  group: sieve
permissions:
  contents: write
  issues: write
  pull-requests: write
  actions: write
jobs:
  sieve:
    if: >-
      github.event_name != 'issues' ||
      (contains(github.event.issue.labels.*.name, '提案') && github.event.issue.user.type != 'Bot' &&
       contains(fromJSON('["OWNER","MEMBER","COLLABORATOR"]'), github.event.issue.author_association))
    uses: commons-ground/ground/.github/workflows/sieve.yml@main
    with:
      payload: ${{ toJSON(github.event.client_payload) }}
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
```

`/propose`・「コモンズに提案」・`/ai`・`/record` のあとにも篩を動かすには、それぞれの workflow（`discord-propose.yml`・`discord-ai.yml`・`discord-meeting.yml`）の最後に、同じ `uses:` のジョブを `needs:` と `if: always()` で足します（winegrowers が見本）。受け口（worker.js）は変えなくてよい。

`#提案` に人が直接書いた発言は、Discord が知らせてくれないので、次に篩が起きたときに拾われます。

## 設定（呼び出し側の `discord/config.json`）

| 名前 | 既定 | 中身 |
|:--|:--|:--|
| `proposal_channel` | 提案 | 提案のチャンネル。ここの人の発言は、〔提案〕と書いていなくてもすべて提案として拾う |
| `sieve_report_channel` | スキルの相談 | 影響が中・大の知らせと、見直しの声を書くチャンネル |
| `sieve_channels` | すべてのテキストチャンネル | 〔提案〕〔覚えておく〕を探すチャンネル |
| `sieve_since` | なし | この日より前の発言は見ない（つなぎ始めの日を書く） |
| `sieve_lookback_days` | 14 | 何日前までさかのぼるか |
| `sieve_max_budget_usd` | 1.0 | 1回の振り分けの上限額 |
| `sieve_model` | `model` と同じ | 振り分けに使うモデル |
| `sieve_guild_id` | ボットが入っているサーバー | ボットが2つ以上のサーバーにいるときだけ書く |

## 鍵（リポジトリには置かない）

| 名前 | 要るか | 置き場 |
|:--|:--|:--|
| `ANTHROPIC_API_KEY` | 要る | 呼び出し側の Actions secrets（キーの持ち主に請求される） |
| `DISCORD_BOT_TOKEN` | 任意（無ければ GitHub の提案だけを見る） | 呼び出し側の Actions secrets。ボットに「リアクションの追加」と「メッセージ履歴を読む」の権限 |
| `SIEVE_APP_ID`・`SIEVE_APP_PRIVATE_KEY` | 任意 | 篩用の GitHub App。あると、篩のプルリクエストでふつうに validate と自動マージが動く |

## 費用

| もの | 費用 |
|:--|:--|
| 集める・書き出す | GitHub Actions。公開リポジトリなら無料 |
| 振り分ける（Claude） | 集めたものがあるときだけ。1回 `sieve_max_budget_usd` まで |
