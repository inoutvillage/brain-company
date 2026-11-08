#!/usr/bin/env bash
#
# start-secretariat.sh - 秘書室専用の tmux セッションを冪等に起動／再接続する
#
# 役割:
#   秘書室専用の tmux セッション '<TMUX_SESSION>-secretariat'（既定 'brain-company-secretariat'）を作り、
#   その中で Claude Code を起動する。部署側のセッション '<TMUX_SESSION>'（start-agents-all.sh）とは分ける
#   （＝部署側を止めても・落ちても秘書は生き残る。ターミナルや VS Code を閉じても会話の文脈が残る）。
#
# ウィンドウ構成:
#   0: secretariat  (秘書本体。cwd = <ROOT>/secretariat)
#   1: extractor    (SessionEnd hook / cron の送出先, /extract-actions 受信。cwd = <ROOT>)
#
# 🚨 extractor の cwd は <ROOT>（秘書室配下にしないこと）:
#   .claude/hooks/on-session-end.sh は cwd が <ROOT>/secretariat 配下の時だけ発火する。
#   extractor を secretariat 配下で起動すると、extractor 自身のセッション終了が
#   SessionEnd hook を再発火させ、抽出の自己ループになる。`-c "$ROOT"` を `$WORKDIR` に変えないこと。
#
# 🚨 秘書の cwd は必ず <ROOT>/secretariat であること:
#   会話ログ hook（.claude/hooks/log-user-prompt.sh）は「claude 起動時の cwd」で部署判定する。
#   起動後に cd しても判定は変わらないため、起動 cwd を外すと会話ログが無言で記録されなくなる。
#
# 🚨 --add-dir .. を落とさないこと:
#   秘書は他部署の reports/ や requests/ を横断で読み書きするため必須。
#   落とすと秘書の業務がエラーにならずに壊れる。
#
# 🚨 watcher.sh は秘書へ send-keys しない（直さないこと）:
#   watcher.sh は部署側セッションの window 名完全一致でしか send-keys しない。
#   秘書への知らせは secretariat/inbox/ へのファイル書き出しで届く（秘書が読みに行く）。
#
# 🚨 tmux の -t は '=名前'（完全一致）で指す:
#   tmux は同名のセッションが無いと前方一致で探す。部署側 'brain-company' が止まっている時に
#   '-t brain-company' と書くと、この 'brain-company-secretariat' に当たる。
#
# 使い方:
#   $ ./start-secretariat.sh              # 起動（既に居れば再接続のみ）
#   $ ./start-secretariat.sh --no-attach  # 起動のみ・接続しない（一斉起動・extractor の補完用）
#   $ CLAUDE_FRESH=1 ./start-secretariat.sh   # 秘書を前の会話から再開せず、新しい会話で起こす
#
# 冪等性:
#   セッションが既に存在する場合は claude を再送しない（send-keys 二重撃ちは既存プロンプトを壊す）。
#   attach（tmux 外）／ switch-client（tmux 内）のみ行う。
#   ただし「セッションは在るが extractor window が無い」場合は、
#   稼働中のセッションを落とさずに extractor window だけを補完する。
#
# 終了コード:
#   0 = 成功（起動 ／ 再接続 ／ extractor 補完 ／ extractor 既存で何もせず）
#   1 = 失敗（依存不足・秘書室ディレクトリ無し・extractor window の補完失敗。理由は stderr）
#       補完失敗でも window 0（秘書本体）は落とさない。「補完しました」「起動完了」は成功時にしか出ない
#   2 = 引数エラー
#

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPT_SESSION="${TMUX_SESSION:-brain-company}"
SESSION="${DEPT_SESSION}-secretariat"
WORKDIR="$ROOT/secretariat"
MAIN_WINDOW="secretariat"
# 秘書室はこの dir の最新の対話の会話から再開する（claude-role.sh。会話が無い・ほかで使用中・読めない時は
# 新しい会話。白紙で起こすなら CLAUDE_FRESH=1 ./start-secretariat.sh、起動の後なら /clear）
# 窓のシェルが読むコマンドなので、場所は引用して渡す（会社のフォルダーの場所に空白があっても動くように）
CLAUDE_CMD="$(printf '%q' "$ROOT/.claude/scripts/claude-role.sh") --add-dir .. --dangerously-skip-permissions"
# tmux の窓のシェルにはこのスクリプトの環境が届かないので、打ち込むコマンドに付ける
[ "${CLAUDE_FRESH:-}" = "1" ] && CLAUDE_CMD="CLAUDE_FRESH=1 $CLAUDE_CMD"
EXTRACTOR_WINDOW="extractor"
# extractor はルート起動でプロジェクト全体が見えるため --add-dir は不要
# extractor は再開しない（毎回新しい会話）: 日ごとの抽出の頼みはそれだけで完結し、前の日の文脈は要らない。
# 再開すると前の日の抽出の文脈が積み上がり、毎回の利用量が増え、別の日の内容と混ざりうる
EXTRACTOR_CMD="claude --dangerously-skip-permissions"

