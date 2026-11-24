# 試行一覧

トライアル期間のあいだ、話し合いや使い方から出たアイデアは、まず入れてみて、おかしければ取り下げる。ここはその一覧。足し方と見直し方は core の harvest スキルにある。

篩（core の sieve）を通して入った試行は、ここには書かず、各コモンズの提案箱の Issue（ラベル `ふるい:試行中`）を正本にする：[ground](https://github.com/commons-ground/ground/issues?q=label%3A%22%E3%81%B5%E3%82%8B%E3%81%84%3A%E8%A9%A6%E8%A1%8C%E4%B8%AD%22)・[winegrowers](https://github.com/commons-ground/winegrowers/issues?q=label%3A%22%E3%81%B5%E3%82%8B%E3%81%84%3A%E8%A9%A6%E8%A1%8C%E4%B8%AD%22)

- **状態**：試行中 → 定着 か 取り下げ
- **見直し**：入れてから1か月が目安。分からなければ1か月延ばし、2回延ばしたら取り下げる

| 入れた日 | 何を | 出どころ | 場所 | 見直し | 状態 |
| --- | --- | --- | --- | --- | --- |
| 2026-11-24 | 会議・Discord・会話から改善を拾って入れる（core の harvest） | 旭さんとの打ち合わせ | ground `plugins/core/skills/harvest` | 2026-12-24 | 試行中 |
| 2026-11-24 | 各自の Claude から Discord を読み書きし、作ったものを知らせる（core の commons-chat） | 旭さんとの打ち合わせ | ground `plugins/core/skills/commons-chat` | 2026-12-24 | 試行中 |
| 2026-11-24 | スキルに加えて、知識とアプリも共有する（propose-change の7、`docs/apps/`） | 旭さんとの打ち合わせ | ground `plugins/core/skills/propose-change` | 2026-12-24 | 試行中 |
| 2026-11-24 | GitHub につないでいない人の提案を Discord の「〔提案〕」で受ける | 旭さんとの打ち合わせ | ground `plugins/core/skills/propose-change`・`commons-chat` | 2026-12-24 | 試行中 |
| 2026-11-24 | はじめかたに「Discord に入り、入口を Discord でログインしてつなぐ」を足す | 旭さんとの打ち合わせ | ground `docs/getting-started.md`・`docs/index.html` | 2026-12-24 | 試行中 |
| 2026-11-24 | 知識コモンズの入口に「Discord でログイン」（参加者コードを配らなくてよい） | 旭さんとの打ち合わせ | winegrowers `servers/commons-mcp` | 2026-12-24 | 試行中 |
| 2026-11-25 | GitHub の `@claude` に、Discord の AI と同じふるまい・覚えていることで答える。やりとりの「〔覚えておく〕」を harvest で `memory.md` に戻す | ひろしさん | ground `tools/ai-member`・`.github/workflows/github-ai*.yml` | 2026-12-25 | 試行中 |
| 2026-11-25 | Discord の通話を `/record` で録り、文字起こし・議事録・〔提案〕まで自動で出す | ひろしさんの依頼 | ground `tools/discord-meeting` | 2026-12-25 | 試行中 |
| 2026-11-25 | Discord での AI とのやり取りをコマンドにそろえる（/ai・/propose・/record・/help・「コモンズに提案」） | ひろしさんの依頼 | ground `tools/discord-ai-member` | 2026-12-25 | 試行中 |
| 2026-11-25 | 提案の置き場を Discord の `#提案` に1本化（書けば提案、/propose・「コモンズに提案」も `#提案` に載る） | ひろしさん（Discord で） | ground `tools/discord-ai-member` | 2026-12-25 | 試行中 |
| 2026-11-25 | 提案を篩（ふるい）にかけてから入れる：提案箱（Issue）、重なりのまとめ、一般化、影響（小・中・大）での振り分け、👍・👎 での見直し（core の sieve、`tools/sieve`） | ひろしさんの依頼 | ground `plugins/core/skills/sieve`・`tools/sieve`・`docs/sieve.md` | 2026-12-25 | 試行中 |
