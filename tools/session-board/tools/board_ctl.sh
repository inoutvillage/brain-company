#!/usr/bin/env bash
# セッションの一覧の画面を起動・停止する。 board_ctl.sh start|stop|status [番号]
# 番号の既定は SESSION_BOARD_PORT（無ければ 18790）。start は、動いていれば何もしない。
# 扱うのは、この置き場の bin/session-board をこの番号で起こした物だけ（別の置き場の画面・別の番号の画面には触れない）
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd -P)"
BIN="$HERE/bin/session-board"
PY="${PYTHON:-python3}"
# 置き場の決め方は board/config.py の state_dir と同じ（変える時は両方を変える）
STATE="${SESSION_BOARD_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/brain-company/session-board}"
[[ "$STATE" == /* ]] || STATE="$PWD/$STATE"
PORT="${2:-${SESSION_BOARD_PORT:-18790}}"
if ! [[ "$PORT" =~ ^[1-9][0-9]{0,4}$ ]] || (( PORT > 65535 )); then
  echo "番号の形が違う（1〜65535 の数）: $PORT" >&2; exit 2
fi
PIDFILE="$STATE/board-$PORT.pid"

need() {
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || { echo "見つからない: $c" >&2; exit 1; }
  done
}

is_board() {
  # 番号の使い回し・別の置き場の画面に当たらないよう、命令の行（… <BIN> serve --port <番号>）で本人かを確かめる
  local args
  args="$(tr '\0' '\n' 2>/dev/null < "/proc/$1/cmdline")" || return 1
  [[ "$args" == *$'\n'"$BIN"$'\n'serve$'\n'--port$'\n'"$PORT" ]]
}

running_pid() {
  local pid=""
  [[ -f "$PIDFILE" ]] && pid="$(cat "$PIDFILE")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && is_board "$pid"; then echo "$pid"; return 0; fi
  # 番号の控えが無い・古い時は、プロセスの一覧から探す
  for pid in $(pgrep -f "session-board serve --port $PORT\$" || true); do
    if is_board "$pid"; then echo "$pid"; return 0; fi
  done
  return 1
}

need pgrep
# 本人の見分けと集める所の両方が /proc を使う。無い PC（macOS 等）では、起こしても見分けられずに 10 秒待って残るので、すぐ止める
[[ -d /proc ]] || { echo "Linux / WSL2 専用（/proc が無い）。この PC では動かない" >&2; exit 1; }
case "${1:-}" in
  start)
    if pid="$(running_pid)"; then echo "もう動いている（pid $pid・http://127.0.0.1:$PORT/）"; exit 0; fi
    need "$PY" curl setsid nohup
    umask 077
    mkdir -p "$STATE"; chmod 700 "$STATE"
    # 起こした端末を閉じても止まらないよう、別のセッションで起こす。置き場は決めた物をそのまま渡す
    SESSION_BOARD_STATE_DIR="$STATE" setsid nohup "$PY" "$BIN" serve --port "$PORT" </dev/null >>"$STATE/board.out" 2>&1 &
    launched=$!
    deadline=$((SECONDS + 10))  # 呼んだ側（一斉起動など）を遅らせないよう、待つのは 10 秒まで
    while (( SECONDS < deadline )); do
      if curl -fsS -m 1 -o /dev/null "http://127.0.0.1:$PORT/healthz" 2>/dev/null && pid="$(running_pid)"; then
        echo "$pid" >"$PIDFILE"
        echo "起動した（pid $pid・http://127.0.0.1:$PORT/）"; exit 0
      fi
      # 起きずに終わった時（番号が使われている・Python の版が足りない等）は、待ち切らずにすぐ返す
      if ! kill -0 "$launched" 2>/dev/null && ! running_pid >/dev/null; then
        echo "起動できなかった（$STATE/board.out を見る）" >&2; exit 1
      fi
      sleep 0.5
    done
    echo "起動を確かめられない（$STATE/board.out を見る）" >&2; exit 1
    ;;
  stop)
    if pid="$(running_pid)"; then
      kill "$pid"
      for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
      if kill -0 "$pid" 2>/dev/null; then echo "止まらない（pid $pid）" >&2; exit 1; fi
      rm -f "$PIDFILE"; echo "止めた（pid $pid）"
    else
      echo "動いていない"
    fi
    ;;
  status)
    if pid="$(running_pid)"; then
      need curl
      echo "動いている（pid $pid・http://127.0.0.1:$PORT/）"; curl -fsS -m 2 "http://127.0.0.1:$PORT/healthz"; echo
    else
      echo "動いていない"; exit 3
    fi
    ;;
  *)
    echo "使い方: $0 start|stop|status [番号]" >&2; exit 2
    ;;
esac
