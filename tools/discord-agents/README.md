# discord-agents（各自の分身の AI）

コモンズの Discord で、参加者それぞれの「分身の AI」を呼べるようにする仕組みです。`@ひろしのAI 〇〇を調べて` のように AI 用のロールをメンションすると、その人の分身が、その人の Claude のサブスクで動いて答えます。分身どうしのやりとりもできます。

## 呼び方

| 書き方 | 意味 | 動き |
| --- | --- | --- |
| `@ひろし` | 人への連絡 | 人に通知が届く。各自の Claude は、コネクタの受け取り箱（`discord_inbox`）で開いたときに読む |
| `@ひろしのAI` | その人の分身への依頼 | 人には通知しない。分身がすぐ動いて、同じ場所に答える |
| `/ai` | コモンズ共通の AI | `discord-ai-member` が答える |

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

## 安全のための決まり

- 分身ができることは、依頼した人で変わる（`agent.md`）。持ち主本人からでも、持ち主のデータへの書き込みや外への送信は、返事で確かめてから
- ほかの参加者や AI には、持ち主の事業データを出さない
- AI どうしの往復は3回まで。自分に自分で答えない。1つの分身が動くのは1時間に20回まで
- 分身の返事が @ で呼べるのは、AI 用ロールと持ち主だけ

## 分身を持つ（各自）

1. 自分の**非公開**のリポジトリを作り、`member/discord-agent.yml` を `.github/workflows/` に置く。分身のふるまい（自分の仕事、口調など）を `agent/agent.md` に書いてもよい
2. 手元で `claude setup-token` を動かし、出てきたトークンをそのリポジトリの Actions secrets に `CLAUDE_CODE_OAUTH_TOKEN` として入れる
3. 世話役から受け取った合言葉を `AGENT_REPLY_KEY` として入れる
4. そのリポジトリに dispatch できるトークン（Contents の Read and write、そのリポジトリだけ）を作り、世話役に渡す

## 世話役がすること

1. Discord で AI 用のロール（例：`ひろしのAI`）を作る。メンション可にし、誰にも付けない
2. 中継の Worker の変数 `AGENTS` に `{"ロールID": {"name": "ひろしのAI", "owner": "持ち主のユーザーID", "repo": "持ち主/リポジトリ"}}` を足す
3. Secret の `AGENT_GITHUB_TOKENS`（持ち主から受け取ったトークン）と `AGENT_REPLY_KEYS`（合言葉）に、同じロールIDで足す
4. コネクタ（受け取り箱）の変数 `DISCORD_AI_ROLES` に `{"持ち主のユーザーID": "ロールID"}` を足す

中継の Worker には、ほかに `DISCORD_GUILD_ID`・`DISCORD_CHANNELS`・`PUBLIC_URL`（中継自身の URL）の変数、`DISCORD_BOT_TOKEN` の Secret、`STATE` の KV、毎分の Cron トリガーが要ります。
