#!/usr/bin/env bash
# セッションの一覧の画面をブラウザで開く。 open_board.sh [番号]
# 番号の既定は SESSION_BOARD_PORT（無ければ 18790）。画面が動いているかは見ない（起こすのは board_ctl.sh start）。
# 使う物の順: $BROWSER → wslview → explorer.exe（WSL の時だけ）→ xdg-open → open（macOS の時だけ）。
# どれも無ければ URL を出して 1 で終わる
set -euo pipefail

PORT="${1:-${SESSION_BOARD_PORT:-18790}}"
if ! [[ "$PORT" =~ ^[1-9][0-9]{0,4}$ ]] || (( PORT > 65535 )); then
  echo "番号の形が違う（1〜65535 の数）: $PORT" >&2; exit 2
fi
URL="http://127.0.0.1:$PORT/"

is_wsl() {
  [[ -n "${WSL_DISTRO_NAME:-}" ]] && return 0
  [[ -r /proc/sys/kernel/osrelease ]] || return 1
  [[ "$(< /proc/sys/kernel/osrelease)" == *[Mm]icrosoft* ]]
}

opened() { echo "開いた（$1・$URL）"; exit 0; }

# $BROWSER はコマンドの名前か場所（引数は付けない）
if [[ -n "${BROWSER:-}" ]] && command -v "$BROWSER" >/dev/null 2>&1; then
  "$BROWSER" "$URL" && opened "$BROWSER"
fi
if command -v wslview >/dev/null 2>&1; then
  wslview "$URL" && opened wslview
fi
if is_wsl && command -v explorer.exe >/dev/null 2>&1; then
  # explorer.exe は開けた時も 1 を返す。動かせなかった時（126・127。Windows の物を動かせない設定など）だけ次へ
  rc=0; explorer.exe "$URL" || rc=$?
  (( rc == 126 || rc == 127 )) || opened explorer.exe
fi
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" && opened xdg-open
fi
if [[ "${OSTYPE:-}" == darwin* ]] && command -v open >/dev/null 2>&1; then
  open "$URL" && opened open
fi
echo "ブラウザを開く道具が見つからない（\$BROWSER・wslview・explorer.exe・xdg-open・open）。ブラウザで開く: $URL" >&2
exit 1
