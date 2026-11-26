// discord-agents の中継（Cloudflare Worker）
//
// コモンズの Discord で「各自の AI」（AI 用のロール、例：@ひろしのAI）がメンションされたら、
// その人のリポジトリに repository_dispatch で知らせる。分身はその人のリポジトリで、その人の
// Claude のサブスク（公式の Claude Code GitHub Action）で動き、答えを /reply に返す。
// 中継は分身の鍵も、その人の事業データも持たない。
//
// Discord はふつうの発言を Webhook で知らせないので、Gateway に常時つなぐ（Durable Object「Gateway」）。
// 1分おきの見回り（Cron トリガー）は、常時接続を起こし直す番と、切れていた間の取りこぼしを拾う予備。
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
//   KV      STATE                どこまで見たか、発言ごとの往復回数、頼んだ印
//   Durable Object GATEWAY       常時接続の係（クラス Gateway）
//   変数    SIEVE                （任意）JSON {"channel": "提案", "repo": "commons-ground/winegrowers"}。
//                                あれば篩の入り口を受け持つ。そのリポジトリにも Commons Agents アプリを入れておく。
//                                channel は DISCORD_CHANNELS にも入れておく
//   変数    DISCORD_PUBLIC_KEY   Discord のコマンドの受け口（/interactions）で署名を確かめる公開キー（interactions.js）
//   変数    COMMANDS_REPO        コマンドを渡す先のリポジトリ（例 commons-ground/winegrowers）
//   変数    HEALTH_CHANNEL       （任意）健康診断の知らせ先のチャンネル名。既定は「スキルの相談」
//   変数    COMMONS_AI           （任意）JSON {"repo": "commons-ground/winegrowers", "user_id": "ボットのユーザーID"}。
//                                あれば、コモンズのAI（ボット）へのメンションを拾い、/ai と同じ AI に答えさせる
//                                （そのリポジトリに discord-mention の repository_dispatch を送る）。
//                                #提案 でのメンションは篩が受け持つので、ここでは拾わない
//
// 守ること
//   - 分身の返事は「🤖 ひろしのAI」と名乗って投稿する。@ で呼べるのは AI 用ロールと、その分身の持ち主だけ
//   - AI どうしの往復は MAX_HOPS 回まで。自分のロールに自分で答えることはしない
//   - 1つの分身が1時間に動くのは MAX_PER_HOUR 回まで

import { DurableObject, WorkerEntrypoint } from "cloudflare:workers";
import { handleInteraction, notifyFail } from "./interactions.js";

const API = "https://discord.com/api/v10";
const MAX_HOPS = 3;
const MAX_PER_HOUR = 20;

export default {
  async scheduled(_event, env, ctx) {
    // 常時接続（Gateway）が生きていれば、発言はそちらで即座に拾っている。見回りは、切れていたときの取りこぼしを拾う予備
    let alive = false;
    if (env.GATEWAY) {
      try {
        alive = (await env.GATEWAY.get(env.GATEWAY.idFromName("discord")).ensure()).alive;
      } catch (e) {
        console.log(`gateway ensure: ${e.message}`);
      }
    }
    if (!alive) ctx.waitUntil(poll(env));
    ctx.waitUntil(checkThinking(env).catch((e) => console.log(`thinking check: ${e.message}`)));
    ctx.waitUntil(healthCheck(env).catch((e) => console.log(`health check: ${e.message}`)));
  },
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/reply" && request.method === "POST") return reply(request, env);
    // 見回りが走っているかを外から確かめるための入口（中身は日付だけ。when-to-ask の7）
    if (url.pathname === "/health") {
      const last = await env.STATE.get("health:last");
      return new Response(JSON.stringify({ health_checked: last || null }), { headers: { "content-type": "application/json" } });
    }
    // Discord のコマンドの受け口（interactions.js）。以前の commons-discord-hook を寄せた（#72）
    if (url.pathname === "/interactions" && request.method === "POST") {
      return handleInteraction(request, env, ctx, async (payload, failText) => {
        const r = await dispatchRepo(env, env.COMMANDS_REPO, payload).catch((e) => ({ ok: false, status: e.message }));
        if (!r.ok) await notifyFail(payload, failText);
      });
    }
    return new Response("discord-agents");
  },
};

