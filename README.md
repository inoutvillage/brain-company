# Brain Company — AI Organization Template

Claude Code 上で動く **AI 社員擬似会社** のテンプレート。
一人社長の業務を AI チームに委任し、複数の AI エージェントが部署として協働する仕組み。



---

## 🎯 何ができるか

- **9 部署 × 独立 AI エージェント** が並列稼働
- **秘書室を玄関口** に、社長の指示を構造化・部署別に振り分け
- **watcher.sh** がファイル監視して部署間の依頼・報告を tmux 経由で自動配信
- **Slack 連携**（任意）でクライアントとの進捗共有・KPI ダッシュボード
- **再帰的な戦略立案ループ**（サブエージェント多重起動による深掘り分析）

### 部署一覧
- 👑 **ceo-office**: 意思決定・ビジョン
- 📋 **secretariat**: 全タスクの玄関口
- 📊 **product-management**: プロジェクト管理
- 💻 **development**: 個人開発実装
- 🔍 **research**: 市場・競合・トレンド調査
- 📣 **marketing**: SNS・コンテンツ・集客
- 💰 **accounting**: 収支・予算・分析
- ⚖️ **legal**: 契約・法人・PII・コンプラ・労務
- 🎯 **corporate-planning**: 事業計画・戦略立案・統合編集

詳細は `org-chart.md` を参照。

---

## 🚀 Quick Start

### 必要環境
- Linux / macOS / WSL2（推奨）
- [Claude Code CLI](https://claude.com/claude-code) インストール済み
- tmux
- bash 4+

### 1. clone & setup
```bash
git clone https://github.com/mitsubacha/brain-company.git my-company
cd my-company

# パス設定（後述の SETUP.md 参照）
# .vscode/tasks.json の `<YOUR_PATH>` を実パスに置換
```

### 2. 個人情報・外部連携の追加
```bash
# 社長プロフィールを作成（git管理外）
cp ceo-office/profile.md.example ceo-office/profile.md

# Slack や MCP 連携設定のベースを作成
cp .mcp.json.example .mcp.json
```

#### Slack 連携
`.mcp.json` に Slack Bot Token を設定することで連携可能です。

#### Google カレンダー連携
Claude Pro等のサブスクリプション環境では、**Claude.ai（Web版）の設定画面（Integrations）からGoogleアカウントを連携するだけ**で、Claude Code (CLI) にも自動的に連携が引き継がれます（`.mcp.json` の設定は不要です）。

※ ローカルで独自に設定を管理する場合のみ、以下を `.mcp.json` に追記してください。
```json
"google-calendar": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-google-calendar"],
  "env": {
    "GOOGLE_CLIENT_ID": "<YOUR_CLIENT_ID>",
    "GOOGLE_CLIENT_SECRET": "<YOUR_CLIENT_SECRET>",
    "GOOGLE_REFRESH_TOKEN": "<YOUR_REFRESH_TOKEN>"
  }
}
```

### 3. 起動
```bash
# 全部署 tmux 一括起動
./start-agents-all.sh

# 別ターミナルで秘書室を独立起動
cd secretariat && claude --dangerously-skip-permissions
```

詳細セットアップは [docs/SETUP.md](docs/SETUP.md)。

---

## 🏗 アーキテクチャ

- 各部署は独立した Claude Code セッションで稼働
- 部署間通信はファイルシステム経由（`requests/` `reports/`）
- watcher.sh が新規ファイルを検知して関連部署に tmux send-keys で通知
- 秘書室は AntiGravity（VS Code 互換）の独立ターミナル運用

詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 📚 ドキュメント

- [docs/SETUP.md](docs/SETUP.md): セットアップ手順
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): 設計思想
- [docs/EXAMPLES.md](docs/EXAMPLES.md): 使用例

---

## ⚠️ ライセンス・注意事項

- 個人利用・小規模チーム利用を想定
- Claude API/Slack API のコストは利用者負担
- 機密データ（contracts/, decisions/, profile.md など）は **必ず .gitignore に含める**こと（既に設定済）
- 自社の機密情報を誤ってコミットしないよう、push 前に必ず `git status` で確認

---

## 🤝 Contributing

カスタマイズ歓迎。fork して自社用に改造してください。
本テンプレートへのフィードバック・PR は issue 経由で。

---

## 🙏 Credits

Powered by [Claude Code](https://claude.com/claude-code) (Anthropic)
インスピレーション: 「Claude Code Company」動画ワークフロー
