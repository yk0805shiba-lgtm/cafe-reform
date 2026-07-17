# イベントソース取得可否レジストリ

確認日: 2026-07-16  
担当: cafe-reform market-intelligence

---

## 1. 新宿文化センター (regasu-shinjuku.or.jp)

| 項目 | 内容 |
|------|------|
| source名 | regasu_bunka_center |
| 確認URL | https://www.regasu-shinjuku.or.jp/bunka-center/event-calendar/ |
| 確認日時 | 2026-07-16 |
| **取得可否** | **可** |

### robots.txt
```
Disallow: /bunka-center/wp-admin/
```
`/bunka-center/event-calendar/` への禁止ルールなし。

### 規約の該当箇所
標準的著作権表示のみ。二次利用禁止の明文なし。

### 判断理由
- robots.txtでイベントカレンダーパスへのアクセス禁止がない
- 転載・二次利用を明示的に禁止する規約条項なし
- 内部業務利用（店舗運営判断用）のみで再配布しない用途

### 許容される取得頻度
1日1回まで（1リクエスト/ページで完結）

### 保存可能な項目
- 公演日（日付）
- 開演時間
- 催事名（タイトル）
- 料金
- 会場名（大ホール/小ホール/展示室）
- 住所・座標（固定: 東京都新宿区新宿6-14-1）

### 公開ICSへ含められる項目（制限事項）
内部業務用フィードに限定。外部再配布禁止。公開ICS（`docs/market-intelligence/events/`）への含め方は内部参照のみとし、一般公開するカレンダーには含めないこと。

### 技術メモ
SSL証明書エラーあり。`ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE` を使用して接続。

---

## 2. 新宿御苑・環境省 (env.go.jp)

| 項目 | 内容 |
|------|------|
| source名 | (未実装) |
| 確認URL | https://www.env.go.jp/garden/shinjukugyoen/event/ |
| 確認日時 | 2026-07-16 |
| **取得可否** | **スキップ** |

### robots.txt
```
Disallow: /cgi-bin/
```
イベントページへの禁止ルールなし。

### 規約の該当箇所
PDL1.0（パブリックデータライセンス）。商用利用可、出典記載必要。ライセンス水準は許可範囲。

### スキップ理由
イベントサブページ `/national-garden/shinjukugyoen/event/`、`news/` 等が全て HTTP 404。SPA（シングルページアプリケーション）・クライアントサイドルーティングのため、JavaScriptなしでは取得不可。静的HTTPアクセスでイベントデータを取得できない。

### 将来対応メモ
ライセンスはPDL1.0で問題ない。JS実行環境（Playwrightなど）が整い次第対応可。対応時は出典記載「国土交通省・環境省」が必要。

---

## 3. 伊勢丹新宿店 (isetan.mistore.jp)

| 項目 | 内容 |
|------|------|
| source名 | (未実装) |
| 確認URL | https://www.isetan.mistore.jp/shinjuku/ |
| 確認日時 | 2026-07-16 |
| **取得可否** | **スキップ** |

### robots.txt
event_calendarパスへの禁止なし。

### 規約の該当箇所
規約上の判断が不明確（ブラウザ自動化の許可/不許可が不明示）。

### スキップ理由
イベントデータがJavaScript描画。静的取得ではHTMLが約61,576文字あるが日付データ0件。ブラウザ自動化が必要だが、利用規約上の許可/不許可が明確でなく判断できない。

### 将来対応メモ
利用規約を公式に確認し、ブラウザ自動化許可が得られた場合のみ対応可。

---

## 4. しんじゅくノート (shinjuku.mypl.net)

| 項目 | 内容 |
|------|------|
| source名 | (未実装) |
| 確認URL | https://shinjuku.mypl.net/ |
| 確認日時 | 2026-07-16 |
| **取得可否** | **スキップ** |

### robots.txt
```
Crawl-delay: 90
Allow: /
```

### 規約の該当箇所
二次利用条件が不明確。規約上判断できない。

### スキップ理由
- Crawl-delay 90秒：1ページあたり90秒待機が必要で、複数ページ取得は実用的でない
- 二次利用条件が規約上明確でない

### 将来対応メモ
利用規約が明文化された場合、Crawl-delay遵守の上での対応を検討可。

---

## 実装済みソース一覧（Phase 1-3時点）

| source_type | source名 | ステータス |
|-------------|----------|-----------|
| csv | 手動登録イベント | Phase 1実装済 |
| ical | ICalendarフィード | Phase 1実装済 |
| doorkeeper_api | Doorkeeper新宿 | Phase 2実装済 |
| html_scrape (kanko_shinjuku) | 新宿観光振興協会 | Phase 2実装済 |
| html_scrape (regasu_bunka_center) | 新宿文化センター | Phase 3実装済 |