// ── 見学者をコモンズメンバーに迎える（docs/membership.md） ─────────────
// #ようこそ の発言に、コモンズメンバーが ✅ を付けたら、書いた人に「コモンズメンバー」のロールを付けて迎える。
// 承認するのは人（メンバー）だけ。AI は承認しない。ロールとチャンネルは名前で探す（ID をリポジトリに書かない）。
// ロールとチャンネルを用意するのは tools/members/setup.py。どちらかが無いあいだは何もしない
const MEMBER_ROLE_NAME = "コモンズメンバー";
const WELCOME_CHANNEL = "ようこそ";
const APPROVE = new Set(["✅", "☑️", "✔️"]);

async function membershipPlaces(env) {
  const cached = json(await env.STATE.get("members:places"), null);
  if (cached) return cached;
  const roles = await discord(env, "GET", `/guilds/${env.DISCORD_GUILD_ID}/roles`);
  const chans = await discord(env, "GET", `/guilds/${env.DISCORD_GUILD_ID}/channels`);
  const places = {
    role: roles.find((r) => r.name === (env.MEMBER_ROLE_NAME || MEMBER_ROLE_NAME))?.id || "",
    welcome: chans.find((c) => c.type === 0 && c.name === (env.WELCOME_CHANNEL || WELCOME_CHANNEL))?.id || "",
  };
  await env.STATE.put("members:places", JSON.stringify(places), { expirationTtl: 3600 });
  return places;
}

async function welcomeOnApproval(env, d) {
  if (!APPROVE.has(d.emoji?.name) || (env.DISCORD_GUILD_ID && d.guild_id !== env.DISCORD_GUILD_ID)) return;
  const { role, welcome } = await membershipPlaces(env);
  if (!role || d.channel_id !== welcome) return;
  if (!(d.member?.roles || []).includes(role)) return; // 付けたのがメンバーでなければ数えない
  const msg = await discord(env, "GET", `/channels/${d.channel_id}/messages/${d.message_id}`);
  const who = msg.author;
  if (!who || who.bot || who.id === d.user_id) return; // 自分で自分を承認しない
  const member = await discord(env, "GET", `/guilds/${env.DISCORD_GUILD_ID}/members/${who.id}`).catch(() => null);
  if (!member || member.roles.includes(role)) return;
  if (!(await once(env, `welcome:${who.id}`))) return;
  await discord(env, "PUT", `/guilds/${env.DISCORD_GUILD_ID}/members/${who.id}/roles/${role}`);
  await discord(env, "POST", `/channels/${d.channel_id}/messages`, {
    content: [
      `🎉 <@${who.id}> さん、コモンズメンバーへようこそ！（<@${d.user_id}> さんが迎えてくれたよ）`,
      "これで #提案 に書いたり、みんなのスキルや知識コモンズを自分の Claude で使えるようになったよ。",
      "はじめかた → https://commons-ground.github.io/ground/",
    ].join("\n"),
    message_reference: { message_id: d.message_id, fail_if_not_exists: false },
    allowed_mentions: { users: [who.id] },
  });
}

// ── 健康診断（1日1回、朝8時以降の最初の見回りで） ──────────────────
// Claude の定期実行を増やさずに、毎分の見回りに相乗りする。異常があったときだけ #スキルの相談 に知らせる。
//   - 鍵の台帳（tools/health/keys.json、値は書かない）：期限まで14日を切った鍵
//   - Discord の招待：あと3日で切れる、または残り回数が1以下（招待を読む権限が無ければ飛ばす）
//   - 1日以上動きのない、下書きでないプルリクエスト（ground・winegrowers）
//   - 見直し日を過ぎた試行（docs/trials.md の「試行中」の行）
//   - 門番（guard）の成功の記録なしに入った PR（安全策が本当に走っているか）
// 変数 HEALTH_CHANNEL（任意）で知らせる先のチャンネル名を変えられる
const RAW = "https://raw.githubusercontent.com/commons-ground";
const HEALTH_REPOS = ["commons-ground/ground", "commons-ground/winegrowers"];
const DAY = 86400000;

function jstNow() {
  const d = new Date(Date.now() + 9 * 3600000);
  return { date: d.toISOString().slice(0, 10), hour: d.getUTCHours() };
}

