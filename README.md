# Brain Company — AI Organization Template

Claude Code 上で動く **AI 社員擬似会社** のテンプレート。
一人社長の業務を AI チームに委任し、複数の AI エージェントが部署として協働する仕組み。



---

## 🎯 何ができるか

- **9 部署 × 独立 AI エージェント** が並列稼働
- **秘書室を玄関口** に、社長の指示を構造化・部署別に振り分け
- **watcher.sh** がファイル監視して部署間の依頼・報告を tmux 経由で自動配信
- **各種 MCP 連携**（Slack / Google Calendar / Gmail 等）で更に便利に拡張可能
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

### 1. clone
```bash
git clone https://github.com/inoutvillage/brain-company.git my-company
cd my-company
```

### 2. 初期セットアップ

> 💡 **推奨: `/company-setup` スキルで対話的に完了**
>
> ```bash
> claude --dangerously-skip-permissions
> ```
> セッション内で `/company-setup` と入力するだけで、会社名・CEO ハンドル・事業部・tmux セッション名等を質問形式で答えていくと、以下が自動生成されます:
> - `.vscode/tasks.json` の `<YOUR_PATH>` 一括置換
> - `CLAUDE.md` `org-chart.md` の会社名・CEO ハンドル置換
> - `ceo-office/profile.md` 生成（任意・個人情報入力時のみ）
>
> 最後に VS Code タスク（秘書独立起動 + 全部署一斉起動）の手順案内まで自動。
> Slack 連携など API キーが必要なものは `docs/SETUP.md §6` を参照。

#### 手動でセットアップする場合
```bash
# .vscode/tasks.json の <YOUR_PATH> を実パスに置換
sed -i "s|<YOUR_PATH>|$(pwd)|g" .vscode/tasks.json

# 社長プロフィールを作成（git管理外）
cp ceo-office/profile.md.example ceo-office/profile.md

# Slack や MCP 連携設定のベースを作成
cp .mcp.json.example .mcp.json
```

詳細は [docs/SETUP.md](docs/SETUP.md)。

#### 外部連携（Slack・Googleカレンダー等）
Claude Pro等のサブスクリプション環境を利用している場合、基本的には **Claude.ai（Web版）の設定画面（Integrations）から各サービスを連携するだけ**で、Claude Code (CLI) にも自動的に連携が反映されます（`.mcp.json` の設定は不要です）。

※ ローカルで個別にMCP連携を管理したい場合のみ、以下を参考に `.mcp.json` へ追記してください。

**Slack 手動設定例**
`.mcp.json` に Slack Bot Token などを直接設定します。

**Google カレンダー 手動設定例**
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

> ⚠️ **`--dangerously-skip-permissions` フラグについて**
>
> このフラグは Claude Code に対して **ファイル読み書き・コマンド実行の都度承認をスキップ** させ、対話速度を大幅に上げるため、本テンプレート（複数部署エージェントが頻繁にファイル操作する設計）では **推奨** しています。
>
> ただし以下の挙動上のリスクがあるため、**運用時は留意** してください:
>
> - **AI が機密ファイルを誤って Read / Edit する可能性**（軽減策: `.claude/settings.json` の `permissions.deny` で `.env` `secrets/**` `~/.ssh/**` 等を明示的にブロック済、本テンプレ既設）
> - **AI が破壊的コマンド (`rm -rf`, `git push --force` 等) を独自判断で実行する可能性**（軽減策: 同 `permissions.deny` で `rm -rf /*` `dd` `mkfs` 等のパターンをブロック済）
> - **本番環境・公開サーバ等のクリティカル環境では使用禁止**。本テンプレは個人開発・小規模チームのローカル / 開発機運用を前提
>
> 不安な場合は `--dangerously-skip-permissions` を外して通常モードで起動し、各操作を都度承認する運用も可能です（速度は落ちますが安全性は最大）。詳細は `docs/SETUP.md` の「権限設定」を参照。

詳細セットアップは [docs/SETUP.md](docs/SETUP.md)。

### 💡 推奨設定: Remote Control を有効化

秘書室は社長の対話の主窓口として **常時稼働** するエージェントです。本テンプレートを最大限活かすには、**スマホ・外出先からも秘書セッションへ指示が飛ばせる状態** が極めて有用です。

Claude Code の **「Enable Remote Control for all sessions」を `true`** に設定することを **強く推奨** します:

- `/config` コマンドで設定画面を開いて有効化
- または `~/.claude/settings.json` に直接以下を追記:

```json
{
  "remoteControlAtStartup": true
}
```

これにより claude.ai / モバイルアプリから自分のセッションへリモート接続でき、移動中・外出先でも秘書に指示・状況確認が可能になります。**いつでも秘書がそばにいる** という本テンプレートの設計思想と完全に整合する設定です。

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

## 🙏 Credits

Powered by [Claude Code](https://claude.com/claude-code) (Anthropic)
