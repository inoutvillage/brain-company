---
name: company-setup
description: BrainCompany テンプレートを clone した直後に走らせる初回セットアップウィザード。会社名・CEO ハンドル・プロジェクトパス・事業部・tmux セッション名等を質問形式で対話的に収集し、`.vscode/tasks.json` `CLAUDE.md` `org-chart.md` `ceo-office/profile.md` 等のプレースホルダを一括置換する。最後に VS Code タスク（秘書独立起動 + 全部署一斉起動）の実行手順を案内する。起動例「セットアップして」「初期設定したい」「/company-setup」。冪等（再実行で既設定値を上書き可）。
---

# company-setup スキル

## このスキルの目的

BrainCompany テンプレートを clone した直後の社長が、**1 セッション内の質問応答だけで会社設定を完了**できるようにする。手動で `sed` を打つ・複数ファイルを横断編集する手間を排除する。

最終ゴール: `.vscode/tasks.json` から「🎧【秘書】独立起動」「🏢【tmux】全部署 一斉起動」を押すだけで会社が動き出す状態にする。

---

## 起動方法

- スラッシュ: `/company-setup`
- 自然言語: 「セットアップして」「初期設定したい」「会社の初期化を」「テンプレを自分用にして」

---

## 処理フロー（厳守）

### Step 0. 事前チェック

#### 0-1. プロジェクトルートの確認

`pwd` および以下のファイル存在で BrainCompany ルートか判定:
- `CLAUDE.md`
- `org-chart.md`
- `.vscode/tasks.json`
- `ceo-office/profile.md.example`

いずれか欠ける場合: 「BrainCompany プロジェクトルートで実行してください」と案内して **停止**。

#### 0-2. 既セットアップの検出

以下を順に grep:

```bash
grep -l '<YOUR_PATH>' .vscode/tasks.json
grep -l '<YOUR_COMPANY>' CLAUDE.md
grep -l '<CEO_HANDLE>' CLAUDE.md
grep -l '<YOUR_COMPANY>' org-chart.md
test -f ceo-office/profile.md
```

**全プレースホルダが置換済 + profile.md が存在** → 既セットアップ完了。社長に「既に設定済みです。再セットアップしますか？(yes/no)」と確認。`no` なら停止。`yes` なら続行（値を上書き）。

#### 0-3. プロジェクトパスの自動取得

`pwd` の結果を `<PROJECT_PATH>` として保持。WSL 環境想定（`/mnt/d/...` 形式）。

---

### Step 1. 必須情報の収集

社長に **AskUserQuestion** で 1 問ずつ確認（複数選択肢が無い質問はテキスト入力）:

#### 1-1. 会社名
- 質問: 「会社名を教えてください（例: <YOUR_COMPANY> / 株式会社ABC / 個人事業主の屋号 等）」
- 用途: `<YOUR_COMPANY>` の置換値
- 必須

#### 1-2. CEO ハンドル
- 質問: 「CEO（あなた）のハンドル名を教えてください。社内ドキュメント・SNS で使う名前です。」
- 用途: `<CEO_HANDLE>` の置換値
- 必須

これらの **回答が両方そろうまで Step 2 へ進まない**。

---

### Step 2. プロフィール（任意・スキップ可）

社長に「`ceo-office/profile.md` を今作成しますか？（後でも可）」と確認。

- **スキップ選択時**: profile.md は **作成しない**。「後で `cp ceo-office/profile.md.example ceo-office/profile.md` で雛形を作って手動編集してください」と案内し Step 3 へ。
- **作成選択時**: 以下を順に質問:
  - 本名（読みも）
  - メールアドレス（メイン）
  - GitHub username（`https://github.com/USERNAME`）
  - Git commit identity（`Your Name <email>` 形式、空なら GitHub の値で組み立て）

回答を保持し、**Step 6 で profile.md を生成**する。

---

### Step 3. 事業部の設定

**デフォルトは本体事業 1 つだけ**（`business-unit-1`）。サブブランドや別事業を持つ場合のみ追加。

#### 3-1. 本体事業の名称・内容（必須）

社長に AskUserQuestion で順に確認:
- 「本体事業のブランド名は？（例: <BU1_NAME> / 個人事業の屋号 / 会社名と同じでも可）」
- 「本体事業は何をやっていますか？（1 行で説明）」

回答を `BU1_NAME` / `BU1_DESC` として保持。
→ **Step 6 で必ず適用**: `org-chart.md` / `CLAUDE.md` / profile.md（作成時）の business-unit-1 の表記を更新。

