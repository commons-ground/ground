// Discord のコマンドの受け口（中継 router.js の /interactions）
//
// Discord のコマンド（tools/discord-ai-member/commands.json）を受ける。どのコマンドも、ここで3秒以内に一言返す。
//   /ai        … 「考え中…」を返し、repository_dispatch（discord-interaction）でリポジトリの Claude に渡す
//   /record start … 「準備しています」を返し、repository_dispatch（discord-record）で録音の仕事を起こす
//   /record stop … 「⏹ 録音を止めます」と書く。録音中のボットがこの書き込みを合図に止まる
//   /propose   … repository_dispatch（discord-propose）で、Actions が #提案 に載せる。篩の仕組みがあとで拾う
//   メッセージの「アプリ」→「コモンズに提案」… その発言を、同じように #提案 に載せる
//   /help    … コマンドの一覧（本人にだけ見える）
// 以前は別の Worker（commons-discord-hook）だったが、Discord の玄関を1つにするため中継に寄せた（#72）。
// GitHub への受け渡しは、中継がコモンズの GitHub アプリ（Commons Agents）として、1時間だけの鍵で行う。
//
// 必要な設定（中継の Worker）
//   変数 DISCORD_PUBLIC_KEY … Discord 開発者画面「一般情報」の公開キー（秘密ではない）
//   変数 COMMANDS_REPO      … 宛先リポジトリ（例 commons-ground/winegrowers）
// Discord の開発者画面の「Interactions Endpoint URL」に、中継の URL ＋ /interactions を入れる。

const PING = 1;
const APPLICATION_COMMAND = 2;
const PONG = 1;
const CHANNEL_MESSAGE = 4;
const DEFERRED_CHANNEL_MESSAGE = 5;
const EPHEMERAL = 64;
const STOP_MARK = "⏹ 録音を止めます"; // record.mjs と合わせる

// /help の中身。commands.json を変えたら、ここも合わせる
const HELP = [
  "**コモンズのAIのコマンド**",
  "`@コモンズのAI 質問` … 会話の中で聞く。読んだら 👀 が付き、1〜2分で元の発言への返信が来る。その返信にリプライすれば続けて聞ける",
  "`/ai 質問` … 単発で聞く。すぐ「考え中…」が出て、質問を引用した答えに書き換わる（ほかの人の会話に割り込まずに聞きたいとき、急ぎのとき）",
  "`/propose 内容` … 提案を #提案 に載せる。#提案 に直接書いても提案になる（篩にかけてから入る）",
  "`/record start` → `/record stop` … 入っているボイスチャンネルを録り、文字起こし・議事録・改善の提案まで作る（全員抜けても止まる）",
  "発言の「…」→「アプリ」→「コモンズに提案」… その発言を #提案 に載せる",
  "入ったものを戻したいとき … #提案 に「〇〇を取り下げて」と書く（すぐ戻すプルリクエストが出る）",
  "自分の Claude からは「Discord で何話してた？」「Discord に共有して」で読み書きできる",
].join("\n");