async function healthCheck(env) {
  const { date, hour } = jstNow();
  if (hour < 8 || (await env.STATE.get(`health:${date}`))) return;
  await env.STATE.put(`health:${date}`, "1", { expirationTtl: 2 * 86400 });
  await env.STATE.put("health:last", date);
  const found = [];
  const part = async (name, f) => {
    try {
      found.push(...(await f()));
    } catch (e) {
      console.log(`health ${name}: ${e.message}`);
    }
  };
  await part("keys", () => checkKeys(date));
  await part("invites", () => checkInvites(env));
  await part("prs", () => checkPulls());
  await part("guard", () => checkGuardRan());
  await part("trials", () => checkTrials(date));
  if (!found.length) return;
  const name = env.HEALTH_CHANNEL || "スキルの相談";
  const ch = (await discord(env, "GET", `/guilds/${env.DISCORD_GUILD_ID}/channels`)).find((c) => c.type === 0 && c.name === name);
  if (!ch) return console.log(`health: channel ${name} not found`);
  const text = [`🩺 きょうの健康診断：気になるところが ${found.length} 件あったよ`, ...found.map((f) => `- ${f}`)].join("\n");
  await discord(env, "POST", `/channels/${ch.id}/messages`, { content: text.slice(0, 1900), allowed_mentions: { parse: [] } });
}

const daysUntil = (from, to) => Math.round((Date.parse(to) - Date.parse(from)) / DAY);

async function checkKeys(today) {
  const res = await fetch(`${RAW}/ground/main/tools/health/keys.json`);
  if (!res.ok) throw new Error(`keys.json ${res.status}`);
  return (await res.json()).keys
    .filter((k) => k.expires && daysUntil(today, k.expires) <= 14)
    .map((k) => {
      const d = daysUntil(today, k.expires);
      return `🔑 ${k.name}（${k.where}）が${d < 0 ? `${-d}日前に切れてる` : d === 0 ? "きょう切れる" : `あと${d}日で切れる`}。${k.fix}`;
    });
}

async function checkInvites(env) {
  const list = await discord(env, "GET", `/guilds/${env.DISCORD_GUILD_ID}/invites`);
  if (!Array.isArray(list)) return [];
  const now = Date.now();
  return list.flatMap((i) => {
    const left = i.max_uses ? i.max_uses - i.uses : Infinity;
    const end = i.max_age ? Date.parse(i.created_at) + i.max_age * 1000 : Infinity;
    if (left > 1 && end - now > 3 * DAY) return [];
    const why = left <= 1 ? `残り${left}回` : `あと${Math.max(0, Math.ceil((end - now) / DAY))}日`;
    return [`📨 招待 discord.gg/${i.code} が ${why} で使えなくなる。新しい招待を作ってピン留めを差し替えてね`];
  });
}

// 機械の安全策が本当に走っているか（when-to-ask の7）：この1日に入った PR に、門番（guard）が成功した記録があるか
async function checkGuardRan() {
  const gh = (path) =>
    fetch(`https://api.github.com/repos/${path}`, { headers: { Accept: "application/vnd.github+json", "User-Agent": "discord-agents" } }).then((r) => {
      if (!r.ok) throw new Error(`${path} ${r.status}`);
      return r.json();
    });
  const out = [];
  for (const repo of HEALTH_REPOS) {
    const merged = (await gh(`${repo}/pulls?state=closed&sort=updated&direction=desc&per_page=30`)).filter(
      (p) => p.merged_at && Date.now() - Date.parse(p.merged_at) < DAY,
    );
    for (const p of merged) {
      const runs = (await gh(`${repo}/commits/${p.head.sha}/check-runs?per_page=100`)).check_runs || [];
      const ok = runs.some((r) => /guard/.test(r.name) && r.conclusion === "success");
      const labeled = (p.labels || []).some((l) => l.name === "確認済み");
      if (!ok && !labeled) out.push(`🚨 ${repo.split("/")[1]}#${p.number}「${p.title}」が、門番（guard）の成功の記録なしに入ってる → ${p.html_url}`);
    }
  }
  return out;
}

