#!/usr/bin/env bash
#
# watcher.sh - Brain Company ファイル監視デーモン（ポーリング版）
#
# 役割:
#   各部署の依頼/チケット/報告ディレクトリをポーリングし、
#   新規/変更ファイルを検知して以下の動作を行う:
#
#   - requests/ (PM宛)  → tmux:pm にプロンプト自動送信
#   - tickets/  (開発宛) → tmux:dev にプロンプト自動送信
#   - reports/  (全部) → secretariat/inbox/ にメモ書き出し
#                        + 関連部署（開発→PM）には tmux 送信併用
#
# ⚠️ 当初 inotify-tools で実装したが、WSL2 の /mnt/d/（Windows FS）では
#    inotify が動作しないため、ポーリング方式に変更。
#    5秒おきに find -newer でスキャン、mtime 比較で変更検知。
#
# 🛡️ デバウンス（2026-04-24 追加）:
#    同一ファイルが短時間で複数回保存される場合（エージェントが同じ方針メモを
#    反復書き換える等）、窓内の2回目以降は処理をスキップし inbox 多重通知を防ぐ。
#    デフォルト 60 秒、環境変数 DEBOUNCE_WINDOW で上書き可。
#
# 使い方:
#   $ ./watcher.sh                                 # フォアグラウンド
#   $ nohup ./watcher.sh > watcher.log 2>&1 &      # バックグラウンド
#
# 依存: find, tmux, bash 4+ （全て標準環境で利用可能）
#

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- tmux セッション名（start-agents.sh と合わせる） ---
SESSION="${TMUX_SESSION:-brain-company}"

# --- 秘書 inbox ディレクトリ ---
INBOX="$ROOT/secretariat/inbox"

# --- 状態ファイル（最終スキャン時刻のマーカー） ---
STATE_FILE="$ROOT/.watcher-last-scan"

# --- ポーリング間隔（秒） ---
POLL_INTERVAL=5

# --- デバウンス設定（2026-04-24 追加） ---
# 同一ファイルが短時間内に複数回保存される場合（エージェントが方針メモを
# 反復更新する等）、秘書 inbox に多重通知が入るのを防ぐ。
# 窓内の2回目以降はスキップするが、窓を超えた変更は正常処理される。
# 環境変数 DEBOUNCE_WINDOW で上書き可（例: DEBOUNCE_WINDOW=30 ./watcher.sh）
DEBOUNCE_WINDOW=${DEBOUNCE_WINDOW:-60}  # 秒
declare -A LAST_PROCESSED_TS  # ファイルパス → 最終処理epoch時刻

# --- 監視対象 ---
WATCH_DIRS=(
  "$ROOT/product-management/requests"
  "$ROOT/product-management/reports"
  "$ROOT/development/tickets"
  "$ROOT/development/reports"
  # --- 2026-04-23 追加: 4 部署 ---
  "$ROOT/research/requests"
  "$ROOT/research/reports"
  "$ROOT/marketing/requests"
  "$ROOT/marketing/reports"
  "$ROOT/accounting/requests"
  "$ROOT/accounting/reports"
  "$ROOT/legal/requests"
  "$ROOT/legal/reports"
  # --- 2026-04-25 追加: 経営企画部 ---
  "$ROOT/corporate-planning/requests"
  "$ROOT/corporate-planning/reports"
)

# --- ディレクトリ初期化 ---
for d in "${WATCH_DIRS[@]}" "$INBOX"; do
  if [ ! -d "$d" ]; then
    mkdir -p "$d"
    echo "[init] created: ${d#$ROOT/}"
  fi
done

# --- 色定義 ---
C_INFO='\033[0;36m'
C_EVENT='\033[1;33m'
C_FILE='\033[0;32m'
C_WARN='\033[0;31m'
C_SENT='\033[0;35m'
C_INBOX='\033[0;34m'
C_OFF='\033[0m'

# --- 起動メッセージ ---
echo -e "${C_INFO}[watcher]${C_OFF} start polling ($(date '+%Y-%m-%d %H:%M:%S'))"
echo -e "${C_INFO}[watcher]${C_OFF} tmux session target: ${SESSION}"
echo -e "${C_INFO}[watcher]${C_OFF} inbox (秘書宛): ${INBOX#$ROOT/}"
echo -e "${C_INFO}[watcher]${C_OFF} poll interval: ${POLL_INTERVAL} seconds"
echo -e "${C_INFO}[watcher]${C_OFF} mode: polling (inotify は WSL /mnt/d/ で動作しないため)"
for d in "${WATCH_DIRS[@]}"; do
  echo "  - ${d#$ROOT/}"
done
echo "---"

