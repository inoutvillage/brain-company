# SETUP — セットアップ手順

このドキュメントでは、本テンプレートを clone してから自分の AI 会社として動かすまでの手順を説明します。

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

### 任意（あると便利）
- Node.js 18+（Slack MCP 連携時）
- VS Code / AntiGravity（GUI で tmux 管理）
- Python 3.8+（hooks スクリプト用）

---

## 1. リポジトリ取得

```bash
git clone https://github.com/YOUR_USERNAME/your-company-template.git my-company
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

デフォルトは `your-company`。変えたい場合:

```bash
# .bashrc または .zshrc に追加
export TMUX_SESSION="my-business"
```

または `start-agents-all.sh` 実行時に環境変数で指定:
```bash
TMUX_SESSION=my-business ./start-agents-all.sh
```

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

### 全部署 tmux 一括起動
```bash
./start-agents-all.sh
tmux attach -t your-company  # または $TMUX_SESSION
```

これで 9 ウィンドウ（pm/dev/watcher/extractor/research/marketing/accounting/legal/ceo-office/corporate-planning）が立ち上がります。

### 秘書室は別ターミナルで独立起動
```bash
cd secretariat
claude --dangerously-skip-permissions
```

理由: 秘書室は社長の対話の主窓口なので、AntiGravity / VS Code の独立ターミナルで運用するのが推奨。

---

## 8. 動作確認

### 8-1. watcher.sh の確認
tmux の `watcher` ウィンドウに以下が表示されているか:
```
[watcher] start polling (...)
[watcher] tmux session target: your-company
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
- `watcher.sh` の `WATCH_DIRS` に追加
- `start-agents-all.sh` に新しい window を追加
- `.vscode/tasks.json` に起動タスク追加

### 部署を減らしたい
- 該当ディレクトリを削除（または使わないだけでも可）
- watcher.sh / start-agents-all.sh を該当部分削除

---

## 10. トラブルシューティング

### Q. tmux 起動しない
- `tmux` コマンドが install されているか確認
- 既存セッションがないか: `tmux ls`
- 既にあれば: `tmux kill-session -t your-company`

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
