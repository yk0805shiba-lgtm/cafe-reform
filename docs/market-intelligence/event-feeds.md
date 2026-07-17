# イベントICSフィード（Phase 1）

## 概要

店舗周辺イベントをICS（iCalendar）形式で出力する機能。
カレンダーアプリで購読して、シフト・仕込み・SNS施策を計画するために使う。

Phase 1では外部Collectorなし。手動CSVとdemoデータのみ有効。

## ICSファイル一覧

生成場所: `docs/market-intelligence/events/`

| ファイル名 | 内容 |
|---|---|
| `cafe.ics` | カフェ業態（全店舗） |
| `delivery.ics` | デリバリー業態（全店舗） |
| `all.ics` | 全業態・全店舗 |
| `cafe_01_cafe.ics` | cafe_01 カフェ |
| `cafe_01_delivery.ics` | cafe_01 デリバリー |
| `delivery_01_delivery.ics` | delivery_01 デリバリー |

impact score（0-5）に応じて SUMMARY に ★ が付く。

## CLIコマンド

```bash
# スキーマ初期化（初回のみ）
python3 market_intelligence/cli.py init

# デモデータで収集（APIキー不要）
python3 market_intelligence/cli.py events collect --demo --no-llm

# ICS生成
python3 market_intelligence/cli.py events build --no-llm

# イベント一覧をJSON確認
python3 market_intelligence/cli.py events query --store cafe_01 --business-unit cafe --json

# イベント一覧をテキスト確認
python3 market_intelligence/cli.py events query --store cafe_01 --business-unit cafe

# 特定期間で絞り込み
python3 market_intelligence/cli.py events query --store cafe_01 --from 2026-07-20 --to 2026-07-26 --json
```

## デモ実行手順

```bash
cd /home/yuki/projects/cafe-reform

# 1. 依存確認
pip install -r market_intelligence/requirements.txt

# 2. 初期化
python3 market_intelligence/cli.py init

# 3. デモデータで収集
python3 market_intelligence/cli.py events collect --demo --no-llm

# 4. ICS生成
python3 market_intelligence/cli.py events build --no-llm

# 5. 確認
python3 market_intelligence/cli.py events query --store cafe_01 --business-unit cafe --json

# 6. ローカルHTTP配信（別ターミナルで）
python3 -m http.server 8000 --directory docs
# → http://localhost:8000/market-intelligence/events/cafe.ics
```

## ICSの内容

各VEVENTに以下を含む:

- `SUMMARY`: `★★★ イベント名`（impact score分の★）
- `DTSTART` / `DTEND`: JSTタイムゾーン付き
- `LOCATION`: 会場名 + 住所
- `DESCRIPTION`: 説明・情報源・Impact・Signals・注意書き
- `X-IMPACT-SCORE`: 0-5
- `X-IMPACT-REASONS`: スコア内訳
- `X-OPERATIONAL-SIGNALS`: 店舗向けシグナル（pre_event_walk_in等）
- `X-DISTANCE-M`: 店舗からの直線距離（メートル）

## 注意

- 需要増加は予測であり保証ではありません
- 中止・延期は公式サイトで要確認
- デモデータは実在するイベントではありません