# --- 起動時刻を基準にする（初回スキャンで既存ファイルを誤検知しないため） ---
touch "$STATE_FILE"

# --- tmux へプロンプト送信（安全ラッパ） ---
#
# Claude Code の TUI は、1回の send-keys で「文字列 + Enter」を送ると
# Enter が「改行」として解釈されてしまう（bracketed paste の挙動）。
# そのため、本文を -l (literal) で送信 → 少し待つ → 単独 Enter で送信、
# の3段階に分けてメッセージ送信する。
send_to_tmux() {
  local window="$1"
  local prompt="$2"
  if [ -z "$window" ] || [ -z "$prompt" ]; then
    return 0
  fi
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    # window 単位で存在確認してから送信（2026-04-23 追加: オンデマンド起動部署の誤「sent」ログ防止）
    if tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -Fxq "$window"; then
      # 1. テキストをリテラルで送信（改行解釈されない）
      tmux send-keys -t "${SESSION}:${window}" -l "$prompt"
      # 2. Claude Code UI が入力を取り込むのを少し待つ
      sleep 0.3
      # 3. 単独で Enter キーを送信（これが「送信」トリガー）
      tmux send-keys -t "${SESSION}:${window}" Enter
      echo -e "   ${C_SENT}→ tmux sent: ${SESSION}:${window}${C_OFF}"
    else
      echo -e "   ${C_WARN}⚠ tmux window '${window}' not found in session '${SESSION}', prompt skipped${C_OFF}"
    fi
  else
    echo -e "   ${C_WARN}⚠ tmux session '${SESSION}' not running, prompt skipped${C_OFF}"
  fi
}

