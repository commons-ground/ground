# sieve（篩の仕事）

コモンズに出てきた提案を、篩の係の AI が1件ずつ運ぶ仕組みです。手順は core の `sieve` スキル、考え方は [docs/sieve.md](../../docs/sieve.md) にあります。

## 起こし方（イベントだけ。定期実行は使わない）

| 出来事 | 起こすもの |
| --- | --- |
| Discord の `/propose`・「コモンズに提案」 | 受け口（`tools/discord-ai-member/worker.js`）が送る repository_dispatch `discord-propose` を、`#提案` に載せる仕事（`discord-propose.yml`）と篩が両方受け取る |
| `#提案` に直接書いた発言、通話の議事録から出た〔提案〕 | 中継（`tools/discord-agents/router.js`）が毎分の見回りのついでに見つけ、repository_dispatch `sieve-intake` を送る |
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
| 書き込みの門（点検してから書く。Discord への知らせ・返事、見直しの声を数える） | `tools/sieve/safe.py`（知らせは呼び出し側の `config.json` の `sieve_channel`、無ければ `#スキルの相談`） |
| 提案の様式 | `.github/ISSUE_TEMPLATE/proposal.yml` |

## 呼び出し側の workflow（各コモンズのリポジトリ）

```yaml
on:
  repository_dispatch:
    types: [discord-propose, sieve-intake]
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

## 別のリポジトリに書く（篩のアプリ）

コモンズのカードで、直す先が ground のときは、篩が ground に直接プルリクエストを出します。使うのは GitHub アプリ「Commons Sieve」の鍵で、仕事のたびに1時間だけ有効な鍵を作ります（`actions/create-github-app-token`）。書き込みは呼び出し側と同じく `safe.py` の門を通り、`commons-ground` の外には書きません。

アプリの鍵（組織の Actions secrets の `SIEVE_APP_ID`・`SIEVE_APP_PRIVATE_KEY`）が無いあいだは、これまでどおりカードにラベル `行き先:ground` を付け、人の Claude が harvest で運びます。

呼び出し側の workflow の `secrets:` に、次の2行を足します。

```yaml
      SIEVE_APP_ID: ${{ secrets.SIEVE_APP_ID }}
      SIEVE_APP_PRIVATE_KEY: ${{ secrets.SIEVE_APP_PRIVATE_KEY }}
```

## 費用

| もの | 費用 |
| --- | --- |
| GitHub Actions | 公開リポジトリなら無料 |
| 篩の係（Claude） | 提案1件・コメント1件ごとに1回。`max_turns` までで、API キーの持ち主に請求される |

## まだ無いもの

- AI の返事の〔覚えておく〕を、自動で篩に渡す道。いまは harvest で拾う

## 中継に篩の入り口を受け持たせる（世話役が1回）

1. GitHub アプリ「Commons Agents」を、コモンズのリポジトリ（例：`commons-ground/winegrowers`）にも入れる（repository_dispatch を送るため）
2. 中継の Worker の変数 `SIEVE` に `{"channel": "提案", "repo": "commons-ground/winegrowers"}` を足し、`DISCORD_CHANNELS` に `提案` が入っているかを確かめる
3. 中継を置き直す（`router.js`）

## 篩の係にできること・できないこと

| できる | できない |
| --- | --- |
| gh で読む（issue・pr の一覧と中身、検索）、git の手元の操作（ブランチ、commit） | gh の書き込みと git push を直接すること（門 `safe.py` を通す） |
| 門を通して、カード・コメント・ラベル・プルリクエストを作る、Discord に書く | 個人や事業の情報らしき文字・鍵の値を含む文を書くこと（門が止める） |
| 門を通して、ラベル「人の確認」を付ける | ラベル「人の確認」を外すこと、main への push、Web 検索 |
