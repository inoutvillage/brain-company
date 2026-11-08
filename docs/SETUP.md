# SETUP — セットアップ手順

このドキュメントでは、本テンプレートを clone してから自分の AI 会社として動かすまでの手順を説明します。

---

## 💡 推奨: `/company-setup` スキルで対話的に完了

§2〜§5（パス置換・CLAUDE.md パーソナライズ・profile.md 作成・tmux セッション名）は、対話型スキル `/company-setup` で **質問形式に答えるだけで完了** します。

```bash
cd my-company
claude --dangerously-skip-permissions
```

セッション内で:
```
/company-setup
```

ウィザードが順に質問:
1. 会社名・CEO ハンドル（必須）
2. プロフィール作成（任意: 本名・メール・GitHub）
3. 事業部設定（任意: 1〜3 ブランド）
4. tmux セッション名（任意: デフォルト `brain-company`）
5. サマリー確認 → 一括適用 → 検証 → 起動案内

完了後、VS Code タスク（🚀【一斉】起動 & アタッチ）の手順が表示されます。

> Slack や Google カレンダー等の **API キーが必要な連携** はこのスキルでは扱いません。`§6 Slack 連携` を別途参照してください。
>
> 「ウィザードを使わず手動で全部やりたい」場合は §0 から順に進めてください。

---

## 0. 前提環境

### 推奨 OS
- **WSL2 (Ubuntu / AlmaLinux 等) on Windows 10/11** ← 開発元の検証環境
- macOS (Apple Silicon / Intel)
- Linux (Ubuntu / Debian / RHEL系)

### 必須ツール
| ツール | バージョン | 確認 |
|---|---|---|
| Claude Code CLI | 最新 | `claude --version` |
| tmux | 3.0+ | `tmux -V` |
| bash | 4.0+ | `bash --version` |
| git | 2.0+ | `git --version` |
| jq | 1.6+ | `jq --version`（hook が Claude Code からの入力を読むのに使う） |
| GNU date | — | `date --version`（hook が時刻を書くのに使う。macOS の date は形が違う） |

### 任意（あると便利）
- Node.js 18+（Slack MCP 連携時）
- VS Code / AntiGravity（GUI で tmux 管理）
- Python 3.9+（前の会話からの再開・日次の自動抽出・セッションの一覧の画面が使う。無ければ再開せず毎回新しい会話で起動する）

### Linux / WSL2 だけで動くもの
- 日次の自動抽出（`.claude/scripts/extract-actions-daily.sh`）と、セッションの一覧の画面（`tools/session-board/`）は `/proc` と GNU の `date` を使うため、macOS では動きません
- 前の会話からの再開も `/proc` で「その会話がほかで使用中か」を確かめます。`/proc` が無い PC では確かめられないので、混ざらないよう毎回新しい会話で起動します

---

## 1. リポジトリ取得

```bash
git clone https://github.com/YOUR_USERNAME/brain-company.git my-company
cd my-company
```

ディレクトリ名は自由に変えて OK（例: `my-business`, `acme-corp` 等）。

---

## 2. パスの置換（必須）

`.vscode/tasks.json` 内の `<YOUR_PATH>` を実際のフルパスに一括置換します。

### WSL2 の例
```bash
# my-company が /mnt/d/projects/my-company にある場合
sed -i 's|<YOUR_PATH>|/mnt/d/projects/my-company|g' .vscode/tasks.json
```

### macOS / Linux の例
```bash
sed -i '' 's|<YOUR_PATH>|/Users/yourname/projects/my-company|g' .vscode/tasks.json
```

### 確認
```bash
grep '<YOUR_PATH>' .vscode/tasks.json
# → 何も出なければ置換完了
```

---

## 3. CLAUDE.md のパーソナライズ

ルートの `CLAUDE.md` を開き、以下のプレースホルダーを置換:

| プレースホルダ | 置換例 |
|---|---|
| `<YOUR_COMPANY>` | あなたの会社名（例: <YOUR_COMPANY>） |
| `<CEO_HANDLE>` | 社長のハンドル名 |

事業部が3つない・名前が違う場合は、CLAUDE.md と `org-chart.md` を編集してください。

---

## 4. 社長プロフィール作成

```bash
cp ceo-office/profile.md.example ceo-office/profile.md
# profile.md を編集して個人情報を記入
```

