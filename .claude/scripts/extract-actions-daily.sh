#!/usr/bin/env bash
#
# extract-actions-daily.sh - cron から日次で「未抽出の会話ログ」の /extract-actions を送出する
#
# 背景:
#   会話ログからの自動抽出は、秘書室セッションの終了（SessionEnd hook: .claude/hooks/on-session-end.sh）を起点にしている。
#   秘書室は専用の tmux セッションに常駐するのでセッションが滅多に終わらず、hook だけでは抽出が実質止まる。
#   そこで cron から日次で送出する。hook とは並存する（秘書を止めた時・落ちた時は hook が拾う）。
#
# 有効化（既定は停止。止まっている間は何もせず、ログに 1 行だけ残す）:
#   $ echo active > .claude/extract-cron.state
#
# 使い方:
#   $ ./extract-actions-daily.sh              # 直近 N 日から未抽出日を1つ選んで処理
#   $ ./extract-actions-daily.sh 2026-01-15   # 対象日を明示（回収・検証用。走査せず必ずその日）
#   $ ./extract-actions-daily.sh --dry-run    # 対象の決定だけ行い、送出しない（動作確認用）
#
# 終了コード:
#   0 = 成功 ／ 走査対象なし ／ 対象ログなし ／ --dry-run ／ 翌日の走査で再試行されるスキップ ／
#       送出先不在（unavailable。inbox 通知で可視化）／ 実行確認 NG（failcount・inbox 通知で可視化）
#   2 = 引数エラー（不明なオプション・対象日の複数指定・日付形式不正）
#   3 = スキップしたが自動では再試行されない（対象日が明日の走査窓＝直近 SCAN_DAYS 日に入らない。
#       extractor のアイドルを確認して同じ引数で手動再実行が必要）
#   ※ 手動実行（stderr が端末）のときはログと同じ行を端末にも出す。cron（非 TTY）はログのみ
#
# crontab 登録（毎日 05:00 JST。<ROOT> は会社のフォルダーの絶対パス）:
#   0 5 * * * TZ=Asia/Tokyo <ROOT>/.claude/scripts/extract-actions-daily.sh >> /tmp/extract-actions-daily.log 2>&1
#
# 前提: Linux / WSL2（GNU date・/proc を使う）。macOS では動かない。
#
# 🚨 「前日固定」にしないこと:
#   冪等性は「同じ日を2回処理しても二重にならない」性質であって、「飛んだ日を後から拾う」性質ではない。
#   前日固定だと、busy スキップ・送出消失・05:00 のマシン停止のいずれでも、その日は**二度と対象にならない**。
#   そこで対象は「直近 SCAN_DAYS 日のうち、まだ抽出しきれていない最も古い日」を毎回**実ファイルから計算**する。
#   state file に進捗を持たない＝state が壊れても復旧不要。
#
# 🚨 引数（対象日のパス）を必ず付けて送出すること:
#   /extract-actions は引数省略時「JST 本日」を対象にする（.claude/skills/extract-actions/SKILL.md「呼び出し方と引数」）。
#
# 🚨 cron は最小環境で走る（PATH=/usr/local/bin:/usr/bin、HOME 未設定）:
#   tmux はフルパスで呼ぶ。tmux ソケット /tmp/tmux-1000/default は UID で解決されるため HOME 不要。
#
# SessionEnd 経路（on-session-end.sh）とは並存する。両者は同じセンチネル/ログ/inbox 書式を共有する
# ── 片方を直す時はもう片方も確認すること。
#
set -u

# --- パス解決（スクリプトの実体位置から。.claude/scripts/ → .claude/ → <ROOT>） ---
SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}")"
ROOT="$(dirname "$(dirname "$(dirname "$SCRIPT_REAL")")")"

LOG="${ROOT}/secretariat/logs/extract-stop.log"
INBOX="${ROOT}/secretariat/inbox"
STATE_FILE="${ROOT}/.claude/extract-cron.state"
FAILCOUNT_FILE="${ROOT}/.claude/extract-cron.failcount"
# on-session-end.sh と共有するセンチネル（1つの障害につき inbox 通知は1件）
SENTINEL="${ROOT}/secretariat/logs/.extractor-unavailable"

