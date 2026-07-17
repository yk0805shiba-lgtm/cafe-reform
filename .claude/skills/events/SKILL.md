---
name: events
description: 店舗周辺イベントを確認し、カフェまたはデリバリーの需要・仕込み・シフト・SNS施策を分析する。ユーザーが /events を明示実行したときに使う。
argument-hint: "[week|weekend|today|tomorrow|YYYY-MM-DD|YYYY-MM-DD to YYYY-MM-DD] [cafe|delivery|all] [store-slug]"
allowed-tools: Bash(python3 market_intelligence/cli.py events query *)
---

# /events スキル — 詳細実装仕様

## ⚠️ 読み取り専用

このスキルは **query のみ** 実行する。以下は絶対に実行しない:

- `events collect` / `events build` / `events sync`
- SNS 投稿・動画生成・広告公開
- Recommendation 承認・CreativeBrief 承認
- 価格変更・営業時間変更
- スタッフへの送信
- `git commit` / `git push`

必要な施策は「提案」として表示するにとどめる。

---

## STEP 1: 引数の解析

`$ARGUMENTS` を空白で分割し、以下の規則で解釈する。

### 日付範囲（第1引数）

| 指定 | 解釈 |
|---|---|
| `today` | 今日 00:00:00〜23:59:59 JST |
| `tomorrow` | 明日 00:00:00〜23:59:59 JST |
| `week` | 当週月曜日 00:00:00〜当週日曜日 23:59:59 JST（過去日も含む。週全体の計画用）|
| `weekend` | 直近の土曜 00:00:00〜日曜 23:59:59 JST（今日が土日なら今週、平日なら次の土日）|
| `YYYY-MM-DD` | 指定日 00:00:00〜23:59:59 JST |
| `YYYY-MM-DD to YYYY-MM-DD` | 指定範囲の開始 00:00:00〜終了 23:59:59 JST |
| 省略時 | `week` と同じ |

**タイムゾーン**: 常に Asia/Tokyo（JST = UTC+9）

**week の定義**: 月曜を週の始まりとする。例: 2026-07-16(木) の "week" は 2026-07-13(月)〜2026-07-19(日)。

**weekend の定義**: 直近の土・日。例: 2026-07-16(木) の "weekend" は 2026-07-18(土)〜2026-07-19(日)。

### 業態フィルタ（第2引数）

| 指定 | 動作 |
|---|---|
| `cafe` | カフェのみ（cafe_01 / business_unit=cafe） |
| `delivery` | デリバリーのみ（delivery_01 / business_unit=delivery） |
| `all` | カフェとデリバリーを別セクションで表示 |
| 省略時 | `all` と同じ |

### 店舗スラッグ（第3引数）

| 指定 | 解釈 |
|---|---|
| `zstea` / `cafe_01` / `cafe01` | --store cafe_01 |
| `delivery_01` / `delivery01` | --store delivery_01 |
| 省略時 | 業態に応じたデフォルト店舗 |

---

## STEP 2: クエリコマンドの構築

### 単一業態の場合（cafe または delivery）

```bash
python3 market_intelligence/cli.py events query \
  --store {store_id} \
  --business-unit {business_unit} \
  --from {from_date} \
  --to {to_date} \
  --json
```

- `store_id`: cafe → `cafe_01`、delivery → `delivery_01`
- `--from` / `--to`: `YYYY-MM-DD` 形式

### "all" の場合（両業態）

2回クエリを実行する:

```bash
# クエリ1: カフェ
python3 market_intelligence/cli.py events query \
  --store cafe_01 --business-unit cafe \
  --from {from_date} --to {to_date} --json

# クエリ2: デリバリー
python3 market_intelligence/cli.py events query \
  --store delivery_01 --business-unit delivery \
  --from {from_date} --to {to_date} --json
```

---

## STEP 3: JSONの解釈

受け取った JSON を解析する。ICS ファイルを直接再パースしない。

### JSON スキーマ

```json
{
  "generated_from": "normalized_event_store",
  "range": { "from": "...", "to": "...", "timezone": "Asia/Tokyo" },
  "store": { "id": "...", "name": "...", "business_unit": "..." },
  "events": [
    {
      "uid": "...",
      "title": "...",
      "starts_at": "2026-07-18T10:30:00+09:00",
      "ends_at": "2026-07-18T13:30:00+09:00",
      "all_day": false,
      "venue_name": "...",
      "address": "...",
      "distance_m": 450,
      "impact_score": 4,
      "impact_reasons": ["distance_lt_1000m:+2", "category_culture:+1", "weekend:+1"],
      "operational_signals": ["pre_event_walk_in", "takeout_opportunity"],
      "category": "culture",
      "source_id": "新宿文化センター",
      "source_url": "https://...",
      "fetched_at": "2026-07-16T17:07:44+09:00",
      "confidence": 0.9,
      "status": "confirmed",
      "cancelled": false,
      "merged_from_source_ids": [],
      "data_warnings": [],
      "expected_audience": null,
      "languages": ["ja"]
    }
  ],
  "warnings": []
}
```

