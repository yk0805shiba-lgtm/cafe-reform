# Local Market Intelligence

新宿エリアの近隣イベントを収集し、ICSカレンダーとして公開するPython CLIツール。

## 概要

- イベントソース: Doorkeeper / 新宿観光振興協会 / 新宿文化センター / デモデータ
- GitHub Actions で毎朝自動収集 → GitHub Pages に ICS を公開
- Google Calendar API は使用しない（ICS 購読方式）
- データは `market_intelligence/data/`（gitignore）に保存

---

## StoreProfile JSON スキーマ

`STORE_PROFILES_JSON` Secret（または `market_intelligence/data/store_profiles.json`）は **list-of-dicts** 形式で記述します。

```json
[
  {
    "id": "cafe_01",
    "name": "店舗名",
    "business_unit": "cafe",
    "address": "東京都新宿区...",
    "latitude": 35.6918,
    "longitude": 139.7044,
    "search_radius_km": 1.0,
    "timezone": "Asia/Tokyo",
    "languages": ["ja"],
    "event_sources": [...],
    "opening_hours": {"open": "09:00", "close": "21:00"},
    "enabled": true
  }
]
```

### 必須フィールド
| フィールド | 型 | 説明 |
|---|---|---|
| `id` | string | ストアID（一意） |
| `business_unit` | string | `"cafe"` / `"delivery"` / `"both"` |
| `latitude` / `longitude` | float | 座標（`lat`/`lon` は使わない） |
| `event_sources` | list | イベントソース設定（list-of-dicts） |

---

## event_sources フォーマット

`event_sources` は **list-of-dicts** 形式。文字列リストは不可（バリデーションエラーになる）。

```json
"event_sources": [
  {"type": "kanko_shinjuku", "name": "新宿観光振興協会", "enabled": true, "max_pages": 3},
  {"type": "doorkeeper", "name": "Doorkeeper新宿", "enabled": true, "keyword": "新宿"},
  {"type": "regasu_bunka_center", "name": "新宿文化センター", "enabled": true},
  {"type": "demo", "name": "デモイベント", "enabled": true}
]
```

### 対応 source type
| type | 説明 |
|---|---|
| `kanko_shinjuku` | 新宿観光振興協会 |
| `doorkeeper` | Doorkeeper API |
| `regasu_bunka_center` | 新宿文化センター（Regasu） |
| `demo` | デモデータ（テスト用） |
| `csv` | CSVファイル |
| `ical` | iCal URL |
| `manual` | 手動入力 |

---

## Secret 未設定時のデモ Fallback

`STORE_PROFILES_JSON` Secret が未設定の場合、GitHub Actions は自動的にデモプロファイルを生成します。

```yaml
- name: Prepare StoreProfile config
  run: |
    if [ -n "$STORE_PROFILES_JSON" ]; then
      echo "$STORE_PROFILES_JSON" > market_intelligence/data/store_profiles.json
    else
      python3 market_intelligence/cli.py events config create-demo \
        --output market_intelligence/data/store_profiles.json
    fi
```

デモプロファイルは `cafe_01`（cafe）と `delivery_01`（delivery）の2店舗分を含みます。

---

## 設定の検証

```bash
# デモプロファイルを生成
python3 market_intelligence/cli.py events config create-demo --output /tmp/store_profiles.json

# スキーマ検証
python3 market_intelligence/cli.py events config validate --file /tmp/store_profiles.json
```

不正な形式（dict-keyed、文字列 event_sources など）は明確なエラーメッセージが表示されます。

---

## 設定の優先順位

1. `STORE_PROFILES_JSON` Secret → `market_intelligence/data/store_profiles.json` に書き込む
2. Secret 未設定 → `events config create-demo` でデモプロファイルを生成
3. `market_intelligence/overrides/operational_overrides.json` を読み込んで source/event の状態を上書き

---

## operational_overrides.json

**ファイル:** `market_intelligence/overrides/operational_overrides.json`
**git管理:** 対象（gitignore しない）

