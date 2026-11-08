# ARCHITECTURE — 設計思想

本テンプレートの設計判断と理由を解説します。

---

## 1. 中心思想：「秘書室を玄関口」

```
社長
 │ 指示・思考の吐き出し
 ▼
secretariat（秘書室）
 │ 整理・振り分け
 ▼
各専門部署（product-management / research / marketing / accounting / legal / corporate-planning / development）
 │ 処理・成果物
 ▼
secretariat（統合）
 │ 報告
 ▼
社長
```

### なぜ秘書室を玄関口にするか
- 社長の指示は不定形・断片的・矛盾を含むことが多い
- 各部署 AI に直接振っても整理できない
- 秘書室 AI が「受付・整理・振り分け」を1段挟むことで、各部署 AI は specific な依頼に集中できる

### Single Responsibility Principle の応用
- 秘書室: 受付・整理・記録
- PM: プロジェクト管理・調整
- 開発: 実装
- 経営企画: 戦略・統合
- 経理: 数字
- 法務: 法規・労務
- マーケ: 集客
- リサーチ: 調査
- 社長室（ceo-office）: 意思決定の不可逆記録

各部署が一つのことに専念。横断は秘書室 or PM が担う。

---

## 2. 通信モデル：ファイルシステム経由

### なぜ tmux send-keys や API 直結ではなく、ファイル経由か
- **永続化**: 議論・依頼・報告が物理ファイルとして残り、検索・参照可能
- **非同期**: 各部署 AI は独立したタイミングで動作
- **デバッグ可能**: ファイルがある = 通信が成立した、見える状態
- **可逆性**: ファイル削除で「未送信状態」に戻せる

### ファイル種別
| ディレクトリ | 役割 |
|---|---|
| `<dept>/requests/` | この部署への依頼（INBOX） |
| `<dept>/reports/` | この部署の出力（OUTBOX） |
| `secretariat/inbox/` | 秘書室への通知（watcher 経由） |

### watcher.sh の役割
- 5秒おきに各 `requests/` `reports/` を `find -newer` でスキャン
- 新規ファイル検知 → tmux send-keys で関連部署に通知
- `secretariat/inbox/` には watcher が「他部署から報告ファイル来た」を書き出し

### inotify ではなくポーリングな理由
- WSL2 の `/mnt/d/`（DrvFs）では inotify が動作しない
- 5秒間隔のポーリングで実用上問題なし

### debounce（多重通知防止）
- 同一ファイルを短時間に複数回保存（エージェントが反復書込）→ 多重通知になる問題があった
- watcher.sh は **60秒の debounce window** で同一ファイルパスの再処理を抑止
- 環境変数 `DEBOUNCE_WINDOW=30` で調整可

---

## 3. tmux 2 セッション運用

### 部署側セッション `brain-company`（8 ウィンドウ。`start-agents-all.sh`）
```
0: pm                 ← プロジェクトマネジメント
1: dev                ← 開発
2: watcher            ← ファイル監視デーモン
3: research
4: marketing
5: accounting
6: legal
7: corporate-planning
```
- 軽量版 `start-agents.sh` は 0〜2（pm / dev / watcher）だけ
- 社長室（ceo-office）は常駐エージェントを置かない保管ディレクトリなので、window を持たない（`org-chart.md` 参照）

### 秘書室セッション `brain-company-secretariat`（2 ウィンドウ。`start-secretariat.sh`）
```
0: secretariat        ← 秘書本体（社長との対話の主窓口。cwd = secretariat/）
1: extractor          ← /extract-actions の送出先（cwd = ルート）
```
- 秘書室は社長との対話の主窓口なので、部署側とは別のセッションに置く
  - 部署側を止めても・落ちても秘書は生き残る。ターミナルを閉じても文脈が残る
  - watcher.sh は部署側セッションの window 名でしか send-keys しないので、知らせが秘書の対話に割り込まない（秘書への知らせは `secretariat/inbox/` のファイル）
- extractor の cwd はルート。秘書室配下にすると、extractor 自身の終了が SessionEnd hook を再発火させて自己ループする

### セッション名は完全一致（`=名前`）で指す
- tmux は同名のセッションが無いと**前方一致**で探す。部署側が止まっている時に `-t brain-company` と書くと `brain-company-secretariat` に当たり、一斉起動が「起動中」と誤判定したり、停止が秘書を落としたりする
- スクリプトと `.vscode/tasks.json` は `tmux has-session -t =brain-company` のように `=` を付けて指す

### 前の会話から再開して起動する
- 秘書・各部署の claude は `.claude/scripts/claude-role.sh` 経由で起動し、その dir の最新の対話の会話から再開する（`role_resume.py` が選ぶ）
- 会話が無い・ほかの claude が今使っている・記録が読めない時は、新しい会話で起動する（理由を 1 行 `~/.local/state/brain-company/claude-role.log` に残す）
- 「今使っている」は `/proc` で確かめる。`/proc` が無い PC（macOS 等）では確かめられないので、毎回新しい会話で起動する
- 一発の会話（`claude -p`・SDK）は選ばない。白紙で起こすなら `CLAUDE_FRESH=1`、起動の後なら `/clear`
- extractor は再開しない（日ごとの抽出はそれだけで完結し、前の日の文脈は要らない）
- `~/.claude/projects/` と `~/.claude/sessions/` という Claude Code の公開されていない内部形式に頼っている。形式が変わった時は、新しい会話で起動する側に倒れる

