#!/usr/bin/env python3
"""篩の1段目：集める（Claude は使わない）。

Discord と提案箱（GitHub の Issue）から、まだ篩に通していないものを集めて items.json にする。
何も無ければ count=0 を返し、2段目（Claude）を動かさない。だから、何度起きても費用はかからない。

集めるもの
  - Discord の提案のチャンネル（#提案）の発言と、ほかのチャンネルの「〔提案〕」「〔覚えておく〕」を含む発言で、
    ボットの 🧺 も ⏸️ も付いていないもの（#提案 では、人の発言はすべて提案。ボットの発言は〔提案〕を含むものだけ）
  - 提案箱の Issue（ラベル「提案」）で、影響のラベルがまだ無いもの（GitHub の提案の書式から出たもの）
  - ラベル「ふるい:試行中」で、見直し日を過ぎたもの
  - ラベル「ふるい:見直し中」で、見直しの声を聞き始めて7日たったもの（👍・👎 の数を添える）
あわせて、重なりを調べるために提案箱の一覧を proposals.json にする。

環境変数
  PAYLOAD            … 起こした側から渡された JSON（channel_id があればそのチャンネルも見る）
  MEMBER_DIR         … 設定フォルダ（config.json）
  DISCORD_BOT_TOKEN  … （任意）無ければ Discord は見ない
  GH_TOKEN           … Issue を読む
  OUT_DIR            … 出力先
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

from common import KINDS, MARK_DONE, MARK_HOLD, discord, gh, load_config, out_dir, summary

MAX_ITEMS = 10
JST = timezone(timedelta(hours=9))
TEXT_TYPES = {0, 5}
LINK = re.compile(r"https://discord\.com/channels/(\d+)/(\d+)/(\d+)")


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def marked(m: dict) -> bool:
    return any(r.get("me") and r.get("emoji", {}).get("name") in (MARK_DONE, MARK_HOLD) for r in m.get("reactions") or [])


def discord_items(config: dict, payload: dict) -> list[dict]:
    if not os.environ.get("DISCORD_BOT_TOKEN"):
        return []
    guild = payload.get("guild_id") or config.get("sieve_guild_id")
    if not guild:
        guilds = discord("GET", "/users/@me/guilds")
        if len(guilds) != 1:
            print("Discord のサーバーが1つに決まらないので、Discord は見ない（config.json に sieve_guild_id を書く）")
            return []
        guild = guilds[0]["id"]
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=config.get("sieve_lookback_days", 14))
    if config.get("sieve_since"):
        since = max(since, datetime.fromisoformat(config["sieve_since"]).replace(tzinfo=JST))
    names = set(config.get("sieve_channels") or [])
    channels = [c for c in discord("GET", f"/guilds/{guild}/channels") if c.get("type") in TEXT_TYPES]
    if names:
        channels = [c for c in channels if c["name"] in names]
    ids = {c["id"]: c["name"] for c in channels}
    try:
        for t in discord("GET", f"/guilds/{guild}/threads/active").get("threads", []):
            if t.get("parent_id") in ids:
                ids[t["id"]] = f"{ids[t['parent_id']]} のスレッド「{t['name']}」"
    except requests.RequestException:
        pass
    if payload.get("channel_id"):
        ids.setdefault(payload["channel_id"], "（呼ばれたチャンネル）")
    proposal_channel = config.get("proposal_channel", "提案")

    items = []
    for cid, cname in ids.items():
        try:
            msgs = discord("GET", f"/channels/{cid}/messages", params={"limit": 50})
        except requests.RequestException:
            continue  # 読めないチャンネルは飛ばす
        for m in msgs:
            text = m.get("content") or ""
            a = m.get("author", {})
            whole = cname == proposal_channel and not a.get("bot") and m.get("type", 0) in (0, 19)
            if parse_time(m["timestamp"]) < since or marked(m) or not (whole or any(k in text for k in KINDS)):
                continue
            ref = (m.get("message_reference") or {}).get("message_id")
            items.append({
                "id": f"discord:{cid}:{m['id']}",
                "kind": "覚えておく" if "〔覚えておく〕" in text and "〔提案〕" not in text and not whole else "提案",
                "where": f"Discord #{cname}",
                "author": (m.get("member") or {}).get("nick") or a.get("global_name") or a.get("username") or "?",
                "by_bot": bool(a.get("bot")),
                "link": f"https://discord.com/channels/{guild}/{cid}/{m['id']}",
                "at": m["timestamp"],
                "text": text[:2500],
                "reply_to": f"https://discord.com/channels/{guild}/{cid}/{ref}" if ref else None,
                "reactions": {r["emoji"]["name"]: r["count"] for r in m.get("reactions") or [] if r.get("emoji")},
            })
    return items


def issue_list(state: str) -> list[dict]:
    out = gh("issue", "list", "--label", "提案", "--state", state, "--limit", "200",
             "--json", "number,title,body,labels,state,stateReason,createdAt,url,comments")
    return json.loads(out or "[]")


def labels_of(i: dict) -> set[str]:
    return {x["name"] for x in i.get("labels") or []}


def review_date(body: str) -> str | None:
    m = re.search(r"見直し日[:：]\s*(\d{4}-\d{2}-\d{2})", body or "")
    return m.group(1) if m else None


def github_items(open_issues: list[dict]) -> list[dict]:
    today = datetime.now(JST).date().isoformat()
    items = []
    for i in open_issues:
        labels = labels_of(i)
        base = {"issue": i["number"], "title": i["title"], "link": i["url"], "body": (i.get("body") or "")[:3000]}
        if not any(x.startswith("影響:") for x in labels):
            items.append({"id": f"issue:{i['number']}", "kind": "GitHubの提案", **base,
                          "comments": [c.get("body", "")[:800] for c in i.get("comments") or []][-5:]})
        elif "ふるい:試行中" in labels and (review_date(i.get("body")) or "9999") <= today:
            items.append({"id": f"review:{i['number']}", "kind": "見直し", **base})
        elif "ふるい:見直し中" in labels:
            poll = [c for c in i.get("comments") or [] if "見直しの声：" in (c.get("body") or "")]
            if not poll:
                continue
            last = poll[-1]
            if datetime.now(timezone.utc) - parse_time(last["createdAt"]) < timedelta(days=7):
                continue
            votes = {}
            m = LINK.search(last["body"])
            if m and os.environ.get("DISCORD_BOT_TOKEN"):
                try:
                    msg = discord("GET", f"/channels/{m.group(2)}/messages/{m.group(3)}")
                    for r in msg.get("reactions") or []:
                        votes[r["emoji"]["name"]] = r["count"] - (1 if r.get("me") else 0)
                except requests.RequestException:
                    pass
            items.append({"id": f"result:{i['number']}", "kind": "見直しの結果", **base, "votes": votes,
                          "comments": [c.get("body", "")[:800] for c in i.get("comments") or []][-5:]})
    return items


def main() -> int:
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    payload = json.loads(os.environ.get("PAYLOAD") or "{}") or {}
    config = load_config(os.environ.get("MEMBER_DIR"))

    open_issues = issue_list("open")
    items = discord_items(config, payload) + github_items(open_issues)
    items.sort(key=lambda x: x.get("at", ""))
    rest = max(0, len(items) - MAX_ITEMS)
    items = items[:MAX_ITEMS]

    closed = issue_list("closed")
    proposals = [
        {"number": i["number"], "title": i["title"], "state": i["state"], "reason": i.get("stateReason"),
         "labels": sorted(labels_of(i)), "body": (i.get("body") or "")[:600]}
        for i in open_issues + closed
    ]
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
    (out / "proposals.json").write_text(json.dumps(proposals, ensure_ascii=False, indent=1))

    kinds: dict[str, int] = {}
    for x in items:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    summary([
        "### 篩：集めたもの", "",
        "| 種類 | 件数 |", "|:--|:--|",
        *[f"| {k} | {v} |" for k, v in kinds.items()],
        f"| 次回に回したもの | {rest} |",
        f"| 提案箱の件数 | {len(proposals)} |", "",
    ])
    gho = os.environ.get("GITHUB_OUTPUT")
    if gho:
        with open(gho, "a") as f:
            f.write(f"count={len(items)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