// send(payload, failText)：GitHub に渡す係（中継が用意する）。渡せなかったら notifyFail で知らせる
export async function handleInteraction(request, env, ctx, send) {
  const raw = await request.text();

  // 1. 署名の確認。Discord は URL を登録するときに、わざと壊した署名も送って確かめに来る
  const sig = request.headers.get("X-Signature-Ed25519") || "";
  const ts = request.headers.get("X-Signature-Timestamp") || "";
  if (!(await validSignature(env.DISCORD_PUBLIC_KEY, sig, ts, raw))) {
    return new Response("bad signature", { status: 401 });
  }

  const body = JSON.parse(raw);
  if (body.type === PING) return json({ type: PONG });
  if (body.type !== APPLICATION_COMMAND) return json({ type: PONG });

  const user = body.member?.user || body.user || {};
  const userName = body.member?.nick || user.global_name || user.username || "";
  const name = body.data?.name || "";
  const sub = body.data?.options?.find((o) => o.type === 1);
  const options = Object.fromEntries(((sub ? sub.options : body.data?.options) || []).map((o) => [o.name, o.value]));
  const base = {
    application_id: body.application_id,
    token: body.token,
    channel_id: body.channel_id || "",
    guild_id: body.guild_id || "",
    user_id: user.id || "",
    user_name: userName,
  };
  const say = (content, ephemeral = false) =>
    json({ type: CHANNEL_MESSAGE, data: { content, allowed_mentions: { parse: [] }, ...(ephemeral ? { flags: EPHEMERAL } : {}) } });

  // 2. コマンドごとに振り分ける
  if (name === "ai") {
    const payload = { event_type: "discord-interaction", client_payload: { ...base, command: "ai", question: String(options.question || "") } };
    // Discord には3秒以内に答える決まりなので、「考え中…」を先に返し、GitHub への受け渡しは後ろで行う
    ctx.waitUntil(send(payload, "いまAIを呼び出せませんでした。少し待って、もう一度 /ai で聞いてください。"));
    return json({ type: DEFERRED_CHANNEL_MESSAGE });
  }
  if (name === "record" && sub?.name === "start") {
    const payload = { event_type: "discord-record", client_payload: { ...base, command: "record" } };
    ctx.waitUntil(send(payload, "録音を始められませんでした。少し待って、もう一度 `/record start` を打ってください。"));
    return say("⏳ 録音の準備をしています（ボットが入るまで1分ほど）。");
  }
  if (name === "record" && sub?.name === "stop") {
    return say(`${STOP_MARK}（${userName || "参加者"}さん）。文字起こしと議事録は、できしだい #議事録 に置きます。`);
  }
  if (name === "propose" || name === "コモンズに提案") {
    let extra = { text: String(options.text || "") };
    if (name === "コモンズに提案") {
      const target = body.data?.resolved?.messages?.[body.data?.target_id];
      if (!target?.content) return say("その発言には、提案にできる文がありません。", true);
      extra = {
        text: target.content,
        source_author: target.author?.global_name || target.author?.username || "",
        source_link: `https://discord.com/channels/${body.guild_id}/${body.channel_id}/${target.id}`,
      };
    }
    // 提案は #提案 にまとめる。ほかのチャンネルに書くにはボットの鍵が要るので、Actions に渡す
    const payload = { event_type: "discord-propose", client_payload: { ...base, command: "propose", ...extra } };
    ctx.waitUntil(send(payload, "提案を受け付けられませんでした。少し待って、もう一度出してください。"));
    return say("📮 提案を受け付けました。#提案 に載せます（30秒ほど）。", true);
  }
  if (name === "help") return say(HELP, true);
  return say("そのコマンドは、まだこのボットが知りません。`/help` で一覧を見られます。", true);
}

// GitHub に渡せなかったら、「考え中…」のままにせず、その場で知らせる
export async function notifyFail(payload, failText) {
  const { application_id, token } = payload.client_payload;
  await fetch(`https://discord.com/api/v10/webhooks/${application_id}/${token}/messages/@original`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: failText,
      allowed_mentions: { parse: [] },
    }),
  }).catch(() => {});
}

function json(obj) {
  return new Response(JSON.stringify(obj), { headers: { "Content-Type": "application/json" } });
}

async function validSignature(publicKeyHex, sigHex, timestamp, raw) {
  if (!publicKeyHex || !sigHex || !timestamp) return false;
  try {
    const data = new TextEncoder().encode(timestamp + raw);
    const sig = hexToBytes(sigHex);
    const keyBytes = hexToBytes(publicKeyHex);
    let key;
    try {
      key = await crypto.subtle.importKey("raw", keyBytes, { name: "Ed25519" }, false, ["verify"]);
      return await crypto.subtle.verify({ name: "Ed25519" }, key, sig, data);
    } catch {
      // 古い Workers の書き方
      key = await crypto.subtle.importKey(
        "raw", keyBytes, { name: "NODE-ED25519", namedCurve: "NODE-ED25519" }, false, ["verify"],
      );
      return await crypto.subtle.verify("NODE-ED25519", key, sig, data);
    }
  } catch {
    return false;
  }
}

function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}
