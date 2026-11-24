# はじめかた

自分の Claude で、コモンズのスキルを使い始める手順です。Claude と Notion のアカウントがあれば、15分ほどで終わります。仕組みの説明は [コモンズのしくみ](how-commons-work.md) にあります。

Claude を契約していない人は、この手順は要りません。家庭や会社のコモンズに AI がいれば、Notion のコメントで「@AI の名前」と書くだけで使えます。

## あなたがやること

画面の表示が英語のときは、かっこ内の言葉を探してください。

1. **Claude のプランを確かめる**（1分）
   プラグインは有料プラン（Pro 以上）で使えます。無料プランなら、Claude の設定画面から Pro に切り替えます（2026年11月時点で月20ドル）。
2. **Claude に Notion をつなぐ**（3分）
   「カスタマイズ（Customize）」→「コネクタ（Connectors）」で Notion を選び、「接続」を押して、Notion の画面で許可します。
3. **コモンズのスキルを入れる**（5分）
   1. 「カスタマイズ」→「プラグイン（Plugins）」→ 右上の「＋追加（Add）」→「マーケットプレイスを追加（Add marketplace）」→「リポジトリから追加（Add from a repository）」
   2. URL の欄に `commons-ground/ground` と入れて「同期（Sync）」を押す。ワイン生産者は、同じ手順で `commons-ground/winegrowers` も足す
   3. 一覧に出てきたプラグインの「追加（Add）」を押す。迷ったら、まず「基盤」だけ入れる
4. **話し合いの場と入口をつなぐ**（5分。ワイン生産者など、個別のコモンズに入る人）
   1. 世話役から届いた招待リンクで、コモンズの Discord サーバーに入る。Discord のアカウントが無ければ、その画面で作れます
   2. Discord の `#一般` のピン留めにある「入口（コネクタ）の URL」をコピーする
   3. Claude の「カスタマイズ」→「コネクタ」→「＋」→「カスタムコネクタを追加（Add custom connector）」で、名前にコモンズの名前（例：`Winegrowers Commons`）、URL に2の URL を入れる
   4. 「接続（Connect）」→「Discord でログインしてつなぐ」→ Discord の画面で「認証（Authorize）」

   これで自分の Claude から、コモンズの知識の置き場と Discord を読み書きできます。「Discord で最近何話してた？」と聞けば確かめられます。
5. **使ってみる**（5分）
   新しいチャットで、たとえば「来週の打ち合わせのメモを、人間向けの資料づくりのスキルで、分かりやすい Notion ページにして」と頼みます。
6. **気づいたら Claude に言う**
   「ここが違う」「こうしてほしい」と思ったら、そのまま Claude に言ってください。何か作ったら「Discord に共有して」と言えば、仲間に知らせます。

## あとは自動で

- 誰かがスキルを直すと、次の日から自分の Claude にも届きます（「自動で同期」が最初からオン）
- 入れたプラグインは、どのチャット・どのプロジェクトでも効きます
- 6で言ったことのうち、ほかの人にも効くものは、Claude が名前や金額を抜いて、土台への提案にまとめます。GitHub につないでいなければ、Discord の `#スキルの相談` に提案として書き、つないでいる人の Claude が拾います
- 打ち合わせの記録（Notion の AI ミーティングノートなど）を Claude に渡して「この打ち合わせから仕組みを改善して」と言えば、出たアイデアを試しに入れます

入っているプラグインの一覧は [README](../README.md) にあります。

<details>
<summary>スキルを自分で直す側にも加わりたいとき</summary>

GitHub の団体 `commons-ground` に入ります。招待メール（件名に `commons-ground` が入ったもの）を開き、GitHub のアカウントが無ければメールのボタンから作って、「Join commons-ground」を押します。入らなくても、気づいたことは Claude に言えば足ります（提案は Discord 経由で届きます）。

直す側に加わるには、2つの準備が要ります。どちらも1回だけです。

1. **GitHub の団体 `commons-ground` に入る**（上の招待メールから）。招待は、団体のオーナーに GitHub のユーザー名かメールアドレスを伝えて送ってもらいます
2. **Claude に GitHub をつなぐ**：[claude.ai/code](https://claude.ai/code) を開き、「GitHub でサインイン（Sign in with GitHub）」を押して、GitHub の画面で許可します。Claude の GitHub アプリは団体に入れてあるので、自分で入れる必要はありません

これで、Claude に「このスキルをコモンズに提案して」と言えば、Claude がブランチを作ってプルリクエストを出すところまで進めます。出す先は、業種を問わないものは `commons-ground/ground`、ワイン生産者に固有のものは `commons-ground/winegrowers` です。

つないだのに Claude が「GitHub につながっていない」と言うときは、その会話が GitHub を使えない種類のものです。Code（クラウドのセッション）で新しく始めて、リポジトリに `commons-ground/ground` か `commons-ground/winegrowers` を選んでください。

</details>