#### 3-2. 追加事業部があるか（任意・デフォルト no）

社長に質問: 「サブブランドや別事業がありますか？追加事業部を設定しますか？」

- **no（デフォルト推奨）**: 本体事業のみで Step 4 へ進む。`marketing/` `accounting/` 配下にサブフォルダは作成しない（出力は直接配置）。
- **yes**: 続けて
  - 「いくつ追加しますか？（1 / 2）」 ← business-unit-1 は本体固定なので追加は最大 2 つ
  - 各追加事業部について順に: 「ブランド名」「事業内容（1 行）」
  - 追加分は `business-unit-2`, `business-unit-3` として割り当て、`BU2_NAME` / `BU2_DESC` …として保持

→ **Step 6 で追加適用**:
- `marketing/` `accounting/` 配下に `business-unit-1/`, `business-unit-2/`, `business-unit-3/` サブフォルダを作成（既存の出力があれば `business-unit-1/` に移動）
- `org-chart.md` の事業部 mermaid に行追加
- `ceo-office/profile.md` の事業部表に行追加
- `CLAUDE.md` の事業部セクションに行追加

---

### Step 4. tmux セッション名（任意）

社長に「tmux セッション名を変えますか？（デフォルト: `brain-company`）」と確認。

- **デフォルトのまま**: 何もしない。
- **変更**: 新しい名前を質問（kebab-case 推奨）。Step 6 で以下を一括置換:
  - `start-agents.sh`, `start-agents-all.sh`, `watcher.sh`
  - `.vscode/tasks.json`（`tmux attach -t brain-company` 等）
  - `.claude/hooks/on-stop.sh`（`SESSION="${TMUX_SESSION:-brain-company}"` のデフォルト値）

---

### Step 5. サマリー確認

ここまで集めた値を**読みやすく整形して社長に提示**:

```
以下の内容で適用します:

【プロジェクトパス】 <PROJECT_PATH>
【会社名】 <YOUR_COMPANY>
【CEOハンドル】 <CEO_HANDLE>

【プロフィール】 作成する
  - 本名: <REAL_NAME> (<よみがな>)
  - メール: example@example.com
  - GitHub: <GITHUB_USERNAME>
  - Git identity: <GITHUB_USERNAME> <example@example.com>

【事業部】
  - business-unit-1 (本体): <BU1_NAME> — 個人開発・コンテンツ制作
  - 追加事業部: なし（必要に応じて後から追加可）

【tmuxセッション名】 brain-company (デフォルト)

【影響を受けるファイル】
  - .vscode/tasks.json (13箇所)
  - CLAUDE.md (5箇所 + 事業部セクション更新)
  - org-chart.md (2箇所 + 事業部 mermaid 更新)
  - ceo-office/profile.md (新規作成)

この内容で適用してよろしいですか？(yes/no/修正したい)
```

- `yes` → Step 6 へ
- `no` → 停止（変更なし）
- `修正したい` → どのステップを直すか質問して該当ステップに戻る

---

### Step 6. 一括適用

#### 6-1. プレースホルダ置換

以下を **`Edit --replace_all` または `sed -i`** で一括置換。`sed` 実行時はバッククォート・特殊文字に注意（値に `&` `/` 等が含まれる場合は別文字 delimiter を使う）:

| ファイル | 置換 |
|---|---|
| `.vscode/tasks.json` | `<YOUR_PATH>` → `<PROJECT_PATH>` |
| `CLAUDE.md` | `<YOUR_COMPANY>` → 会社名、`<CEO_HANDLE>` → CEO ハンドル |
| `org-chart.md` | `<YOUR_COMPANY>` → 会社名、`<CEO_HANDLE>` → CEO ハンドル |

**事業部の更新（Step 3 で必ず取得した本体事業の情報を反映）**:

| ファイル | 更新内容 |
|---|---|
| `CLAUDE.md` 事業部セクション | `business-unit-1` の行を `BU1_NAME — BU1_DESC` に更新 |
| `org-chart.md` 事業部 mermaid | `IOV["🎯 business-unit-1<br/>本体事業"]` を `IOV["🎯 business-unit-1<br/>BU1_NAME"]` に更新 |
| `ceo-office/profile.md`（作成時） | 事業部表の business-unit-1 行を `BU1_NAME / BU1_DESC` で埋める |

