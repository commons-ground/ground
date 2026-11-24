// discord-agents の中継（Cloudflare Worker）
//
// コモンズの Discord で「各自の AI」（AI 用のロール、例：@ひろしのAI）がメンションされたら、
// その人のリポジトリに repository_dispatch で知らせる。分身はその人のリポジトリで、その人の
// Claude のサブスク（公式の Claude Code GitHub Action）で動き、答えを /reply に返す。
// 中継は分身の鍵も、その人の事業データも持たない。
//
// Discord はふつうの発言を外に知らせないので、1分おきに（Cloudflare の Cron トリガー）見に行く。
//
// 設定（Worker の設定画面。リポジトリには ID や鍵を書かない）
//   変数    DISCORD_GUILD_ID     コモンズの Discord サーバーのID
//   変数    DISCORD_CHANNELS     見るチャンネル名のカンマ区切り（その中のスレッドも見る）
//   変数    AGENTS               JSON {"ロールID": {"name": "ひろしのAI", "owner": "持ち主のユーザーID", "repo": "owner/repo"}}
//   Secret  DISCORD_BOT_TOKEN    ボット「コモンズのAI」の鍵
//   Secret  AGENT_GITHUB_TOKENS  JSON {"ロールID": "その人のリポジトリに dispatch できるトークン"}
//   Secret  AGENT_REPLY_KEYS     JSON {"ロールID": "その人の分身が /reply に使う合言葉"}
//   KV      STATE                どこまで見たか、発言ごとの往復回数
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
  if (!roleIds.length) return;
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

async function underLimit(env, roleId) {
  const k = `count:${roleId}:${new Date().toISOString().slice(0, 13)}`;
  const n = Number((await env.STATE.get(k)) || 0);
  if (n >= MAX_PER_HOUR) return false;
  await env.STATE.put(k, String(n + 1), { expirationTtl: 7200 });
  return true;
}

async function dispatch(env, roleId, agent, ch, m, hop, agents) {
  const token = json(env.AGENT_GITHUB_TOKENS, {})[roleId];
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
  const keys = json(env.AGENT_REPLY_KEYS, {});
  const auth = (request.headers.get("Authorization") || "").replace(/^Bearer /, "");
  if (!keys[body.role_id] || !(await same(auth, keys[body.role_id]))) return new Response("unauthorized", { status: 401 });
  const agent = json(env.AGENTS, {})[body.role_id];
  // 返事を投稿できるのは、見ているチャンネル（とそのスレッド）だけ
  const allowed = (await watchedChannels(env)).some((c) => c.id === body.channel_id);
  if (!agent || !allowed) return new Response("not allowed", { status: 403 });
  const agentRoles = Object.keys(json(env.AGENTS, {}));
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

async function same(a, b) {
  const enc = new TextEncoder();
  const [x, y] = await Promise.all([a, b].map((s) => crypto.subtle.digest("SHA-256", enc.encode(s))));
  const u = new Uint8Array(x),
    v = new Uint8Array(y);
  let d = 0;
  for (let i = 0; i < u.length; i++) d |= u[i] ^ v[i];
  return d === 0;
}
