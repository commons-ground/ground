// discord-ai-member の受け口（Cloudflare Worker）
//
// Discord のスラッシュコマンド（/ai）を受けて、すぐに「考え中…」を返し、
// GitHub の repository_dispatch でコモンズのリポジトリに渡す。Claude の鍵は持たない。
// 返事は runner が、Discord から渡された一時的な合鍵（interaction token、15分有効）で書き戻す。
//
// 必要な設定（Cloudflare の Worker の設定画面）
//   変数    DISCORD_PUBLIC_KEY … Discord 開発者画面「一般情報」の公開キー（秘密ではない）
//   変数    REPO               … 宛先リポジトリ（例 commons-ground/winegrowers）
//   Secret  GITHUB_TOKEN       … 宛先リポジトリに dispatch できるトークン
//
// Discord の開発者画面の「Interactions Endpoint URL」に、この Worker の URL を入れる。

const PING = 1;
const APPLICATION_COMMAND = 2;
const PONG = 1;
const DEFERRED_CHANNEL_MESSAGE = 5;

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("ok");
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

    // 2. 質問と、聞いた人の呼び名を取り出す
    const options = Object.fromEntries((body.data?.options || []).map((o) => [o.name, o.value]));
    const user = body.member?.user || body.user || {};
    const payload = {
      event_type: "discord-interaction",
      client_payload: {
        command: body.data?.name || "",
        question: String(options.question || options["質問"] || ""),
        application_id: body.application_id,
        token: body.token,
        channel_id: body.channel_id || "",
        guild_id: body.guild_id || "",
        user_id: user.id || "",
        user_name: body.member?.nick || user.global_name || user.username || "",
      },
    };

    // 3. Discord には3秒以内に答える決まりなので、「考え中…」を先に返し、GitHub への受け渡しは後ろで行う
    ctx.waitUntil(dispatch(env, payload));
    return json({ type: DEFERRED_CHANNEL_MESSAGE });
  },
};

async function dispatch(env, payload) {
  const res = await fetch(`https://api.github.com/repos/${env.REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "discord-ai-member",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (res.ok) return;
  // GitHub に渡せなかったら、「考え中…」のままにせず、その場で知らせる
  console.log(`dispatch failed: ${res.status}`);
  const { application_id, token } = payload.client_payload;
  await fetch(`https://discord.com/api/v10/webhooks/${application_id}/${token}/messages/@original`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: "いまAIを呼び出せませんでした。少し待って、もう一度 /ai で聞いてください。",
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
