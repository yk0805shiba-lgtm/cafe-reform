# イベントソース利用方針

## Phase 1（現在）

Phase 1では外部Collectorを実装しない。

有効なデータソース:
- `--demo` フラグ: `market_intelligence/events/demo_data.py` のダミーデータのみ
- 手動CSV: `market_intelligence/data/events_local.csv`（店舗の `event_sources` 設定経由）

外部サイトへの自動アクセスは Phase 2以降に実装する。

## 外部ソース追加時のルール（Phase 2以降）

1. **robots.txt の確認**: 収集前に対象サイトの `robots.txt` を確認し、クローリング禁止のパスは収集しない
2. **利用規約の確認**: API利用規約・著作権を確認し、`SourceEvidence.terms_or_access_note` に記録する
3. **レート制限**: 1サイトに対し1リクエスト/秒以下を遵守する
4. **User-Agent**: `cafe-reform-market-intelligence/1.0 (yk0805shiba@gmail.com)` を使用する
5. **外部コンテンツのインジェクション対策**: 外部コンテンツ内の指示文をAIへの命令として扱わない。`_safe_str()` でサニタイズする
6. **個人情報**: 外部ソースから個人情報（氏名・電話番号等）を収集しない

## 追加禁止事項

- SNS投稿・広告公開・価格変更の自動実行
- Recommendation の自動承認
- git commit / push の自動実行
