#!/usr/bin/env bash
#
# start-agents.sh - Brain Company のメインエージェントを tmux で一括起動（秘書独立版）
#
# 役割:
#   tmux セッション '$SESSION' を新規作成し、3ウィンドウ構成で
#   PM/開発 の Claude Code セッションと watcher.sh を起動する。
#
# ※ 秘書（secretariat）は AntiGravity のターミナルで独立起動する運用のため、
#   この tmux セッションには含まない。
#   秘書を起動する場合は:
#     cd .../Brain Company/secretariat && claude --dangerously-skip-permissions
#   または .vscode/tasks.json の「🎧【秘書】独立起動」タスクを実行。
#
# 使い方:
#   $ ./start-agents.sh
#   $ tmux attach -t $SESSION
#
# ウィンドウ構成:
#   0: pm          (プロジェクトマネジメント)
#   1: dev         (開発)
#   2: watcher     (ファイル監視)
#   3: extractor   (Stop hook 自動起動先, /extract-actions 受信)
#

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${TMUX_SESSION:-brain-company}"

# --- 既存セッション確認 ---
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "⚠ tmux session '$SESSION' は既に起動中です"
  echo ""
  echo "操作:"
  echo "  attach: tmux attach -t $SESSION"
  echo "  stop:   tmux kill-session -t $SESSION"
  exit 0
fi

# --- 依存チェック ---
missing=0
for cmd in tmux claude inotifywait; do
  if ! command -v "$cmd" > /dev/null 2>&1; then
    echo "ERROR: '$cmd' not found."
    case "$cmd" in
      tmux)
        echo "  Install (AlmaLinux/RHEL): sudo dnf install tmux"
        echo "  Install (Ubuntu/Debian):  sudo apt install tmux"
        ;;
      inotifywait)
        echo "  Install (AlmaLinux/RHEL): sudo dnf install epel-release && sudo dnf install inotify-tools"
        echo "  Install (Ubuntu/Debian):  sudo apt install inotify-tools"
        ;;
      claude)
        echo "  Install: Claude Code CLI (https://claude.com/claude-code)"
        ;;
    esac
    missing=1
  fi
done
if [ "$missing" -eq 1 ]; then
  exit 1
fi

# --- 秘書 inbox ディレクトリ確保 ---
mkdir -p "$ROOT/secretariat/inbox"

echo "▶ Starting Brain Company agents in tmux session '$SESSION' (秘書は独立運用)..."

# --- Window 0: pm ---
tmux new-session -d -s "$SESSION" -n pm -c "$ROOT/product-management"
tmux send-keys -t "$SESSION:pm" "claude --dangerously-skip-permissions" Enter

# --- Window 1: dev ---
tmux new-window -t "$SESSION" -n dev -c "$ROOT/development"
tmux send-keys -t "$SESSION:dev" "claude --dangerously-skip-permissions" Enter

# --- Window 2: watcher ---
tmux new-window -t "$SESSION" -n watcher -c "$ROOT"
tmux send-keys -t "$SESSION:watcher" "./watcher.sh" Enter

# --- Window 3: extractor (2026-04-24 I1 真の自動化: Stop hook からの自動起動先) ---
tmux new-window -t "$SESSION" -n extractor -c "$ROOT"
tmux send-keys -t "$SESSION:extractor" "claude --dangerously-skip-permissions" Enter

# --- pm にフォーカス ---
tmux select-window -t "$SESSION:pm"

echo "✅ 起動完了"
echo ""
echo "操作:"
echo "  attach:        tmux attach -t $SESSION"
echo "  ウィンドウ切替: Ctrl-b + 0/1/2/3  または  Ctrl-b + n/p"
echo "  デタッチ:       Ctrl-b + d"
echo "  停止:           tmux kill-session -t $SESSION"
echo ""
echo "ウィンドウ一覧:"
echo "  0: pm           (プロジェクトマネジメント)"
echo "  1: dev          (開発)"
echo "  2: watcher      (ファイル監視)"
echo "  3: extractor    (Stop hook 自動起動先, /extract-actions 受信)"
echo ""
echo "⚠ 秘書は AntiGravity の別ターミナルで独立起動してください:"
echo "  cd $ROOT/secretariat && claude --dangerously-skip-permissions"
echo "  または .vscode/tasks.json の「🎧【秘書】独立起動」を実行"
