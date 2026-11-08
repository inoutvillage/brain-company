#!/usr/bin/env bash
# 🚨 このスクリプトは `SessionEnd` イベントに登録されている（`Stop` ではない）。
#    登録箇所: .claude/settings.json の hooks.SessionEnd
#    → 発火は「秘書室セッションの終了時」であり、**会話ターンの終了ごとではない**。
#      （`Stop` = ターン終了に登録されているのは会話ログ用の log-assistant-response.sh）
#
# SessionEnd hook: 秘書室セッション終了時に extractor window 経由で /extract-actions を自動送出
#
# 秘書は専用の tmux セッションに常駐し、セッションが終わることは少ない。日次の定期送出は
# .claude/scripts/extract-actions-daily.sh（cron）が担い、本 hook は秘書を止めた時・落ちた時の保険として並存する。
# 両者は同じセンチネル/ログ/inbox 書式と、送る前の状態の確かめ（.claude/scripts/extractor_state.py）を共有する
# ── 片方を直す時はもう片方も確認すること。
#
# 入力: stdin に Claude Code が JSON イベントデータを流す
#   { "session_id": "...", "cwd": "...", "hook_event_name": "SessionEnd", ... }
# 出力: 常に exit 0（セッション終了をブロックしない）
# ログ: secretariat/logs/extract-stop.log に実行履歴と警告を集約
#
# 発火条件:
#   1. cwd が <ROOT>/secretariat または その配下
#   2. tmux セッション `<TMUX_SESSION>-secretariat`（既定 brain-company-secretariat）が存在し、window `extractor` が存在する
#   3. extractor が確認の画面（許可の問い等）で止まっていない
#      （Enter を送ると既定の「Yes」で確認を通してしまう。判定は extractor_state.py。読めない時は送る＝日次と同じ）
# 2・3 を満たさない場合は送らず、ログに残し、secretariat/inbox/ に知らせを書く（同一障害では 1 件だけ）
#
# 前提: jq（入力の JSON を読む）・GNU date。確認の画面の見分けは Linux / WSL2 だけ（/proc。無ければ見分けずに送る）
#
# カスタマイズ:
#   tmux セッション名は start-secretariat.sh / extract-actions-daily.sh と合わせる。
#   環境変数 TMUX_SESSION で上書き可、デフォルトは "brain-company"（秘書はその後ろに -secretariat）。
set -u

# プロジェクトルートをスクリプトの実体パスから再計算（CLAUDE_PROJECT_DIR 非依存、シンボリックリンク経由でも安定）
SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}")"
CLAUDE_PROJECT_DIR="$(dirname "$(dirname "$(dirname "$SCRIPT_REAL")")")"

LOG="${CLAUDE_PROJECT_DIR}/secretariat/logs/extract-stop.log"
mkdir -p "$(dirname "$LOG")"

INPUT=$(cat)
TS=$(TZ=Asia/Tokyo date --iso-8601=seconds)
CWD=$(echo "$INPUT" | jq -r '.cwd // ""')

# tmux セッション名（start-secretariat.sh と合わせる）。-t は '=名前'（完全一致）で指す
SESSION="${TMUX_SESSION:-brain-company}-secretariat"
WINDOW="extractor"
TARGET="=${SESSION}:${WINDOW}"
INBOX="${CLAUDE_PROJECT_DIR}/secretariat/inbox"
# 同一障害での通知重複を抑えるためのセンチネル（O_EXCL による原子的な作成で
# 同一秒の多重発火も取りこぼさない）。送出成功時に削除して次の障害で再武装する。
SENTINEL="${CLAUDE_PROJECT_DIR}/secretariat/logs/.extractor-unavailable"

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

