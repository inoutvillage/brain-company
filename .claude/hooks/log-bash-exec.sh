#!/usr/bin/env bash
# PreToolUse hook: Bash コマンドを secretariat/logs/bash-log.txt に追記（サニタイズ付き）
#
# 入力: stdin に Claude Code が JSON イベントデータを流す
#   { "tool_name": "Bash", "tool_input": { "command": "..." }, "cwd": "...", ... }
# 出力: 1 行 = "<ISO8601-JST> <cwd-masked> PRE <command-sanitized≤200chars>"
# 動作: 常に exit 0
#
# サニタイズ方針:
#   1) 機密キーワード (password|secret|token|api_key|key=) を含む行は全体 REDACTED（安全側・偽陽性許容）
#   2) KEY=VALUE パターン（環境変数代入）は値をマスク
#   3) /home/<user>/ パスは ~/ に置換
#   4) 200 文字で切り詰め
set -u

# プロジェクトルートをスクリプトの実体パスから再計算（CLAUDE_PROJECT_DIR 非依存、シンボリックリンク経由でも安定）
SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}")"
CLAUDE_PROJECT_DIR="$(dirname "$(dirname "$(dirname "$SCRIPT_REAL")")")"

LOG="${CLAUDE_PROJECT_DIR}/secretariat/logs/bash-log.txt"
mkdir -p "$(dirname "$LOG")"

INPUT=$(cat)
TS=$(TZ=Asia/Tokyo date --iso-8601=seconds)
CWD=$(echo "$INPUT" | jq -r '.cwd // "-"')
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // "-"')

# サニタイズ
# 1) 機密キーワードを含む行は全体 REDACTED
if echo "$CMD" | grep -qiE '(password|secret|token|api_key|^key=|[^a-z]key=)'; then
  CMD_OUT="[REDACTED: sensitive keyword detected]"
else
  # 2) KEY=VALUE パターンをマスク（環境変数への代入）
  CMD_MASKED=$(echo "$CMD" | sed -E 's/([A-Z_][A-Z0-9_]*=)[^ ]+/\1******/g')
  # 3) ユーザ名パスのマスク
  CMD_MASKED=$(echo "$CMD_MASKED" | sed -E 's|/home/[^/]+/|~/|g')
  # 4) 200 文字に切り詰め
  CMD_OUT="${CMD_MASKED:0:200}"
fi

CWD_MASKED=$(echo "$CWD" | sed -E 's|/home/[^/]+/|~/|g')

printf '%s %s PRE %s\n' "$TS" "$CWD_MASKED" "$CMD_OUT" >> "$LOG"
exit 0
