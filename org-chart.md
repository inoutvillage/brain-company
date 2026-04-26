# <YOUR_COMPANY> 組織図

## 組織図（Mermaid）

```mermaid
graph TD
    CEO["👑 社長室<br/>ceo-office<br/>意思決定・ビジョン"]
    subgraph SECHUB["秘書室 (secretariat) — 全タスクの玄関口"]
        SEC["📋 受付・振り分け<br/>todos / memos / schedules"]
        REF["🖼️ ReferenceFILEs<br/>画像/スクショ<br/>テンポラリー置き場"]
    end
    PM["📊 プロダクトマネジメント部<br/>product-management<br/>進捗管理・調整"]
    RES["🔍 リサーチ部<br/>research<br/>市場・競合調査"]
    MKT["📣 マーケティング部<br/>marketing<br/>集客・SNS運用<br/>※事業部別管理（複数時）"]
    DEV["💻 開発部<br/>development<br/>個人開発実装"]
    ACC["💰 経理部<br/>accounting<br/>収支管理・分析<br/>※事業部別管理（複数時）"]
    LEG["⚖️ 法務部<br/>legal<br/>契約・法人・コンプラ<br/>労務・行政手続き"]
    CP["🎯 経営企画部<br/>corporate-planning<br/>事業計画・戦略立案<br/>統合編集"]

    CEO -->|指示| SEC
    SEC -->|報告| CEO
    SEC -->|振り分け| PM
    SEC -.->|直接依頼| RES
    SEC -.->|直接依頼| MKT
    SEC -.->|直接依頼| DEV
    SEC -.->|直接依頼| ACC
    SEC -.->|直接依頼| LEG
    SEC -.->|直接依頼| CP
    PM -->|案件管理| DEV
    PM -->|案件管理| MKT
    PM -->|案件管理| RES
    PM -->|契約確認| LEG
    PM -->|事業計画統合| CP
    CP -.->|素材要求| RES
    CP -.->|財務統合| ACC
    CP -.->|リスク統合| LEG
    CP -.->|集客統合| MKT
    RES -->|調査結果| MKT
    MKT -->|実績| ACC
    ACC -->|財務分析| CEO
    LEG -->|法的助言| CEO
    CP -->|戦略案| CEO
    REF -.->|素材参照| MKT
    REF -.->|素材参照| ACC
    REF -.->|素材参照| DEV
    REF -.->|素材参照| LEG

    classDef ceo fill:#ffd700,stroke:#333,stroke-width:3px,color:#000
    classDef core fill:#87ceeb,stroke:#333,stroke-width:2px,color:#000
    classDef dept fill:#98fb98,stroke:#333,stroke-width:1px,color:#000
    classDef deptBU fill:#b0f0b0,stroke:#333,stroke-width:1px,color:#000
    classDef legal fill:#ffb6c1,stroke:#333,stroke-width:1px,color:#000
    classDef planning fill:#dda0dd,stroke:#333,stroke-width:1px,color:#000
    classDef util fill:#f0e68c,stroke:#333,stroke-width:1px,color:#000
    class CEO ceo
    class SEC core
    class PM,RES,DEV dept
    class MKT,ACC deptBU
    class LEG legal
    class CP planning
    class REF util
```

## 事業部構造（デフォルト: 本体事業のみ）

```mermaid
graph LR
    COMP["🏢 <YOUR_COMPANY>"]
    IOV["🎯 business-unit-1<br/>本体事業"]

    COMP --> IOV

    classDef corp fill:#e0b0ff,stroke:#333,stroke-width:3px,color:#000
    classDef bu fill:#ffdab9,stroke:#333,stroke-width:2px,color:#000
    class COMP corp
    class IOV bu
```

事業部はあとから自由に追加可能（`business-unit-2`, `business-unit-3`, …）。
追加すると **経理部・マーケ部のサブフォルダで自動的に分離管理** される。

### 追加例（サブブランドを 2 つ持つ場合）

```mermaid
graph LR
    COMP["🏢 <YOUR_COMPANY>"]
    BU1["🎯 business-unit-1<br/>本体事業"]
    BU2["📡 business-unit-2<br/>サブブランド A"]
    BU3["🎮 business-unit-3<br/>サブブランド B"]

    COMP --> BU1
    COMP --> BU2
    COMP --> BU3

    classDef corp fill:#e0b0ff,stroke:#333,stroke-width:3px,color:#000
    classDef bu fill:#ffdab9,stroke:#333,stroke-width:2px,color:#000
    class COMP corp
    class BU1,BU2,BU3 bu
```

