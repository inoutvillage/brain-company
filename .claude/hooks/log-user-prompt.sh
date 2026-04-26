#!/usr/bin/env bash
# UserPromptSubmit hook: 社長の発言を会話ログにリアルタイム追記
#
# 入力: stdin に Claude Code が JSON イベントデータを流す
#   { "session_id": "...", "cwd": "...", "prompt": "...", ... }
# 出力: 常に exit 0（記録は副次機能、失敗しても本体処理を止めない）
# 動作: <dept>/ 配下のセッション時のみ <dept>/memos/YYYY-MM-DD_会話ログ.md に追記
#
# 設計:
#   - トークン消費ゼロ（シェルのみ、LLM 介在なし）
#   - 日付境界は JST 0:00（TZ=Asia/Tokyo）
#   - ターン番号は既存ログを grep して自動採番
set -u

# プロジェクトルートをスクリプトの実体パスから再計算（CLAUDE_PROJECT_DIR 非依存、シンボリックリンク経由でも安定）
SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}")"
CLAUDE_PROJECT_DIR="$(dirname "$(dirname "$(dirname "$SCRIPT_REAL")")")"

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // ""')

# 部署判定（CLAUDE_PROJECT_DIR/<dept>/ 配下なら <dept> を抽出、ルートは secretariat 扱い）
case "$CWD" in
  "${CLAUDE_PROJECT_DIR}"|"${CLAUDE_PROJECT_DIR}/")
    DEPT="secretariat"
    ;;
  "${CLAUDE_PROJECT_DIR}/"*)
    REL="${CWD#${CLAUDE_PROJECT_DIR}/}"
    DEPT="${REL%%/*}"
    # 隠しディレクトリ（.claude 等）は記録対象外
    case "$DEPT" in
      .*) exit 0 ;;
    esac
    ;;
  *) exit 0 ;;
esac

# プロンプト空 or null なら no-op
if [ -z "$PROMPT" ] || [ "$PROMPT" = "null" ]; then
  exit 0
fi

DATE=$(TZ=Asia/Tokyo date +%F)
TIME=$(TZ=Asia/Tokyo date +%H:%M)
LOG="${CLAUDE_PROJECT_DIR}/${DEPT}/memos/${DATE}_会話ログ.md"
mkdir -p "$(dirname "$LOG")"

# 新規ファイルなら最小ヘッダ作成
if [ ! -f "$LOG" ]; then
  cat > "$LOG" <<EOF
# 会話ログ: ${DATE}

## 概要
- セッション状態: 継続中
- 自動記録: hook 型（log-user-prompt.sh / log-assistant-response.sh）

## やり取り
EOF
fi

# 直近のターン番号を取得（#NN を grep）
LAST_TURN=$(grep -oE '^### \[#[0-9]+' "$LOG" 2>/dev/null | grep -oE '[0-9]+' | sort -n | tail -1)
NEXT_TURN=$((${LAST_TURN:-0} + 1))

# 追記（社長発言、引用形式）
{
  echo ""
  echo "### [#${NEXT_TURN} ${TIME} JST] 社長"
  echo ""
  echo "$PROMPT" | sed 's/^/> /'
  echo ""
} >> "$LOG"

exit 0