# 秘書のセッション名（start-secretariat.sh と合わせる）。cron は TMUX_SESSION を持たないので、
# セッション名を変えた時は /company-setup がこの既定値を書き換える
SESSION="${TMUX_SESSION:-brain-company}-secretariat"
WINDOW="extractor"
PANE="${SESSION}:${WINDOW}"
# tmux に渡す時は '=名前'（完全一致）。tmux は同名のセッションが無いと前方一致で探す
TARGET="=${PANE}"

# 未抽出日を探す範囲（当日は含めない）
SCAN_DAYS=7
# 送出後、フロントマターの更新を待つ上限秒と、その間のポーリング間隔
#   実績: 送出 → フロントマター更新まで 16〜140 秒（会話量とキュー状況による）。
#   未抽出日は翌日の走査が拾うので、長く待つ必要はない。
#   EXTRACT_VERIFY_TIMEOUT は検証用の上書き口（本番の既定値は変えないこと）
VERIFY_TIMEOUT="${EXTRACT_VERIFY_TIMEOUT:-240}"
VERIFY_POLL=5
# 連続失敗が何回続いたら inbox 通知するか
#   1回目は fluke の可能性がある。2回目は「M3 による同じ日の再試行も失敗」＝パターン確定なので 2 とする
FAIL_NOTIFY_THRESHOLD=2

# cron の PATH は最小のためフルパスで呼ぶ
TMUX_BIN="/usr/bin/tmux"

# 終了コード（冒頭コメントの表と一致させること。0 以外は「呼び出し側が何かすべき」の合図）
EXIT_USAGE=2          # 引数エラー
EXIT_SKIP_NO_RETRY=3  # スキップしたが自動では再試行されない（手動再実行が必要）

mkdir -p "$(dirname "$LOG")"

# タイムスタンプは呼び出しの都度取る（実行確認で数分走ることがあるため）
# 手動実行（stderr が端末）のときは同じ行を端末にも出す。ログファイルにしか出ないと、
# 「翌日再試行されない」等の『直せ』の案内が実行者に届かない。
# cron（非 TTY）は現行どおりログのみ。
log() {
  local line
  line="$(TZ=Asia/Tokyo date --iso-8601=seconds) [cron] $*"
  echo "$line" >> "$LOG" 2>&1
  if [ -t 2 ]; then echo "$line" >&2; fi
}

# --- 引数 ---
TARGET_DATE=""
DRY_RUN=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1 ;;
    -*)
      log "ERROR: 不明なオプション: '$a'（使用可: --dry-run）"
      exit "$EXIT_USAGE"
      ;;
    *)
      if [ -n "$TARGET_DATE" ]; then
        log "ERROR: 対象日が複数指定されています: '$TARGET_DATE' と '$a'"
        exit "$EXIT_USAGE"
      fi
      TARGET_DATE="$a"
      ;;
  esac
done

# --- state file（不在時は paused = 安全側。inbox-monitor.sh と同じ作法） ---
[ -f "$STATE_FILE" ] || echo "paused" > "$STATE_FILE"
STATE=$(tr -d '\r\n ' < "$STATE_FILE")
if [ "$STATE" != "active" ]; then
  log "skip (state=${STATE}) — 有効化する場合: echo active > ${STATE_FILE#${ROOT}/}"
  exit 0
fi

# --- tmux 実行可能性 ---
if [ ! -x "$TMUX_BIN" ]; then
  TMUX_BIN="$(command -v tmux 2>/dev/null || true)"
fi

# --- 会話ログの読み取りヘルパ ---

# 置き場は会話ログ hook（.claude/hooks/log-user-prompt.sh）と同じ secretariat/memos/YYYY-MM-DD_会話ログ.md
log_path_for() { echo "${ROOT}/secretariat/memos/${1}_会話ログ.md"; }

# フロントマター（先頭の --- ブロック）から値を取り出す。無ければ空文字。
frontmatter_get() {
  local f="$1" key="$2"
  [ -f "$f" ] || { printf ''; return; }
  head -1 "$f" | grep -q '^---[[:space:]]*$' || { printf ''; return; }
  awk -v k="^${key}:" 'NR==1 {next} /^---[[:space:]]*$/ {exit} $0 ~ k { sub(/^[^:]*:[[:space:]]*/, ""); print; exit }' "$f"
}

