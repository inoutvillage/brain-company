#!/usr/bin/env bash
# claude-role.sh — start Claude Code for a role (the secretariat or a department) in the current dir.
#
# Resumes the newest interactive conversation of this dir that no running claude is using (role_resume.py picks it).
# Starts a new conversation instead, and says why, when there is none, when the newest one is in use elsewhere, or
# when its record cannot be read. Arguments go to claude unchanged.
#
#   CLAUDE_FRESH=1 claude-role.sh ...   start a new conversation on purpose (inside a running session: /clear)
#
# Claude clears the screen when it starts, so each choice is also kept as one line in
# ~/.local/state/brain-company/claude-role.log (CLAUDE_ROLE_LOG overrides; the last 500 lines are kept).
#
# Do not run one-shot `claude` / `claude -p` in a role dir (the secretariat, a department) or in the company root
# (the extractor): an interactive one-shot would be picked up by the next resume, and `-p` adds records even though it
# is skipped. When one is unavoidable, add --no-session-persistence or run it from another dir.
set -u

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
log="${CLAUDE_ROLE_LOG:-$HOME/.local/state/brain-company/claude-role.log}"

note() {  # note <resume|new> <id or -> <message>
  echo "▶ $3"
  {
    mkdir -p "$(dirname "$log")" &&
    printf '%s %s %s %s %s\n' "$(TZ=Asia/Tokyo date '+%F %T')" "$PWD" "$1" "$2" "$3" >> "$log" &&
    if [ "$(wc -l < "$log")" -gt 1000 ]; then tail -n 500 "$log" > "$log.tmp" && cat "$log.tmp" > "$log" && rm -f "$log.tmp"; fi
  } 2>/dev/null
  return 0
}

if [ "${CLAUDE_FRESH:-}" = "1" ]; then
  note new - "新しい会話で起動します（CLAUDE_FRESH=1）"
  exec claude "$@"
fi

py="$(command -v python3 || command -v python3.11)"
line=""
[ -n "$py" ] && line="$("$py" "$here/role_resume.py" "$PWD" 2>/dev/null)"
IFS=$'\t' read -r kind first second <<< "$line"

if [ "$kind" = "resume" ] && [ -n "$first" ]; then
  note resume "${first:0:8}" "この dir の最新の会話を再開します（最後の更新 ${second}）。白紙で起こすなら CLAUDE_FRESH=1、起動の後なら /clear"
  exec claude --resume "$first" "$@"
fi

note new - "新しい会話で起動します（${first:-会話を選べなかった}）"
exec claude "$@"
