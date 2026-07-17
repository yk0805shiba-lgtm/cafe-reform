# Local Market Intelligence

抹茶カフェとデリバリー専門混ぜそば店の両方で利用できる近隣市場インテリジェンス基盤。
2つの業務Agentを共通基盤（`market_intelligence/`）として実装しています。

---

## 機能概要

| Agent | 識別子 | 目的 |
|---|---|---|
| 近隣イベント連動Agent | `local_event_promotion` | 周辺イベント・天気・季節情報を収集し、販促提案・CreativeBriefを生成 |
| 競合モニタリングAgent | `competitor_monitoring` | 競合の公開情報を定期記録し、差分を検知して戦略提案を生成 |

### 対応店舗区分

| 区分 | 説明 |
|---|---|
| `cafe` | 抹茶カフェ（テイクアウト・体験・インバウンド向け提案） |
| `delivery` | デリバリー専門混ぜそば（ピーク・セット・ボリューム訴求向け提案） |
| `both` | 両店舗共通（それぞれ異なる提案を生成） |

---

## アーキテクチャ

```
cafe-reform/
└── market_intelligence/        # 共通基盤
    ├── agents/
    │   ├── local_event_agent.py   # 近隣イベントAgent
    │   └── competitor_agent.py    # 競合モニタリングAgent
    ├── adapters/               # データソースアダプター
    │   ├── base.py             # 共通インターフェース
    │   ├── fixture_adapter.py  # Demoモード用
    │   ├── ical_adapter.py     # ICS/iCalendar
    │   ├── csv_event_adapter.py # CSV
    │   └── manual_adapter.py   # 手動登録
    ├── models/                 # データモデル
    ├── storage/                # JSONファイルベースストレージ
    ├── llm/                    # LLM抽象化（Claude API）
    ├── scoring.py              # 関連度スコアリング
    ├── reports.py              # HTMLレポート生成
    ├── cli.py                  # CLIエントリーポイント
    ├── fixtures/               # デモ用フィクスチャデータ
    ├── scheduler/              # cron設定スクリプト
    ├── tests/                  # テスト
    └── data/                   # 実行時データ（gitignore）
```

### データの流れ

```
外部ソース（ICS/CSV/手動/fixture）
  ↓ Adapter.fetch + normalize
EventRecord + SourceEvidence（JSONファイルに保存）
  ↓ スコアリング（ルールベース）
  ↓ LLMで提案生成（省略可）
Recommendation（draft状態で保存）
  ↓ 承認操作（CLI/手動）
  ↓ CreativeBrief → 既存SNS動画広告生成へ渡す
  ↓ TemporaryPlaybook → 既存マニュアル機能へ渡す
```

---

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip3 install anthropic icalendar requests pytest --break-system-packages
```

### 2. 環境変数の設定（任意）

```bash
cp market_intelligence/.env.example .env
# .envを編集してAPIキーを設定
```

### 3. 初期化（マイグレーション）

```bash
cd ~/projects/cafe-reform
python3 market_intelligence/cli.py init
```

これでJSONスキーマが初期化され、デモ用店舗プロファイルと競合プロファイルが作成されます。

---

## Demo modeの実行方法

APIキーや実店舗情報がなくてもデモデータで全機能を確認できます。

```bash
cd ~/projects/cafe-reform
python3 market_intelligence/cli.py demo
```

デモデータには以下のシナリオが含まれています：
- 花火大会（来場2万人・距離1.8km・外国人来場あり）
- 猛暑日（最高気温35度）
- 雨天予報
- 大型音楽ライブ
- 外国人観光客向けフェスタ
- 競合A：価格変更（1,000円→1,100円）
- 競合B：新セット追加（温玉追い飯セット）
- 競合C：営業時間変更（21時→23時）

> ⚠ DEMOデータはすべて架空です。実在する店舗・競合ではありません。

生成されたHTMLレポートは `docs/market-intelligence-*.html` で確認できます。

---

## 手動実行方法

### 近隣イベントAgentを実行

```bash
# cafeの近隣イベントを更新（90日先まで）
python3 market_intelligence/cli.py event run --store cafe_01

