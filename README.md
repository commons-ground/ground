# ground

いろいろなコモンズ（家庭、会社、ワイン生産者の集まりなど）の土台になる、Claudeの共有基盤です。ワイン生産者に固有のもの（畑・栽培のスキル、知識コモンズの入口）は [commons-ground/winegrowers](https://github.com/commons-ground/winegrowers) にあります。考え方は Notion の「コモンズの土と植物」。

スキル（AIへの作業手順書）、DBの設計図、基本ルールを、ここでみんなで共有して直していきます。各自の事業データはここには入れず、それぞれのNotion・freee・Google Driveに置いたままにします。

はじめかたは [docs/getting-started.md](docs/getting-started.md)、全体の設計は [docs/design.md](docs/design.md)、向かう方角は [docs/north-star.md](docs/north-star.md) にあります。

## 入れ方

Claude（アプリ）では、カスタマイズ → プラグイン → マーケットプレイスを追加 で `commons-ground/ground` を指定し、使うプラグインを入れます。

Claude Code では次の1行です。

```
/plugin install core --marketplace commons-ground/ground
```

## いま入っているもの

| プラグイン | 中身 |
| --- | --- |
| core（基盤・必須） | 基本ルール（basic-rules）、人に確認する線引き（when-to-ask）、人間向けの資料づくり（writing-for-humans）、情報の構造の読み取り（structure-reading）、図解（diagram） |
| research（調べる・確かめる） | ポッドキャストの回の文字起こしと解説（podcast-notes）。文字起こしは共有のワークフロー（`.github/workflows/podcast-transcribe.yml`）を各自の非公開リポジトリから呼んで動かす |

畑・醸造・販売・経理・補助金などの分野別プラグインは、これから順に足します。

research を入れるときは、`/plugin install research --marketplace commons-ground/ground`。

## 直し方

- 使っていて「ここ違う」「これ足りない」と思ったら、Claudeに伝えるか、このリポジトリにIssueを立ててください
- 変更はプルリクエストで入れます。作業のルールは `CLAUDE.md` にあります
