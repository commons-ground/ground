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
- 宣言が効くのは、そのフォルダを信頼したときだけ（信頼していないフォルダでは黙って無視される）
- `-p` や CI の実行では、プラグインが裏で入るので最初の1回に間に合わないことがある。待たせるときは環境変数 `CLAUDE_CODE_SYNC_PLUGIN_INSTALL=1`
- 公式の説明：https://code.claude.com/docs/en/plugins/org （リポジトリごとに必須にする節）

## apparatus の hook を止めたいとき

Claude Code には、プラグインの hook を1本だけ外す設定が無い。だから apparatus の hook は、次のファイルに名前が書いてあると何もしない。

```
.claude/state/hooks-off      # そのリポジトリだけ（gitignore 推奨）
~/.claude/hooks-off          # その端末の全部
```

1行に1つ、hook の名前（`wait-loop-guard` など）か `all` を書く。行を消せば戻る。

プラグインごと止めるときは `enabledPlugins` の `apparatus@ground` を `false` にする。
