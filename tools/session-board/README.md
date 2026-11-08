# session-board — セッションの一覧の画面

## 概要
動いている Claude Code（と Codex CLI）のセッションを、1 枚のページにカードで並べる読み取り専用の画面。
秘書室・各部署・aipair の各案件など、どのセッションが「社長の番（答え待ち）」で、どれが作業中かをひと目で見る。

- Claude Code と Codex が自分で書いている記録と tmux を**読むだけ**で集める（hook は足さない。tmux に文字を送らない）
- 画面で直した物（表示しない・グループ）だけを、手元のファイル 1 つに残す
- 待ち受けは `127.0.0.1` だけ。Python の標準ライブラリだけで動く（外のパッケージ・外の API なし）

## 必要な物
- **Linux か WSL2**（`/proc` を読むため。**macOS・Windows（WSL の外）では動かない**）
- Python 3.9 以上（`python3`。版が足りなければ起動の時に止まって知らせる。`PYTHON` で別の物を指定できる）
- Claude Code
- 任意: tmux（無くても動く。部署・秘書室・aipair の見分けと名前は tmux から取る）、Codex CLI（npm で入れた `@openai/codex`）
- `tools/board_ctl.sh` が使う物: bash・curl・setsid・nohup・pgrep（ふつうの Linux には入っている）

## 使い方
会社のルート（このテンプレートのルート）から:

```bash
tools/session-board/tools/board_ctl.sh start    # 起こす（動いていれば何もしない）→ http://127.0.0.1:18790/
tools/session-board/tools/board_ctl.sh status   # 動いているかと、数だけ（中身は出さない）
tools/session-board/tools/board_ctl.sh stop     # 止める
tools/session-board/tools/open_board.sh         # ブラウザで開く
tools/session-board/bin/session-board check     # 本物を集めて、数だけを出す（画面は起こさない）
tools/session-board/bin/session-board serve --port 18791 --demo   # 作り物の中身の見本（画面の写し・試し用）
```

- `board_ctl.sh start|stop|status [番号]`: 番号を渡すと、その番号の画面を扱う（無ければ `SESSION_BOARD_PORT`、それも無ければ 18790）
- `start` は別のセッション（`setsid`）で起こすので、起こした端末を閉じても止まらない。待つのは 10 秒まで。起きずに終わった時（番号が使われている・Python の版が足りない等）はすぐ失敗を返す。理由は置き場の `board.out` に出る
- `board_ctl.sh` が扱うのは、**この置き場の `bin/session-board` をその番号で起こした物だけ**（命令の行で確かめる）。別の置き場の画面や、手で起こした画面は止めない
- `open_board.sh [番号]` は、`$BROWSER` → `wslview` → `explorer.exe`（WSL の時だけ）→ `xdg-open` → `open`（macOS の時だけ）の順に、ある物で開く。どれも無ければ URL を出して 1 で終わる。画面が動いているかは見ない
- `start-agents-all.sh`（全部署の一斉起動）が `board_ctl.sh start` を流すので、ふだんは部署と一緒に起きる（失敗しても部署の起動は止めない）。VS Code なら「📋【一覧】セッションの一覧の画面をブラウザで開く」

## 設定（環境変数）
| 名前 | 既定 | 読む所 | 意味 |
|---|---|---|---|
| `SESSION_BOARD_COMPANY_ROOT` | この道具の置き場（`tools/session-board/`）の 2 つ上 | `board/config.py` | 会社のルート。「会社」のグループの見分けに使う。その 1 つ上が案件のフォルダーの根（aipair の案件をこの下の一番上のフォルダーごとにまとめる） |
| `TMUX_SESSION` | `brain-company` | `board/config.py` | 部署側の tmux セッション名（`start-agents-all.sh` と同じ）。秘書のセッション名は `<これ>-secretariat` |
| `SESSION_BOARD_STATE_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/brain-company/session-board` | `board/config.py`・`tools/board_ctl.sh`（同じ規則） | 置き場（番号の控え・起動の出力・失敗の記録・画面の設定） |
| `XDG_STATE_HOME` | `$HOME/.local/state` | 同上 | 置き場の既定の根 |
| `SESSION_BOARD_PORT` | `18790` | `bin/session-board`・`tools/board_ctl.sh`・`tools/open_board.sh` | 待ち受けの番号（1〜65535。頭に 0 を付けない） |
| `PYTHON` | `python3` | `tools/board_ctl.sh` | 画面を起こす Python |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | `board/config.py` | Claude Code の置き場（`sessions/`・`projects/` を読む） |
| `CODEX_HOME` | `~/.codex` | `board/config.py` | Codex の置き場（`sessions/` の下の記録だけを Codex の物と見なす） |
| `BROWSER` | なし | `tools/open_board.sh` | ブラウザを開くコマンド（名前か場所。引数は付けない） |

