#!/usr/bin/env bash
# End-to-end check of .claude/scripts/extract-actions-daily.sh and .claude/hooks/on-session-end.sh
# in a temporary copy of the company root.
#   - tmux runs on a private server: TMUX_TMPDIR points into the temp dir and TMUX is unset,
#     so the real tmux server (and any live session) is never touched (the daily script calls /usr/bin/tmux directly)
#   - the extractor window runs a fake that records what it receives and, like the real skill,
#     writes last_extracted_at / last_extracted_turn into the conversation log's front matter
# Usage: tests/test_extract_daily.sh   (Linux / WSL2; needs tmux, jq, python3, GNU date)
set -u
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/bc-extract-e2e.XXXXXX")"
TT="$T/tmux"; mkdir -p "$TT"
TM() { env -u TMUX TMUX_TMPDIR="$TT" tmux "$@"; }
kill_private() {
  local sock
  sock="$(TM display-message -p '#{socket_path}' 2>/dev/null || true)"
  case "$sock" in "$TT"/*) TM kill-server 2>/dev/null ;; "") ;; *) echo "refusing to kill a server outside the temp dir: $sock" >&2; exit 1 ;; esac
}
cleanup() { kill_private; rm -rf "$T"; }
trap cleanup EXIT

R="$T/company"; H="$T/home"; OUT="$T/out"
mkdir -p "$R/.claude/scripts" "$R/.claude/hooks" "$R/secretariat/memos" "$R/secretariat/inbox" "$H" "$OUT"
cp "$REAL/.claude/scripts/extract-actions-daily.sh" "$REAL/.claude/scripts/extractor_state.py" "$R/.claude/scripts/"
cp "$REAL/.claude/hooks/on-session-end.sh" "$R/.claude/hooks/"
chmod +x "$R/.claude/scripts/extract-actions-daily.sh" "$R/.claude/hooks/on-session-end.sh"
DAILY="$R/.claude/scripts/extract-actions-daily.sh"
HOOK="$R/.claude/hooks/on-session-end.sh"

day() { TZ=Asia/Tokyo date -d "$1 days ago" +%F; }
D1="$(day 1)"; D2="$(day 2)"; D3="$(day 3)"
log_of() { echo "$R/secretariat/memos/$1_会話ログ.md"; }
mklog() {  # mklog <date> <extracted turn or ""> <turns>
  local f; f="$(log_of "$1")"
  {
    [ -n "$2" ] && printf -- '---\nlast_extracted_at: 2000-01-01T00:00:00+09:00\nlast_extracted_turn: %s\n---\n\n' "$2"
    printf '# 会話ログ: %s\n\n## やり取り\n\n' "$1"
    for n in $(seq 1 "$3"); do printf '### [#%s 10:0%s JST] 社長\n\n> テスト %s\n\n' "$n" "$n" "$n"; done
  } > "$f"
}
mklog "$D3" "" 2      # pending (oldest)
mklog "$D2" 2 2       # already extracted
mklog "$D1" 1 3       # pending

cat > "$T/fake-extractor.sh" <<EOF
#!/usr/bin/env bash
while IFS= read -r line; do
  echo "\$line" >> "$OUT/extractor-got.txt"
  f="\${line#/extract-actions }"
  [ -f "\$f" ] || continue
  max=\$(grep -oE '^### \[#[0-9]+' "\$f" | grep -oE '[0-9]+' | sort -n | tail -1)
  body=\$(awk 'NR==1 && /^---/ {fm=1; next} fm && /^---/ {fm=0; skip=1; next} fm {next} skip && /^\$/ {skip=0; next} {skip=0; print}' "\$f")
  printf -- '---\nlast_extracted_at: %s\nlast_extracted_turn: %s\n---\n\n%s\n' "\$(date --iso-8601=seconds)" "\$max" "\$body" > "\$f"
done
EOF
chmod +x "$T/fake-extractor.sh"

run() {  # cron-like environment
  env -i HOME="$H" PATH="/usr/bin:/bin" LANG=C.UTF-8 TMUX_TMPDIR="$TT" EXTRACT_VERIFY_TIMEOUT=30 "$@" > "$OUT/run.log" 2>&1
}
start_secretariat() {  # the secretariat session with a fake extractor
  TM new-session -d -s brain-company-secretariat -n secretariat -c "$R/secretariat" 'sleep 600'
  TM set-window-option -t "=brain-company-secretariat:secretariat" automatic-rename off > /dev/null
  TM new-window -d -t "=brain-company-secretariat:" -n extractor -c "$R" "$T/fake-extractor.sh"
  TM set-window-option -t "=brain-company-secretariat:extractor" automatic-rename off > /dev/null
  sleep 0.5
}
inbox_count() { ls "$R/secretariat/inbox" | grep -c 'extractor送出失敗' ; }
fails=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fails=$((fails + 1)); fi; }
STATE="$R/.claude/extract-cron.state"
ELOG="$R/secretariat/logs/extract-stop.log"
SENT="$R/secretariat/logs/.extractor-unavailable"

# 1) disabled by default
run "$DAILY"; rc=$?
check "no state file: creates paused, exits 0, sends nothing" '[ "$rc" -eq 0 ] && [ "$(cat "$STATE")" = paused ] && grep -q "skip (state=paused)" "$ELOG" && [ ! -e "$OUT/extractor-got.txt" ]'
echo active > "$STATE"

# 2) dry run picks the oldest pending day from the flat memos layout
run "$DAILY" --dry-run
check "dry run selects the oldest pending day ($D3)" 'grep -q "対象決定: $D3（走査" "$ELOG" && grep -q -- "--dry-run のため送出しません" "$ELOG"'

# 3) bad arguments
run "$DAILY" 2026/01/01; rc1=$?
run "$DAILY" --nope; rc2=$?
check "malformed date and unknown option exit 2" '[ "$rc1" -eq 2 ] && [ "$rc2" -eq 2 ]'

# 4) no secretariat session: one inbox notice per outage
run "$DAILY"; rc=$?
check "no session: exit 0, inbox notice and sentinel" '[ "$rc" -eq 0 ] && [ "$(inbox_count)" -eq 1 ] && [ -e "$SENT" ]'
check "inbox notice names the secretariat session" 'grep -q "brain-company-secretariat:extractor" "$R"/secretariat/inbox/*extractor送出失敗.md'
run "$DAILY"
check "same outage again: no second notice" '[ "$(inbox_count)" -eq 1 ] && grep -q "inbox 通知は抑制" "$ELOG"'

# 5) another session whose name only starts with the secretariat's must not be taken for it
#    (tmux falls back to a prefix match when no session has the exact name)
TM new-session -d -s brain-company-secretariat2 -n extractor "cat >> '$OUT/wrong-target.txt'"
TM set-window-option -t "=brain-company-secretariat2:extractor" automatic-rename off > /dev/null
check "precondition: plain -t would match the other session by prefix" 'TM has-session -t brain-company-secretariat 2>/dev/null'
run "$DAILY"
sleep 0.5
check "prefix-only match is not used as the target" '[ ! -s "$OUT/wrong-target.txt" ] && [ ! -e "$OUT/extractor-got.txt" ] && grep -q "extractor UNAVAILABLE" "$ELOG"'
TM kill-session -t =brain-company-secretariat2

# 6) the real path: send, verify, recover
start_secretariat
run "$DAILY"; rc=$?
check "sends /extract-actions with the flat log path of $D3" 'grep -qx "/extract-actions $(log_of "$D3")" "$OUT/extractor-got.txt"'
check "verification OK, failcount 0, sentinel cleared" '[ "$rc" -eq 0 ] && grep -q "実行確認 OK" "$ELOG" && [ "$(cat "$R/.claude/extract-cron.failcount")" = 0 ] && [ ! -e "$SENT" ]'
run "$DAILY"
check "next run moves on to $D1" 'grep -qx "/extract-actions $(log_of "$D1")" "$OUT/extractor-got.txt"'
run "$DAILY"; rc=$?
check "nothing pending: exit 0 without sending" '[ "$rc" -eq 0 ] && [ "$(wc -l < "$OUT/extractor-got.txt")" -eq 2 ] && grep -q "未抽出の対象なし" "$ELOG"'

hook() { printf '{"cwd":"%s","hook_event_name":"SessionEnd"}' "$1" | env -u TMUX -u CLAUDE_CONFIG_DIR HOME="$H" TMUX_TMPDIR="$TT" PATH="/usr/bin:/bin" "$HOOK"; }

# 6b) the extractor sits on a confirmation prompt: neither the daily run nor the hook may press Enter
#     (a fake Claude Code session record for the extractor pane, as ~/.claude/sessions/<pid>.json)
mkrec() {  # mkrec <status>
  local t="=brain-company-secretariat:extractor" pid pane win start
  pid=$(TM display-message -p -t "$t" '#{pane_pid}'); pane=$(TM display-message -p -t "$t" '#{pane_id}')
  win=$(TM display-message -p -t "$t" '#{window_id}')
  start=$(python3 -c 'import sys;print(open("/proc/%s/stat" % sys.argv[1]).read().rsplit(")", 1)[1].split()[19])' "$pid")
  mkdir -p "$H/.claude/sessions"
  printf '{"pid":%s,"procStart":"%s","tmux":"brain-company-secretariat:%s.%s","status":"%s","waitingFor":"permission","updatedAt":1}\n' \
    "$pid" "$start" "$win" "$pane" "$1" > "$H/.claude/sessions/$pid.json"
}
got() { wc -l < "$OUT/extractor-got.txt"; }
notice_says() { grep -l "$1" "$R"/secretariat/inbox/*extractor送出失敗.md > /dev/null 2>&1; }
D4="$(day 4)"; mklog "$D4" "" 1
mkrec waiting
n=$(got)
run "$DAILY"; rc=$?
sleep 0.5
check "daily: extractor on a confirmation prompt -> nothing sent, notice" '[ "$rc" -eq 0 ] && [ "$(got)" -eq "$n" ] && notice_says "確認の画面" && grep -q "skip: 送出先 .*確認の画面" "$ELOG"'
rm -f "$R"/secretariat/inbox/*.md "$SENT"
hook "$R/secretariat"; rc=$?
sleep 0.5
check "hook: extractor on a confirmation prompt -> nothing sent, notice" '[ "$rc" -eq 0 ] && [ "$(got)" -eq "$n" ] && notice_says "確認の画面"'
rm -f "$R"/secretariat/inbox/*.md "$SENT"
mkrec idle
hook "$R/secretariat"; sleep 1
check "hook: idle extractor -> sends /extract-actions" '[ "$(got)" -eq $((n + 1)) ] && [ "$(tail -1 "$OUT/extractor-got.txt")" = "/extract-actions" ]'

# 7) SessionEnd hook
n=$(got)
hook "$R"; rc=$?
sleep 0.5
check "hook: non-secretariat cwd is a no-op" '[ "$rc" -eq 0 ] && [ "$(got)" -eq "$n" ]'
hook "$R/secretariat-foo"
check "hook: secretariat-foo is not the secretariat" '[ "$(got)" -eq "$n" ]'
hook "$R/secretariat"; sleep 1
check "hook: secretariat cwd sends /extract-actions to the extractor" '[ "$(tail -1 "$OUT/extractor-got.txt")" = "/extract-actions" ]'
kill_private; rm -f "$R"/secretariat/inbox/*
hook "$R/secretariat"; rc=$?
check "hook: no session -> exit 0, one inbox notice" '[ "$rc" -eq 0 ] && [ "$(inbox_count)" -eq 1 ] && [ -e "$SENT" ]'
hook "$R/secretariat"
check "hook: same outage again -> no second notice" '[ "$(inbox_count)" -eq 1 ]'

echo "failures: $fails"
exit $(( fails > 0 ))
