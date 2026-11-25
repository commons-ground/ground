# 試行一覧

トライアル期間のあいだ、話し合いや使い方から出たアイデアは、まず入れてみて、おかしければ取り下げる。ここはその一覧。足し方と見直し方は core の harvest と sieve スキルにある。載せるのは影響が中以上のもの（[篩](sieve.md)）。

- **状態**：試行中 → 定着 か 取り下げ
- **見直し**：入れてから1か月が目安。分からなければ1か月延ばし、2回延ばしたら取り下げる
- **出どころ**：人の名前は書かず、「参加者」「世話役」などの役割で書く（公開のリポジトリなので）
- 11月に入れた試行は、年末に見直しが重ならないよう、1月中旬の「棚卸しの会」（Discord の通話）でまとめて見直す。会で出た〔提案〕は、人が見てから篩に回す

| 入れた日 | 何を | 出どころ | 場所 | 見直し | 状態 |
| --- | --- | --- | --- | --- | --- |
| 2026-11-24 | 会議・Discord・会話から改善を拾って入れる（core の harvest） | 参加者の打ち合わせ | ground `plugins/core/skills/harvest` | 2027-01-15 | 試行中 |
| 2026-11-24 | 各自の Claude から Discord を読み書きし、作ったものを知らせる（core の commons-chat） | 参加者の打ち合わせ | ground `plugins/core/skills/commons-chat` | 2027-01-15 | 試行中 |
| 2026-11-24 | スキルに加えて、知識とアプリも共有する（propose-change の7、`docs/apps/`） | 参加者の打ち合わせ | ground `plugins/core/skills/propose-change` | 2027-01-15 | 試行中 |
| 2026-11-24 | GitHub につないでいない人の提案を Discord の「〔提案〕」で受ける | 参加者の打ち合わせ | ground `plugins/core/skills/propose-change`・`commons-chat` | 2027-01-15 | 試行中 |
| 2026-11-24 | はじめかたに「Discord に入り、入口を Discord でログインしてつなぐ」を足す | 参加者の打ち合わせ | ground `docs/getting-started.md`・`docs/index.html` | 2027-01-15 | 試行中 |
| 2026-11-24 | 知識コモンズの入口に「Discord でログイン」（参加者コードを配らなくてよい） | 参加者の打ち合わせ | winegrowers `servers/commons-mcp` | 2027-01-15 | 試行中 |
| 2026-11-25 | GitHub の `@claude` に、Discord の AI と同じふるまい・覚えていることで答える。やりとりの「〔覚えておく〕」を harvest で `memory.md` に戻す | 世話役 | ground `tools/ai-member`・`.github/workflows/github-ai*.yml` | 2027-01-15 | 試行中 |
| 2026-11-25 | Discord の通話を `/record` で録り、文字起こし・議事録・〔提案〕まで自動で出す | 世話役の依頼 | ground `tools/discord-meeting` | 2027-01-15 | 試行中 |
| 2026-11-25 | Discord での AI とのやり取りをコマンドにそろえる（/ai・/propose・/record・/help・「コモンズに提案」） | 世話役の依頼 | ground `tools/discord-ai-member` | 2027-01-15 | 試行中 |
| 2026-11-25 | 提案の置き場を Discord の `#提案` に1本化（書けば提案、/propose・「コモンズに提案」も `#提案` に載る） | 世話役（Discord） | ground `tools/discord-ai-member` | 2027-01-15 | 試行中 |
| 2026-11-25 | 篩（ふるい）：提案を篩のカード（Issue）にまとめ、一般化し、影響の小・中・大で振り分けてから入れる。小は試行一覧にも Discord にも出さない | 世話役の依頼 | ground `plugins/core/skills/sieve`・`tools/sieve`・`docs/sieve.md` | 2027-01-15 | 試行中 |
| 2026-11-25 | 篩に3つ足す：`#提案` に直接書いた発言を中継の見回りで拾う、書き込みの前の機械の点検（門 `safe.py`）、見直しで 👍・👎 を7日聞く | 世話役 | ground `tools/sieve`・`tools/discord-agents/router.js`・`plugins/core/skills/sieve` | 2027-01-15 | 試行中 |
| 2026-11-24 | 自動で動く仕組みは「出来事 → すでにある見回りへの相乗り → 新しい定期実行」の順で起こし方を選ぶ（making-skills の7） | 世話役 | ground `plugins/core/skills/making-skills` | 2027-01-15 | 試行中 |
| 2026-11-25 | Discord で `@コモンズのAI` とメンションしても、`/ai` と同じ AI が返信で答える（中継の毎分の見回りに相乗り。篩のカード winegrowers#16） | 参加者（Discord） | ground `tools/discord-agents/router.js`・`tools/discord-ai-member/run.py` | 2027-01-15 | 試行中 |
| 2026-11-26 | Claude Code の装置を ground に返し・取り込む仕組み（apparatus の growth-loop）と、最初の取り込み（core の grounding・premise-doubt・thesis-first・step-fidelity・expert-questions、apparatus の adr-authoring と hook 2本） | 世話役の依頼 | ground `plugins/apparatus`・`plugins/core`・`docs/apparatus.md` | 2027-01-15 | 試行中 |
