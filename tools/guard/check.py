"""プルリクエストの差分を機械で点検する（門番）。

人に「とりあえず確認」を回さない代わりに、危ない変更を機械で止める。
- 止める（BLOCK）：鍵の書き込み、スクリプトの注入、外から落としたものをそのまま実行、など。直すまで入らない
- 人に回す（HUMAN）：人にしか決められないこと。鍵・権限を足す、お金の上限を上げる、
  安全の仕組み（この門番と自動マージ）を変える、基本ルール（コモンズの価値観）を変える、大きく消す
- それ以外は、validate が通れば自動で入る。おかしければ「取り下げ」で戻す

使い方：python check.py pr.diff  → 結果を JSON で標準出力に出す
"""
import json
import re
import sys

# いま使っている鍵の名前。これ以外の secrets を参照し始めたら、人が鍵を用意する話なので人に回す
KNOWN_SECRETS = {
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLOUDFLARE_API_TOKEN",
    "DISCORD_BOT_TOKEN", "GITHUB_TOKEN", "NOTION_TOKEN",
}

SECRET_LITERALS = [
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub のトークン"),
    (r"github_pat_[A-Za-z0-9_]{30,}", "GitHub のトークン"),
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic の鍵"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "秘密鍵"),
    (r"xox[abprs]-[A-Za-z0-9-]{10,}", "Slack のトークン"),
    (r"AKIA[0-9A-Z]{16}", "AWS の鍵"),
    (r"[MN][A-Za-z0-9]{23,25}\.[\w-]{6}\.[\w-]{27,}", "Discord ボットの鍵"),
    (r"secret_[A-Za-z0-9]{40,}|ntn_[A-Za-z0-9]{40,}", "Notion の鍵"),
]

# 安全の仕組みそのもの。ここを変えるのは、門番を弱められるかどうかの話なので人に回す
SAFETY_FILES = re.compile(r"^(tools/guard/|\.github/workflows/(guard|auto-merge)\.yml$)")
VALUES_FILES = re.compile(r"^plugins/core/skills/basic-rules/")
WORKFLOW = re.compile(r"^\.github/workflows/.+\.ya?ml$")
WRITE_PERM = re.compile(
    r"^\s*(contents|issues|pull-requests|actions|packages|id-token|deployments|statuses|checks|pages|"
    r"security-events|repository-projects|discussions|attestations)\s*:\s*write\b"
)
INJECTION = re.compile(r"\$\{\{\s*github\.event\.(issue|comment|pull_request|review|discussion)\.(title|body)")
PIPE_SH = re.compile(r"(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z)?sh\b")
MONEY = re.compile(r"(max_budget_usd|MAX_PER_HOUR|max_turns)\b.*?(\d+(\.\d+)?)")
BIG_DELETE = 800


def parse(diff: str):
    files, cur = {}, None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            cur = m.group(2) if m else None
            files.setdefault(cur, {"add": [], "del": []})
        elif cur is None or line.startswith(("+++", "---")):
            continue
        elif line.startswith("+"):
            files[cur]["add"].append(line[1:])
        elif line.startswith("-"):
            files[cur]["del"].append(line[1:])
    return files


def check(diff: str) -> dict:
    block, human = [], []
    files = parse(diff)
    deleted = 0
    for path, ch in files.items():
        deleted += len(ch["del"])
        added = "\n".join(ch["add"])
        for pat, name in SECRET_LITERALS:
            if re.search(pat, added):
                block.append(f"`{path}`：{name}らしき値が書かれている。鍵は secrets に置く")
        for line in ch["add"]:
            if PIPE_SH.search(line):
                block.append(f"`{path}`：外から落としたものをそのまま実行している（`{line.strip()[:80]}`）")
        if WORKFLOW.match(path or ""):
            for line in ch["add"]:
                if INJECTION.search(line):
                    block.append(f"`{path}`：Issue やコメントの本文を workflow の式に直接入れている（中身で命令を書き込まれる）。env に入れてから使う")
                if WRITE_PERM.match(line):
                    human.append(f"`{path}`：書き込みの権限を足している（`{line.strip()}`）")
                if "pull_request_target" in line and not SAFETY_FILES.match(path):
                    human.append(f"`{path}`：`pull_request_target` を使い始めている（外の人の PR でも鍵つきで動く）")
                for s in re.findall(r"secrets\.([A-Z0-9_]+)", line):
                    if s not in KNOWN_SECRETS:
                        human.append(f"`{path}`：新しい鍵 `{s}` を使い始めている（人が鍵を用意する）")
        for line in ch["add"]:
            m = MONEY.search(line)
            if m:
                old = [MONEY.search(x) for x in ch["del"]]
                old = [float(o.group(2)) for o in old if o and o.group(1) == m.group(1)]
                if old and float(m.group(2)) > max(old):
                    human.append(f"`{path}`：お金・回数の上限 `{m.group(1)}` を上げている（{max(old):g} → {m.group(2)}）")
        if SAFETY_FILES.match(path or ""):
            human.append(f"`{path}`：安全の仕組み（門番・自動マージ）を変えている")
        if VALUES_FILES.match(path or ""):
            human.append(f"`{path}`：基本ルール（コモンズの考え方）を変えている")
    if deleted > BIG_DELETE:
        human.append(f"全体で {deleted} 行を消している（大きく消すときは人が確かめる）")
    dedup = lambda xs: list(dict.fromkeys(xs))
    return {"block": dedup(block), "human": dedup(human), "files": len(files)}


if __name__ == "__main__":
    print(json.dumps(check(open(sys.argv[1], encoding="utf-8").read()), ensure_ascii=False))
