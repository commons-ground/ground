// discord-agents の中継（Cloudflare Worker）
//
// コモンズの Discord で「各自の AI」（AI 用のロール、例：@ひろしのAI）がメンションされたら、
// その人のリポジトリに repository_dispatch で知らせる。分身はその人のリポジトリで、その人の
// Claude のサブスク（公式の Claude Code GitHub Action）で動き、答えを /reply に返す。
// 中継は分身の鍵も、その人の事業データも持たない。
//
// Discord はふつうの発言を外に知らせないので、1分おきに（Cloudflare の Cron トリガー）見に行く。
//
// ついでに、篩（tools/sieve）の入り口も受け持つ。提案のチャンネル（#提案）に人が直接書いた発言と、
// 通話の議事録から出た〔提案〕を見つけたら、コモンズのリポジトリに repository_dispatch（sieve-intake）で知らせる。
// 新しい定期実行を足さずに、すでにある見回りに相乗りするため。
//
// 設定（Worker の設定画面。リポジトリには ID や鍵を書かない）
//   変数    DISCORD_GUILD_ID     コモンズの Discord サーバーのID
//   変数    DISCORD_CHANNELS     見るチャンネル名のカンマ区切り（その中のスレッドも見る）
//   変数    AGENTS               JSON {"ロールID": {"name": "ひろしのAI", "owner": "持ち主のユーザーID", "repo": "owner/repo"}}
//   Secret  DISCORD_BOT_TOKEN    ボット「コモンズのAI」の鍵
//   変数    GITHUB_APP_ID        コモンズの GitHub アプリ（Commons Agents）の App ID
//   Secret  GITHUB_APP_PRIVATE_KEY  そのアプリの秘密鍵（.pem の中身）
//   変数    PUBLIC_URL           この中継自身の URL（分身が返事を返す先）
//
// 各自は、自分のリポジトリにコモンズの GitHub アプリを入れるだけでよい（トークンや合言葉を渡さない）。
// 中継はアプリとしてそのリポジトリに dispatch し、返事は GitHub Actions の身分証明（OIDC）で
// 「そのリポジトリの、ground の discord-agent.yml から来たか」を確かめてから投稿する。
//   KV      STATE                どこまで見たか、発言ごとの往復回数
//   変数    SIEVE                （任意）JSON {"channel": "提案", "repo": "commons-ground/winegrowers"}。
//                                あれば篩の入り口を受け持つ。そのリポジトリにも Commons Agents アプリを入れておく。
//                                channel は DISCORD_CHANNELS にも入れておく
//
// 守ること
//   - 分身の返事は「🤖 ひろしのAI」と名乗って投稿する。@ で呼べるのは AI 用ロールと、その分身の持ち主だけ
//   - AI どうしの往復は MAX_HOPS 回まで。自分のロールに自分で答えることはしない
//   - 1つの分身が1時間に動くのは MAX_PER_HOUR 回まで

const API = "https://discord.com/api/v10";
const MAX_HOPS = 3;
const MAX_PER_HOUR = 20;

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(poll(env));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/reply" && request.method === "POST") return reply(request, env);
    return new Response("discord-agents");
  },
};

const json = (s, fallback) => {
  try {
    return JSON.parse(s || "");
  } catch {
    return fallback;
  }
};

async function discord(env, method, path, body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bot ${env.DISCORD_BOT_TOKEN}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
  return res.status === 204 ? null : res.json();
}

async function watchedChannels(env) {
  const names = new Set((env.DISCORD_CHANNELS || "").split(",").map((s) => s.trim()).filter(Boolean));
  const list = await discord(env, "GET", `/guilds/${env.DISCORD_GUILD_ID}/channels`);
  const chans = list.filter((c) => [0, 5].includes(c.type) && (!names.size || names.has(c.name)));
  const ids = new Set(chans.map((c) => c.id));
  const threads = (await discord(env, "GET", `/guilds/${env.DISCORD_GUILD_ID}/threads/active`)).threads.filter((t) =>
    ids.has(t.parent_id),
  );
  return [...chans, ...threads];
}

async function poll(env) {
  const agents = json(env.AGENTS, {});
  const roleIds = Object.keys(agents);
  const sieve = json(env.SIEVE, null);
  if (!roleIds.length && !sieve?.repo) return;
  for (const ch of await watchedChannels(env)) {
    const key = `last:${ch.id}`;
    const last = await env.STATE.get(key);
    if (!last) {
      // 初めて見るチャンネルは、今の位置から始める（過去の発言には反応しない）
      if (ch.last_message_id) await env.STATE.put(key, ch.last_message_id);
      continue;
    }
    const msgs = await discord(env, "GET", `/channels/${ch.id}/messages?after=${last}&limit=50`);
    if (!msgs.length) continue;
    msgs.sort((a, b) => (BigInt(a.id) < BigInt(b.id) ? -1 : 1));
    for (const m of msgs) {
      if (sieve?.repo && ch.name === sieve.channel && isProposal(m)) {
        await dispatchSieve(env, sieve, ch, m);
      }
      const hop = Number((await env.STATE.get(`hop:${m.id}`)) || 0);
      const from = await env.STATE.get(`by:${m.id}`); // 分身の返事なら、その分身のロールID
      for (const roleId of m.mention_roles || []) {
        const agent = agents[roleId];
        if (!agent || roleId === from) continue;
        if (hop >= MAX_HOPS) continue;
        if (!(await underLimit(env, roleId))) continue;
        await dispatch(env, roleId, agent, ch, m, hop, agents);
      }
    }
    await env.STATE.put(key, msgs[msgs.length - 1].id);
  }
}

