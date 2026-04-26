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
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // ""')

# 部署判定:
#   セッション開始時の cwd（transcript_path のディレクトリ名にエンコードされている）から判定する。
#   メッセージ送信時の cwd は使わない（cd でユーザが他部署フォルダに出張すると誤ルーティングする）。
#
#   transcript_path 例:
#     /home/admin/.claude/projects/-mnt-d-PC-iTKMAIN-dev-BrainCompany-secretariat/<uuid>.jsonl
#   ENCODED_DIR = -mnt-d-PC-iTKMAIN-dev-BrainCompany-secretariat
#
#   PROJECT_BASENAME（例: BrainCompany）の後ろの SUFFIX を取り出し、
#   実在する <dept>/ ディレクトリ名と最長一致で照合（corporate-planning 等のハイフン入り名対応）。
PROJECT_BASENAME="$(basename "$CLAUDE_PROJECT_DIR")"
DEPT=""

if [ -n "$TRANSCRIPT" ] && [ "$TRANSCRIPT" != "null" ]; then
  ENCODED_DIR="$(basename "$(dirname "$TRANSCRIPT")")"
  SUFFIX="${ENCODED_DIR##*-${PROJECT_BASENAME}}"
  SUFFIX="${SUFFIX#-}"
  if [ -z "$SUFFIX" ]; then
    DEPT="secretariat"
  else
    for d in "$CLAUDE_PROJECT_DIR"/*/; do
      [ -d "$d" ] || continue
      name="$(basename "$d")"
      case "$name" in .*) continue ;; esac
      case "$SUFFIX" in
        "$name"|"${name}-"*)
          if [ "${#name}" -gt "${#DEPT}" ]; then
            DEPT="$name"
          fi
          ;;
      esac
    done
  fi
fi

# フォールバック: cwd ベース判定
if [ -z "$DEPT" ]; then
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
fi

case "$DEPT" in
  .*|"") exit 0 ;;
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