async function checkPulls() {
  const out = [];
  for (const repo of HEALTH_REPOS) {
    const res = await fetch(`https://api.github.com/repos/${repo}/pulls?state=open&per_page=100`, {
      headers: { Accept: "application/vnd.github+json", "User-Agent": "discord-agents" },
    });
    if (!res.ok) throw new Error(`${repo} pulls ${res.status}`);
    for (const p of await res.json()) {
      if (p.draft || Date.now() - Date.parse(p.updated_at) < DAY) continue;
      out.push(`⏳ ${repo.split("/")[1]}#${p.number}「${p.title}」が1日以上止まってる → ${p.html_url}`);
    }
  }
  return out;
}

async function checkTrials(today) {
  const res = await fetch(`${RAW}/ground/main/docs/trials.md`);
  if (!res.ok) throw new Error(`trials.md ${res.status}`);
  const late = (await res.text())
    .split("\n")
    .map((l) => l.split("|").map((c) => c.trim()))
    .filter((c) => c.length >= 8 && c[6] && c[6].includes("試行中") && /^\d{4}-\d{2}-\d{2}$/.test(c[5]) && c[5] < today);
  return late.length ? [`🧪 見直し日を過ぎた試行が ${late.length} 件（例：${late[0][2]}）→ https://github.com/commons-ground/ground/blob/main/docs/trials.md`] : [];
}

// ほかの Worker から、サービスバインディングで呼ぶ入口。外の URL からは呼べない。
// 期限つきのトークン（PAT）を持たずに、コモンズの GitHub アプリとして dispatch できるようにする。
// いまは使う Worker が無い（コマンドの受け口は /interactions として中継に入った）。次に別の Worker を足すとき用。
// 送れるのは commons-ground の中のリポジトリだけ。
export class Dispatcher extends WorkerEntrypoint {
  async dispatch(repo, payload) {
    return dispatchRepo(this.env, repo, payload);
  }
}

async function dispatchRepo(env, repo, payload) {
  if (!/^commons-ground\/[A-Za-z0-9._-]+$/.test(String(repo))) return { ok: false, status: 400 };
  const token = await installationToken(env, repo);
  const res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "discord-agents",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  console.log(`dispatch ${payload?.event_type}: ${res.status}`);
  return { ok: res.ok, status: res.status };
}

// ── 常時接続（Discord Gateway） ──────────────────────────────
// Discord はふつうの発言を Webhook で知らせないので、発言を即座に知るには Gateway に常時つなぐしかない。
// Durable Object は、外向きの WebSocket がつながっている間は止められない（Cloudflare、2026年6月から）。
// 1つ（128MB）を1日つなぎっぱなしにして約 10,800 GB-s で、無料枠（13,000 GB-s/日）に収まる。
// 切れたら毎分の見回りが ensure() で起こし直し、その間の取りこぼしは見回りが拾う。
const GATEWAY_URL = "https://gateway.discord.gg/?v=10&encoding=json";
const INTENTS = (1 << 0) | (1 << 9) | (1 << 10) | (1 << 15); // GUILDS, GUILD_MESSAGES, GUILD_MESSAGE_REACTIONS, MESSAGE_CONTENT