// 篩に渡す発言か。人のふつうの発言はすべて提案。ボットの発言は、通話の議事録から出た〔提案〕だけ
// （/propose と「コモンズに提案」でボットが書いたものは、受け口から別に篩が起きているので渡さない）
function isProposal(m) {
  if (![0, 19].includes(m.type) || !(m.content || "").trim()) return false;
  if (!m.author?.bot) return true;
  return (m.content || "").startsWith("〔提案〕") && (m.content || "").includes("拾った候補");
}

async function dispatchSieve(env, sieve, ch, m) {
  const token = await installationToken(env, sieve.repo).catch((e) => {
    console.log(`token sieve: ${e.message}`);
    return null;
  });
  if (!token) return;
  const res = await fetch(`https://api.github.com/repos/${sieve.repo}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "discord-agents",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      event_type: "sieve-intake",
      client_payload: {
        text: (m.content || "").slice(0, 4000),
        user_name: m.member?.nick || m.author?.global_name || m.author?.username || "",
        source_link: `https://discord.com/channels/${env.DISCORD_GUILD_ID}/${ch.id}/${m.id}`,
        channel_id: ch.id,
        message_id: m.id,
      },
    }),
  });
  console.log(`dispatch sieve: ${res.status}`);
}

async function underLimit(env, roleId) {
  const k = `count:${roleId}:${new Date().toISOString().slice(0, 13)}`;
  const n = Number((await env.STATE.get(k)) || 0);
  if (n >= MAX_PER_HOUR) return false;
  await env.STATE.put(k, String(n + 1), { expirationTtl: 7200 });
  return true;
}