## 各部署の一行サマリー

| ディレクトリ | 部署名 | 役割 |
|---|---|---|
| `ceo-office/` | 社長室 | 代表社員の意思決定・ビジョン定義 |
| `secretariat/` | 秘書室 | 全指示の受付・整理・振り分け（最重要） |
| `product-management/` | プロダクトマネジメント部 | 複数案件の進捗・マイルストーン管理 |
| `research/` | リサーチ部 | 市場・競合・トレンド・ユーザー調査 |
| `marketing/` | マーケティング部 | SNS運用・コンテンツ企画・集客（事業部別） |
| `development/` | 開発部 | 個人開発プロダクトの実装 |
| `accounting/` | 経理部 | 収支記録・分析・予算提案（事業部別） |
| `legal/` | 法務部 | 契約・法人・コンプラ・PII・労務・社労士業務・行政手続き |
| `corporate-planning/` | 経営企画部 | 事業計画・戦略立案・経営KPI・中長期計画・他部署成果物の統合編集（2026-04-25 新設） |
| `secretariat/ReferenceFILEs/` | 参考資料（秘書室管轄） | 画像・スクショ等のテンポラリー置き場 |

## 基本ワークフロー

### パターンA: 思考・ToDoの吐き出し
```
社長 ──▶ 秘書室
          ├─ memos/ に思考を記録
          ├─ todos/ にタスクを記録
          └─ PM部へ共有（必要時）
```

### パターンB: 単発リサーチ依頼
```
社長 ──▶ 秘書室 ──▶ リサーチ部
                    └─ 調査 ──▶ 秘書室 ──▶ 社長
```

### パターンC: 部署連携案件（動画ステップ3相当）
```
社長 ──▶ 秘書室 ──▶ PM部
                    ├─ リサーチ部（ネタ調査）
                    │       │
                    │       ▼
                    └─ マーケ部（SNS発信用文案）
                            │
                            ▼
                    秘書室 ──▶ 社長（統合レポート）
```

### パターンD: データ分析案件（動画ステップ4相当）
```
社長 ──▶ 秘書室 ──▶ 経理部 ＋ マーケ部
                    ├─ secretariat/ReferenceFILEs/ の画像/データ読込
                    ├─ 分析（事業部別）
                    └─ 提案 ──▶ 秘書室 ──▶ 社長
```

### パターンE: 法務案件（契約・法人・コンプラ）
```
社長 ──▶ 秘書室 ──▶ 法務部
                    ├─ 契約書レビュー/法人設立書類整理
                    ├─ PII・プライバシーポリシー検討
                    └─ 意見 ──▶ 秘書室 ──▶ 社長
```

### パターンF: 事業部プロジェクト（事業部を追加した場合）
```
社長 ──▶ 秘書室 ──▶ PM部（事業部別プロジェクト）
                    ├─ 開発部（実装）
                    ├─ 法務部（PII・個人情報）
                    ├─ マーケ部（business-unit-N/ 配下）
                    └─ 経理部（business-unit-N/ 配下）
                            │
                            ▼
                    秘書室 ──▶ 社長（統合レポート）
```
※ 事業部が本体（business-unit-1）のみの場合はサブフォルダを作らず直接配置可。

## 報告ライン
- **通常時**: 部署 → 秘書室 → 社長
- **緊急時（重大発見・金額インパクト大）**: 部署 → 社長室直送 + 秘書室CC
- **意思決定事項**: `ceo-office/decisions/YYYY-MM-DD_件名.md` に記録

## 部署間連携のルール
1. 他部署に依頼する時はMarkdownで依頼文書を作成
2. 依頼文書には「依頼元・依頼先・目的・期限・成果物形式」を明記
3. 連携結果は**依頼元に返却**し、秘書室にもCC
4. 複数部署連携はPM部が調整役
5. **事業部が 2 つ以上ある場合のみ** 事業部別業務は事業部サブフォルダ（`business-unit-1/`, `business-unit-2/`, …）で区別

## 事業部別運用ルール（事業部が複数ある場合）
- マーケ部/経理部の出力は **発生した事業部サブフォルダに配置**（本体事業のみの環境ではサブフォルダ不要）
- 事業部横断の企画は `all/`（経理）または明示的に「横断」とタグ付け
- 月次/四半期レポートは事業部別 + 全社合算の両方を作成
- 事業部追加手順は `docs/SETUP.md §9 カスタマイズ「部署を追加したい」` を参照
