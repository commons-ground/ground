#!/usr/bin/env bash
# 上限の無い待つループを止める（PreToolUse / Bash）。
#
# 何を解くか：AI が「until <条件>; do sleep N; done」で何かを待つと、待つ先が来ない（条件が永久に
#   真にならない）ときに裏で回り続ける。ある開発の場では、別のセッションの完了を待つループが
#   3日16時間回っていた。サブエージェントや裏で動かしたシェルの完了は通知で届くので、待つ必要が無い。
# 止めるもの：until/while … do … sleep N … done があり、上限の印が1つも無いコマンド。
# 通すもの：timeout で包んである／回数の印（++、+= 1、$((n+1))、seq、for、-lt などの比較、
#   SECONDS、date +%s）／while read（入力で終わる）／文として書いただけのもの（ヒアドキュメント、
#   -m・--body・--title の値、echo・printf の文字列）。
# 見ないもの：上限の印が「在るか」だけを見る（数えて比べない形は通る）／sleep の無い busy loop／
#   すでに回っているループ／意図した無限の監視（形では区別できないので止まる。スクリプトにして呼ぶ）。
# 試験：plugins/apparatus/tests/run.sh
. "$(dirname "$0")/hooks-off.sh" 2>/dev/null && hooks_off wait-loop-guard && exit 0
command -v python3 >/dev/null 2>&1 || exit 0

input=$(cat)
verdict=$(printf '%s' "$input" | python3 -c '
import sys, json, re
try:
    c = json.load(sys.stdin).get("tool_input", {}).get("command", "") or ""
except Exception:
    c = ""
src = c
def _hd(m):
    ln = src.rfind("\n", 0, m.start()) + 1
    if re.search(r"\b(bash|sh|zsh)\b", src[ln:m.start()]):
        return m.group(0)
    return " "
c = re.sub(r"<<-?\s*[\x27\x22]?(\w+)[\x27\x22]?\n.*?\n\s*\1\b", _hd, c, flags=re.S)
QS = r"([\x27\x22])(?:\\.|(?!{n}).)*{n}"
# 文として書いただけのもの（コミットや PR の本文・題、echo/printf の文字列）は落とす。bash -c の中身は残す
c = re.sub(r"(-m|--message|-b|--body|-t|--title)(\s*=?\s*)" + QS.format(n=r"\3"), r"\1 MSG", c, flags=re.S)
def _say(m):
    return m.group(1) + re.sub(QS.format(n=r"\1"), " MSG ", m.group(2), flags=re.S)
c = re.sub(r"\b(echo|printf)\b((?:[^|;&\n\x27\x22]|" + QS.format(n=r"\3") + r")*)", _say, c, flags=re.S)
loop = re.compile(r"\b(until|while)\b(?P<cond>.*?)(;|\n)\s*do\b(?P<body>.*?)\bdone\b", re.S)
bounded = re.compile(r"\btimeout\s+[0-9]|\+\+|[+-]=\s*[0-9]|\$\(\(.*[+-]\s*1\s*\)\)|\bseq\b|\bfor\b|\s-(lt|le|gt|ge|eq|ne)\s|\bSECONDS\b|date\s+\+%s", re.S)
for m in loop.finditer(c):
    if not (re.search(r"\bsleep\s+[\x27\x22]?[$0-9]", m.group("body")) or re.search(r"\bsleep\s+[\x27\x22]?[$0-9]", m.group("cond"))):
        continue
    if re.match(r"\s*(IFS=\S*\s+)?read\b", m.group("cond")):
        continue
    if re.search(r"\btimeout\s+[0-9]", c[:m.start()]) or bounded.search(m.group(0)):
        continue
    print("BLOCK")
    sys.exit(0)
print("OK")' 2>/dev/null)

[ "$verdict" = BLOCK ] || exit 0
printf '⛔ 上限の無い待つループ\nWHY: サブエージェントや裏で動かしたシェルの完了は通知で届く。上限の無い until/while … sleep は、待つ先が来ないと永久に回る。\nFIX: 待たずに次の手へ進む（完了は通知で届く）。どうしても待つなら回数の上限を付ける（n=0; while [ 条件 ] && [ $n -lt 40 ]; do n=$((n+1)); sleep 30; done）。\nREF: ground の apparatus（scripts/wait-loop-guard.sh）。止めたいときは .claude/state/hooks-off に wait-loop-guard と書く\n' >&2
exit 2
