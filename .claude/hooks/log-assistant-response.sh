#!/usr/bin/env bash
# Stop hook: 秘書の返答を会話ログにリアルタイム追記
#
# 入力: stdin に Claude Code が JSON イベントデータを流す
#   { "session_id": "...", "cwd": "...", "transcript_path": "...",
#     "last_assistant_message": "...", "stop_hook_active": ..., ... }
# 出力: 常に exit 0
# 動作: last_assistant_message を最優先で取得し、無ければ transcript JSONL から
#       最後の user 境界以降の assistant text を全部結合してフォールバック
#
# 設計:
#   - トークン消費ゼロ（jq + シェル）
#   - 完全保存（要約せず、生 text content をそのまま記録）
#   - ツール呼び出し（tool_use / tool_result）は除外、純粋な assistant text のみ
#   - 社長と秘書はセットで同じ #NN を共有（ターン = 1往復）
set -u

# プロジェクトルートをスクリプトの実体パスから再計算（CLAUDE_PROJECT_DIR 非依存、シンボリックリンク経由でも安定）
SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}")"
CLAUDE_PROJECT_DIR="$(dirname "$(dirname "$(dirname "$SCRIPT_REAL")")")"

INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // ""')

# 部署判定（CLAUDE_PROJECT_DIR/<dept>/ 配下なら <dept> を抽出、ルートは secretariat 扱い）
case "$CWD" in
  "${CLAUDE_PROJECT_DIR}"|"${CLAUDE_PROJECT_DIR}/")
    DEPT="secretariat"
    ;;
  "${CLAUDE_PROJECT_DIR}/"*)
    REL="${CWD#${CLAUDE_PROJECT_DIR}/}"
    DEPT="${REL%%/*}"
    case "$DEPT" in
      .*) exit 0 ;;
    esac
    ;;
  *) exit 0 ;;
esac

# 第1優先: hook 入力の last_assistant_message（Claude Code が turn 完了時の生 text を提供）
RESPONSE=$(echo "$INPUT" | jq -r '.last_assistant_message // ""')

# フォールバック: JSONL から「直近の user entry 以降の全 assistant.text」を結合
# 旧実装の `last` だけ参照は、tool_use のみで終わる entry を取って空になる問題があった
if [ -z "$RESPONSE" ] || [ "$RESPONSE" = "null" ]; then
  if [ -f "$TRANSCRIPT" ]; then
    RESPONSE=$(jq -s -r '
      . as $a
      | ($a | length) as $n
      | (
          [ range($n - 1; -1; -1)
            | . as $i
            | select($a[$i].type == "user")
            | $i
          ] | first // -1
        ) as $stop
      | $a[($stop + 1):]
      | map(select(.type == "assistant") | (.message.content // []) | map(select(.type == "text") | .text) | join("\n"))
      | map(select(. != ""))
      | join("\n\n")
    ' "$TRANSCRIPT" 2>/dev/null)
  fi
fi

if [ -z "$RESPONSE" ] || [ "$RESPONSE" = "null" ]; then
  exit 0
fi

DATE=$(TZ=Asia/Tokyo date +%F)
TIME=$(TZ=Asia/Tokyo date +%H:%M)
LOG="${CLAUDE_PROJECT_DIR}/${DEPT}/memos/${DATE}_会話ログ.md"

# ログがまだ存在しない場合（UserPromptSubmit より先に Stop が発火する事は通常無いが防御）
if [ ! -f "$LOG" ]; then
  exit 0
fi

# 直近のターン番号を取得（社長と同じ #NN を共有）
LAST_TURN=$(grep -oE '^### \[#[0-9]+' "$LOG" 2>/dev/null | grep -oE '[0-9]+' | sort -n | tail -1)

if [ -z "$LAST_TURN" ]; then
  exit 0
fi

# 追記（秘書応答、生 text）
{
  echo ""
  echo "### [#${LAST_TURN} ${TIME} JST] 秘書"
  echo ""
  echo "$RESPONSE"
  echo ""
} >> "$LOG"

exit 0