# delivery店舗、30日先まで
python3 market_intelligence/cli.py event run --store delivery_01 --days 30

# 販促カレンダーを表示（30日）
python3 market_intelligence/cli.py event calendar --store cafe_01 --days 30

# cafeフィルター
python3 market_intelligence/cli.py event calendar --store cafe_01 --days 30 --unit cafe
```

### 競合モニタリングAgentを実行

```bash
# 競合モニタリングを実行
python3 market_intelligence/cli.py competitor run --store cafe_01

# 競合一覧
python3 market_intelligence/cli.py competitor list

# 競合を新規登録
python3 market_intelligence/cli.py competitor add
# JSON入力例: {"name":"○○店","business_unit":"delivery","category":"mazesoba","address":"東京都..."}

# 競合の差分を確認
python3 market_intelligence/cli.py competitor diff --id <competitor_id>

# 手動でスナップショットを記録
python3 market_intelligence/cli.py competitor snapshot --id <competitor_id>
```

### 提案の承認・却下

```bash
# 提案一覧（store_id, statusでフィルター可）
python3 market_intelligence/cli.py recommend list --store cafe_01
python3 market_intelligence/cli.py recommend list --store cafe_01 --status draft

# 承認（承認後も外部投稿・価格変更は自動実行されない）
python3 market_intelligence/cli.py recommend approve --id rec_xxxxxxxx --actor "yuki" --comment "コメント"

# 却下
python3 market_intelligence/cli.py recommend reject --id rec_xxxxxxxx --actor "yuki" --comment "理由"
```

### レポート生成

```bash
# HTMLダッシュボードを生成（docs/に保存）
python3 market_intelligence/cli.py report html --store cafe_01
python3 market_intelligence/cli.py report html --store delivery_01

# 実行履歴を確認
python3 market_intelligence/cli.py status
```

---

## 定期実行方法

### cronで自動実行

```bash
# cronを設定（毎日6時：イベント更新、8時：競合更新、9時：レポート生成）
bash market_intelligence/scheduler/cron_setup.sh

# 確認
crontab -l

# 手動で全Agentを実行
bash market_intelligence/scheduler/run_agents.sh

# 特定の店舗・Agentのみ
bash market_intelligence/scheduler/run_agents.sh cafe_01 event
```

---

## イベントソースの登録方法

店舗プロファイルの `event_sources` フィールドに登録します（JSONファイルを直接編集）：

```json
{
  "id": "cafe_01",
  "event_sources": [
    {
      "type": "ical",
      "name": "市区町村公式イベントカレンダー",
      "url": "https://example.com/events.ics"
    },
    {
      "type": "csv",
      "name": "手動登録イベント",
      "path": "/home/yuki/projects/cafe-reform/events.csv"
    }
  ]
}
```

### CSVのフォーマット

```csv
title,starts_at,ends_at,venue_name,address,category,description,official_url,estimated_scale,expected_audience,indoor_or_outdoor,weather_sensitivity
花火大会,2026-08-10T19:00:00+09:00,2026-08-10T20:30:00+09:00,河川敷公園,東京都新宿区,fireworks,恒例の花火大会,https://example.com,large,20000,outdoor,high
```

---

## 競合登録方法

```bash
python3 market_intelligence/cli.py competitor add
```

JSONを入力：
```json
{
  "name": "競合店名",
  "business_unit": "delivery",
  "category": "mazesoba",
  "address": "東京都新宿区○○町1-1",
  "monitoring_enabled": true,
  "monitoring_frequency": "daily",
  "notes": "主要競合。週1回手動スナップショット記録中"
}
```

---

## 承認フロー

```
Agent実行 → Recommendation生成（draft）
  ↓
オーナーまたはインターンが確認
  ↓
CLI/HTMLレポートから承認・却下
  ↓ 承認のみ