`profile.md` は `.gitignore` で除外されているので、コミットされません。

---

## 5. tmux セッション名（任意）

デフォルトは `brain-company`（部署側）。秘書室のセッションは、その後ろに `-secretariat` を付けた名前（`brain-company-secretariat`）になります。

変える時は `/company-setup` の Step 4 で答えるのが確実です（スクリプト・`.vscode/tasks.json`・hook・cron 用スクリプトの既定値をまとめて書き換えます）。

一時的に変えるだけなら環境変数でも指定できます:
```bash
TMUX_SESSION=my-business ./start-secretariat.sh --no-attach
TMUX_SESSION=my-business ./start-agents-all.sh
```
ただし環境変数は、tmux の窓の中の hook や cron には届かないことがあります。常用するなら `/company-setup` で既定値を書き換えてください。

---

## 6. Slack 連携（任意）

Slack を使わない場合はスキップ。

### 6-1. Slack App 作成
1. https://api.slack.com/apps → "Create New App" → "From scratch"
2. App Name 設定、Workspace 選択
3. **OAuth & Permissions** → Bot Token Scopes に以下を追加:
   - `chat:write`
   - `chat:write.public`
   - `channels:read`
   - `channels:history`
   - `groups:read`
   - `groups:write`
   - `groups:history`
   - `users:read`
   - `canvases:read`
   - `canvases:write`
   - `files:write`
   - `pins:write`
   - `bookmarks:write`
   - `reactions:read`
   - `reactions:write`
4. Install to Workspace → Bot User OAuth Token (`xoxb-...`) をコピー
5. Team ID を取得（任意のチャンネル URL から `T...` 部分）

### 6-2. .mcp.json 設定
```bash
cp .mcp.json.example .mcp.json
# .mcp.json を編集
# SLACK_BOT_TOKEN: xoxb-... に置換
# SLACK_TEAM_ID: T... に置換
```

### 6-3. MCP 接続確認
```bash
claude mcp list
# slack: ... ✓ Connected と表示されればOK
```

---

## 7. 初回起動

### 秘書室 → 全部署 の順に起動
```bash
./start-secretariat.sh --no-attach   # 秘書室の専用セッション（secretariat / extractor の 2 窓）
./start-agents-all.sh                # 部署側のセッション（8 窓）＋ セッションの一覧の画面
tmux attach -t =brain-company-secretariat   # 秘書に接続（= は完全一致の指定）
```

VS Code なら `.vscode/tasks.json` の「🚀【一斉】起動 & アタッチ」で同じことができます。

- 部署側 `brain-company`: pm / dev / watcher / research / marketing / accounting / legal / corporate-planning の 8 窓。部署の窓を見るなら `tmux attach -t =brain-company`
- 秘書室 `brain-company-secretariat`: secretariat（秘書本体）/ extractor（自動抽出の送出先）の 2 窓
- 社長室（ceo-office）は常駐エージェントを置かない（記録の保管場所。必要な時だけ「社長室: Claude Code 起動（個別）」）
- 止める: VS Code の「🛑【一斉】停止」、または `tmux kill-session -t =brain-company; tmux kill-session -t =brain-company-secretariat`

理由: 秘書室は社長の対話の主窓口なので、部署側と分けて常駐させる。部署側を止めても秘書は生き残り、ターミナルを閉じても文脈が残る。

### 前の会話から再開する
秘書・各部署は、その dir の最新の対話の会話から再開して起動します（`.claude/scripts/claude-role.sh`）。
- 白紙で起こす: `CLAUDE_FRESH=1 ./start-agents-all.sh`（秘書なら `CLAUDE_FRESH=1 ./start-secretariat.sh`）。起動の後なら `/clear`
- 選んだ結果は `~/.local/state/brain-company/claude-role.log` に 1 行ずつ残る
- 🚨 秘書室・各部署の dir と、会社のフォルダーの一番上（extractor）で、一発の `claude`・`claude -p` を走らせない（次の再開で拾われる）。要る時は `--no-session-persistence` を付けるか、別の dir で

---

## 7.5 日次の自動抽出（任意・Linux / WSL2）

秘書室は常駐してセッションが滅多に終わらないため、セッション終了の hook だけでは会話ログからの抽出（`/extract-actions`）が実質止まります。cron で毎日送るには:

```bash
# 1. 有効化（既定は停止。止まっている間は何もしない）
echo active > .claude/extract-cron.state

# 2. 試し: 対象の日を決めるだけで送らない
.claude/scripts/extract-actions-daily.sh --dry-run

# 3. crontab に 1 行（毎日 05:00 JST。パスは自分の会社のフォルダーに置き換える）
crontab -e
# 0 5 * * * TZ=Asia/Tokyo /path/to/my-company/.claude/scripts/extract-actions-daily.sh >> /tmp/extract-actions-daily.log 2>&1
```

- 直近 7 日の未抽出のうち最も古い日を選んで、秘書室セッションの extractor 窓へ送ります。送った後、会話ログの印が進んだかを確かめます
- 送れなかった時（extractor が無い・確認の画面で止まっている等）や、2 回続けて実行の形跡が無い時は `secretariat/inbox/` に知らせを書きます
- 実行の記録: `secretariat/logs/extract-stop.log`

## 7.6 セッションの一覧の画面（任意・Linux / WSL2）

`start-agents-all.sh` が自動で起こします（`http://127.0.0.1:18790/`）。VS Code なら「📋【一覧】セッションの一覧の画面をブラウザで開く」。
手で操作するなら `tools/session-board/tools/board_ctl.sh start|status|stop`。詳細は `tools/session-board/README.md`。

---

## 8. 動作確認

### 8-1. watcher.sh の確認
tmux の `watcher` ウィンドウに以下が表示されているか:
```
[watcher] start polling (...)
[watcher] tmux session target: brain-company
```

### 8-2. 部署間通信テスト
1. `secretariat` で「テスト依頼を PM に投げて」と社長として指示
2. 秘書室が `product-management/requests/2026-XX-XX_test.md` を配置
3. watcher が検知 → tmux:pm に通知が送信される
4. PM 部署が反応・処理

---

## 9. カスタマイズ

### 各部署の役割を変えたい
- `<dept>/CLAUDE.md` を編集

### 部署を追加したい
- 新規ディレクトリを作成 + `CLAUDE.md` を配置
- `watcher.sh` の `WATCH_DIRS` と `process_file` の case に追加
- `start-agents-all.sh` に新しい window を追加（`$CLAUDE_CMD` で起動）
- `.vscode/tasks.json` に個別起動タスク追加（`.claude/scripts/claude-role.sh` 経由）

### 部署を減らしたい
- 該当ディレクトリを削除（または使わないだけでも可）
- watcher.sh / start-agents-all.sh を該当部分削除

---

## 10. トラブルシューティング

### Q. tmux 起動しない
- `tmux` コマンドが install されているか確認
- 既存セッションがないか: `tmux ls`
- 既にあれば: `tmux kill-session -t =brain-company`（秘書室は `=brain-company-secretariat`。`=` を付けないと、前方一致で別のセッションを落とすことがある）

### Q. 会話ログからの自動抽出が動かない
- `secretariat/inbox/` に「extractor送出失敗」の知らせが無いか
- extractor 窓があるか: `tmux list-windows -t =brain-company-secretariat`。無ければ `./start-secretariat.sh --no-attach`（秘書を落とさずに補完）
- cron を使っているなら `.claude/extract-cron.state` が `active` か、`secretariat/logs/extract-stop.log` に何が残っているか

### Q. claude コマンドが見つからない
- Claude Code CLI を [公式](https://claude.com/claude-code) からインストール
- `which claude` でパス確認

### Q. watcher が動作しない
- WSL の `/mnt/d/` 上では inotify が動かないので、本テンプレートはポーリング方式
- 5秒間隔で `find -newer` 実行
- 古い watcher プロセスが残っていないか: `ps aux | grep watcher.sh`

### Q. Slack に投稿されない
- スコープが揃っているか `claude mcp list` で確認
- Bot がチャンネルに招待されているか
- private channel なら `groups:write` が必要

---

## 次のステップ

- [ARCHITECTURE.md](ARCHITECTURE.md) で設計思想を理解
- [EXAMPLES.md](EXAMPLES.md) で具体的な使い方を確認
- 自社の実プロジェクトを `product-management/projects/` 配下に配置開始

---

質問があれば issue へ。