# --- 引数 ---
ATTACH=1
case "${1:-}" in
  "")          ;;
  --no-attach) ATTACH=0 ;;
  *)
    echo "usage: $(basename "$0") [--no-attach]" >&2
    exit 2
    ;;
esac

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

# --- 秘書室ディレクトリ確認（cwd を外すと会話ログが消えるため必須チェック） ---
if [ ! -d "$WORKDIR" ]; then
  echo "ERROR: 秘書室ディレクトリが見つかりません: $WORKDIR"
  exit 1
fi

# --- 接続（tmux 内からは attach できないので switch-client に分岐） ---
connect() {
  if [ "$ATTACH" -eq 0 ]; then
    echo "ℹ --no-attach 指定のため接続しません（接続: tmux attach -t =$SESSION）"
    return 0
  fi
  if [ -n "${TMUX:-}" ]; then
    # tmux 内で attach すると "sessions should be nested with care" で失敗する
    tmux switch-client -t "=$SESSION"
  else
    tmux attach -t "=$SESSION"
  fi
}

# --- extractor window の補完（無ければ作る・在れば何もしない） ---
# 稼働中セッションを落とさずに window を足せるようにするための分岐。
# 戻り値: 0 = 追加した / 1 = 既に在ったので何もしなかった（skipped） / 2 = 失敗（理由は stderr）
# 🚨 new-window / set-window-option / send-keys の 3 ステップそれぞれの戻り値を検査する。
#    検査せずに 0 を返すと、全部失敗しても呼び出し側が「補完しました」と表示してしまう。
ensure_extractor_window() {
  local target="=${SESSION}:${EXTRACTOR_WINDOW}"
  local err
  if tmux list-windows -t "=$SESSION" -F '#{window_name}' 2>/dev/null | grep -Fxq "$EXTRACTOR_WINDOW"; then
    return 1
  fi
  # 🚨 -t は "=${SESSION}:"（末尾コロン＝セッション限定・次の空き index）。
  # 🚨 -d で、作成した window を active にしない（稼働中の秘書の表示を extractor に奪わせない）。
  # 🚨 -c は "$ROOT"。"$WORKDIR" にすると SessionEnd hook が自己ループする
  if ! err=$(tmux new-window -d -t "=${SESSION}:" -n "$EXTRACTOR_WINDOW" -c "$ROOT" 2>&1); then
    echo "ERROR: extractor window の作成に失敗 (step: new-window, target: '=${SESSION}:'): ${err:-tmux からの出力なし}" >&2
    return 2
  fi
  # 🚨 window 名を固定する。automatic-rename はサーバ既定が on で、
  #    有効なままだと実行中コマンド名（claude 等）に改名されてしまい、
  #    on-session-end.sh / extract-actions-daily.sh の window 名一致（grep -Fxq extractor）が
  #    外れて送出先を見失う。
  if ! err=$(tmux set-window-option -t "$target" automatic-rename off 2>&1); then
    echo "ERROR: extractor window の名前固定に失敗 (step: set-window-option, target: '$target'): ${err:-tmux からの出力なし}（window は作成済み・claude 未起動）" >&2
    return 2
  fi
  if ! err=$(tmux send-keys -t "$target" "$EXTRACTOR_CMD" Enter 2>&1); then
    echo "ERROR: extractor への claude 起動コマンド送出に失敗 (step: send-keys, target: '$target'): ${err:-tmux からの出力なし}（window は作成済み・claude 未起動）" >&2
    return 2
  fi
  return 0
}

