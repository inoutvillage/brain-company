#!/usr/bin/env bash
# Stop hook: 秘書室セッション終了時に extractor window 経由で /extract-actions を自動送出
#
# 役割:
#   secretariat/ 配下で claude セッションが終了した時、tmux の extractor window へ
#   /extract-actions を自動送信し、会話ログから ToDo/意思決定/思考メモを抽出する。
#
# 入力: stdin に Claude Code が JSON イベントデータを流す
#   { "session_id": "...", "cwd": "...", "hook_event_name": "Stop", ... }
# 出力: 常に exit 0（セッション終了をブロックしない、extractor 失敗は silent）
# ログ: secretariat/logs/extract-stop.log に実行履歴と警告を集約
#
# 発火条件:
#   1. cwd が ${CLAUDE_PROJECT_DIR}/secretariat または その配下
#   2. tmux セッション `${TMUX_SESSION:-<TMUX_SESSION>}` が存在し、window `extractor` が存在する
#   いずれも満たさない場合はフォールバック（ログ記録のみ、セッション終了は通常通り）
#
# カスタマイズ:
#   tmux セッション名は start-agents.sh / watcher.sh / .vscode/tasks.json と合わせる必要あり。
#   環境変数 TMUX_SESSION で上書き可、デフォルトは "brain-company"。
set -u

# プロジェクトルートをスクリプトの実体パスから再計算（CLAUDE_PROJECT_DIR 非依存、シンボリックリンク経由でも安定）
SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}")"
CLAUDE_PROJECT_DIR="$(dirname "$(dirname "$(dirname "$SCRIPT_REAL")")")"

LOG="${CLAUDE_PROJECT_DIR}/secretariat/logs/extract-stop.log"
mkdir -p "$(dirname "$LOG")"

INPUT=$(cat)
TS=$(TZ=Asia/Tokyo date --iso-8601=seconds)
CWD=$(echo "$INPUT" | jq -r '.cwd // ""')

# tmux セッション名（start-agents.sh と合わせる）
SESSION="${TMUX_SESSION:-brain-company}"
WINDOW="extractor"

# 秘書室セッション判定
# CLAUDE_PROJECT_DIR/secretariat 配下で起動した時のみ発火
# 偽陽性除外: `secretariat-foo` のようなパスは case パターンで除外される
case "$CWD" in
  "${CLAUDE_PROJECT_DIR}/secretariat"|"${CLAUDE_PROJECT_DIR}/secretariat/"*) ;;
  *)
    # 非秘書セッションは no-op
    exit 0
    ;;
esac

# tmux セッション存在 + extractor window 存在確認
if tmux has-session -t "$SESSION" 2>/dev/null && \
   tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -Fxq "$WINDOW"; then
  # send-keys 3 ステップ（watcher.sh の send_to_tmux と同パターン）
  # 1. テキストをリテラルで送信（改行解釈されない）
  # 2. Claude Code UI が入力を取り込むのを少し待つ
  # 3. 単独で Enter キーを送信（これが「送信」トリガー）
  {
    echo "$TS Stop hook fired, cwd=$CWD"
    echo "$TS   → sending /extract-actions to ${SESSION}:${WINDOW}"
  } >> "$LOG" 2>&1
  tmux send-keys -t "${SESSION}:${WINDOW}" -l "/extract-actions"
  sleep 0.3
  tmux send-keys -t "${SESSION}:${WINDOW}" Enter
  echo "$TS   → send-keys completed (3 steps: literal / sleep 0.3 / Enter)" >> "$LOG"
else
  # extractor 不在 → フォールバック（ログのみ記録）
  {
    echo "$TS ⚠ extractor window UNAVAILABLE, Stop hook fallback"
    echo "$TS   cwd=$CWD"
    echo "$TS   (次回秘書セッション起動時に /extract-actions の手動実行を推奨)"
    echo "$TS   復旧: start-agents.sh 再起動 or tasks.json から 'extractor: Claude Code 起動（個別）' を発火"
  } >> "$LOG" 2>&1
fi

exit 0
