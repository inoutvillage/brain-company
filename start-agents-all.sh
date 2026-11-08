#!/usr/bin/env bash
#
# start-agents-all.sh - Brain Company 全部署を tmux で一括起動
#
# 役割:
#   tmux セッション '$SESSION'（既定 'brain-company'）を新規作成し、8 ウィンドウ構成で
#   全部署（PM/開発/リサーチ/マーケ/経理/法務/経営企画）+ watcher を起動する。
#   あわせて、セッションの一覧の画面（tools/session-board）を起こす。
#
# ※ 秘書（secretariat）は専用の tmux セッション '<SESSION>-secretariat' で運用するため、
#   この tmux セッションには含まない。起動は ./start-secretariat.sh（extractor もそちらにいる）。
#
# ※ 社長室（ceo-office）は常駐エージェントを置かない保管ディレクトリなので、window を起動しない。
#   意思決定の記録（ceo-office/decisions/）は秘書室が書く。必要な時だけ .vscode/tasks.json の
#   「社長室: Claude Code 起動（個別）」から起こせる。
#
# 使い方:
#   $ ./start-agents-all.sh
#   $ tmux attach -t =$SESSION
#
# 軽量版: 3 ウィンドウだけで十分な場合は `./start-agents.sh` を使う（pm/dev/watcher）
#
# ウィンドウ構成:
#   0: pm          (プロジェクトマネジメント)
#   1: dev         (開発)
#   2: watcher     (ファイル監視)
#   3: research    (リサーチ部)
#   4: marketing   (マーケティング部)
#   5: accounting  (経理部)
#   6: legal       (法務部)
#   7: corporate-planning (経営企画部)
#
# 各部署の claude は、その dir の最新の対話の会話から再開する（.claude/scripts/claude-role.sh。会話が無い・
#   ほかで使用中・読めない時は新しい会話）。白紙で起こすなら CLAUDE_FRESH=1 ./start-agents-all.sh、起動の後なら /clear。
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

# --- セッションの一覧の画面（読むだけ・127.0.0.1 だけ）。部署が動いている時（下の exit 0）にも起こすよう、ここに置く。失敗しても部署の起動は続ける ---
"$ROOT/tools/session-board/tools/board_ctl.sh" start || echo "⚠ セッションの一覧の画面を起こせなかった（部署の起動は続ける）"

# --- 既存セッション確認 ---
if tmux has-session -t "=$SESSION" 2>/dev/null; then
  echo "⚠ tmux session '$SESSION' は既に起動中です"
  echo ""
  echo "操作:"
  echo "  attach: tmux attach -t =$SESSION"
  echo "  stop:   tmux kill-session -t =$SESSION"
  echo ""
  echo "既存セッションに部署 window を追加する場合:"
  echo "  tmux new-window -t =$SESSION: -n <部署名> -c <ディレクトリ>"
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

echo "▶ Starting Brain Company ALL departments in tmux session '$SESSION'..."

# --- Window 0: pm ---
tmux new-session -d -s "$SESSION" -n pm -c "$ROOT/product-management"
tmux send-keys -t "=$SESSION:pm" "$CLAUDE_CMD" Enter

# --- Window 1: dev ---
tmux new-window -t "=$SESSION:" -n dev -c "$ROOT/development"
tmux send-keys -t "=$SESSION:dev" "$CLAUDE_CMD" Enter

# --- Window 2: watcher ---
tmux new-window -t "=$SESSION:" -n watcher -c "$ROOT"
tmux send-keys -t "=$SESSION:watcher" "./watcher.sh" Enter

# --- Window 3: research ---
tmux new-window -t "=$SESSION:" -n research -c "$ROOT/research"
tmux send-keys -t "=$SESSION:research" "$CLAUDE_CMD" Enter

# --- Window 4: marketing ---
tmux new-window -t "=$SESSION:" -n marketing -c "$ROOT/marketing"
tmux send-keys -t "=$SESSION:marketing" "$CLAUDE_CMD" Enter

# --- Window 5: accounting ---
tmux new-window -t "=$SESSION:" -n accounting -c "$ROOT/accounting"
tmux send-keys -t "=$SESSION:accounting" "$CLAUDE_CMD" Enter

# --- Window 6: legal ---
tmux new-window -t "=$SESSION:" -n legal -c "$ROOT/legal"
tmux send-keys -t "=$SESSION:legal" "$CLAUDE_CMD" Enter

# --- Window 7: corporate-planning ---
tmux new-window -t "=$SESSION:" -n corporate-planning -c "$ROOT/corporate-planning"
tmux send-keys -t "=$SESSION:corporate-planning" "$CLAUDE_CMD" Enter

# --- pm にフォーカス ---
tmux select-window -t "=$SESSION:pm"

echo "✅ 全部署 起動完了"
echo ""
echo "操作:"
echo "  attach:        tmux attach -t =$SESSION"
echo "  ウィンドウ切替: Ctrl-b + 0〜7  または  Ctrl-b + n/p"
echo "  デタッチ:       Ctrl-b + d"
echo "  停止:           tmux kill-session -t =$SESSION"
echo ""
echo "ウィンドウ一覧:"
echo "  0: pm                 (プロジェクトマネジメント)"
echo "  1: dev                (開発)"
echo "  2: watcher            (ファイル監視)"
echo "  3: research           (リサーチ部)"
echo "  4: marketing          (マーケティング部)"
echo "  5: accounting         (経理部)"
echo "  6: legal              (法務部)"
echo "  7: corporate-planning (経営企画部)"
echo ""
echo "ℹ 秘書は専用の tmux セッション '${SESSION}-secretariat' で運用します（このセッションには含みません）:"
echo "  ./start-secretariat.sh"
echo "  または .vscode/tasks.json の「🚀【一斉】起動 & アタッチ」「🎧【秘書】秘書だけ起動 & アタッチ」を実行"