### ソート順

1. `impact_score` 降順（高い方が先）
2. `starts_at` 昇順（日時が近い方が先）
3. `uid` 昇順（同点同日時の場合）

JSON は既にこの順で返ってくる。

### 情報不足の区別

| 状態 | 判断基準 | 表示 |
|---|---|---|
| イベントなし | `events` が空配列 | 「取得データなし（イベント0件）」|
| ソース取得失敗 | `warnings` にエラーメッセージ | 「データ取得に問題がありました」と warnings 表示 |
| source未設定 | `source_id` が空 | 「情報源不明」|
| 古いデータ | `fetched_at` から7日以上 | 「⚠ 取得から{N}日経過」|
| 低信頼度 | `confidence` < 0.9 | 「信頼度: {X}」|
| 住所不明 | `address` が空 | 「住所不明」|
| 距離計算不能 | `distance_m` が null | 「距離不明」|
| 開催確認待ち | `status == "tentative"` | 「⚠ 開催確認待ち」|
| 延期 | `status == "postponed"` | 「⚠ 延期の可能性あり」|
| data_warnings | per-event の品質警告 | 各イベントに表示 |

取得失敗を「イベントなし」と表示しない。

---

## STEP 4: 出力形式

### 基本ヘッダー

```
# イベント概要

対象店舗: {store.name}（{store.id}）
対象業態: {business_unit}
対象期間: {range.from の日付}〜{range.to の日付}（Asia/Tokyo）
イベント件数: {events.length} 件
```

### イベントがない場合

```
# イベント概要
...（ヘッダー）

現在の期間にイベントデータが存在しません。

ヒント:
- データが未収集の場合: python3 market_intelligence/cli.py events collect --no-llm --demo
- 収集後にビルド: python3 market_intelligence/cli.py events build --no-llm
```

warnings がある場合はその内容も表示する。

### 重要イベント（impact_score > 0 のもの、最大5件を詳細表示）

各イベントについて:

```
## [★×N] タイトル

- 日時: YYYY/MM/DD(曜) HH:MM〜HH:MM（または終日）
- 会場: {venue_name}
- 住所: {address}
- 店舗からの距離: {distance_m}m（または「距離不明」）
- カテゴリ: {category}
- impact score: {impact_score}/5
- impact理由: {impact_reasons を日本語で解説}
- operational signals: {operational_signals を日本語で解説}
- 情報源: {source_id}（{source_url があればリンク表示}）
- 取得日時: {fetched_at}
- 信頼度: {confidence}
- 参加想定人数: {expected_audience または「不明」}
- 対応言語: {languages}
- 状態: {status（confirmed=通常、tentative=確認待ち、postponed=延期）}
- ⚠ {data_warnings があれば各行表示}
```

impact_reasons の日本語解説例:
- `distance_lt_500m:+3` → 「店舗から500m以内（+3点）」
- `distance_lt_1000m:+2` → 「店舗から1km以内（+2点）」
- `category_culture:+1` → 「文化系イベント（+1点）」
- `weekend:+1` → 「土日開催（+1点）」

operational_signals の日本語解説例:
- `pre_event_walk_in` → 「イベント前の来店需要」
- `during_event_walk_in` → 「開催中の来店需要」
- `takeout_opportunity` → 「テイクアウト需要」
- `daytime_peak_possible` → 「昼間ピーク発生の可能性」
- `post_event_delivery` → 「イベント後のデリバリー需要」
- `night_delivery_possible` → 「夜間デリバリー需要」

### 想定来客傾向

**事実と推論を必ず分けて表示する。断定しない。**

```
### 事実
- 店舗から{distance_m}mにイベントが開催される
- 開始時刻: {starts_at}、終了時刻: {ends_at}
- {category}系イベント、{weekday}開催
- 想定参加人数: {expected_audience または「不明」}
- 対応言語: {languages}
（JSONに存在する事実のみ記載。存在しないことは書かない）

### 推論
（根拠と不確実性を明示した上で）
- ○○の可能性がある（根拠: ～）
- ○○の需要が増える可能性がある
```

### 業態別示唆

#### カフェ向け（business_unit=cafe または all）