# --- 操作案内 ---
usage_note() {
  echo ""
  echo "操作:"
  echo "  attach:   tmux attach -t =$SESSION      （tmux 内からは: tmux switch-client -t =$SESSION）"
  echo "  デタッチ: Ctrl-b + d                   （セッションは生き続ける）"
  echo "  停止:     tmux kill-session -t =$SESSION"
  echo ""
}

# --- 既存セッション確認（冪等性: あれば claude を再送しない） ---
if tmux has-session -t "=$SESSION" 2>/dev/null; then
  echo "⚠ tmux session '$SESSION' は既に起動中です（claude は再送しません）"
  # 稼働中セッションはそのままに、extractor window だけ不足していれば補完する
  # （0 = 追加 / 1 = 既存 / それ以外 = 失敗。失敗を「補完しました」と表示しない）
  ensure_extractor_window
  case "$?" in
    0) echo "➕ extractor window が無かったため補完しました（cwd: $ROOT）" ;;
    1) echo "   extractor window は既に存在します" ;;
    *)
      # 復旧目的の実行者にエラーを見せるため attach せずに終了する（attach すると画面が切り替わって流れる）
      echo "❌ extractor window の補完に失敗しました（理由は上の ERROR 行）。window 0 '$MAIN_WINDOW' は無傷です" >&2
      echo "   extractor が無い間、SessionEnd hook / cron の抽出は送出されず、secretariat/inbox/ に知らせが残ります" >&2
      exit 1
      ;;
  esac
  usage_note
  connect
  exit 0
fi

# --- 秘書 inbox ディレクトリ確保（watcher.sh の書き出し先） ---
mkdir -p "$WORKDIR/inbox"

echo "▶ 秘書室セッション '$SESSION' を起動します（cwd: $WORKDIR）..."

# --- Window 0: secretariat（-c で cwd を固定。会話ログ hook の発火条件） ---
tmux new-session -d -s "$SESSION" -n "$MAIN_WINDOW" -c "$WORKDIR"
# new-session -n は new-window -n と違い automatic-rename を落とさない（実測）ため明示的に切る
tmux set-window-option -t "=${SESSION}:${MAIN_WINDOW}" automatic-rename off > /dev/null
tmux send-keys -t "=${SESSION}:${MAIN_WINDOW}" "$CLAUDE_CMD" Enter

# --- Window 1: extractor（SessionEnd hook / cron の送出先。cwd は $ROOT） ---
# （0 = 追加 / 1 = 既存 / それ以外 = 失敗。失敗時は「✅ 起動完了」を出さず非 0 で終了。window 0 は落とさない）
ensure_extractor_window
case "$?" in
  0) ;;
  1) echo "ℹ extractor window は既に存在していました（作成をスキップ）" ;;
  *)
    echo "❌ 起動は不完全です: window 0 '$MAIN_WINDOW'（秘書本体）は起動済み ／ extractor window は未作成（理由は上の ERROR 行）" >&2
    echo "   extractor が無い間、SessionEnd hook / cron の抽出は送出されず、secretariat/inbox/ に知らせが残ります" >&2
    echo "   復旧: 原因を取り除いた後に ./start-secretariat.sh --no-attach を再実行（window 0 はそのまま・extractor だけ補完されます）" >&2
    exit 1
    ;;
esac

echo "✅ 起動完了"
echo ""
echo "  セッション: $SESSION（部署側 '$DEPT_SESSION' とは独立。部署側を止めても生存）"
echo ""
echo "  0: $MAIN_WINDOW   (秘書本体)  cwd=$WORKDIR"
echo "     コマンド: $CLAUDE_CMD"
echo "  1: $EXTRACTOR_WINDOW     (SessionEnd hook / cron の送出先, /extract-actions 受信)  cwd=$ROOT"
echo "     コマンド: $EXTRACTOR_CMD"
usage_note

connect