source の pause/resume とイベントの hide/show の状態を永続化します。
GitHub Actions の runs 間でも状態が引き継がれます。

```json
{
  "schema_version": 1,
  "source_overrides": [],
  "event_visibility_overrides": []
}
```

### source pause/resume

```bash
# pause（設定は削除しない。planned_resume_at は自動再開しない、メモのみ）
python3 market_intelligence/cli.py events source pause \
  --name "Doorkeeper新宿" --store cafe_01 \
  --reason "API制限" --planned-resume-at 2026-08-01

# resume
python3 market_intelligence/cli.py events source resume \
  --name "Doorkeeper新宿" --store cafe_01

# 状態確認
python3 market_intelligence/cli.py events source status
```

**重要:** `planned_resume_at` は自動再開しません。メモ用のフィールドです。
Actions に反映させるには **commit → push** が必要です。

### event hide/show

```bash
# イベントを非表示（visibility=hidden。status=cancelled とは別）
python3 market_intelligence/cli.py events event hide --id evt_xxxxxxxx --reason "季節外れ"

# 再表示
python3 market_intelligence/cli.py events event show --id evt_xxxxxxxx
```

**重要:** hide/show の状態を Actions に反映させるには **commit → push** が必要です。

---

## canonical_events.json（canonical snapshot）

**ファイル:** `state/canonical_events.json`（プロジェクトルート）
**git管理:** 対象（gitignore しない）

source 障害時の前回正常データを保持します。
- 成功した source → 今回の取得結果を使用
- 失敗した source → 前回 snapshot のイベントを保持
- 全 source 失敗 + snapshot あり → snapshot を返す（errors あり）
- 全 source 失敗 + snapshot なし → 空 + errors

snapshot は `events sync` 実行後に自動更新されます。

---

## 収集モード

| モード | 説明 |
|---|---|
| `shadow` | 自動収集 → `shadow_event_records`（canonical に影響しない） |
| `active` | 自動収集 → `event_records`（canonical）。オーナーの承認が必要 |
| `manual-only` | 手動入力のみ使用。外部 source 障害時の緊急退避 |

現在はデフォルト `shadow` のみ有効。

```bash
python3 market_intelligence/cli.py events mode show
python3 market_intelligence/cli.py events mode set --mode shadow
```

---

## GitHub Actions ワークフロー

毎日 06:00 JST（21:00 UTC）に自動実行されます。

1. `events config create-demo`（Secret 未設定時）または Secret を注入
2. `events config validate` でスキーマ検証
3. `events sync --no-llm` でイベント収集
4. `events build --no-llm` で ICS 生成
5. ICS バリデーション
6. `docs/market-intelligence/`、`state/canonical_events.json`、`overrides/operational_overrides.json` を commit → push
7. GitHub Pages に deploy

---

## ICS 購読 URL

GitHub Pages が公開された後、以下の URL で ICS を購読できます。

```
https://{username}.github.io/cafe-reform/market-intelligence/events/all.ics
https://{username}.github.io/cafe-reform/market-intelligence/events/cafe.ics
https://{username}.github.io/cafe-reform/market-intelligence/events/delivery.ics
```

**注意:** GitHub Pages のリポジトリは公開（public）である必要があります。

---

## 主要 CLI コマンド一覧

```bash
# イベント収集
python3 market_intelligence/cli.py events collect --no-llm --demo

# ICS 生成
python3 market_intelligence/cli.py events build --no-llm

# イベント一覧（JSONで）
python3 market_intelligence/cli.py events query --store cafe_01 --json

# shadow sync（GitHub Actions と同じ）
python3 market_intelligence/cli.py events sync --no-llm

# source 状態確認
python3 market_intelligence/cli.py events source status

# デモ設定生成
python3 market_intelligence/cli.py events config create-demo

# 設定バリデーション
python3 market_intelligence/cli.py events config validate --file path/to/store_profiles.json
```

---

## テスト

```bash
python -m pytest market_intelligence/tests/ -q --tb=short
```
