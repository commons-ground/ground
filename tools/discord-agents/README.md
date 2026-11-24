# discord-agents（各自の分身の AI）

コモンズの Discord で、参加者それぞれの「分身の AI」を呼べるようにする仕組みです。`@ひろしのAI 〇〇を調べて` のように AI 用のロールをメンションすると、その人の分身が、その人の Claude のサブスクで動いて答えます。分身どうしのやりとりもできます。

## 呼び方

| 書き方 | 意味 | 動き |
| --- | --- | --- |
| `@ひろし` | 人への連絡 | 人に通知が届く。各自の Claude は、コネクタの受け取り箱（`discord_inbox`）で開いたときに読む |
| `@ひろしのAI` | その人の分身への依頼 | 人には通知しない。分身がすぐ動いて、同じ場所に答える |
| `/ai`、または `@コモンズのAI` | コモンズ共通の AI | `discord-ai-member` が答える（メンションは中継が1分以内に拾い、元の発言に返信する） |

AI 用のロールは、誰にも付けないメンション専用のロールです。

## 流れ

```
@ひろしのAI 〇〇
  → 中継（Cloudflare Worker、router.js）が1分おきに見つける
  → 持ち主のリポジトリに repository_dispatch
  → 持ち主のリポジトリの workflow → ground の discord-agent.yml
      公式の Claude Code GitHub Action が、持ち主の Claude のサブスクで答えを作る
  → 中継の /reply に返す → 中継が「🤖 ひろしのAI」と名乗って投稿
```

- 分身は持ち主のリポジトリで、持ち主の鍵で動く。中継もコモンズも、分身の鍵や持ち主の事業データを持たない
- 費用は、持ち主の Claude のサブスクの利用枠から使われる（API の請求ではない）
- Discord はふつうの発言を外に知らせないので、中継が1分おきに見に行く（Cloudflare の Cron トリガー。Claude の定期実行は使わない）

## 篩の入り口も受け持つ

中継は、毎分の見回りのついでに、`#提案` に人が直接書いた発言と、通話の議事録から出た〔提案〕を見つけ、コモンズのリポジトリに `sieve-intake` を送って篩（`tools/sieve`）を起こします。新しい定期実行を足さずに済ませるためです。使うときは、中継の変数 `SIEVE` に `{"channel": "提案", "repo": "commons-ground/winegrowers"}` を足し、そのリポジトリにも GitHub アプリ「Commons Agents」を入れます。

## コモンズのAIへのメンションも受け持つ

`@コモンズのAI 〇〇` とメンションすると、中継が毎分の見回りで見つけ、コモンズのリポジトリに `discord-mention` を送ります。`/ai` と同じ AI（`discord-ai-member`）が、元の発言への返信として答えます。使うときは、中継の変数 `COMMONS_AI` に `{"repo": "commons-ground/winegrowers", "user_id": "ボットのユーザーID"}` を足します。

- 人の発言だけ拾う（ボットどうしの往復は起こさない）。1時間に20回まで
- `#提案` でのメンションは篩が受け持つので拾わない
- 答えが出るまで1〜2分かかる（見回りの間隔と、GitHub Actions の立ち上がり）。急ぐときは `/ai`

## 安全のための決まり

- 分身ができることは、依頼した人で変わる（`agent.md`）。持ち主本人からでも、持ち主のデータへの書き込みや外への送信は、返事で確かめてから
- ほかの参加者や AI には、持ち主の事業データを出さない
- AI どうしの往復は3回まで。自分に自分で答えない。1つの分身が動くのは1時間に20回まで
- 分身の返事が @ で呼べるのは、AI 用ロールと持ち主だけ

## 分身を持つ（各自）

1. GitHub のアカウントを作る（コモンズのスキルを直す側に加わるときにも使う）
2. 雛形 [commons-ground/agent-template](https://github.com/commons-ground/agent-template) で「Use this template」→ 自分のアカウントに**非公開（Private）**で作る
3. コモンズの GitHub アプリ「Commons Agents」を、2で作ったリポジトリだけに入れる（インストールの画面で「Only select repositories」）
4. 手元で `claude setup-token` を動かし、出てきたトークンを2のリポジトリの Actions secrets に `CLAUDE_CODE_OAUTH_TOKEN` として入れる
5. 世話役に、2のリポジトリの名前を伝える

トークンや合言葉を世話役に渡すことはありません。中継はアプリとしてそのリポジトリに知らせ、返事は GitHub Actions の身分証明（OIDC）で「そのリポジトリの、ground の `discord-agent.yml` から来たか」を確かめてから投稿します。

## 世話役がすること

1. Discord で AI 用のロール（例：`ひろしのAI`）を作る。メンション可にし、誰にも付けない
2. 中継の Worker の変数 `AGENTS` に `{"ロールID": {"name": "ひろしのAI", "owner": "持ち主のユーザーID", "repo": "持ち主/リポジトリ"}}` を足す
3. コネクタ（受け取り箱）の変数 `DISCORD_AI_ROLES` に `{"持ち主のユーザーID": "ロールID"}` を足す

中継の Worker には、ほかに `DISCORD_GUILD_ID`・`DISCORD_CHANNELS`・`PUBLIC_URL`（中継自身の URL）・`GITHUB_APP_ID` の変数、`DISCORD_BOT_TOKEN`・`GITHUB_APP_PRIVATE_KEY` の Secret、`STATE` の KV、毎分の Cron トリガーが要ります。GitHub アプリ「Commons Agents」の権限は Contents の Read and write だけです（repository_dispatch を送るのに GitHub が求める権限）。
