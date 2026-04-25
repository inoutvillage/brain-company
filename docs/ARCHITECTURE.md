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

## 3. tmux 多重ウィンドウ運用

### 9ウィンドウ構成
```
0: pm                 ← プロジェクトマネジメント
1: dev                ← 開発
2: watcher            ← ファイル監視デーモン
3: extractor          ← 自動抽出（Stop hook 受信）
4: research
5: marketing
6: accounting
7: legal
8: ceo-office
9: corporate-planning
```

### 秘書室は tmux 外
- 秘書室は社長との対話の主窓口
- VS Code / AntiGravity の独立ターミナルで稼働
- tmux 内に入れると send-keys 通知の受け手になり、対話と通知が混線するため

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
2. `watcher.sh` の WATCH_DIRS に追加
3. `start-agents-all.sh` に window 追加
4. `.vscode/tasks.json` に起動タスク追加

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