async function dispatch(env, roleId, agent, ch, m, hop, agents) {
  const token = await installationToken(env, agent.repo).catch((e) => {
    console.log(`token ${agent.name}: ${e.message}`);
    return null;
  });
  if (!token) return;
  // 直前のやりとり（流れが分かるように）
  const recent = await discord(env, "GET", `/channels/${ch.id}/messages?before=${m.id}&limit=10`);
  const name = (u, mem) => mem?.nick || u?.global_name || u?.username || "?";
  const roleName = (text) =>
    (text || "").replace(/<@&(\d+)>/g, (_, id) => `@${agents[id]?.name || "ロール"}`).replace(/<@!?(\d+)>/g, "@メンバー");
  const payload = {
    event_type: "discord-agent",
    client_payload: {
      role_id: roleId,
      agent_name: agent.name,
      channel_id: ch.id,
      channel_name: ch.name,
      message_id: m.id,
      author: name(m.author, m.member),
      author_is_owner: m.author?.id === agent.owner,
      author_is_agent: Boolean(await env.STATE.get(`by:${m.id}`)),
      text: roleName(m.content).slice(0, 4000),
      context: recent
        .reverse()
        .map((r) => `${name(r.author, r.member)}：${roleName(r.content).slice(0, 500)}`)
        .join("\n"),
      hop,
      reply_url: `${env.PUBLIC_URL || ""}/reply`,
    },
  };
  const res = await fetch(`https://api.github.com/repos/${agent.repo}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "discord-agents",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  console.log(`dispatch ${agent.name}: ${res.status}`);
}

async function reply(request, env) {
  const body = await request.json().catch(() => null);
  if (!body?.role_id || !body?.channel_id || !body?.text) return new Response("bad request", { status: 400 });
  const agents = json(env.AGENTS, {});
  const agent = agents[body.role_id];
  if (!agent) return new Response("unknown agent", { status: 403 });
  // 身分証明（GitHub Actions の OIDC）で、その分身のリポジトリの、決まった workflow から来たかを確かめる
  const jwt = (request.headers.get("Authorization") || "").replace(/^Bearer /, "");
  const claims = await verifyOidc(env, jwt).catch((e) => {
    console.log(`oidc: ${e.message}`);
    return null;
  });
  if (
    !claims ||
    String(claims.repository).toLowerCase() !== String(agent.repo).toLowerCase() ||
    !String(claims.job_workflow_ref || "").startsWith(WORKFLOW_REF)
  ) {
    return new Response("unauthorized", { status: 401 });
  }
  // 返事を投稿できるのは、見ているチャンネル（とそのスレッド）だけ
  const allowed = (await watchedChannels(env)).some((c) => c.id === body.channel_id);
  if (!allowed) return new Response("not allowed", { status: 403 });
  const agentRoles = Object.keys(agents);
  const text = `**🤖 ${agent.name}**\n${String(body.text)}`;
  let first;
  for (let i = 0; i < text.length; i += 1900) {
    const m = await discord(env, "POST", `/channels/${body.channel_id}/messages`, {
      content: text.slice(i, i + 1900),
      allowed_mentions: { parse: [], roles: agentRoles, users: agent.owner ? [agent.owner] : [] }, // 呼べるのは AI 用ロールと持ち主だけ
      ...(i === 0 && body.message_id ? { message_reference: { message_id: body.message_id, fail_if_not_exists: false } } : {}),
    });
    first ??= m;
    await env.STATE.put(`hop:${m.id}`, String(Number(body.hop || 0) + 1), { expirationTtl: 86400 });
    await env.STATE.put(`by:${m.id}`, body.role_id, { expirationTtl: 86400 });
  }
  return Response.json({ ok: true, message_id: first.id });
}

// ---- GitHub アプリとして動く（各自のリポジトリへの dispatch） ----

const WORKFLOW_REF = "commons-ground/ground/.github/workflows/discord-agent.yml@";
const OIDC_ISSUER = "https://token.actions.githubusercontent.com";
const OIDC_AUDIENCE = "commons-discord-agents";

const b64url = (buf) =>
  btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64urlJson = (o) => b64url(new TextEncoder().encode(JSON.stringify(o)));
const fromB64url = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0));

// GitHub の秘密鍵（PKCS#1 の "BEGIN RSA PRIVATE KEY"）を、WebCrypto が読める PKCS#8 に包み直す
function pemToPkcs8(pem) {
  const der = Uint8Array.from(atob(pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "")), (c) => c.charCodeAt(0));
  if (!pem.includes("BEGIN RSA PRIVATE KEY")) return der;
  const len = (n) => (n < 0x80 ? [n] : n < 0x100 ? [0x81, n] : [0x82, n >> 8, n & 0xff]);
  const algo = [0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00];
  const octet = [0x04, ...len(der.length), ...der];
  const inner = [0x02, 0x01, 0x00, ...algo, ...octet];
  return new Uint8Array([0x30, ...len(inner.length), ...inner]);
}

async function appJwt(env) {
  const key = await crypto.subtle.importKey(
    "pkcs8",
    pemToPkcs8(env.GITHUB_APP_PRIVATE_KEY),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const now = Math.floor(Date.now() / 1000);
  const unsigned = `${b64urlJson({ alg: "RS256", typ: "JWT" })}.${b64urlJson({ iat: now - 60, exp: now + 540, iss: env.GITHUB_APP_ID })}`;
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(unsigned));
  return `${unsigned}.${b64url(sig)}`;
}

async function gh(path, token, method = "GET", body) {
  const res = await fetch(`https://api.github.com${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "discord-agents",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
  return res.json();
}

// そのリポジトリ1つだけに効く、1時間のトークンをもらう（50分だけ取っておく）
async function installationToken(env, repo) {
  const cacheKey = `tok:${repo.toLowerCase()}`;
  const cached = await env.STATE.get(cacheKey);
  if (cached) return cached;
  const jwt = await appJwt(env);
  const inst = await gh(`/repos/${repo}/installation`, jwt);
  const tok = await gh(`/app/installations/${inst.id}/access_tokens`, jwt, "POST", {
    repositories: [repo.split("/")[1]],
  });
  await env.STATE.put(cacheKey, tok.token, { expirationTtl: 3000 });
  return tok.token;
}

async function verifyOidc(env, jwt) {
  const [h, p, s] = jwt.split(".");
  if (!s) throw new Error("not a jwt");
  const header = JSON.parse(new TextDecoder().decode(fromB64url(h)));
  const claims = JSON.parse(new TextDecoder().decode(fromB64url(p)));
  let jwks = await env.STATE.get("oidc:jwks", "json");
  if (!jwks || !jwks.keys.some((k) => k.kid === header.kid)) {
    jwks = await (await fetch(`${OIDC_ISSUER}/.well-known/jwks`)).json();
    await env.STATE.put("oidc:jwks", JSON.stringify(jwks), { expirationTtl: 3600 });
  }
  const jwk = jwks.keys.find((k) => k.kid === header.kid);
  if (!jwk) throw new Error("unknown kid");
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, fromB64url(s), new TextEncoder().encode(`${h}.${p}`));
  if (!ok) throw new Error("bad signature");
  const now = Date.now() / 1000;
  if (claims.iss !== OIDC_ISSUER || claims.aud !== OIDC_AUDIENCE || claims.exp < now || claims.nbf > now + 60) {
    throw new Error("bad claims");
  }
  return claims;
}