- `TMUX_SESSION` などは、**画面を起こした時の値**で決まる。部署を別の名前で起こしているなら、同じ値を入れてから `board_ctl.sh start` する（値を変えたら `stop`・`start`）
- 置き場は 700、画面の設定（`prefs.json`）は 600 で作る。置く物は、番号の控え・起動の出力・失敗の記録（理由と数だけ）・画面の設定だけ

## 画面の見方

### 状態の色
| 色 | いつ |
|---|---|
| 黄（社長の番） | `waiting`（許可の問い・質問への答え待ち・画面の操作待ち）／社長と話す所（aipair・秘書室の本体・tmux の外）で、社長の最後の頼みへの最後の返事が問いかけで終わった時（「社長への問いかけ」）。どちらも時間の上限なし（答えるまで黄） |
| 黄（決めごとの節） | 社長と話す所で、社長の最後の頼みへの最後の返事の**最後の節**が、決めてほしいことの節の時。最後の見出し（`#` の見出し・太字だけの行。コードのかたまりの中は見ない）に決めごとの言葉（`collect.DECISION_RE`: まだ決まっていない・決めてほしい・選んでほしい・選択肢・ご判断・質問・提案・案〈案件・案内は除く〉・Open questions・Decisions 等）があれば黄。見出しが無ければ、最後のかたまりが「その言葉の行＋番号つきの一覧・表」なら黄。本文の途中だけの言葉・「残ること」「次にすること」の節で終わる返事は待機。迷う時は見出しにあれば黄に倒す（取りこぼしの方が害が大きい） |
| 待機（緑） | 社長と話す所で `idle` になり、問いかけで終わっていない時。最後に動いてから 2 時間まで。社長の番ではない |
| 青（作業中） | `busy`／`shell`（返事の後も裏で命令が動いている）／Codex が作業中 |
| 灰 | 待機のまま 2 時間より前（「しばらく動いていない」）／知らせで動く所の `idle`（社長の番ではない。待機にもしない） |
| 読めない | `status` が無い・知らない値。欄ごとの「読めない」は理由を出す |
| 灰（一時停止中） | プロセスが止めてある（Ctrl-Z 等。`/proc/<番号>/stat` の状態が `T`・`t`）。記録の `status` に関わらず黄にしない。動いている物と同じ会話を持っていれば注意を出す |

- **知らせで動く所**: 部署側のセッション（`TMUX_SESSION`）の全部の窓と、秘書のセッションの `extractor` の窓。チケット・報告の知らせで動くので、手が空いても社長の番ではない。秘書のセッションの `secretariat` の窓（秘書の本体）は社長と話す所。セッション名は**完全一致**で比べる（部署側の名前は秘書の名前の頭と同じなので、頭だけで比べると取り違える）
- **問いかけの見方**: 社長の最後の頼み（「頼んだこと」と同じ物）への最後の返事で見る。自動のターン（`origin` が無いか `human` でない頼み。作業の知らせ等）への返事は飛ばす。`tasks/todo.md` の済・未は色の決め手にしない
- **問いかけの見分け**（`collect.is_question`）: 返事の最後の 1 行の終わり（句点・閉じ括弧・強調の印を外した後）が「？」「?」、「〜ますか・ですか・でしょうか・ませんか・ましょうか・かな」、「教えて・選んで・決めて・答えて・返して＋ください」、「ご判断・ご指示・ご回答・ご返事・ご確認＋を＋ください・お願いします」。迷う物は黄にしない側に倒す
- **並び**: 黄（許可の問い・質問が先）→ 青 → 読めない → 待機 → 灰。同じ色の中では、社長と話す所が知らせで動く所より先。止めてある物は最後
- **名前**: 部署は窓の名前から（`pm` → PM 部 など）、aipair はセッション名から、ほかは作業の場所のフォルダー名

