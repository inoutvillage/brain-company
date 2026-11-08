#!/usr/bin/env bash
# End-to-end check of the start scripts in a temporary copy of the company root.
#   - tmux runs on a private server: TMUX_TMPDIR points into the temp dir and TMUX is unset,
#     so the real tmux server (and any live session) is never touched
#   - HOME is a fake home (its .bashrc / .bash_profile pin PATH so the fakes win inside tmux windows)
#   - claude is a fake that records its dir and arguments, then waits
#   - the session board's board_ctl.sh is a fake that records it was called
#   - the company root has a space in its path
# Checks: window layout of both sessions, every role window runs claude-role.sh in its own dir, resume / new /
# CLAUDE_FRESH=1, the extractor stays a plain new claude at the root, the CEO office gets no window,
# idempotent restart and extractor repair, exact session-name matching, TMUX_SESSION.
# Usage: tests/test_start_scripts.sh   (Linux / WSL2; needs tmux and python3)
set -u
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/bc-start-e2e.XXXXXX")"
TT="$T/tmux"; mkdir -p "$TT"
TM() { env -u TMUX TMUX_TMPDIR="$TT" tmux "$@"; }
kill_private() {
  local sock
  sock="$(TM display-message -p '#{socket_path}' 2>/dev/null || true)"
  case "$sock" in "$TT"/*) TM kill-server 2>/dev/null ;; "") ;; *) echo "refusing to kill a server outside the temp dir: $sock" >&2; exit 1 ;; esac
}
cleanup() { kill_private; rm -rf "$T"; }
trap cleanup EXIT

# a space in the company path: every command typed into a window must quote it
R="$T/my company"; H="$T/home"; BIN="$T/bin"; OUT="$T/out"
mkdir -p "$R/.claude/scripts" "$R/tools/session-board/tools" "$H" "$BIN" "$OUT"
cp "$REAL"/start-secretariat.sh "$REAL"/start-agents-all.sh "$REAL"/start-agents.sh "$R/"
cp "$REAL"/.claude/scripts/claude-role.sh "$REAL"/.claude/scripts/role_resume.py "$R/.claude/scripts/"
for d in secretariat product-management development research marketing accounting legal corporate-planning ceo-office; do mkdir -p "$R/$d"; done
printf '#!/usr/bin/env bash\nsleep 600\n' > "$R/watcher.sh"
printf '#!/usr/bin/env bash\necho "$*" >> "%s/board_ctl.calls"\n' "$OUT" > "$R/tools/session-board/tools/board_ctl.sh"
chmod +x "$R"/*.sh "$R/tools/session-board/tools/board_ctl.sh" "$R/.claude/scripts/claude-role.sh"

printf '#!/usr/bin/env bash\necho "dir=$(basename "$PWD") fresh=${CLAUDE_FRESH:-} args=$*" > "%s/$(basename "$PWD").txt"\nsleep 600\n' "$OUT" > "$BIN/claude"
chmod +x "$BIN"/*
printf 'export PATH="%s:/usr/bin:/bin"\nexport PYTHONDONTWRITEBYTECODE=1\n' "$BIN" > "$H/.bashrc"
cp "$H/.bashrc" "$H/.bash_profile"

# one interactive conversation for development, so its window must resume it
DEV_REAL="$(cd "$R/development" && pwd -P)"
SID=11111111-2222-4333-8444-555555555555
PDIR="$H/.claude/projects/$(printf '%s' "$DEV_REAL" | sed 's/[^A-Za-z0-9]/-/g')"
mkdir -p "$PDIR"
printf '{"type":"user","cwd":"%s","entrypoint":"cli","sessionId":"%s"}\n' "$DEV_REAL" "$SID" > "$PDIR/$SID.jsonl"

run() {  # run <env...> <script> [args]
  env -i HOME="$H" PATH="$BIN:/usr/bin:/bin" TERM=xterm-256color LANG=C.UTF-8 TMUX_TMPDIR="$TT" "$@" > "$OUT/script.log" 2>&1
}
started() { ls "$OUT" | grep -c '\.txt$'; }
wait_for() {  # wait until n claude fakes have written their line
  for _ in $(seq 1 100); do [ "$(started)" -ge "$1" ] && return 0; sleep 0.1; done; return 1
}
windows() { TM list-windows -t "=$1" -F '#{window_name}' 2>/dev/null | tr '\n' ' '; }
reset() { kill_private; rm -f "$OUT"/*.txt "$OUT"/board_ctl.calls; }
fails=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fails=$((fails + 1)); fi; }

# 1) all departments
run "$R/start-agents-all.sh"; wait_for 7
check "start-agents-all: 8 windows in order, no extractor / ceo-office" '[ "$(windows brain-company)" = "pm dev watcher research marketing accounting legal corporate-planning " ]'
check "start-agents-all: 7 department windows started claude" '[ "$(started)" -eq 7 ]'
check "ceo-office gets no agent" '[ ! -e "$OUT/ceo-office.txt" ]'
check "development resumes its conversation" 'grep -qx "dir=development fresh= args=--resume $SID --dangerously-skip-permissions" "$OUT/development.txt"'
for d in product-management research marketing accounting legal corporate-planning; do
  check "$d starts new with the same flags" 'grep -qx "dir='"$d"' fresh= args=--dangerously-skip-permissions" "$OUT/'"$d"'.txt"'
done
check "role log has one line per window" '[ "$(wc -l < "$H/.local/state/brain-company/claude-role.log")" -eq 7 ]'
check "start-agents-all starts the session board" 'grep -qx "start" "$OUT/board_ctl.calls"'
check "start-agents-all no longer requires inotifywait" '! grep -q inotifywait "$OUT/script.log"'
run "$R/start-agents-all.sh"
check "second start-agents-all says running and starts nothing" 'grep -q "既に起動中" "$OUT/script.log" && [ "$(started)" -eq 7 ]'
reset

# 2) the light set with CLAUDE_FRESH=1
run CLAUDE_FRESH=1 "$R/start-agents.sh"; wait_for 2
check "start-agents: 3 windows pm dev watcher" '[ "$(windows brain-company)" = "pm dev watcher " ]'
check "start-agents with CLAUDE_FRESH=1: development starts new" 'grep -qx "dir=development fresh=1 args=--dangerously-skip-permissions" "$OUT/development.txt"'
check "start-agents with CLAUDE_FRESH=1: pm starts new" 'grep -qx "dir=product-management fresh=1 args=--dangerously-skip-permissions" "$OUT/product-management.txt"'
reset

# 3) secretariat and extractor
run "$R/start-secretariat.sh" --no-attach; wait_for 2
check "secretariat session is named brain-company-secretariat" 'TM has-session -t =brain-company-secretariat'
check "secretariat session has secretariat and extractor windows" '[ "$(windows brain-company-secretariat)" = "secretariat extractor " ]'
check "secretariat starts through claude-role.sh with --add-dir" 'grep -qx "dir=secretariat fresh= args=--add-dir .. --dangerously-skip-permissions" "$OUT/secretariat.txt"'
check "extractor stays a plain new claude at the root" 'grep -qx "dir=my company fresh= args=--dangerously-skip-permissions" "$OUT/my company.txt"'
check "extractor did not go through claude-role.sh" '! grep -q " $R \(new\|resume\) " "$H/.local/state/brain-company/claude-role.log" 2>/dev/null'
sleep 1
check "window names stay fixed while claude runs (automatic-rename off)" '[ "$(windows brain-company-secretariat)" = "secretariat extractor " ]'

# 4) exact names: with only the secretariat session up, the department session must still start
run "$R/start-agents-all.sh"; wait_for 9
check "departments start even though brain-company-secretariat exists (no prefix match)" '[ "$(windows brain-company)" = "pm dev watcher research marketing accounting legal corporate-planning " ]'

# 5) idempotent start and extractor repair, without touching window 0
rm -f "$OUT"/*.txt
run "$R/start-secretariat.sh" --no-attach
check "second start-secretariat does not resend claude" 'grep -q "既に起動中" "$OUT/script.log" && [ "$(started)" -eq 0 ]'
TM kill-window -t "=brain-company-secretariat:extractor"
run "$R/start-secretariat.sh" --no-attach; wait_for 1
check "missing extractor window is repaired" 'grep -q "補完しました" "$OUT/script.log" && [ "$(windows brain-company-secretariat)" = "secretariat extractor " ]'
check "repair started only the extractor" '[ "$(started)" -eq 1 ] && [ -e "$OUT/my company.txt" ]'
check "repair leaves window 0 alone" '! [ -e "$OUT/secretariat.txt" ]'
reset

# 6) TMUX_SESSION renames both sessions
run TMUX_SESSION=acme "$R/start-secretariat.sh" --no-attach
run TMUX_SESSION=acme "$R/start-agents.sh"; wait_for 4
check "TMUX_SESSION=acme: acme and acme-secretariat" 'TM has-session -t =acme && TM has-session -t =acme-secretariat && ! TM has-session -t =brain-company 2>/dev/null'
reset

# 7) bad argument
run "$R/start-secretariat.sh" --nope; rc=$?
check "start-secretariat rejects an unknown argument with 2" '[ "$rc" -eq 2 ]'

echo "failures: $fails"
exit $(( fails > 0 ))
