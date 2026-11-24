// コモンズの通話を録る（discord-meeting の1段目）。
//
// /record start を打った人がいるボイスチャンネルに、ボットが入って録る。
// 話している人ごと・話のかたまりごとに、生の音（48kHz・2ch・16bit の .pcm）に書き出す（あとで transcribe.py が文字にする）。
// 次のどれかで止まる：
//   - 人間が全員抜けて、EMPTY_GRACE_SEC 秒たった
//   - /record stop（受け口が「⏹ 録音を止めます」と書く。ボット自身のその書き込みを合図にする）
//   - MAX_MINUTES 分たった
//
// 音声・発言の中身はログに出さない（公開リポジトリの Actions で動くため）。
//
// 環境変数
//   PAYLOAD            … 受け口から渡された JSON（guild_id, user_id, user_name, application_id, token）
//   DISCORD_BOT_TOKEN  … ボットの鍵
//   OUT_DIR            … 書き出し先
//   MAX_MINUTES        … 録る長さの上限（既定 180）
//   EMPTY_GRACE_SEC    … 全員抜けてから止めるまでの待ち（既定 60）

import { createWriteStream, mkdirSync, writeFileSync } from "node:fs";
import { pipeline } from "node:stream/promises";
import { join } from "node:path";
import { Client, Events, GatewayIntentBits } from "discord.js";
import { EndBehaviorType, VoiceConnectionStatus, entersState, joinVoiceChannel } from "@discordjs/voice";
import prism from "prism-media";

const API = "https://discord.com/api/v10";
const STOP_MARK = "⏹ 録音を止めます";
const p = JSON.parse(process.env.PAYLOAD);
const token = process.env.DISCORD_BOT_TOKEN;
const outDir = process.env.OUT_DIR || "rec";
const maxMs = Number(process.env.MAX_MINUTES || 180) * 60_000;
const graceMs = Number(process.env.EMPTY_GRACE_SEC || 60) * 1000;
mkdirSync(join(outDir, "segments"), { recursive: true });

// 受け口の「準備しています」を書き換える（合鍵は15分有効。始まりの知らせにだけ使う）
async function editOriginal(content) {
  await fetch(`${API}/webhooks/${p.application_id}/${p.token}/messages/@original`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, allowed_mentions: { parse: [] } }),
  }).catch(() => {});
}

async function post(channelId, content) {
  await fetch(`${API}/channels/${channelId}/messages`, {
    method: "POST",
    headers: { Authorization: `Bot ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ content, allowed_mentions: { parse: [] } }),
  }).catch(() => {});
}

const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates, GatewayIntentBits.GuildMessages],
});

let finish, closeAll;
const done = new Promise((r) => (finish = r)); // 止める合図
const closed = new Promise((r) => (closeAll = r)); // 書き出しまで終わった
let stopReason = "";
const stop = (why) => {
  if (!stopReason) {
    stopReason = why;
    finish();
  }
};

client.once(Events.ClientReady, async () => {
  const guild = await client.guilds.fetch(p.guild_id);
  const vs = guild.voiceStates.cache.get(p.user_id);
  const channel = vs?.channel;
  if (!channel) {
    await editOriginal("先にボイスチャンネルに入ってから、もう一度 `/record start` を打ってください。");
    stop("not-in-voice");
    closeAll();
    return;
  }

  const startedAt = Date.now();
  const connection = joinVoiceChannel({
    channelId: channel.id,
    guildId: guild.id,
    adapterCreator: guild.voiceAdapterCreator,
    selfDeaf: false,
    selfMute: true,
  });
  try {
    await entersState(connection, VoiceConnectionStatus.Ready, 30_000);
  } catch {
    await editOriginal("ボイスチャンネルに入れませんでした。ボットに「接続」の権限があるか確かめてください。");
    connection.destroy();
    stop("join-failed");
    closeAll();
    return;
  }

  const names = {};
  const nameOf = async (id) => {
    if (!names[id]) {
      const m = await guild.members.fetch(id).catch(() => null);
      names[id] = m?.displayName || m?.user?.globalName || m?.user?.username || "参加者";
    }
    return names[id];
  };
  const writing = new Set();
  const pending = [];
  let count = 0;

  // 話し始めたら、その人の音を、黙るまでの1かたまりとして書き出す（48kHz・2ch・16bit の生の音）
  connection.receiver.speaking.on("start", (userId) => {
    if (writing.has(userId) || stopReason) return;
    try {
      writing.add(userId);
      const offset = Date.now() - startedAt;
      const file = join(outDir, "segments", `${String(offset).padStart(9, "0")}_${userId}.pcm`);
      const opus = connection.receiver.subscribe(userId, { end: { behavior: EndBehaviorType.AfterSilence, duration: 1200 } });
      const decoder = new prism.opus.Decoder({ rate: 48000, channels: 2, frameSize: 960 });
      nameOf(userId);
      count++;
      pending.push(
        pipeline(opus, decoder, createWriteStream(file))
          .catch((e) => console.log(`かたまりを書けなかった: ${e?.name || e}`))
          .finally(() => writing.delete(userId)),
      );
    } catch (e) {
      // 1つのかたまりで失敗しても、録音全体は止めない
      writing.delete(userId);
      console.log(`かたまりを始められなかった: ${e?.name || e}`);
    }
  });

  // 人間が誰もいなくなったら、少し待って止める
  let emptySince = 0;
  const humans = () => channel.members.filter((m) => !m.user.bot).size;
  const timer = setInterval(() => {
    if (Date.now() - startedAt > maxMs) return stop("max-duration");
    if (humans() === 0) {
      emptySince ||= Date.now();
      if (Date.now() - emptySince > graceMs) stop("everyone-left");
    } else emptySince = 0;
  }, 5000);

  // /record stop の合図（受け口がボットの名前で書く）
  client.on(Events.MessageCreate, (m) => {
    if (m.author.id === client.user.id && m.guildId === guild.id && m.content.includes(STOP_MARK)) stop("command");
  });

  await editOriginal(`🔴 「${channel.name}」の録音を始めました。`);
  await post(
    channel.id,
    `🔴 録音中です（${p.user_name || "参加者"}さんが開始）。\n` +
      "全員が抜けるか `/record stop` で止まり、文字起こしと議事録を #議事録 に置きます。録られたくない人は、いったん抜けてください。",
  );

  await done;
  clearInterval(timer);
  connection.destroy();
  await Promise.allSettled(pending);
  writeFileSync(
    join(outDir, "meta.json"),
    JSON.stringify(
      {
        channel_id: channel.id,
        channel_name: channel.name,
        guild_id: guild.id,
        started_at: new Date(startedAt).toISOString(),
        ended_at: new Date().toISOString(),
        started_by: p.user_name || "",
        stop_reason: stopReason,
        names,
      },
      null,
      2,
    ),
  );
  console.log(`録音を終えた：理由=${stopReason} かたまり=${count} 人数=${Object.keys(names).length}`);
  closeAll();
});

client.login(token);
await closed;
client.destroy();
// 録れなかったとき（ボイスチャンネルにいない・入れない）は meta.json を書かないので、あとの段は動かない
process.exit(0);
