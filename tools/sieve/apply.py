#!/usr/bin/env python3
"""篩の3段目：書き出す（Claude は使わない）。

sieve.py の plan.json を、そのとおりに GitHub と Discord に書く。公開の場所に書く前に、
個人や事業の情報らしき文字（電話番号・メールアドレス・各自の Notion や Drive・金額）を機械で点検し、
引っかかったものは書かずに保留にする（Discord の元の発言に ⏸️）。

プルリクエストは、影響が小・中なら自動マージを予約し、大なら下書きにしてラベル「人の確認」を付ける。
マージそのものはしない（自動マージの仕組みと validate に任せる）。

環境変数
  OUT_DIR / SELF_DIR / MEMBER_DIR / GH_TOKEN / GITHUB_REPOSITORY / DISCORD_BOT_TOKEN（任意）/ GITHUB_RUN_ID
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from common import MARK_DONE, MARK_HOLD, discord, gh, load_config, out_dir, private_hits, summary

LABELS = {
    "提案": "0e8a16", "影響:小": "c2e0c6", "影響:中": "fbca04", "影響:大": "d93f0b",
    "ふるい:試行中": "1d76db", "ふるい:見直し中": "5319e7", "ふるい:人の判断": "b60205",
    "行き先:ground": "bfdadc", "人の確認": "5b5308",
}
FOOTER = "\n\n---\n_篩（ground の tools/sieve）が作りました。ルールは core:sieve。_"
HOLD_TEXT = "公開の前の点検で止めました（個人や事業の情報らしき文字がありました）。世話役の Claude が見て、言い方を直してから入れます。"

repo = os.environ["GITHUB_REPOSITORY"]
out = out_dir().resolve()
self_dir = Path(os.environ["SELF_DIR"]).resolve()
config = load_config(os.environ.get("MEMBER_DIR"))
has_discord = bool(os.environ.get("DISCORD_BOT_TOKEN"))
stats: dict[str, int] = {}


def count(k: str) -> None:
    stats[k] = stats.get(k, 0) + 1


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(self_dir), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} が失敗（{r.returncode}）")
    return r.stdout.strip()


class Links:
    """{issue:k1}・{issue:12}・{pr:p1} を URL に置きかえる。"""

    def __init__(self):
        self.issues: dict[str, str] = {}
        self.prs: dict[str, str] = {}
        self.blocked: set[str] = set()

    def num(self, ref) -> int | None:
        url = self.issues.get(str(ref))
        if url:
            return int(url.rsplit("/", 1)[1])
        return int(ref) if str(ref).isdigit() else None

    def fill(self, text: str) -> str:
        def rep(m):
            kind, key = m.group(1), m.group(2)
            if kind == "pr":
                return self.prs.get(key, "（プルリクエストは作れませんでした）")
            if key in self.issues:
                return self.issues[key]
            return f"https://github.com/{repo}/issues/{key}" if key.isdigit() else "（Issue は作れませんでした）"
        return re.sub(r"\{(issue|pr):([^}]+)\}", rep, text or "")

    def refs(self, text: str) -> set[str]:
        return set(re.findall(r"\{issue:([^}]+)\}", text or ""))


def safe(*texts: str) -> bool:
    return not any(private_hits(t) for t in texts)


def apply_issues(plan: dict, links: Links) -> None:
    for x in plan["issues"]:
        title, body = x.get("title", ""), x.get("body", "")
        if not title or not safe(title, body):
            links.blocked.add(str(x.get("key")))
            count("止めた Issue")
            continue
        labels = [lb for lb in x.get("labels") or [] if lb in LABELS] or ["提案"]
        args = ["issue", "create", "--title", title, "--body-file", "-"]
        for lb in labels:
            args += ["--label", lb]
        url = gh(*args, input_text=body + FOOTER).strip().splitlines()[-1]
        links.issues[str(x.get("key"))] = url
        count("作った Issue")
    for x in plan["edits"]:
        n, body = links.num(x.get("issue")), links.fill(x.get("body", ""))
        if n and body and safe(body):
            gh("issue", "edit", str(n), "--body-file", "-", input_text=body)
            count("直した Issue")
    for x in plan["labels"]:
        n = links.num(x.get("issue"))
        if not n:
            continue
        args = ["issue", "edit", str(n)]
        for lb in x.get("add") or []:
            if lb in LABELS and lb != "人の確認":
                args += ["--add-label", lb]
        for lb in x.get("remove") or []:
            if lb != "人の確認":
                args += ["--remove-label", lb]
        if len(args) > 3:
            gh(*args, check=False)
    for x in plan["comments"]:
        n, body = links.num(x.get("issue")), links.fill(x.get("body", ""))
        if n and body and safe(body):
            gh("issue", "comment", str(n), "--body-file", "-", input_text=body)
            count("コメント")


def changed_lines(rel: str) -> str:
    new = (out / "edit" / rel).read_text(errors="replace").splitlines()
    old_path = self_dir / rel
    old = set(old_path.read_text(errors="replace").splitlines()) if old_path.exists() else set()
    return "\n".join(line for line in new if line not in old)


def apply_prs(plan: dict, links: Links) -> None:
    if not plan["prs"]:
        return
    token = os.environ["GH_TOKEN"]
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("remote", "set-url", "origin", os.environ.get("SIEVE_PUSH_URL") or f"https://x-access-token:{token}@github.com/{repo}.git")
    base = git("rev-parse", "HEAD")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    run = os.environ.get("GITHUB_RUN_ID", "0")
    used: set[str] = set()

    for x in plan["prs"]:
        try:
            make_pr(x, links, base, stamp, run, used)
        except RuntimeError as e:
            print(f"プルリクエストを作れなかった: {e}")
            count("作れなかったプルリクエスト")
    git("checkout", "-q", base)


def make_pr(x: dict, links: Links, base: str, stamp: str, run: str, used: set[str]) -> None:
    files = [f for f in x.get("files") or [] if f not in used and not f.startswith(".github/")
             and ".." not in Path(f).parts and (out / "edit" / f).is_file()]
    title, body = x.get("title", ""), links.fill(x.get("body", ""))
    if not files or not title or not safe(title, body, *(changed_lines(f) for f in files)):
        count("止めたプルリクエスト")
        return
    impact = x.get("impact", "中")
    branch = f"sieve/{stamp}-{run}-{x.get('key', 'p')}"
    git("checkout", "-q", "-B", branch, base)
    for f in files:
        dst = self_dir / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / "edit" / f, dst)
    git("add", "--", *files)
    if not git("status", "--porcelain"):
        count("変更なしのプルリクエスト")
        return
    git("commit", "-q", "-m", title)
    git("push", "-q", "-f", "origin", branch)
    used.update(files)

    nums = [n for n in (links.num(r) for r in x.get("issues") or []) if n]
    if impact == "小":
        refs = "\n".join(f"Closes #{n}" for n in nums)
    else:
        refs = "\n".join(f"提案：#{n}" for n in nums)
    full = f"{body}\n\n影響：{impact}\n{refs}{FOOTER}"
    args = ["pr", "create", "--base", "main", "--head", branch, "--title", title, "--body-file", "-"]
    if impact == "大":
        args.append("--draft")
    url = gh(*args, input_text=full).strip().splitlines()[-1]
    links.prs[str(x.get("key"))] = url
    count(f"プルリクエスト（影響:{impact}）")
    if impact == "大":
        # 下書きで作ってラベルを付けてから、レビュー可にする（CLAUDE.md の手順）
        gh("pr", "edit", url, "--add-label", "人の確認", check=False)
        gh("pr", "ready", url, check=False)
    else:
        # GITHUB_TOKEN で作ったプルリクエストでは validate が自動で走らないので、名指しで起こす
        gh("workflow", "run", "validate.yml", "--ref", branch, check=False)
        gh("pr", "merge", "--auto", "--merge", url, check=False)
    for n in nums:
        gh("issue", "comment", str(n), "--body", f"{'試行として' if impact == '中' else ''}入れるプルリクエスト：{url}", check=False)
        if impact == "中":
            gh("issue", "edit", str(n), "--add-label", "ふるい:試行中", check=False)


def guild_id(items: list[dict]) -> str | None:
    if config.get("sieve_guild_id"):
        return config["sieve_guild_id"]
    for i in items:
        if i["id"].startswith("discord:"):
            return i["link"].split("/")[4]
    guilds = discord("GET", "/users/@me/guilds")
    return guilds[0]["id"] if len(guilds) == 1 else None


def channel_by_name(guild: str, name: str) -> str | None:
    for c in discord("GET", f"/guilds/{guild}/channels"):
        if c.get("name") == name and c.get("type") in (0, 5):
            return c["id"]
    return None


def post(channel: str, text: str, reply_to: str | None = None) -> dict:
    # 篩の書き込みが、次の篩で提案として拾われないように、印の括弧を外す
    text = text.replace("〔提案〕", "提案：").replace("〔覚えておく〕", "覚えておく：")
    body = {"content": text[:1900], "allowed_mentions": {"parse": []}}
    if reply_to:
        body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
    return discord("POST", f"/channels/{channel}/messages", json=body)


def react(channel: str, message: str, emoji: str) -> None:
    try:
        discord("PUT", f"/channels/{channel}/messages/{message}/reactions/{quote(emoji)}/@me")
    except requests.RequestException:
        pass


def apply_discord(plan: dict, items: list[dict], links: Links, planned: bool) -> None:
    held = {h.get("item") for h in plan["held"]}
    replies = {r.get("item"): r.get("text", "") for r in plan["replies"]}

    for item in items:
        iid = item["id"]
        text = replies.get(iid, "")
        blocked = iid in held or bool(links.refs(text) & links.blocked)
        if iid.startswith("issue:"):
            if blocked:
                gh("issue", "comment", str(item["issue"]), "--body", HOLD_TEXT, check=False)
            continue
        if not iid.startswith("discord:") or not has_discord:
            continue
        _, channel, message = iid.split(":")
        if blocked:
            post(channel, HOLD_TEXT, reply_to=message)
            react(channel, message, MARK_HOLD)
            count("保留")
            continue
        if text:
            post(channel, links.fill(text), reply_to=message)
            count("返事")
        if planned:
            react(channel, message, MARK_DONE)

    if not has_discord or not (plan["announce"] or plan["polls"]):
        return
    guild = guild_id(items)
    ch = guild and channel_by_name(guild, config.get("sieve_report_channel", "スキルの相談"))
    if not ch:
        print("知らせるチャンネルが見つからない")
        return
    for a in plan["announce"]:
        text = links.fill(a if isinstance(a, str) else a.get("text", ""))
        if text and safe(text):
            post(ch, text)
            count("知らせ")
    for p in plan["polls"]:
        n, text = links.num(p.get("issue")), links.fill(p.get("text", ""))
        if not (n and text and safe(text)):
            continue
        m = post(ch, text)
        link = f"https://discord.com/channels/{guild}/{ch}/{m['id']}"
        gh("issue", "comment", str(n), "--body", f"見直しの声：{link}（7日たったら、篩が 👍・👎 の数で決めます）", check=False)
        count("見直しの声")


def main() -> int:
    plan = json.loads((out / "plan.json").read_text())
    items = json.loads((out / "items.json").read_text())
    planned = any(plan.values())
    for name, color in LABELS.items():
        gh("label", "create", name, "--color", color, "--force", check=False)
    links = Links()
    apply_issues(plan, links)
    apply_prs(plan, links)
    apply_discord(plan, items, links, planned)
    for x in plan["closes"]:
        n = links.num(x.get("issue"))
        if not n:
            continue
        comment = links.fill(x.get("comment", ""))
        reason = {"completed": "completed", "duplicate": "not planned"}.get(x.get("reason"), "not planned")
        args = ["issue", "close", str(n), "--reason", reason]
        if comment and safe(comment):
            args += ["--comment", comment]
        gh(*args, check=False)
        count("閉じた Issue")
    rows = [f"| {k} | {v} |" for k, v in stats.items()] or ["| なし | 0 |"]
    summary(["### 篩：書き出したもの", "", "| もの | 件数 |", "|:--|:--|", *rows, ""])
    return 0


if __name__ == "__main__":
    sys.exit(main())
