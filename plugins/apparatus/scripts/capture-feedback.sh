#!/usr/bin/env bash
# 訂正らしき発話を、受け箱（.claude/learnings-inbox.md）に1行積む（UserPromptSubmit）。
#
# 何をするか：短い発話に強い訂正の言葉（「違う」「そうじゃなくて」「やめて」など）があれば、
#   日付とともに受け箱へ候補として積む。上げるのは点検係（growth-loop の6）。挙動は変えない。
# 入れ方：受け箱 .claude/learnings-inbox.md がある（そのリポジトリが育てる仕組みを入れた）ときだけ動く。
#   無ければ何もしない＝このプラグインを入れただけで、ほかのリポジトリにファイルを作らない。
# 鉄則：止めない・何も表示しない・どんな失敗でも exit 0（ふつうの会話を邪魔しない）。
# 見ないもの：長い発話の中の訂正（誤検知を減らすため80字までしか見ない）／言葉を使わない訂正
#   （黙ってやり直させる、など）／訂正でない「違う」（誤検知は点検係の仕分けで落とす）。
. "$(dirname "$0")/hooks-off.sh" 2>/dev/null && hooks_off capture-feedback && exit 0

inbox="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/learnings-inbox.md"
[ -f "$inbox" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

input=$(cat)
printf '%s' "$input" | python3 -c '
import sys, json, datetime, re
inbox = sys.argv[1]
try:
    prompt = json.load(sys.stdin).get("prompt") or ""
except Exception:
    sys.exit(0)
text = re.sub(r"\s+", " ", prompt).strip()
if not text or len(text) > 80:
    sys.exit(0)
markers = ["違う", "ちがう", "そうじゃ", "じゃなくて", "ではなく", "やめて", "ダメ", "だめ", "次からは",
           "no, use", "don'"'"'t", "do not", "instead", "should be", "actually", "remember:"]
low = text.lower()
if not any(m in low for m in markers):
    sys.exit(0)
line = "- [%s / inbox] \"%s\"\n" % (datetime.date.today().isoformat(), text)
try:
    with open(inbox, "a", encoding="utf-8") as f:
        f.write(line)
except Exception:
    pass
' "$inbox" 2>/dev/null
exit 0
