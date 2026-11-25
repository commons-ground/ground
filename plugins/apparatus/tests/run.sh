#!/usr/bin/env bash
# apparatus の hook の試験。止める側・通す側・何も起きない側を必ず置く（core の grounding の2「直った」）。
# 使い方：bash plugins/apparatus/tests/run.sh
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_PROJECT_DIR="$tmp/proj" HOME="$tmp/home"
mkdir -p "$CLAUDE_PROJECT_DIR/.claude/state" "$HOME/.claude"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
ng()  { fail=$((fail+1)); echo "NG: $1"; }

bashcmd() { python3 -c 'import json,sys; print(json.dumps({"tool_input":{"command":sys.argv[1]}}))' "$1" 2>/dev/null; }
wl() { bashcmd "$1" | "$here/scripts/wait-loop-guard.sh" 2>/dev/null; echo $?; }

# 止める側
for c in \
  'until [ -f /tmp/x ]; do sleep 20; done' \
  'while ! grep -q done log; do sleep 5; done' \
  $'until test -f a\ndo\n  sleep 3\ndone'; do
  [ "$(wl "$c")" = 2 ] && ok || ng "止めるべき: $c"
done
# 通す側
for c in \
  'n=0; while [ ! -f x ] && [ $n -lt 40 ]; do n=$((n+1)); sleep 30; done' \
  'timeout 60 bash -c "until [ -f x ]; do sleep 1; done"' \
  'while read -r l; do sleep 1; echo $l; done < f' \
  'for i in $(seq 5); do sleep 1; done' \
  'git commit -m "until x; do sleep 1; done"' \
  'ls -la' ; do
  [ "$(wl "$c")" = 0 ] && ok || ng "通すべき: $c"
done
# 止めるスイッチ
echo wait-loop-guard > "$CLAUDE_PROJECT_DIR/.claude/state/hooks-off"
[ "$(wl 'until [ -f x ]; do sleep 2; done')" = 0 ] && ok || ng "hooks-off で止まるべき"
rm "$CLAUDE_PROJECT_DIR/.claude/state/hooks-off"
echo all > "$HOME/.claude/hooks-off"
[ "$(wl 'until [ -f x ]; do sleep 2; done')" = 0 ] && ok || ng "~/.claude/hooks-off の all で止まるべき"
rm "$HOME/.claude/hooks-off"

# capture-feedback
cf() { python3 -c 'import json,sys; print(json.dumps({"prompt":sys.argv[1]}))' "$1" 2>/dev/null | "$here/scripts/capture-feedback.sh" >"$tmp/out" 2>&1; echo $?; }
inbox="$CLAUDE_PROJECT_DIR/.claude/learnings-inbox.md"
[ "$(cf 'そうじゃなくて、先に原因を調べて')" = 0 ] && [ ! -f "$inbox" ] && ok || ng "受け箱が無ければ何もしないべき"
: > "$inbox"
cf 'そうじゃなくて、先に原因を調べて' >/dev/null
cf 'ありがとう、続けて' >/dev/null
cf "$(printf 'あ%.0s' $(seq 100))違う" >/dev/null
[ "$(wc -l < "$inbox")" -eq 1 ] && grep -q '先に原因を調べて' "$inbox" && ok || ng "訂正1行だけ積むべき（$(wc -l < "$inbox")行）"
[ ! -s "$tmp/out" ] && ok || ng "capture-feedback は何も出力しないべき"
printf '{bad json' | "$here/scripts/capture-feedback.sh"; [ $? = 0 ] && ok || ng "壊れた入力でも exit 0"

# 件数の下限（試験が死んでいないか）
total=$((pass+fail))
[ "$total" -ge 15 ] || { echo "NG: 試験の件数が少なすぎる（$total）"; fail=$((fail+1)); }
echo "pass=$pass fail=$fail"
[ "$fail" = 0 ]
