# sieve（篩の仕事）

コモンズに出てきた提案を、篩の係の AI が1件ずつ運ぶ仕組みです。手順は core の `sieve` スキル、考え方は [docs/sieve.md](../../docs/sieve.md) にあります。

## 起こし方（イベントだけ。定期実行は使わない）

| 出来事 | 起こすもの |
| --- | --- |
| Discord の `/propose`・「Propose to Commons」 | 受け口（`tools/discord-ai-member/worker.js`）が repository_dispatch `sieve-intake` を送る |
| 提案の Issue を作る（様式「提案（篩にかける）」、またはタイトルが「〔提案〕」） | GitHub の `issues: opened` |
| カード（ラベル「篩」の Issue）にコメントが付く | GitHub の `issue_comment: created` |

見直しの日が過ぎた試行は、どの出来事で動いたときもついでに1件見ます。提案が来ない間は見直しも止まりますが、そのあいだは困る人もいないので、そのままにします。

## 置き場所

| もの | 場所 |
| --- | --- |
| 仕事の流れ（本体） | `.github/workflows/sieve.yml`（各コモンズから呼ぶ） |
| ground 自身の呼び出し | `.github/workflows/sieve-here.yml` |
| 篩の係への指示 | `tools/sieve/agent.md` |
| 篩の手順 | `plugins/core/skills/sieve/SKILL.md` |
| Discord に知らせる | `tools/sieve/discord_post.py` |
| 提案の様式 | `.github/ISSUE_TEMPLATE/proposal.yml` |

## 呼び出し側の workflow（各コモンズのリポジトリ）

```yaml
on:
  repository_dispatch:
    types: [sieve-intake]
  issues:
    types: [opened]
  issue_comment:
    types: [created]
permissions:
  contents: write
  issues: write
  pull-requests: write
  id-token: write
  actions: read
jobs:
  sieve:
    uses: commons-ground/ground/.github/workflows/sieve.yml@main
    with:
      member_dir: discord
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
```

提案の様式（`.github/ISSUE_TEMPLATE/proposal.yml`）も、ground から写して置きます。

## 費用

| もの | 費用 |
| --- | --- |
| GitHub Actions | 公開リポジトリなら無料 |
| 篩の係（Claude） | 提案1件・コメント1件ごとに1回。`max_turns` までで、API キーの持ち主に請求される |

## まだ無いもの

- 別のリポジトリへの書き込み。いまの鍵は呼び出し側のリポジトリにしか書けないので、行き先が ground のカードにはラベル `行き先:ground` を付け、人の Claude が harvest で運ぶ
- 通話の〔提案〕（`tools/discord-meeting`）と AI の返事の〔覚えておく〕を、自動で篩に渡す道。いまは Discord に出たものを harvest で拾う
