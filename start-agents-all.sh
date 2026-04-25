#!/usr/bin/env bash
#
# start-agents-all.sh - Your Company 全部署を tmux で一括起動
#
# 役割:
#   tmux セッション '$SESSION' を新規作成し、9ウィンドウ構成で
#   全部署（PM/開発/マーケ/経理/リサーチ/法務/社長室）+ watcher + extractor を起動する。
#
# ※ 秘書（secretariat）は AntiGravity のターミナルで独立起動する運用のため、
#   この tmux セッションには含まない。
#
# 使い方:
#   $ ./start-agents-all.sh
#   $ tmux attach -t $SESSION
#
# 軽量版: 4 ウィンドウだけで十分な場合は `./start-agents.sh` を使う（pm/dev/watcher/extractor）
#
# ウィンドウ構成:
#   0: pm          (プロジェクトマネジメント)
#   1: dev         (開発)
#   2: watcher     (ファイル監視)
#   3: extractor   (Stop hook 自動起動先, /extract-actions 受信)
#   4: research    (リサーチ部)
#   5: marketing   (マーケティング部)
#   6: accounting  (経理部)
#   7: legal       (法務部)
#   8: ceo-office  (社長室)
#   9: corporate-planning (経営企画部、2026-04-25 追加)
#

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${TMUX_SESSION:-your-company}"

# --- 既存セッション確認 ---
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "⚠ tmux session '$SESSION' は既に起動中です"
  echo ""
  echo "操作:"
  echo "  attach: tmux attach -t $SESSION"
  echo "  stop:   tmux kill-session -t $SESSION"
  echo ""
  echo "既存セッションに部署 window を追加する場合:"
  echo "  tmux new-window -t $SESSION -n <部署名> -c <ディレクトリ>"
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

echo "▶ Starting Your Company ALL departments in tmux session '$SESSION'..."

# --- Window 0: pm ---
tmux new-session -d -s "$SESSION" -n pm -c "$ROOT/product-management"
tmux send-keys -t "$SESSION:pm" "claude --dangerously-skip-permissions" Enter

# --- Window 1: dev ---
tmux new-window -t "$SESSION" -n dev -c "$ROOT/development"
tmux send-keys -t "$SESSION:dev" "claude --dangerously-skip-permissions" Enter

# --- Window 2: watcher ---
tmux new-window -t "$SESSION" -n watcher -c "$ROOT"
tmux send-keys -t "$SESSION:watcher" "./watcher.sh" Enter

# --- Window 3: extractor (Stop hook 自動起動先) ---
tmux new-window -t "$SESSION" -n extractor -c "$ROOT"
tmux send-keys -t "$SESSION:extractor" "claude --dangerously-skip-permissions" Enter

# --- Window 4: research ---
tmux new-window -t "$SESSION" -n research -c "$ROOT/research"
tmux send-keys -t "$SESSION:research" "claude --dangerously-skip-permissions" Enter

# --- Window 5: marketing ---
tmux new-window -t "$SESSION" -n marketing -c "$ROOT/marketing"
tmux send-keys -t "$SESSION:marketing" "claude --dangerously-skip-permissions" Enter

# --- Window 6: accounting ---
tmux new-window -t "$SESSION" -n accounting -c "$ROOT/accounting"
tmux send-keys -t "$SESSION:accounting" "claude --dangerously-skip-permissions" Enter

# --- Window 7: legal ---
tmux new-window -t "$SESSION" -n legal -c "$ROOT/legal"
tmux send-keys -t "$SESSION:legal" "claude --dangerously-skip-permissions" Enter

# --- Window 8: ceo-office ---
tmux new-window -t "$SESSION" -n ceo-office -c "$ROOT/ceo-office"
tmux send-keys -t "$SESSION:ceo-office" "claude --dangerously-skip-permissions" Enter

# --- Window 9: corporate-planning (2026-04-25 追加) ---
tmux new-window -t "$SESSION" -n corporate-planning -c "$ROOT/corporate-planning"
tmux send-keys -t "$SESSION:corporate-planning" "claude --dangerously-skip-permissions" Enter

# --- pm にフォーカス ---
tmux select-window -t "$SESSION:pm"

echo "✅ 全部署 起動完了"
echo ""
echo "操作:"
echo "  attach:        tmux attach -t $SESSION"
echo "  ウィンドウ切替: Ctrl-b + 0〜8  または  Ctrl-b + n/p"
echo "  デタッチ:       Ctrl-b + d"
echo "  停止:           tmux kill-session -t $SESSION"
echo ""
echo "ウィンドウ一覧:"
echo "  0: pm                 (プロジェクトマネジメント)"
echo "  1: dev                (開発)"
echo "  2: watcher            (ファイル監視)"
echo "  3: extractor          (Stop hook 自動起動先, /extract-actions 受信)"
echo "  4: research           (リサーチ部)"
echo "  5: marketing          (マーケティング部)"
echo "  6: accounting         (経理部)"
echo "  7: legal              (法務部)"
echo "  8: ceo-office         (社長室)"
echo "  9: corporate-planning (経営企画部)"
echo ""
echo "⚠ 秘書は AntiGravity の別ターミナルで独立起動してください:"
echo "  cd $ROOT/secretariat && claude --dangerously-skip-permissions"
echo "  または .vscode/tasks.json の「🎧【秘書】独立起動」を実行"