export class Gateway extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.ws = null;
    this.seq = null;
    this.session = null;
    this.resumeUrl = null;
    this.beat = null;
    this.lastAck = 0;
    this.channels = new Map();
    this.channelsAt = 0;
  }

  // 毎分の見回りから呼ばれる。つながっていなければつなぐ。生きていれば alive: true
  async ensure() {
    const fresh = this.ws && Date.now() - this.lastAck < 3 * 60 * 1000;
    if (!fresh) await this.connect();
    return { alive: Boolean(fresh) };
  }

  async connect() {
    try {
      this.ws?.close();
    } catch {}
    clearInterval(this.beat);
    const url = (this.session && this.resumeUrl ? this.resumeUrl + "/?v=10&encoding=json" : GATEWAY_URL).replace("wss://", "https://");
    const res = await fetch(url, { headers: { Upgrade: "websocket" } });
    const ws = res.webSocket;
    if (!ws) throw new Error(`gateway: ${res.status}`);
    ws.accept();
    this.ws = ws;
    this.lastAck = Date.now();
    ws.addEventListener("message", (e) => this.ctx.waitUntil(this.onMessage(e.data).catch((err) => console.log(`gateway msg: ${err.message}`))));
    ws.addEventListener("close", (e) => {
      console.log(`gateway closed: ${e.code}`);
      clearInterval(this.beat);
      if (this.ws === ws) this.ws = null;
      // 4004（鍵が違う）・4014（権限が足りない）などは、つなぎ直しても同じなので見回りに任せる
      if (e.code < 4000 || [4000, 4007, 4009].includes(e.code)) {
        if (e.code === 4007 || e.code === 4009) this.session = null;
        this.ctx.waitUntil(new Promise((r) => setTimeout(r, 3000)).then(() => this.connect()).catch(() => {}));
      }
    });
  }

  send(op, d) {
    this.ws?.send(JSON.stringify({ op, d }));
  }

  async onMessage(raw) {
    const p = JSON.parse(raw);
    if (p.s != null) this.seq = p.s;
    if (p.op === 10) {
      // Hello：心拍を始め、名乗る（つなぎ直しなら続きから）
      clearInterval(this.beat);
      this.beat = setInterval(() => this.send(1, this.seq), p.d.heartbeat_interval);
      if (this.session) this.send(6, { token: this.env.DISCORD_BOT_TOKEN, session_id: this.session, seq: this.seq });
      else this.send(2, { token: this.env.DISCORD_BOT_TOKEN, intents: INTENTS, properties: { os: "cloudflare", browser: "commons", device: "commons" } });
    } else if (p.op === 11) {
      this.lastAck = Date.now();
    } else if (p.op === 1) {
      this.send(1, this.seq);
    } else if (p.op === 7) {
      this.ws?.close(4000, "reconnect");
    } else if (p.op === 9) {
      this.session = p.d ? this.session : null;
      this.ws?.close(4000, "invalid session");
    } else if (p.op === 0) {
      if (p.t === "READY") {
        this.session = p.d.session_id;
        this.resumeUrl = p.d.resume_gateway_url;
        this.lastAck = Date.now();
      } else if (p.t === "MESSAGE_CREATE" || p.t === "MESSAGE_UPDATE") {
        await this.onDiscordMessage(p.t, p.d);
      } else if (p.t === "MESSAGE_REACTION_ADD") {
        await welcomeOnApproval(this.env, p.d).catch((e) => console.log(`welcome: ${e.message}`));
      }
    }
  }

  async channel(id) {
    if (Date.now() - this.channelsAt > 5 * 60 * 1000 || !this.channels.has(id)) {
      this.channels = new Map((await watchedChannels(this.env)).map((c) => [c.id, c]));
      this.channelsAt = Date.now();
    }
    return this.channels.get(id);
  }

  async onDiscordMessage(type, m) {
    if (this.env.DISCORD_GUILD_ID && m.guild_id && m.guild_id !== this.env.DISCORD_GUILD_ID) return;
    const ch = await this.channel(m.channel_id);
    if (!ch) return; // 見ていないチャンネル
    if (type === "MESSAGE_CREATE") {
      await handleMessage(this.env, ch, m);
      await this.env.STATE.put(`last:${ch.id}`, m.id); // 見回りが同じ発言を見直さないように
    } else {
      // 編集：コモンズのAIへのメンションを足したときだけ拾う（MESSAGE_UPDATE は本文が来ないこともある）
      const ai = await withBotRoles(this.env, json(this.env.COMMONS_AI, null));
      const sieve = json(this.env.SIEVE, null);
      if (ai?.repo && m.content !== undefined && m.author && mentionsCommonsAi(m, ai) && !(sieve?.repo && ch.name === sieve.channel)) {
        await askCommonsAi(this.env, ai, ch, m);
      }
    }
  }
}

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

// 「読んだよ」の印（👀）を、AI に頼めた発言に付ける。返事はそのあと1〜2分で付く
async function seen(env, ch, m) {
  await discord(env, "PUT", `/channels/${ch.id}/messages/${m.id}/reactions/${encodeURIComponent("👀")}/@me`).catch((e) =>
    console.log(`reaction: ${e.message}`),
  );
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
  const commonsAi = json(env.COMMONS_AI, null);
  if (!roleIds.length && !sieve?.repo && !commonsAi?.repo) return;
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
    for (const m of msgs) await handleMessage(env, ch, m);
    await env.STATE.put(key, msgs[msgs.length - 1].id);
  }
  if (commonsAi?.repo) await pollEdits(env, await withBotRoles(env, commonsAi), sieve);
}

