# リポジトリに ground をつなぐ

リポジトリの `.claude/settings.json` に次を足す。マーケットプレイスの名前（キー）は ground の `marketplace.json` の `name` で、`ground`。

```json
{
  "extraKnownMarketplaces": {
    "ground": {
      "source": { "source": "github", "repo": "commons-ground/ground" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "core@ground": true,
    "apparatus@ground": true
  }
}
```

- `autoUpdate: true` で、ground の更新が裏で取り込まれ、次のセッションから効く
- ワイン生産者のリポジトリなら、`winegrowers` も同じ形で足す（`"repo": "commons-ground/winegrowers"`）
- クラウドのセッションに届くかは、公式の説明で確かめきれていない（growth-loop の9）
- 宣言が効くのは、そのフォルダを信頼したときだけ（信頼していないフォルダでは黙って無視される）
- `-p` や CI の実行では、プラグインが裏で入るので最初の1回に間に合わないことがある。待たせるときは環境変数 `CLAUDE_CODE_SYNC_PLUGIN_INSTALL=1`
- 公式の説明：https://code.claude.com/docs/en/plugins/org （リポジトリごとに必須にする節）

## apparatus の hook を止めたいとき

Claude Code には、プラグインの hook を1本だけ外す設定が無い。だから apparatus の hook は、次のファイルに名前が書いてあると何もしない。

```
.claude/state/hooks-off      # そのリポジトリだけ（gitignore 推奨。作業フォルダ（git worktree）からも本体のこのファイルを見る）
~/.claude/hooks-off          # その端末の全部
```

1行に1つ、hook の名前（`wait-loop-guard` など）か `all` を書く。行を消せば戻る。

プラグインごと止めるときは `enabledPlugins` の `apparatus@ground` を `false` にする。

## core を有効にするとき

core を有効にすると、basic-rules（最初に 🧭 AI設定ページを読む、など）や when-to-ask が、そのリポジトリの全セッションに載る。リポジトリにすでに自律の線や止まる条件の決まりがあるなら、`CLAUDE.md` に「このリポジトリの CLAUDE.md と自律の決まりが、ground の core に優先する」と1行書いてから有効にする（basic-rules の0「自分の設定が勝つ」と同じ向き）。迷うなら、先に apparatus だけを有効にする。