# ログ内の「社長ターン」の最大番号。ターンが無ければ 0。
max_owner_turn() {
  local n
  n=$(grep -oE '^### \[#[0-9]+.*\] 社長' "$1" 2>/dev/null | grep -oE '#[0-9]+' | tr -d '#' | sort -n | tail -1)
  echo "${n:-0}"
}

# 未抽出か（フロントマターの last_extracted_turn がログの最大ターンに追いついていない）
is_pending() {
  local f="$1" fm mx
  mx=$(max_owner_turn "$f")
  [ "$mx" -gt 0 ] || return 1     # 社長ターンが無いログは対象外
  fm=$(frontmatter_get "$f" last_extracted_turn)
  case "$fm" in ''|*[!0-9]*) fm=0 ;; esac
  [ "$fm" -lt "$mx" ]
}

# 直近 SCAN_DAYS 日（当日を除く）から、未抽出の**最も古い**日を返す
find_pending_date() {
  local i d f
  for ((i = SCAN_DAYS; i >= 1; i--)); do
    d=$(TZ=Asia/Tokyo date -d "$i days ago" +%F)
    f=$(log_path_for "$d")
    [ -f "$f" ] || continue
    if is_pending "$f"; then echo "$d"; return 0; fi
  done
  return 1
}

# --- 「明日の走査で再試行されるか」の判定 ---
# 走査は毎回「i days ago, i = SCAN_DAYS..1」（当日除外）なので、明日の走査窓は
#   明日-SCAN_DAYS .. 明日-1 ＝ 今日-(SCAN_DAYS-1) .. 今日
# に入る日だけが自動で拾い直される。走査窓の最古日（今日-SCAN_DAYS）を今日スキップすると
# 明日は窓の外に出るため、引数指定・自動走査のどちらの経路でも再試行されない。
# 🚨 SCAN_DAYS を直書きせず連動させる。判定はこの関数に一本化し、案内文はすべてここに従う。
next_scan_floor() { TZ=Asia/Tokyo date -d "$((SCAN_DAYS - 1)) days ago" +%F; }
retried_by_next_scan() {
  local d="$1" floor
  floor=$(next_scan_floor)
  # YYYY-MM-DD 同士なので文字列比較で日付順になる
  ! [[ "$d" < "$floor" ]]
}

# --- 送出先ペインが処理中か ---
#
# 「'esc to interrupt' の速判定 ＋ 1秒あけた2回キャプチャの差分」という一般的な判定は、
# この送出先ペインでは成立しないことを実測した。そのため「処理中にだけ現れるマーカー」を見る:
#
#   ① 'esc to interrupt' は 0.5秒間隔30サンプル中、1度も出現しなかった（速判定として当てにできない）。
#   ② 差分判定はアイドルなのに 36〜45 行の差分を出し、10回中4回 busy と誤判定した
#      （バックグラウンドの表示が画面全体を再描画するため。閾値を上げても分離できない）。
#      アイドルを busy と誤らないことが最重要なので、差分判定は使わない。
#   ③ 一方、処理中はスピナー行 `<動詞>… (Ns · …)` が安定して出る。
#      完了後の表示は `✻ Baked for 2s` のように括弧を伴わないため、区別できる。
#
# よって次の3つを「処理中マーカー」とする。いずれもアイドル時には表示されない:
#   - スピナー行（`… (3s ·` / `… (1m 34s ·`）… 処理中
#   - 'queued message' … 未処理の投入が溜まっている（送っても積まれるだけ）
#   - 'esc to interrupt' … 出れば処理中（このペインでは出なかったが、他の表示状態への保険）
#
# ⚠️ 既知の限界: TUI が自前のスクロールバック表示になっている間はスピナーが
#    スクロール通知に置き換わるため、投入が無い状態の処理中は検出できない。
#    その場合は1通だけ積まれ、次回は 'queued message' が立って検出できる（自己収束）。
BUSY_MARKERS='esc to interrupt|queued message|…[^)]*\(([0-9]+m )?[0-9]+s'
pane_busy() {
  local pane="$1" cap
  cap="$("$TMUX_BIN" capture-pane -p -t "$pane" 2>/dev/null)" || return 1
  printf '%s' "$cap" | grep -qiE "$BUSY_MARKERS"
}