SNS動画広告生成（CreativeBrief → tiktok-videos/を参照）
一時運用手順書（TemporaryPlaybook → 手動で活用）
```

**重要:** 承認後も以下は自動実行されません。手動で対応してください。
- SNS投稿
- 価格変更
- メニュー変更
- スタッフへの指示

---

## SNS動画広告生成との連携

近隣イベントAgentは、承認待ちのCreativeBriefを生成します。

```bash
# CreativeBriefの一覧（JSONファイルを直接確認）
cat market_intelligence/data/creative_briefs.json | python3 -m json.tool
```

承認されたCreativeBriefは `tiktok-videos/` の制作ワークフローへ手動で渡します。
将来的な自動連携のために `status: "approved"` フィールドが用意されています。

---

## マニュアル機能との連携

イベント対応の一時運用手順書（TemporaryPlaybook）が生成されます。

```bash
cat market_intelligence/data/temporary_playbooks.json | python3 -m json.tool
```

承認後に `docs/` または既存のマニュアルフォルダへ手動でコピーして活用します。

---

## 環境変数

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `LOCAL_INTELLIGENCE_DEMO_MODE` | `false` | `true`にするとフィクスチャデータで動作 |
| `LOCAL_INTELLIGENCE_ENABLED` | `true` | システム全体の有効/無効 |
| `LOCAL_EVENT_LOOKAHEAD_DAYS` | `90` | 何日先まで見るか |
| `LOCAL_EVENT_DEFAULT_RADIUS_KM` | `3.0` | 検索半径（km） |
| `COMPETITOR_PRICE_CHANGE_HIGH_THRESHOLD` | `10.0` | 価格変更highしきい値（%） |
| `COMPETITOR_PRICE_CHANGE_MEDIUM_THRESHOLD` | `5.0` | 価格変更mediumしきい値（%） |
| `ANTHROPIC_API_KEY` | （なし） | Claude API（なくてもdemoモードで動作） |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | 使用するモデル |

全項目は `market_intelligence/.env.example` を参照。

---

## 本番運用前に必要な設定

以下はコードでは設定できないため、実際の店舗情報を入力してください：

1. **店舗プロファイルの更新**
   - 実際の店舗住所・緯度経度
   - メニュー一覧と価格
   - 正確な営業時間
   - ブランドポジション（他店との差別化）
   - デリバリーエリア

2. **競合登録**
   - 実在する競合店の情報
   - 公式URL・デリバリープラットフォームURL

3. **APIキーの設定（任意だが推奨）**
   - `ANTHROPIC_API_KEY`：LLMによる提案品質向上
   - `WEATHER_API_KEY`：実際の天気予報連携
   - `GEOCODING_API_KEY`：住所から緯度経度を自動計算

4. **イベントソースの登録**
   - 地域の公式ICSカレンダーURL
   - CSVでの手動登録

---

## トラブルシューティング

### `ModuleNotFoundError: No module named 'market_intelligence'`

```bash
cd ~/projects/cafe-reform
python3 market_intelligence/cli.py demo
# ↑ cafe-reform/ ディレクトリから実行してください
```

### LLM機能が動作しない

`ANTHROPIC_API_KEY`が未設定の場合、ルールベースの提案にフォールバックします。
デモモードでの動作確認は可能です。

### 提案が生成されない

関連度スコアが20点未満のイベントはスキップされます。
フィクスチャデータで確認する場合: `python3 market_intelligence/cli.py demo`

---

## 利用規約とスクレイピングに関する注意

- 競合情報の取得は公開情報のみを対象とします
- robots.txtと各サービスの利用規約を必ず確認してください
- Google Maps、各デリバリープラットフォームは正式APIが必要です（未接続）
- SNS（Instagram、TikTok）の自動スクレイピングは行いません
- 取得できない情報は「未取得」として記録し、推測しません

---

## 現在未接続の外部ソース

以下はシステムが対応予定ですが、正式APIの申請・設定が必要です：

| ソース | 状況 | 代替手段 |
|---|---|---|
| 天気予報API | 未設定（providerはnone） | フィクスチャで代替 |
| Google Maps API | 未設定 | 住所・距離は手動設定 |
| 食べログAPI | 非公開のため未対応 | 手動スナップショット |
| Uber Eats API | 非公開のため未対応 | 手動スナップショット |
| Demaecan API | 非公開のため未対応 | 手動スナップショット |
| Instagram API | 申請が必要 | 手動確認 |
| 自治体公式ICS | URLを要設定 | event_sourcesに登録 |