### グループ
- 最初は自動で分ける（`board/groups.py`）。名前を変える・別のグループへ移す（新しいグループも作れる）・畳むことができ、直した分は `prefs.json` に残る
  - **会社**: 作業の場所が会社のルートそのものか、そのすぐ下（部署）の物（aipair を除く）。畳んで始まる
  - **案件 · <上のフォルダー>**: aipair の各案件を、案件のフォルダーの根（会社のルートの 1 つ上）の下の一番上のフォルダーごとに（会社の中は `development/projects` など 2 段）
  - **そのほか**: どれにも当たらない物（tmux の外・Codex だけ 等）
- グループの並び: 黄のあるグループが上（黄の件数の多い順）→ 青のあるグループ → 残り。同じ段の中は、案件（名前の順）→ 作ったグループ → 会社 → そのほか。数えるのは見出しの数と同じ（隠したカードは数えない）
- 並びが変わっても見ている所が飛ばない（下を見ている時は、画面の上から 3 割の所にあるグループの位置を保つ）。並びが変わったグループは、しばらく青い縁取りで知らせる

### 画面の部品
- **絞り込み**: 上の色の数の丸を押すと、その色のカードと、その色があるグループだけを出す（もう一度押すと全部。ブラウザが覚える）
- **カードの ⋯**: グループを移す・表示しない。隠したカードは、上の「隠している」から表示に戻せる。新しく始まったセッションは表示する
- **全文**: 「頼んだこと」と「返事の頭」を押す（か、選んで Enter・Space）と、全文をモーダルで出す。全文は押した時に `GET /text` へ取りに行き、伏せ字を当て、200KB で切る
- **大きさ**: `board/render.py` の CSS の頭の `:root{--scale:1}` の 1 か所で、字・余白・カードの幅が全部変わる（.75 でブラウザを 75% に縮めた時と同じ見え方）。変えたら `stop`・`start` すると、開いているページは自分で読み直す
- 5 秒ごとに新しくする。時刻はその PC の時間帯で出す

### 隠す印
起こし直しても変わらない物を使う（プロセスの番号・会話の ID は使わない）。名前を付けた tmux の窓（部署・秘書室）は `tmux:<セッション名>:<窓の名前>`、名前が自動で変わる窓（aipair）は `tmux:<セッション名>:#<窓の番号>`、tmux の外は `cwd:<作業の場所>`、Codex だけのカードは頭に `codex:`。止めてある物は、後ろに `:stopped:<番号>-<起動の時刻>` を足す。

## 守っていること
- 読む道は `/`・`/cards`・`/board.css`・`/board.js`・`/healthz`・`/favicon.ico`（中身なし）・`/text`（全文）だけ。tmux に文字を送る・ファイルを開く・命令を流す入り口は無い。URL から場所を受け取らない
- `Host` が `127.0.0.1:<番号>`・`localhost:<番号>` 以外の要求は断る（421。DNS rebinding よけ）
- 全文の道（`GET /text`）は、ページだけが付ける `X-Session-Board: 1` が要る（無ければ 403）。項目は `card` と `kind`（prompt・reply）の 2 つだけ、`card` は今のカードの番号（`claude-<pid>`・`codex-<pid>`）だけ。隠す印は同じ場所の 2 つの会話で重なりうるので、全文を選ぶのには使わない
- 書く入り口は `POST /prefs` の 1 つだけ。受け付けるのは、このページからの要求だけ:
  - `Origin` が `http://127.0.0.1:<番号>`・`http://localhost:<番号>`（無い・違えば 403）
  - `Content-Type: application/json`（フォームの形は 415）と `X-Session-Board: 1`（無ければ 403）
  - 中身は 1KB まで（413）。操作ごとに決まった項目だけ。印は今のカードか今隠している物、グループは今ある物だけ（400）
  - グループの名前は 1〜40 字・改行なし。画面に出す時は必ず escape する
  - 数の上限: 隠す 200・移す 300・覚えるグループ 100・作るグループ 30・ファイル 64KB
  - CORS の見出しは返さない（OPTIONS も 405）。ほかの道の POST・PUT 等は 405
  - 書くのは `prefs.json` だけ（一時のファイルに書いてから入れ替える・600）。読めないファイルには書かない（中身を消さない）