```
### カフェへの示唆

**仕込みで確認すべき項目**
（過去データがない場合は「通常より多め」などの断定をせず「確認すべき項目」として提示）
- 抹茶・牛乳・氷・カップ・テイクアウト包材の在庫確認
- イベント規模・天候によって冷たいドリンク需要が変化する可能性
- スイーツ類（インバウンド客対応の場合はラインナップ確認）

**シフトで検討すべき時間帯**
（人数を自動決定しない。「増員を検討する時間帯」として提示）
- {starts_at の1〜2時間前}: イベント前の来店増加の可能性
- {イベント開催中}: テイクアウト・観光客対応
- {ends_at 前後}: 観光客・インバウンドの来店ピークの可能性
- 外国語対応: {languages に en/zh 等があれば特記}

**SNS企画案**
（商標・ロゴ・主催者画像の無断利用は提案しない）
（情報源の画像を自店広告へ転載する提案は禁止）

- Instagram投稿: ...
- Instagram Stories: ...
- 店頭POP: ...
- Googleビジネスプロフィール: ...

**TikTok Live企画案**（必要な場合）
- 目的: ...
- 対象顧客: ...
- 配信推奨時間: ...
- テーマ: ...
- 冒頭のフック: ...
- 紹介商品: ...
- CTA（行動喚起）: ...
- 必要素材: ...
- イベントとの関連付け方: ...
- 注意事項: ...
```

#### デリバリー向け（business_unit=delivery または all）

```
### デリバリーへの示唆

**仕込みで確認すべき項目**
- 麺・タレ・チャーシュー・温玉・容器の在庫確認
- イベント終了後の注文増加に備えたピーク前仕込みタイミング
- 調理負荷が高い商品の取り扱い確認

**シフトで検討すべき時間帯**
- {ends_at 〜 ends_at +2時間}: イベント終了後の注文増加の可能性
- 夜間ピーク（{operational_signalsにnight_delivery_possibleがあれば特記}）
- 受付停止リスク: 調理能力を超える注文集中の可能性
- 配達遅延リスク: ピーク時間帯の配達エリア混雑

**広告配信候補時間帯**
（提案のみ。実際の設定はオーナーが実施）
- ...
```

### 注意事項（warnings / data_warnings）

```
## 注意事項

- {warnings の内容}
- {取得失敗があれば明記}
- {古いデータがあれば明記}
- {cancelled_count > 0 なら「X件の中止イベントを除外」}
```

---

## STEP 5: "all" 業態の表示

"all" の場合は以下の順で表示する:

```
# イベント概要（全業態）

## カフェ（cafe_01）
{カフェ向けの全セクション}

---

## デリバリー（delivery_01）
{デリバリー向けの全セクション}
```

---

## 実行例

### `/events week`
→ 当週月〜日、cafe と delivery 両方

Bash を2回実行:
1. `python3 market_intelligence/cli.py events query --store cafe_01 --business-unit cafe --from 2026-07-13 --to 2026-07-19 --json`
2. `python3 market_intelligence/cli.py events query --store delivery_01 --business-unit delivery --from 2026-07-13 --to 2026-07-19 --json`

### `/events weekend cafe`
→ 直近の土日、カフェのみ

Bash を1回:
`python3 market_intelligence/cli.py events query --store cafe_01 --business-unit cafe --from 2026-07-18 --to 2026-07-19 --json`

### `/events 2026-07-25 delivery`
→ 指定日、デリバリーのみ

`python3 market_intelligence/cli.py events query --store delivery_01 --business-unit delivery --from 2026-07-25 --to 2026-07-25 --json`

### `/events week cafe zstea`
→ 当週、カフェ、zstea 店舗（= cafe_01）

`python3 market_intelligence/cli.py events query --store cafe_01 --business-unit cafe --from 2026-07-13 --to 2026-07-19 --json`

---

## エラー時の動作

| エラー | 表示 |
|---|---|
| CLI が exit 1 を返す | 「イベントデータの取得に失敗しました。CLIの出力を確認してください: {stderr}」|
| JSON パースエラー | 「JSONの解析に失敗しました。events build を再実行してください」|
| `warnings` に内容あり | 警告として出力末尾に表示 |
| `events` が空 | 「取得データなし（イベント0件）」+ hints 表示 |
| query CLI 自体が存在しない | 「market_intelligence パッケージが見つかりません。pip install -r market_intelligence/requirements.txt を実行してください」|

---

## スキルが実行しないこと（再確認）

```
collect / build / sync / Recommendation承認 / CreativeBrief承認
SNS投稿 / 動画生成 / 広告公開 / 価格変更 / 営業時間変更
スタッフへの送信 / git commit / git push
```