// 1件の発言を見て、篩・コモンズのAI・分身に知らせる。
// 毎分の見回りと、常時接続（Gateway）の両方から呼ばれるので、同じ発言で同じ相手を2回起こさないよう、
// 頼んだら KV に印を残す（once）
async function handleMessage(env, ch, m) {
  const agents = json(env.AGENTS, {});
  const sieve = json(env.SIEVE, null);
  const commonsAi = await withBotRoles(env, json(env.COMMONS_AI, null));
  if (sieve?.repo && ch.name === sieve.channel && isProposal(m) && (await once(env, `sv:${m.id}`))) {
    await dispatchSieve(env, sieve, ch, m);
  }
  if (commonsAi?.repo && mentionsCommonsAi(m, commonsAi) && !(sieve?.repo && ch.name === sieve.channel)) {
    await askCommonsAi(env, commonsAi, ch, m);
  }
  const hop = Number((await env.STATE.get(`hop:${m.id}`)) || 0);
  const from = await env.STATE.get(`by:${m.id}`); // 分身の返事なら、その分身のロールID
  // 本文の <@&ID> も見る（コネクタやボットの投稿は通知を切っているので mention_roles が空になる）
  const mentioned = new Set([...(m.mention_roles || []), ...[...(m.content || "").matchAll(/<@&(\d+)>/g)].map((x) => x[1])]);
  for (const roleId of mentioned) {
    const agent = agents[roleId];
    if (!agent || roleId === from) continue;
    if (hop >= MAX_HOPS) continue;
    if (!(await underLimit(env, roleId))) continue;
    if (!(await once(env, `ag:${roleId}:${m.id}`))) continue;
    await dispatch(env, roleId, agent, ch, m, hop, agents);
  }
}

// 初めてなら印を付けて true。すでに印があれば false
async function once(env, key) {
  if (await env.STATE.get(key)) return false;
  await env.STATE.put(key, "1", { expirationTtl: 86400 });
  return true;
}

// コモンズのAIに1回だけ頼む（同じ発言で2回動かない）
async function askCommonsAi(env, ai, ch, m) {
  if (await env.STATE.get(`ai:${m.id}`)) return;
  if (!(await underLimit(env, "commons-ai"))) return;
  await env.STATE.put(`ai:${m.id}`, "1", { expirationTtl: 86400 });
  await dispatchCommonsAi(env, ai, ch, m);
}