- 断った要求は `board.log` に、道・`Host`・`Origin` の頭だけを残す（中身・印は書かない）
- CSP で外の読み込みとページの中に直接書いたスクリプトを止める。文は全部サーバーで escape し、全文は `textContent` で文字のまま出す
- 秘密らしい文字列（よくある形の API の鍵・トークン・秘密鍵・Webhook の URL 等）は伏せてから出す（`board/mask.py`）。当たらない形の鍵は伏せられない
- `~/.claude/sessions/` の `.key` は開かない（`*.json` だけを読む）

## どこから何を読むか
> **注意**: Claude Code の `sessions/*.json` と `projects/*/*.jsonl`、Codex の `rollout-*.jsonl` は、**公開されていない内部の形式**。
> 版が上がると形が変わり、欄が「読めない」になることがある（形が違う時は、空の画面ではなく「読めない」と理由を出す）。
> `waitingFor` の値と意味は Claude Code 2.1.312 の中身から読んだ。

| カードの欄 | 元 |
|---|---|
| 生きているか | `<CLAUDE_CONFIG_DIR>/sessions/<pid>.json` の `procStart` と `/proc/<pid>/stat` の起動の時刻・`pidDomain`（番号の使い回しを外す） |
| 案件の名前・場所 | 同じ記録の `tmux`（「セッション名:@窓.%ペイン」）と `tmux list-panes -a`。aipair はセッション名、部署は窓の名前 |
| 状態の色 | 同じ記録の `status`・`waitingFor`（上の表） |
| 最後に頼んだこと | `<CLAUDE_CONFIG_DIR>/projects/*/<sessionId>.jsonl` の、`origin.kind` が `human` の最後の依頼 |
| 最後の返事の頭 | その依頼の後の、最後の返事の文の頭の 1 行（依頼の後に返事が無ければ「まだ」） |
| 進み具合 | 作業の場所の `tasks/todo.md` の `- [x]`・`- [ ]`・`- [!]` |
| 最後に動いた時刻 | `statusUpdatedAt` と会話の記録の最後の時刻の新しい方 |
| Codex | Codex の本体のプロセス（npm の `@openai/codex` の `codex`）が開いている `<CODEX_HOME>/sessions/…/rollout-*.jsonl` の、最後の `task_started`／`task_complete`。tmux の同じセッションの Claude Code のカードに付ける（無ければ「Codex だけ」のカード） |

## 試験の流し方
```bash
cd tools/session-board
python3 -m unittest tests.test_board                     # 作り物の記録（偽の ~/.claude・/proc・tmux）と本物の HTTP（番号 0）
python3 -m unittest tests.test_board tests.test_browser  # ブラウザでの試しも（Playwright の Chromium。無ければ飛ばす）
```
- 試験は本物の置き場・本物の記録を使わない。設定の環境変数は試験の中で外し、置き場・HOME は一時の場所、`board_ctl.sh` の試しは空いている番号で起こす（Linux 専用）
- `open_board.sh` の試しは作り物の道具だけを置いた `PATH` で流す（本物のブラウザは開かない）

## ディレクトリ構造
```
bin/session-board      起動（serve・check）
board/config.py        設定（環境変数）
board/collect.py       集める（読むだけ）
board/groups.py        グループ（自動の分け方と、直した分を重ねる）
board/prefs.py         画面で直した物を残す（隠す・グループ・畳む）
board/render.py        HTML・CSS・JS（文は全部ここで escape）
board/server.py        待ち受けと書く入り口
board/mask.py          伏せ字
board/demo.py          作り物の中身の見本
tools/board_ctl.sh     起動・停止
tools/open_board.sh    ブラウザで開く
tests/test_board.py    試し（作り物の記録）
tests/test_browser.py  ブラウザでの試し（Playwright。無ければ飛ばす）
```