### 会話ログからの自動抽出
- 秘書室の会話は hook（`log-user-prompt.sh` / `log-assistant-response.sh`）が `secretariat/memos/YYYY-MM-DD_会話ログ.md` に書く
- extractor 窓に `/extract-actions` を送る経路は 2 つ:
  1. **SessionEnd hook**（`.claude/hooks/on-session-end.sh`）: 秘書のセッションが終わった時
  2. **cron の日次実行**（`.claude/scripts/extract-actions-daily.sh`。任意）: 秘書は常駐してセッションが滅多に終わらないので、こちらが主経路。直近 7 日の未抽出のうち最も古い日を選び、送った後に会話ログの印（`last_extracted_turn`）が進んだかを確かめる
- 送れなかった時・実行された形跡が無い時は、`secretariat/inbox/` に知らせを書く（同じ障害では 1 件だけ）
- extractor が確認の画面で止まっている時は、どちらの経路も送らない（Enter を送ると、既定の「Yes」で確認を通してしまうため）。見分けは `.claude/scripts/extractor_state.py`（Claude Code のセッションの記録の status を読む。2 つの経路で共有）

### セッションの一覧の画面（`tools/session-board/`）
- 動いている Claude Code / Codex のセッションを、ブラウザの 1 枚にカードで並べる（読むだけ・`127.0.0.1` だけで待ち受け）
- `start-agents-all.sh` が起こす。詳細は `tools/session-board/README.md`

### tmux send-keys のクセ対策
- Claude Code TUI は「文字列+Enter」を一度に送ると Enter が改行扱いになる
- watcher.sh は3段階送信:
  1. `tmux send-keys -l "プロンプト"`（リテラル送信）
  2. `sleep 0.3`（UI 取り込み待ち）
  3. `tmux send-keys Enter`（送信トリガー）

---

## 4. CLAUDE.md の階層

```
ルート CLAUDE.md（全社共通ルール）
  ├─ ceo-office/CLAUDE.md（社長室の業務規定）
  ├─ secretariat/CLAUDE.md（秘書室の業務規定）
  ├─ product-management/CLAUDE.md
  ├─ ...
```

### Claude Code 起動時の挙動
- 起動した cwd の親ディレクトリを遡って CLAUDE.md を読む
- 例: `cd secretariat && claude` で起動すると、`secretariat/CLAUDE.md` と ルート `CLAUDE.md` の両方が読み込まれる

### ポインタ化の原則
- CLAUDE.md は **目次＋ポインタ** に徹する
- 詳細ルールは別ファイルに切り出す
- 起動時毎に読まれる → 肥大化はトークン消費に直結

---

## 5. 部署独立性

### 各部署は独立した Claude Code セッション
- 独自の context window を持つ
- 他部署の context を直接共有しない
- 通信は必ずファイル経由（CLAUDE.md でルール明示）

### サブエージェント vs メインエージェント
- 各部署はメインエージェント（独立セッション）
- 必要時のみ Agent ツール（Explore / general-purpose 等）でサブエージェント起動
- 例：リサーチ部が複数視点の調査を並列実行する時にサブエージェントを多重起動

### 利点
- context 汚染を防げる
- 部署独立で stall や api error が連鎖しない
- 並列処理可能

### 欠点
- 部署間の context 共有はファイル経由のみ
- 「秘書室がさっき言った話」を他部署が知らない

---

## 6. 不可逆記録：decisions/

### `ceo-office/decisions/YYYY-MM-DD_件名.md`
- 重要な意思決定をここに記録
- **追記のみ、書き換え禁止**
- 後の判断の整合性チェック・履歴追跡に使う

---

## 7. 自己改善ループ：tasks/lessons.md

### 使い方
- 社長から修正・指摘があれば即座に lessons.md に追記
- 次回以降の起動時、Claude が lessons.md を読んで同じ失敗を回避
- 成功パターンも記録（再現性確保）

---

## 8. 拡張性

### 部署追加
1. 新規ディレクトリ + CLAUDE.md
2. `watcher.sh` の WATCH_DIRS と `process_file` の case に追加
3. `start-agents-all.sh` に window 追加（`$CLAUDE_CMD` で起動し、`-t "=$SESSION:"` で指す）
4. `.vscode/tasks.json` に個別起動タスク追加（`.claude/scripts/claude-role.sh` 経由）

### 事業部別管理
- 経理・マーケのように事業部ごとに `business-unit-1/` `business-unit-2/` 等のサブフォルダ
- 全社集計は `all/` 配下

### Slack / GitHub / Notion 連携
- MCP 経由で外部サービス連携可能
- `.mcp.json` に複数の MCP サーバーを設定

---

## 9. セキュリティ

### .gitignore で機密データを完全除外
- contracts/, decisions/, profile.md, .mcp.json は git 管理外
- `git add -A` 系の使用は注意（誤コミット防止）

### 推奨 git 運用
- `git status` で確認 → `git add <specific files>` で1ファイルずつ追加
- pre-commit hook で機密 grep を入れる（オプション）

---

## 10. 限界

### このシステムの限界
- 秘書室の認知負荷が高い（最初の振り分けでミスると下流が混乱）
- 部署間で同期が必要な情報は、ファイル経由が遅い
- 大規模化（10部署以上）するとオーケストレーションが複雑化
- Claude Code の API コストが線形に増える

### 適合スケール
- 1人社長 + 5-10部署
- 月数万円〜数十万円の API 予算
- 個人事業 / 小規模法人

---

質問があれば issue へ。