**追加事業部がある場合のみ**:
- `marketing/business-unit-1/`, `marketing/business-unit-2/`, `marketing/business-unit-3/` を `mkdir -p` で作成
- `accounting/records/business-unit-1/`, `…business-unit-2/`, `…business-unit-3/` および `accounting/analysis-reports/business-unit-{1,2,3}/`, `accounting/records/all/`, `accounting/analysis-reports/all/` を作成
- `org-chart.md` の事業部 mermaid に追加 BU の行を挿入
- `CLAUDE.md` の事業部セクションに追加 BU の行を挿入
- `ceo-office/profile.md` の事業部表に追加 BU の行を挿入

tmux セッション名変更がある場合のみ追加:
| ファイル | 置換 |
|---|---|
| `start-agents.sh`, `start-agents-all.sh`, `watcher.sh`, `.vscode/tasks.json`, `.claude/hooks/on-stop.sh` | リテラル `brain-company` → 新セッション名 |

#### 6-2. profile.md 生成（作成選択時のみ）

`ceo-office/profile.md.example` を `ceo-office/profile.md` にコピーし、`Edit` で以下を更新:

- 本名フィールド
- メールアドレス
- GitHub URL
- Git commit identity
- 事業部表（事業部設定がある場合）

`profile.md` は `.gitignore` 対象（コミットされない）ので、個人情報を入れて OK。

---

### Step 7. 検証

以下を実行して**全プレースホルダが消えたか確認**:

```bash
grep -rn '<YOUR_PATH>\|<YOUR_COMPANY>\|<CEO_HANDLE>' \
  .vscode/tasks.json CLAUDE.md org-chart.md 2>/dev/null
```

- 出力 0 行 → ✅ 完了
- 何か残っていれば → 該当箇所を表示、社長に確認

`profile.md` の存在確認（作成選択時のみ）:
```bash
test -f ceo-office/profile.md && echo "✓ profile.md created"
```

---

### Step 8. 起動案内（最終ステップ）

社長に **以下のメッセージを表示** して終了:

```
✅ セットアップ完了！

▼ 次にやること（VS Code / AntiGravity 推奨）

1. コマンドパレット (Ctrl+Shift+P) → "Tasks: Run Task" を開く

2. 以下の **2つ** を順に実行:

   ① 🎧【秘書】独立起動（最初にこれ）
      → 専用ターミナルで秘書室の Claude Code セッションが起動。
        社長との対話の主窓口になります。

   ② 🏢【tmux】全部署 一斉起動 & アタッチ（秘書は別途）
      → tmux で 9 ウィンドウ（pm/dev/watcher/extractor/research/
        marketing/accounting/legal/ceo-office/corporate-planning）
        が並列起動 → そのままアタッチ。

3. tmux ウィンドウの切替: Ctrl+b → 数字キー

4. 動作確認:
   - 秘書セッションで「テスト依頼を PM に投げて」と発話
   - watcher が検知 → tmux:pm に通知が飛ぶ

▼ Slack 連携（任意）
docs/SETUP.md §6 を参照（Bot Token 取得 → .mcp.json 作成）。

▼ トラブル
docs/SETUP.md §10 を参照。
```

---

## 注意事項

- **destructive な変更** を含むので、Step 5 の確認なしに Step 6 を実行しない
- `sed` のセパレータは `|` を使う（パスに `/` が含まれるため）
- `<PROJECT_PATH>` に空白や特殊文字が含まれる場合: 警告を出して社長に確認
- 既セットアップの場合: Step 0-2 の確認後、上書き同意を取ってから進む
- `profile.md` 作成スキップ時、Step 8 のメッセージに「後で profile.md を作る場合は…」を含める
- このスキル自体は `secretariat/` 配下のセッションでなくても動く（プロジェクトルート判定で OK）

---

## エラーケース

| 状況 | 対応 |
|---|---|
| プロジェクトルートでない | エラー表示 → 停止 |
| 必須情報が空 | 再質問（最大 3 回まで） |
| `Edit` で `old_string` がマッチしない | 該当ファイルを Read し直して原因調査 → 社長に状況報告 |
| `sed` 失敗 | エラーメッセージを社長に共有 → 手動 `sed` を案内 |
| profile.md 既存 | 「上書きしますか？」と確認、`no` なら skip |

---

## 補足: なぜ AskUserQuestion を使うか

社長の手入力は最小化したい。会社名・ハンドル等の **短い自由記述** は AskUserQuestion の "Other" で受ける。複数選択肢がある質問（追加事業部数 1/2、tmux 名変更 yes/no 等）はラジオボタンで提示。

ただし `AskUserQuestion` は 1 メッセージあたり 4 問までの制限あり。Step ごとに分けて呼ぶ。