# --- 送出先の Claude Code の状態 ---
# 開いたままの確認の画面に Enter を送ると、既定の「Yes」で確認の決まり（rm など）を人の目を通さずに通してしまう
# （実際に起きた）。画面の見分け（pane_busy）は確認の画面を見ないので、セッションの記録の status を読む。
# 判定は .claude/scripts/extractor_state.py（SessionEnd hook と共有）。
# 出力: "<status> <waitingFor>"（busy・idle・waiting・shell）。読めない時は "unknown <理由>"（呼ぶ側は pane_busy に戻る）
# cron は HOME が無いので、設定の置き場はパスワードの表から求める
SESSIONS_DIR="${CLAUDE_CONFIG_DIR:-${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}/.claude}/sessions"
PY_BIN="/usr/bin/python3"
session_state() {
  local pane_id
  pane_id=$("$TMUX_BIN" display-message -p -t "$1" '#{pane_id}' 2>/dev/null) || { echo "unknown ペインの番号を読めない"; return; }
  [ -x "$PY_BIN" ] || PY_BIN="$(command -v python3 2>/dev/null || true)"
  [ -n "$PY_BIN" ] || { echo "unknown python3 が無い"; return; }
  "$PY_BIN" "$ROOT/.claude/scripts/extractor_state.py" "$SESSIONS_DIR" "$SESSION" "$pane_id" 2>/dev/null || echo "unknown 記録を読めない"
}

# copy-mode のペインは send-keys を**無言で食う**。
# 「送出したのに実行されない」の実原因になるため、送出前に必ず解除する。
cancel_copy_mode() {
  local pane="$1"
  if [ "$("$TMUX_BIN" display-message -p -t "$pane" '#{pane_in_mode}' 2>/dev/null || echo 0)" != "0" ]; then
    "$TMUX_BIN" send-keys -t "$pane" -X cancel 2>/dev/null || true
    sleep 0.2
    log "  → copy-mode を解除しました（そのままでは send-keys が無言で捨てられる）"
  fi
}

# --- 連続失敗カウンタ ---
failcount_get() {
  local n
  n=$(tr -d '\r\n ' < "$FAILCOUNT_FILE" 2>/dev/null || echo 0)
  case "$n" in ''|*[!0-9]*) n=0 ;; esac
  echo "$n"
}
failcount_reset() { echo 0 > "$FAILCOUNT_FILE"; }