# --- 送れなかった時の知らせ（同一障害では1件のみ） ---
# $1 = unavailable（送出先が無い） | waiting（確認の画面で止まっている）  $2 = 理由
notify() {
  local kind="$1" reason="$2" what recover
  if [ "$kind" = "waiting" ]; then
    what="extractor が**確認の画面で止まっていた**ため送出しなかった（${reason}）。確認の画面に Enter を送ると、既定の「Yes」で確認を通してしまう"
    recover="extractor の画面（\`tmux attach -t =${SESSION}\` → \`${WINDOW}\` の窓）で確認の中身を見て、人が選ぶ（通してよい時だけ通す）"
  else
    what="\`${SESSION}:${WINDOW}\` へ送出しようとしたが、**送出先が見つからなかった**"
    recover="\`./start-secretariat.sh --no-attach\` を実行する（稼働中の秘書セッションを落とさずに \`extractor\` window だけを補完します）"
  fi
  {
    echo "$TS [SessionEnd] ⚠ extractor ${kind}: ${reason}"
    echo "$TS   cwd=$CWD"
    echo "$TS   (次回秘書セッション起動時に /extract-actions の手動実行を推奨)"
  } >> "$LOG" 2>&1

  # noclobber + O_EXCL によりセンチネル作成は原子的。同一秒に複数プロセスが
  # 到達しても、作成に成功した1つだけが inbox を書く。
  if ( set -o noclobber; echo "$TS" > "$SENTINEL" ) 2>/dev/null; then
    mkdir -p "$INBOX"
    local ts_file ts_human inbox_file
    ts_file=$(TZ=Asia/Tokyo date '+%Y-%m-%d_%H-%M-%S')
    ts_human=$(TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M:%S JST')
    inbox_file="${INBOX}/${ts_file}_システム_extractor送出失敗.md"
    cat > "$inbox_file" <<EOF
---
received: ${ts_human}
source_dept: システム
source_path: ${LOG}
status: unread
---

# Inbox: /extract-actions の自動送出に失敗しました

## 概要
- **検知日時**: ${ts_human}
- **事象**: SessionEnd hook が ${what}
- **影響**: この会話の \`/extract-actions\`（ToDo / 意思決定 / 思考メモの自動抽出）が**実行されていない**
- **セッション終了はブロックしていません**（hook は常に exit 0）

## 復旧手順

1. ${recover}
2. 復旧後、取りこぼした分は \`/extract-actions\` を手動実行して回収する

## 秘書の推奨アクション

1. 上記の復旧手順を実行する
2. 未抽出のターンがあれば \`/extract-actions\` を手動実行
3. 処理完了後、本inboxファイルのステータスを 'processed' に書き換える or \`secretariat/inbox/archive/\` へ移動

## 補足

- 本通知は**同一障害につき1件のみ**生成されます（送出が再び成功した時点で再武装）
- 詳細ログ: \`${LOG}\`
EOF
    echo "$TS   → inbox written: ${inbox_file#${CLAUDE_PROJECT_DIR}/}" >> "$LOG"
  else
    echo "$TS   → inbox 通知は抑制（同一障害で既報）" >> "$LOG"
  fi
}

# --- tmux セッション存在 + extractor window 存在確認 ---
if ! { tmux has-session -t "=$SESSION" 2>/dev/null && \
       tmux list-windows -t "=$SESSION" -F '#{window_name}' 2>/dev/null | grep -Fxq "$WINDOW"; }; then
  notify unavailable "tmux セッション '${SESSION}' または window '${WINDOW}' が存在しません"
  exit 0
fi

# --- 確認の画面で止まっていないか（判定は日次の送出と共有） ---
SESSIONS_DIR="${CLAUDE_CONFIG_DIR:-${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}/.claude}/sessions"
EXTRACTOR_STATE="unknown"; EXTRACTOR_WHY="python3 が無い"
if PY_BIN="$(command -v python3 2>/dev/null)"; then
  if PANE_ID=$(tmux display-message -p -t "$TARGET" '#{pane_id}' 2>/dev/null); then
    read -r EXTRACTOR_STATE EXTRACTOR_WHY <<< "$("$PY_BIN" "${CLAUDE_PROJECT_DIR}/.claude/scripts/extractor_state.py" "$SESSIONS_DIR" "$SESSION" "$PANE_ID" 2>/dev/null || echo "unknown 記録を読めない")"
  else
    EXTRACTOR_WHY="ペインの番号を読めない"
  fi
fi
if [ "$EXTRACTOR_STATE" = "waiting" ]; then
  notify waiting "waiting: ${EXTRACTOR_WHY}"
  exit 0
fi

# --- 送出（send-keys 3 ステップ。watcher.sh の send_to_tmux と同パターン） ---
# 1. テキストをリテラルで送信（改行解釈されない）
# 2. Claude Code UI が入力を取り込むのを少し待つ
# 3. 単独で Enter キーを送信（これが「送信」トリガー）
{
  echo "$TS [SessionEnd] hook fired, cwd=$CWD"
  echo "$TS   → extractor state: ${EXTRACTOR_STATE} ${EXTRACTOR_WHY}"
  echo "$TS   → sending /extract-actions to ${SESSION}:${WINDOW}"
} >> "$LOG" 2>&1
tmux send-keys -t "$TARGET" -l "/extract-actions"
sleep 0.3
tmux send-keys -t "$TARGET" Enter
echo "$TS   → send-keys completed (3 steps: literal / sleep 0.3 / Enter)" >> "$LOG"
# 送出できた＝障害は解消。センチネルを解除して次の障害で再通知できるようにする
if [ -e "$SENTINEL" ]; then
  rm -f "$SENTINEL"
  echo "$TS   → recovered: 通知センチネルを解除しました" >> "$LOG"
fi

exit 0