# --- 秘書 inbox へ書き出し ---
write_to_inbox() {
  local src_dept="$1"
  local src_path="$2"
  local src_file="$3"
  local ts_now
  ts_now="$(date '+%Y-%m-%d_%H-%M-%S')"
  local inbox_file="$INBOX/${ts_now}_${src_dept}_${src_file%.md}.md"
  cat > "$inbox_file" <<EOF
---
received: $(date '+%Y-%m-%d %H:%M:%S JST')
source_dept: ${src_dept}
source_path: ${src_path}
status: unread
---

# Inbox: ${src_dept}からの報告

## 概要
- **検知日時**: $(date '+%Y-%m-%d %H:%M:%S JST')
- **元ファイル**: \`${src_path#$ROOT/}\`
- **部署**: ${src_dept}

## 秘書の推奨アクション

1. 元ファイル（上記パス）の内容を読み込む
2. 社長への報告準備（要旨・アクション候補）
3. 社長に報告 or 必要なら関連部署にリレー
4. 処理完了後、本inboxファイルのステータスを 'processed' に書き換える or \`secretariat/inbox/archive/\` へ移動

## 元ファイルへの直リンク

\`${src_path}\`
EOF
  echo -e "   ${C_INBOX}→ inbox written: ${inbox_file#$ROOT/}${C_OFF}"
}

# --- 1ファイルを処理 ---
process_file() {
  local d="$1"
  local f="$2"
  local file
  file="$(basename "$f")"

  # 一時ファイル/隠しファイル/エディタバックアップの除外（2026-04-24 拡充）
  case "$file" in
    .*|*~|*.swp|*.swx|*.tmp|*.bak|*.orig|\#*\#|4913) return 0 ;;
  esac

  # --- デバウンス: 同一ファイルの短時間連続更新を抑止（2026-04-24 追加） ---
  local now_epoch last_epoch elapsed
  now_epoch=$(date +%s)
  last_epoch="${LAST_PROCESSED_TS[$f]:-0}"
  elapsed=$((now_epoch - last_epoch))
  if [ "$elapsed" -lt "$DEBOUNCE_WINDOW" ]; then
    echo -e "${C_INFO}[debounce]${C_OFF} skip (reprocessed ${elapsed}s ago, window ${DEBOUNCE_WINDOW}s): ${file}"
    return 0
  fi
  LAST_PROCESSED_TS[$f]="$now_epoch"

  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"

  local label=""
  local target_window=""
  local prompt=""
  local inbox_from=""

  case "$d" in
    */product-management/requests*)
      label="📬 PM部 受信: 依頼"
      target_window="pm"
      prompt="product-management/requests/${file} に新しい依頼書が届きました。内容を確認して処理してください。"
      ;;
    */product-management/reports*)
      label="📮 PM部 送信: 報告（→ 開発部 & 秘書inbox）"
      # PM が reports/ に配置する内容は、開発部への返信（レビュー結果/GO/NOGO 等）の可能性が高い。
      # 開発部に tmux 通知することで、PMレビュー後の実装継続を促す。
      # 社長向けの純粋な進捗報告だった場合、開発部は無視すればよい（文脈判断）。
      target_window="dev"
      prompt="product-management/reports/${file} にPM部からの応答/レビュー結果が届きました。内容を確認して、指示に応じて作業を続行してください。"
      inbox_from="PM部"
      ;;
    */development/tickets*)
      label="🎫 開発部 受信: チケット"
      target_window="dev"
      prompt="development/tickets/${file} に新しい実装チケットが届きました。内容を確認して実装を進めてください。"
      ;;
    */development/reports*)
      label="✅ 開発部 送信: 報告（→ PM & 秘書inbox）"
      target_window="pm"
      prompt="development/reports/${file} に開発部からの完了報告が届きました。内容を確認して、必要なら秘書室へリレーしてください。"
      inbox_from="開発部"
      ;;
    # --- 2026-04-23 追加: 4 部署（research / marketing / accounting / legal） ---
    # 設計: requests/ は該当部署 tmux 窓へ送出（窓が無ければ send_to_tmux の警告だけで継続）、
    #       reports/ は tmux 直送せず秘書 inbox のみ（4 部署はオンデマンド起動のため）
    */research/requests*)
      label="📬 リサーチ部 受信: 依頼"
      target_window="research"
      prompt="research/requests/${file} に新しい依頼書が届きました。内容を確認して処理してください。"
      ;;
    */research/reports*)
      label="📮 リサーチ部 送信: 報告（→ 秘書inbox）"
      target_window=""
      prompt=""
      inbox_from="リサーチ部"
      ;;
    */marketing/requests*)
      label="📬 マーケティング部 受信: 依頼"
      target_window="marketing"
      prompt="marketing/requests/${file} に新しい依頼書が届きました。内容を確認して処理してください。"
      ;;
    */marketing/reports*)
      label="📮 マーケティング部 送信: 報告（→ 秘書inbox）"
      target_window=""
      prompt=""
      inbox_from="マーケティング部"
      ;;
    */accounting/requests*)
      label="📬 経理部 受信: 依頼"
      target_window="accounting"
      prompt="accounting/requests/${file} に新しい依頼書が届きました。内容を確認して処理してください。"
      ;;
    */accounting/reports*)
      label="📮 経理部 送信: 報告（→ 秘書inbox）"
      target_window=""
      prompt=""
      inbox_from="経理部"
      ;;
    */legal/requests*)
      label="📬 法務部 受信: 依頼"
      target_window="legal"
      prompt="legal/requests/${file} に新しい依頼書が届きました。内容を確認して処理してください。"
      ;;
    */legal/reports*)
      label="📮 法務部 送信: 報告（→ 秘書inbox）"
      target_window=""
      prompt=""
      inbox_from="法務部"
      ;;
    # --- 2026-04-25 追加: 経営企画部 ---
    */corporate-planning/requests*)
      label="📬 経営企画部 受信: 依頼"
      target_window="corporate-planning"
      prompt="corporate-planning/requests/${file} に新しい依頼書が届きました。内容を確認して処理してください。"
      ;;
    */corporate-planning/reports*)
      label="📮 経営企画部 送信: 報告（→ 秘書inbox）"
      target_window=""
      prompt=""
      inbox_from="経営企画部"
      ;;
    *)
      label="[unknown]"
      ;;
  esac

  printf "\a"
  echo -e "${C_EVENT}[${ts}]${C_OFF} ${label} ${C_FILE}${file}${C_OFF}"
  echo "   path: ${f}"

  send_to_tmux "$target_window" "$prompt"

  if [ -n "$inbox_from" ]; then
    write_to_inbox "$inbox_from" "$f" "$file"
  fi
}

# --- ポーリングループ（堅牢版 2026-04-24 修正） ---
# 旧: mv .next → 本体 の方式は WSL /mnt/d/ (DrvFs) で mv 失敗を連発
# 新: スキャン開始時刻を epoch で記録し、touch -d で state ファイルの mtime を直接更新
while true; do
  # スキャン開始の epoch 時刻を記録（次回の基準になる）
  SCAN_START=$(date +%s)

  for d in "${WATCH_DIRS[@]}"; do
    # 前回スキャン以降にmtimeが更新されたファイルを拾う
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      process_file "$d" "$f"
    done < <(find "$d" -type f -newer "$STATE_FILE" 2>/dev/null)
  done

  # state ファイルの mtime を「スキャン開始時刻」に直接設定
  # スキャン中に更新されたファイルは次回のスキャンで拾える（race 対策）
  # touch -d が失敗した場合は単純な touch で今現在の時刻に更新
  touch -d "@$SCAN_START" "$STATE_FILE" 2>/dev/null || touch "$STATE_FILE"

  sleep "$POLL_INTERVAL"
done
