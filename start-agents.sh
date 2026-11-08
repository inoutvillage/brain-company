#!/usr/bin/env bash
#
# start-agents.sh - Brain Company のメインエージェントを tmux で一括起動（部署側のみ・軽量版）
#
# 役割:
#   tmux セッション '$SESSION'（既定 'brain-company'）を新規作成し、3 ウィンドウ構成で
#   PM/開発 の Claude Code セッションと watcher.sh を起動する。
#
# ※ 秘書（secretariat）は専用の tmux セッション '<SESSION>-secretariat' で運用するため、
#   この tmux セッションには含まない。起動は ./start-secretariat.sh（extractor もそちらにいる）。
#
# 使い方:
#   $ ./start-agents.sh
#   $ tmux attach -t =$SESSION
#
# ウィンドウ構成:
#   0: pm          (プロジェクトマネジメント)
#   1: dev         (開発)
#   2: watcher     (ファイル監視)
#
# 各部署の claude は、その dir の最新の対話の会話から再開する（.claude/scripts/claude-role.sh。会話が無い・
#   ほかで使用中・読めない時は新しい会話）。白紙で起こすなら CLAUDE_FRESH=1 ./start-agents.sh、起動の後なら /clear。
# 🚨 役割の dir（秘書室・各部署）と会社のフォルダーの一番上（extractor）で、一発の `claude`・`claude -p` を走らせない
#   （対話の一発は次の再開で拾われる。`-p` は選び方で飛ばすが記録は増える）。どうしても要る時は --no-session-persistence を付けるか、別の dir で。
#
# 🚨 tmux の -t は '=名前'（完全一致）で指す: tmux は同名のセッションが無いと前方一致で探すため、
#   この部署側が止まっている時に '-t brain-company' と書くと秘書の 'brain-company-secretariat' に当たる。
#

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${TMUX_SESSION:-brain-company}"
# 窓のシェルが読むコマンドなので、場所は引用して渡す（会社のフォルダーの場所に空白があっても動くように）
CLAUDE_CMD="$(printf '%q' "$ROOT/.claude/scripts/claude-role.sh") --dangerously-skip-permissions"
# tmux の窓のシェルにはこのスクリプトの環境が届かないので、打ち込むコマンドに付ける
[ "${CLAUDE_FRESH:-}" = "1" ] && CLAUDE_CMD="CLAUDE_FRESH=1 $CLAUDE_CMD"

# --- 既存セッション確認 ---
if tmux has-session -t "=$SESSION" 2>/dev/null; then
  echo "⚠ tmux session '$SESSION' は既に起動中です"
  echo ""
  echo "操作:"
  echo "  attach: tmux attach -t =$SESSION"
  echo "  stop:   tmux kill-session -t =$SESSION"
  exit 0
fi

# --- 依存チェック ---
missing=0
for cmd in tmux claude; do
  if ! command -v "$cmd" > /dev/null 2>&1; then
    echo "ERROR: '$cmd' not found."
    case "$cmd" in
      tmux)
        echo "  Install (AlmaLinux/RHEL): sudo dnf install tmux"
        echo "  Install (Ubuntu/Debian):  sudo apt install tmux"
        echo "  Install (macOS):          brew install tmux"
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

echo "▶ Starting Brain Company agents in tmux session '$SESSION' (秘書は専用セッション ${SESSION}-secretariat)..."

# --- Window 0: pm ---
tmux new-session -d -s "$SESSION" -n pm -c "$ROOT/product-management"
tmux send-keys -t "=$SESSION:pm" "$CLAUDE_CMD" Enter

# --- Window 1: dev ---
tmux new-window -t "=$SESSION:" -n dev -c "$ROOT/development"
tmux send-keys -t "=$SESSION:dev" "$CLAUDE_CMD" Enter

# --- Window 2: watcher ---
tmux new-window -t "=$SESSION:" -n watcher -c "$ROOT"
tmux send-keys -t "=$SESSION:watcher" "./watcher.sh" Enter

# --- pm にフォーカス ---
tmux select-window -t "=$SESSION:pm"

echo "✅ 起動完了"
echo ""
echo "操作:"
echo "  attach:        tmux attach -t =$SESSION"
echo "  ウィンドウ切替: Ctrl-b + 0/1/2  または  Ctrl-b + n/p"
echo "  デタッチ:       Ctrl-b + d"
echo "  停止:           tmux kill-session -t =$SESSION"
echo ""
echo "ウィンドウ一覧:"
echo "  0: pm           (プロジェクトマネジメント)"
echo "  1: dev          (開発)"
echo "  2: watcher      (ファイル監視)"
echo ""
echo "ℹ 秘書は専用の tmux セッション '${SESSION}-secretariat' で運用します（このセッションには含みません）:"
echo "  ./start-secretariat.sh"
echo "  または .vscode/tasks.json の「🎧【秘書】秘書だけ起動 & アタッチ」を実行"