# --- 失敗の可視化（on-session-end.sh と同じ仕組み・同じセンチネルを共有） ---
# $1=reason $2=kind（unavailable | unverified | waiting）
notify_failure() {
  local reason="$1" kind="${2:-unavailable}" recover
  if [ "$kind" = "waiting" ]; then
    recover="extractor の画面（tmux attach -t =${SESSION} → ${WINDOW} の窓）で確認の中身を見て、人が選ぶ（通してよい時だけ通す）"
  else
    recover="./start-secretariat.sh --no-attach（稼働中セッションを落とさず extractor window を補完）"
  fi
  {
    echo "$(TZ=Asia/Tokyo date --iso-8601=seconds) [cron] ⚠ ${reason}"
    echo "$(TZ=Asia/Tokyo date --iso-8601=seconds) [cron]   target=${TARGET_REL}"
    echo "$(TZ=Asia/Tokyo date --iso-8601=seconds) [cron]   復旧: ${recover}"
  } >> "$LOG" 2>&1

  # noclobber(O_EXCL) による原子的なセンチネル作成。同一障害では1件だけ通知する。
  if ( set -o noclobber; echo "$(TZ=Asia/Tokyo date --iso-8601=seconds)" > "$SENTINEL" ) 2>/dev/null; then
    mkdir -p "$INBOX"
    local ts_file ts_human inbox_file detail
    ts_file=$(TZ=Asia/Tokyo date '+%Y-%m-%d_%H-%M-%S')
    ts_human=$(TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M:%S JST')
    inbox_file="${INBOX}/${ts_file}_システム_extractor送出失敗.md"

    # 「1回だけなら翌日の自動回収に任せる」は対象日が明日の走査窓に入る時だけ真（判定は retried_by_next_scan に一本化）
    local first_fail_note
    if retried_by_next_scan "$TARGET_DATE"; then
      first_fail_note="1回だけなら翌日の自動回収に任せます"
    else
      first_fail_note="対象日は明日の走査窓に入らないため自動回収されず、1回目から手動再実行を案内しています"
    fi
    if [ "$kind" = "unverified" ]; then
      detail="- **事象**: \`${PANE}\` へ送出は成功したが、**${VERIFY_TIMEOUT} 秒以内に抽出が実行された形跡がない**
  （対象ログのフロントマター \`last_extracted_at\` / \`last_extracted_turn\` が更新されなかった）
- **連続失敗**: ${FAIL_NOTIFY_THRESHOLD} 回連続で確認できなかったため通知しています（${first_fail_note}）
- **考えられる原因**: extractor 側の Claude Code が更新・再起動中だった／スキルがエラーで停止した／
  抽出対象が実は無く、スキルがフロントマターを更新せずに終了した（この場合は実害なし）"
    elif [ "$kind" = "waiting" ]; then
      detail="- **事象**: cron の日次実行が \`${PANE}\` へ送出しようとしたが、**extractor が確認の画面で止まっていた**ため送出しなかった
- **理由**: ${reason}
- **送らなかった訳**: 確認の画面に Enter を送ると、既定の「Yes」で確認を通してしまう（人の目を通さずに通る）"
    else
      detail="- **事象**: cron の日次実行が \`${PANE}\` へ送出しようとしたが、**送出先が見つからなかった**
- **理由**: ${reason}"
    fi

    # 補足の「翌日以降が自動で拾う」は、対象日が明日の走査窓に入る時だけ真（判定は retried_by_next_scan に一本化）
    local retry_note
    if retried_by_next_scan "$TARGET_DATE"; then
      retry_note="- 未抽出の日は**翌日以降の実行が自動で拾います**（直近 ${SCAN_DAYS} 日を毎回走査するため）"
    else
      retry_note="- ⚠ ${TARGET_DATE} は明日の走査窓（直近 ${SCAN_DAYS} 日: $(next_scan_floor) 〜 今日）に**入らない**ため、自動では拾われません。上記「復旧手順 2」を**手動で**実行してください"
    fi

    cat > "$inbox_file" <<EOF
---
received: ${ts_human}
source_dept: システム
source_path: ${LOG}
status: unread
---

# Inbox: 日次の /extract-actions が完了できませんでした（cron）

## 概要
- **検知日時**: ${ts_human}
${detail}
- **対象ログ**: \`${TARGET_REL}\`
- **影響**: **${TARGET_DATE} 分の抽出（ToDo / 意思決定 / 思考メモ）が完了していない可能性があります**

## 復旧手順

1. ${recover}
2. 取りこぼした日を回収する（どちらでも可）
   - \`.claude/scripts/extract-actions-daily.sh ${TARGET_DATE}\`
   - または extractor で \`/extract-actions ${TARGET_REL}\` を手動実行

## 秘書の推奨アクション

1. 上記の復旧手順を実行する
2. 処理完了後、本inboxファイルのステータスを 'processed' に書き換える or \`secretariat/inbox/archive/\` へ移動

## 補足

- 本通知は**同一障害につき1件のみ**生成されます（送出が再び成功した時点で再武装）
${retry_note}
- スキルは冪等なので、復旧後にもう一度回しても二重抽出は起きません
- 詳細ログ: \`${LOG}\`
EOF
    log "  → inbox written: ${inbox_file#${ROOT}/}"
  else
    log "  → inbox 通知は抑制（同一障害で既報）"
  fi
}

# =============================================================================
# 対象日の決定
# =============================================================================
if [ -n "$TARGET_DATE" ]; then
  # 明示指定: 走査せず必ずその日（回収・検証用。現行動作を維持）
  case "$TARGET_DATE" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *)
      log "ERROR: 対象日の形式が不正です: '${TARGET_DATE}'（期待: YYYY-MM-DD）"
      exit "$EXIT_USAGE"
      ;;
  esac
  SELECTED_BY="引数指定"
else
  # 走査: 直近 SCAN_DAYS 日（当日を除く）で未抽出の最も古い日
  if ! TARGET_DATE=$(find_pending_date); then
    log "未抽出の対象なし（直近 ${SCAN_DAYS} 日・当日を除く）— 送出せず正常終了"
    exit 0
  fi
  SELECTED_BY="走査（直近 ${SCAN_DAYS} 日の未抽出のうち最古）"
fi

TARGET_LOG=$(log_path_for "$TARGET_DATE")
TARGET_REL="${TARGET_LOG#${ROOT}/}"

# --- 対象ログの存在チェック（会話が無かった日は障害ではない） ---
# 🚫 無言スキップにしない: ログに必ず1行残す
# ⭕ ただし inbox 通知・センチネル設置はしない（毎日通知が出ると狼少年になる）
if [ ! -f "$TARGET_LOG" ]; then
  log "対象ログなし: ${TARGET_REL}（会話が無かった日と判断し、送出せず正常終了）"
  exit 0
fi

BEFORE_AT=$(frontmatter_get "$TARGET_LOG" last_extracted_at)
BEFORE_TURN=$(frontmatter_get "$TARGET_LOG" last_extracted_turn)
MAX_TURN=$(max_owner_turn "$TARGET_LOG")

# 既に抽出しきっている日か（引数指定での再実行時のみ起こりうる。走査では選ばれない）
# 🚨 この場合スキルは「新規抽出対象なし」で終了し、フロントマターを更新しない。
#    実行確認をそのまま適用すると必ず NG になり、誤って失敗カウントが進む。
if is_pending "$TARGET_LOG"; then
  EXPECT_UPDATE=1
else
  EXPECT_UPDATE=0
fi

log "対象決定: ${TARGET_DATE}（${SELECTED_BY}） last_extracted_turn=${BEFORE_TURN:--} / 最大社長ターン=${MAX_TURN}"

if [ "$DRY_RUN" -eq 1 ]; then
  log "  → --dry-run のため送出しません"
  exit 0
fi

# =============================================================================
# 送出
# =============================================================================
if [ -z "$TMUX_BIN" ]; then
  notify_failure "tmux が見つかりません（cron の PATH: ${PATH}）" unavailable
  exit 0
fi

# --- 送出先の存在確認 ---
if ! ( "$TMUX_BIN" has-session -t "=$SESSION" 2>/dev/null && \
       "$TMUX_BIN" list-windows -t "=$SESSION" -F '#{window_name}' 2>/dev/null | grep -Fxq "$WINDOW" ); then
  notify_failure "extractor UNAVAILABLE — tmux セッション '${SESSION}' または window '${WINDOW}' が存在しません" unavailable
  exit 0
fi

# --- 確認の画面で止まっていないか（上の session_state の説明） ---
read -r EXTRACTOR_STATE EXTRACTOR_WHY <<< "$(session_state "$TARGET")"
if [ "$EXTRACTOR_STATE" = "waiting" ]; then
  log "  → skip: 送出先 ${PANE} が確認の画面で止まっている（waiting: ${EXTRACTOR_WHY}）。Enter を送ると既定の「Yes」で通るため、送出しません"
  notify_failure "extractor WAITING — 確認の画面で止まっている（${EXTRACTOR_WHY}）。送出しなかった" waiting
  if retried_by_next_scan "$TARGET_DATE"; then
    exit 0
  fi
  log "  → ⚠ ${TARGET_DATE} は明日の走査窓（直近 ${SCAN_DAYS} 日: $(next_scan_floor) 〜 今日）に入らないため、自動では再試行されません。画面の確認を片付けた後に再実行してください: .claude/scripts/extract-actions-daily.sh ${TARGET_DATE}"
  exit "$EXIT_SKIP_NO_RETRY"
fi
if [ "$EXTRACTOR_STATE" = "unknown" ]; then
  log "  → セッションの記録から状態を読めない（${EXTRACTOR_WHY}）。画面の見分け（pane_busy）で判断します"
fi

# --- busy 判定（処理中なら送らずスキップ。セッションの記録が busy の時も） ---
# 対象日が明日の走査窓に入るなら翌日の走査が同じ日を拾う（cron の正常系。文言・exit 0 とも現行どおり）。
# 入らないなら自動では二度と拾われないため、再実行の手順を明示して専用 exit code で返す
# （引数指定で古い日を回収しようとして busy スキップした時に「翌日再試行」と誤案内し exit 0 で終わる、を防ぐ）。
if [ "$EXTRACTOR_STATE" = "busy" ] || pane_busy "$TARGET"; then
  if retried_by_next_scan "$TARGET_DATE"; then
    log "  → skip: 送出先 ${PANE} が処理中（busy）。今回は送出しません（未抽出のまま翌日の走査で再試行されます）"
    exit 0
  fi
  log "  → skip: 送出先 ${PANE} が処理中（busy）。今回は送出しません"
  log "  → ⚠ ${TARGET_DATE} は明日の走査窓（直近 ${SCAN_DAYS} 日: $(next_scan_floor) 〜 今日）に入らないため、自動では再試行されません（このままだと未抽出のまま残ります）"
  log "  → 手動で再実行してください: extractor のアイドルを確認（${TMUX_BIN} capture-pane -p -t ${TARGET} | tail -5）→ .claude/scripts/extract-actions-daily.sh ${TARGET_DATE}"
  exit "$EXIT_SKIP_NO_RETRY"
fi

# --- 送出（on-session-end.sh と同じ3ステップ） ---
cancel_copy_mode "$TARGET"
log "  → sending /extract-actions to ${PANE}"
# 1. テキストをリテラルで送信（改行解釈されない）
"$TMUX_BIN" send-keys -t "$TARGET" -l "/extract-actions ${TARGET_LOG}"
# 2. Claude Code UI が入力を取り込むのを待つ
sleep 0.3
# 3. 単独で Enter（これが送信トリガー）
"$TMUX_BIN" send-keys -t "$TARGET" Enter
log "  → send-keys completed (3 steps: literal / sleep 0.3 / Enter)"

# =============================================================================
# 実行確認（🚨 発行 ≠ 成功。送出できたことを成功と見なさない）
# =============================================================================
if [ "$EXPECT_UPDATE" -eq 0 ]; then
  log "  → 実行確認はスキップ: ${TARGET_DATE} は既に抽出済み（新規ターンなし）のため、スキルはフロントマターを更新しません"
  exit 0
fi

VERIFIED=0
elapsed=0
while [ "$elapsed" -lt "$VERIFY_TIMEOUT" ]; do
  sleep "$VERIFY_POLL"
  elapsed=$((elapsed + VERIFY_POLL))
  after_at=$(frontmatter_get "$TARGET_LOG" last_extracted_at)
  after_turn=$(frontmatter_get "$TARGET_LOG" last_extracted_turn)
  # 主判定は last_extracted_at の更新（新規ターンが無い日は turn が動かないため）
  if { [ -n "$after_at" ] && [ "$after_at" != "$BEFORE_AT" ]; } || \
     { [ -n "$after_turn" ] && [ "$after_turn" != "$BEFORE_TURN" ]; }; then
    VERIFIED=1
    break
  fi
done

if [ "$VERIFIED" -eq 1 ]; then
  log "  → ✅ 実行確認 OK（${elapsed}秒後） last_extracted_turn: ${BEFORE_TURN:--} → ${after_turn:--}"
  failcount_reset
  # 送出・実行できた＝障害解消。センチネルを解除して次の障害で再通知できるようにする
  if [ -e "$SENTINEL" ]; then
    rm -f "$SENTINEL"
    log "  → recovered: 通知センチネルを解除しました"
  fi
else
  fails=$(( $(failcount_get) + 1 ))
  echo "$fails" > "$FAILCOUNT_FILE"
  log "  → ⚠ 実行確認 NG（${VERIFY_TIMEOUT}秒以内にフロントマターが更新されませんでした） 連続失敗 ${fails} 回目"
  if [ "$fails" -ge "$FAIL_NOTIFY_THRESHOLD" ]; then
    notify_failure "送出は成功したが実行された形跡がない（連続 ${fails} 回）" unverified
  elif retried_by_next_scan "$TARGET_DATE"; then
    log "  → 通知は保留（連続 ${FAIL_NOTIFY_THRESHOLD} 回で通知。未抽出のまま翌日の走査で再試行されます）"
  else
    log "  → 通知は保留（連続 ${FAIL_NOTIFY_THRESHOLD} 回で通知）。${TARGET_DATE} は明日の走査窓（直近 ${SCAN_DAYS} 日）に入らないため自動では再試行されません — 抽出されたか確認し、未抽出なら再実行: .claude/scripts/extract-actions-daily.sh ${TARGET_DATE}"
  fi
fi

exit 0
