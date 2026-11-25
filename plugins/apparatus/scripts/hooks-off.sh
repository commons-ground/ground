#!/usr/bin/env bash
# apparatus の hook を1本だけ（または全部）止めるための共通判定。
#
# Claude Code には、プラグインの hook を1本だけ外す設定が無い。逃がし口が無いと、
# 1本が邪魔なだけでプラグインごと（ほかの hook ごと）止めることになる。
#
# 止め方（1行に1つ。hook の名前か all。行を消せば戻る）:
#   <リポジトリ>/.claude/state/hooks-off   そのリポジトリだけ（作業フォルダからも本体のこのファイルを見る）
#   ~/.claude/hooks-off                    その端末の全部
#
# 使い方（各 hook の先頭で）:
#   . "$(dirname "$0")/hooks-off.sh" && hooks_off "<名前>" && exit 0
#
# 見ないもの：止めたことは記録しない。
hooks_off() {
  local name="${1:-}" f root common
  [ -n "$name" ] || return 1
  root="${CLAUDE_PROJECT_DIR:-$PWD}"
  # 作業フォルダ（git worktree）でも本体の1か所を見る。フォルダごとに割れると止めたつもりが効かない
  common="$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" && root="$(dirname "$common")"
  for f in "$root/.claude/state/hooks-off" "${CLAUDE_PROJECT_DIR:-$PWD}/.claude/state/hooks-off" "${HOME:-/nonexistent}/.claude/hooks-off"; do
    [ -f "$f" ] || continue
    grep -qxF "all" "$f" 2>/dev/null && return 0
    grep -qxF "$name" "$f" 2>/dev/null && return 0
  done
  return 1
}
