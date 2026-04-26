#!/usr/bin/env bash
# PostToolUse hook: Write/Edit のファイルパスを secretariat/logs/tool-usage.log に追記
#
# 入力: stdin に Claude Code が JSON イベントデータを流す
#   { "tool_name": "Write", "tool_input": { "file_path": "..." }, "tool_response": { "success": true }, ... }
# 出力: 1 行 = "<ISO8601-JST> <tool> <success> <file-path-masked>"
# 動作: 常に exit 0（ログ記録は副次機能、失敗しても本体処理を止めない）
set -u

# プロジェクトルートをスクリプトの実体パスから再計算（CLAUDE_PROJECT_DIR 非依存、シンボリックリンク経由でも安定）
SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}")"
CLAUDE_PROJECT_DIR="$(dirname "$(dirname "$(dirname "$SCRIPT_REAL")")")"

LOG="${CLAUDE_PROJECT_DIR}/secretariat/logs/tool-usage.log"
mkdir -p "$(dirname "$LOG")"

INPUT=$(cat)
TS=$(TZ=Asia/Tokyo date --iso-8601=seconds)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // "-"')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // "-"')
SUCCESS=$(echo "$INPUT" | jq -r '.tool_response.success // true')

# ユーザ名のマスク
FILE_MASKED=$(echo "$FILE" | sed -E 's|/home/[^/]+/|~/|g')

printf '%s %s %s %s\n' "$TS" "$TOOL" "$SUCCESS" "$FILE_MASKED" >> "$LOG"
exit 0