// 投稿したあとの編集でメンションを足した発言も拾う。
// 新しい発言だけを見る見回りでは取りこぼすので、各チャンネルの最近の発言のうち、
// 直近10分に編集されたものだけを見直す（読むだけ。KV に書くのは、実際に頼んだときだけ）
async function pollEdits(env, ai, sieve) {
  const since = Date.now() - 10 * 60 * 1000;
  for (const ch of await watchedChannels(env)) {
    if (sieve?.repo && ch.name === sieve.channel) continue;
    const recent = await discord(env, "GET", `/channels/${ch.id}/messages?limit=10`).catch(() => []);
    for (const m of recent) {
      if (!m.edited_timestamp || Date.parse(m.edited_timestamp) < since) continue;
      if (mentionsCommonsAi(m, ai)) await askCommonsAi(env, ai, ch, m);
    }
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

// 人が、コモンズのAI（ボット）をメンションしたか。ボットどうしの往復は起こさない
function mentionsCommonsAi(m, ai) {
  if (m.author?.bot || ![0, 19].includes(m.type)) return false;
  const id = String(ai.user_id || "");
  if (!id) return false;
  const content = m.content || "";
  if ((m.mentions || []).some((u) => u.id === id) || content.includes(`<@${id}>`) || content.includes(`<@!${id}>`)) return true;
  // Discord の候補で、ボットのユーザーではなく、ボットに付くロール（同じ名前）を選んだとき
  return (ai.roles || []).some((r) => (m.mention_roles || []).includes(r) || content.includes(`<@&${r}>`));
}

// ボットに付くロール（Discord がボットに自動で作る、ボットと同じ名前のロール）の ID。Worker が動いている間は覚えておく
let botRoles = null;
async function withBotRoles(env, ai) {
  if (!ai?.user_id) return ai;
  if (!botRoles) {
    const roles = await discord(env, "GET", `/guilds/${env.DISCORD_GUILD_ID}/roles`).catch(() => []);
    botRoles = roles.filter((r) => r.tags?.bot_id === String(ai.user_id)).map((r) => r.id);
  }
  return { ...ai, roles: botRoles };
}

async function dispatchCommonsAi(env, ai, ch, m) {
  const token = await installationToken(env, ai.repo).catch((e) => {
    console.log(`token commons-ai: ${e.message}`);
    return null;
  });
  if (!token) return;
  const question = (m.content || "")
    .replace(new RegExp(`<@!?${ai.user_id}>`, "g"), "")
    .replace(new RegExp(`<@&(${(ai.roles || ["-"]).join("|")})>`, "g"), "")
    .replace(/<@!?(\d+)>/g, "@メンバー")
    .replace(/<@&(\d+)>/g, "@ロール")
    .trim();
  // 👀 のあと答えまで何も出ないと不安なので、先に「考え中…」を返信しておき、答えはそれを書き換える
  const thinking = await discord(env, "POST", `/channels/${ch.id}/messages`, {
    content: THINKING_TEXT,
    message_reference: { message_id: m.id, fail_if_not_exists: false },
    allowed_mentions: { parse: [] },
  }).catch((e) => {
    console.log(`thinking: ${e.message}`);
    return null;
  });
  const res = await fetch(`https://api.github.com/repos/${ai.repo}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "discord-agents",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      event_type: "discord-mention",
      client_payload: {
        command: "mention",
        question: question.slice(0, 2000),
        channel_id: ch.id,
        guild_id: env.DISCORD_GUILD_ID,
        message_id: m.id,
        reply_id: thinking?.id || "",
        user_id: m.author?.id || "",
        user_name: m.member?.nick || m.author?.global_name || m.author?.username || "",
      },
    }),
  });
  console.log(`dispatch commons-ai: ${res.status}`);
  if (res.ok) {
    await seen(env, ch, m);
    if (thinking?.id) await watchThinking(env, ch.id, thinking.id);
  } else if (thinking?.id) {
    await discord(env, "PATCH", `/channels/${ch.id}/messages/${thinking.id}`, { content: STUCK_TEXT }).catch(() => {});
  }
}

const THINKING_TEXT = "🤔 考え中…（1〜2分で、ここに答えが出るよ）";
const STUCK_TEXT = "😵 ごめん、うまく動かなかったみたい…もう一度呼んでみて。続くようなら #提案 で教えてね";

// 「考え中…」のまま12分たったら、動かなかったとみなして書き換える（AI の仕事が起動の時点で落ちたときなど）。
// 毎分の見回りのついでに見る。覚えておく先は KV のキー1つ（一覧の読み出しを毎分しないため）
async function watchThinking(env, channelId, id) {
  const list = json(await env.STATE.get("thinking"), []);
  list.push({ c: channelId, id, at: Date.now() });
  await env.STATE.put("thinking", JSON.stringify(list.slice(-50)));
}

async function checkThinking(env) {
  const list = json(await env.STATE.get("thinking"), []);
  if (!list.length) return;
  const keep = [];
  for (const x of list) {
    if (Date.now() - x.at < 12 * 60 * 1000) {
      keep.push(x);
      continue;
    }
    const msg = await discord(env, "GET", `/channels/${x.c}/messages/${x.id}`).catch(() => null);
    if (msg && (msg.content || "").startsWith("🤔 考え中")) {
      await discord(env, "PATCH", `/channels/${x.c}/messages/${x.id}`, { content: STUCK_TEXT }).catch(() => {});
    }
  }
  if (keep.length !== list.length) await env.STATE.put("thinking", JSON.stringify(keep));
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
    // GitHub は client_payload の直下に10項目までしか受けないので、r の中にまとめる
    client_payload: { r: {
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
    } },
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
  if (res.ok) await seen(env, ch, m);
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
