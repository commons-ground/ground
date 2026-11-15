# 旧案と検討の経緯

いまの形に至るまでに検討して変えた案と、移行の記録。いまの仕組みは [コモンズのしくみ](how-commons-work.md) だけを見ればよい。

## 知識コモンズ

いまの形と、検討して外した案は [commons-ground/winegrowers](https://github.com/commons-ground/winegrowers) の知識コモンズの資料にある。それより前の案は次のとおり。

### 第2案：ゲスト＋毎晩Driveへ書き出し

知識用のNotionワークスペースに参加者をゲストで招き、GitHub Actionsが毎晩DBを共有Driveへ書き出して、各自のClaudeはDrive接続で読む案。AIから書くときは改善提案を経由する。

**変えた理由**：写しができて二重管理になり、最新との差が最大半日あり、AIから直接書けない。自前の入口（MCPサーバー）を置けば、写しなしで読み書きできると分かった。

### 第1案：GitHub・共有Drive・各自の本の3か所に分ける

短い知識はGitHub（プラグインの `knowledge/`）を元にして各自のNotionへ写しを配り、大きな資料は共有Driveフォルダ、本は各自のDriveに置いて索引だけ共有する案。

**変えた理由**：知識は量が多く、参考文献と個別の情報をリレーションで結ぶ必要があり、GitHubのファイルでは人が一覧で管理できない。

## プラグインの分け方

### 最初の案：いまの資産から分けた7本

core、research、labor、freee、vineyard、cellar / sales、guard。

**変えた理由**：いまある資産から分けると、ほかの生産者に要るものが抜け、分野の境目もぶれる。ワイン生産者が関わる分野から分け直した（いまの11本）。

## 育て方

### 最初の案：気づく→ためる→運ぶ→確かめる→配る→棚卸し

確かめるのを「提案者以外の1人の確認」で毎回人が行う案。

**変えた理由**：人の手番が多い。審査ルールとテストで機械的に判定し、人は危険度の高い変更だけを見る形に変えた（いまの自動改善ループ）。3か月ごとの棚卸し（2人とも同じ自分ルールを書いていたら共有に上げる）は、見張り係の点検に含めた。

## 前提として整理した、Notionの中身の4種類

| 種類 | 例 | 行き先 |
| --- | --- | --- |
| 事業データ | スタッフ名簿・出勤簿・給与・ワイン一覧・所有機械・作業記録 | 共有しない。各自のNotion・freee・Drive |
| DBの構造 | 勤怠・給与管理テンプレート（データなし版）、機械×整備ログ×部品 | DBの設計図としてこのリポジトリへ |
| AIの装置 | スキルDB・検証の共通部品・AIの誤りやすいパターン集など | 汎用部分だけ共有プラグインへ |
| 知識 | 資材・肥料・病害虫・微生物・参考文献などの一覧 | 知識コモンズへ |

## 名前と置き場の変更（2026-11-16）

- 最初は「ワイン生産者どうしで育てる共有基盤」として、団体 `winegrowers-commons` のリポジトリ `wine-ai-commons` 1つに全部を置いていた
- 家庭や会社のコモンズも同じ仕組みで作ることになり、業種を問わない土台を `commons-ground/ground`、ワイン生産者に固有のもの（grape、知識コモンズの入口）を `commons-ground/winegrowers` に分けた。古い URL は GitHub が転送する
- 最初の2社向けに書いた「全体設計」は、[コモンズのしくみ](how-commons-work.md) と、winegrowers の資料に分けて書き直した

## 2人＋AIで話す場所

Discord に決めた（2026年11月）。無料で、やり取りが消えず、AI から読み書きできる。決まったこと・残す知識は Discord に置きっぱなしにせず、Notion かリポジトリに移す。

| 外した案 | 理由 |
| --- | --- |
| Slack（無料） | 見られる履歴が直近90日で、1年を超えると消える。Claude の公式の Slack 連携は有料の Slack が前提 |
| Google チャット | Google 公式の接続はあるが試験段階で、Google Cloud の設定が要る |
| LINE・Messenger | AI からやり取りを読めない |
| Chatwork | 使いづらい |
| Notion の共有ワークスペースで話す | チャットには向かない。ためる場所として使う |

## 移行の記録：Notion のプロンプトDBから（2026年11月）

最初の参加者の Notion のプロンプトDB（29件）を確かめ、共有できるものをコモンズへ移した。移したものの正本はこのリポジトリで、Notion には `tools/notion-skill-sync/` が写しを入れる。

事業者ごとの事情（会社名、定款の条文、人名、DBのID、トンマナ）は外し、🧭 AI設定ページの自分ルールと接続表から読む形にした。

### 移したもの

| 元のプロンプト | 移した先 |
| --- | --- |
| 科学調査 | research の science-research |
| Deep Research | research の wide-research（総力調査と合わせた） |
| 参考文献登録 | research の reference-registration |
| 参考文献ページ点検 | research の reference-inspection |
| 参考文献照合チェック | research の citation-check |
| 科学的主張ファクトチェック | research の fact-check |
| 論理整合チェック | research の logic-check |
| 醸造技術 誤りパターン点検 | research の error-patterns |
| ページ検証オーケストレータ | research の page-review |
| 検証共通原則・検証出力スキーマ・主張検証共通基盤・書誌正規化ルール（部品） | research の verification-basics |
| 多言語PDF・Webページ 日本語翻訳 | research の translation |
| 問いづくり | team の question-design |
| 理事会議事録 生成 | team の board-minutes |
| 機械整備項目・部品登録 | equipment の maintenance-setup |
| [月次] 当月分の出勤簿（予定）自動生成 | labor の attendance-plan |
| [月次] 前月分の給与支給記録 作成・更新 | labor の payroll-record |
| ビンテージ一覧生成 | grape の vintage-summary（いまは winegrowers） |
| 税務リスクチェック、節税スキーム査察レビュー | finance の tax-risk-review（会社の前提は自分ルールへ） |

### core に置き換わったもの

| 元のプロンプト | 置き換え先 |
| --- | --- |
| 文体改善、構成リファクタ、文体抽出メタプロンプト | core の writing-for-humans と structure-reading（page-review の文体・構成の段もこれを使う） |

元のプロンプトにあって core に無い細かい手順（中心命題の木、寄与度による置き場の判定など）は、使ってみて要ると分かったら core への提案にする。

### 各自に残すもの（共有しない）

| 元のプロンプト | 理由 |
| --- | --- |
| ワイン紹介文（データシート・Web）、テイスティングコメント | 自社のワインとトンマナに強く結びつく（各自のスキルDBに置く） |
| 資金繰り×節税シミュレーション | 自社の数値の前提が中心（汎用部分は finance の cash-flow と tax-risk-review） |
| レシピ生成、InBody 測定結果の解析 | 事業と関係ない個人の用途 |
| Vikipedia のサブページ移行、Notion 数式レンダリング修正 | 1つのワークスペースの整備作業 |

### 移したあとの元のページ

元のページは名前も中身も変えずに残し、移した先はこの表にだけ書く。2026-11-14 に名前の頭へ「（移行済み→…）」を付けたが、ほかのセッションから名前で見つけられなくなったため、2026-11-15 に元の名前へ戻した。2026-11-15 に、元のページ21件の「スキル」の指定を外した（中身は残っている）。Notion AI が同じスキルを使えるようになるのは、`tools/notion-skill-sync/` の同期を設定してから。元のページは、しばらく困らなければ本人が消す。

### Claude のアカウントのスキルからの移行（2026-11-15）

| 元のスキル | 移した先 |
| --- | --- |
| kagaku-chosa | research の science-research |
| souryoku-chosa | research の wide-research |
| podcast-kaisetsu | research の podcast-notes |
| toi-zukuri | team の question-design |
| slide-zukuri | team の slide-design（自分流の配色・道具は自分ルールへ） |
| jichitai-mirai-data | 各自のNotionのスキルDB（ワインとは別の仕事のため共有しない） |
