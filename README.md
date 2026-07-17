# カフェ店舗改革プロジェクト

個人経営カフェ（1店舗）の店舗改革を担うインターン生のための作業リポジトリです。

---

## Market Intelligence - イベントカレンダー自動収集

### 公開アクセスについての注意
GitHub Pages で公開される ICS ファイルには、外部の公開イベント情報のみが含まれます。
店舗名・スタッフ個人名・売上データ等の内部情報は一切含まれません。

### ICS 出力先（リポジトリ内パス）

| ファイル | 用途 |
|---|---|
| `docs/market-intelligence/events/all.ics` | 全イベント |
| `docs/market-intelligence/events/cafe.ics` | カフェ営業向け |
| `docs/market-intelligence/events/delivery.ics` | デリバリー向け |
| `docs/market-intelligence/events/cafe_01_cafe.ics` | 店舗 cafe_01（カフェ）|
| `docs/market-intelligence/events/delivery_01_delivery.ics` | 店舗 delivery_01（デリバリー）|

### ICS 購読 URL（GitHub Pages 設定後）

`YOUR_GITHUB_USERNAME` を自分の GitHub ユーザー名に書き換えてください。

**HTTPS URL:**
```
https://YOUR_GITHUB_USERNAME.github.io/cafe-reform/market-intelligence/events/all.ics
https://YOUR_GITHUB_USERNAME.github.io/cafe-reform/market-intelligence/events/cafe.ics
https://YOUR_GITHUB_USERNAME.github.io/cafe-reform/market-intelligence/events/delivery.ics
```

**webcal URL（カレンダーアプリから直接購読）:**
```
webcal://YOUR_GITHUB_USERNAME.github.io/cafe-reform/market-intelligence/events/all.ics
webcal://YOUR_GITHUB_USERNAME.github.io/cafe-reform/market-intelligence/events/cafe.ics
webcal://YOUR_GITHUB_USERNAME.github.io/cafe-reform/market-intelligence/events/delivery.ics
```

### Google カレンダーへの追加方法
1. [Google カレンダー](https://calendar.google.com) を開く
2. 左サイドバーの「他のカレンダー」横の「+」→「URL で追加」
3. 上記 HTTPS URL を貼り付けて「カレンダーを追加」

### Apple カレンダーへの追加方法
1. Apple カレンダーアプリを開き、「ファイル」→「新規カレンダーの購読」
2. 上記 webcal URL を入力（または HTTPS URL でも可）
3. 更新頻度: 毎日 を推奨

### GitHub Pages のセットアップ手順

**Pages の配信方式: GitHub Actions**（branch 方式ではありません）

1. GitHub でこのリポジトリを作成・push 済みであること
2. リポジトリの Settings → Pages
3. **Source: GitHub Actions** を選択して Save
4. ワークフローを初回手動実行すると Pages が有効化されます

> `docs/` をアーティファクトルートとして deploy するため、
> `main /docs` や `main /(root)` ではなく **GitHub Actions** を選択してください。

### ワークフローの手動実行
GitHub Actions → "Update Market Intelligence Events" → "Run workflow"

### ローカルでのビルド手順
```bash
cd /path/to/cafe-reform
pip install -r market_intelligence/requirements.txt
python -m market_intelligence events collect --no-llm
python -m market_intelligence events build --no-llm
```

### ICS 検証ツール
[iCalendar Validator](https://icalendar.org/validator.html) で生成済み ICS を検証できます。

### GitHub Secrets の設定（任意）
店舗プロファイルを GitHub Actions に注入する場合:
1. リポジトリ Settings → Secrets and variables → Actions → New repository secret
2. Name: `STORE_PROFILES_JSON`、Value: `market_intelligence/data/store_profiles.json` の内容（店舗名・住所を含むため取り扱い注意）
3. Name: `MARKET_INTELLIGENCE_CONTACT`、Value: `https://github.com/YOUR_GITHUB_USERNAME/cafe-reform/issues`

Secrets が未設定の場合、ワークフローはデモプロファイルで動作します（店舗名なし）。

---

## Active Mode — 自動収集（現在のモード）

**現在のモード: `active`（2026-07-16 切り替え済み）**

自動 Collector が canonical `event_records` に直接書き込みます。
手動入力機能は引き続き有効です（削除・無効化していません）。

| 役割 | 担当 |
|---|---|
| 自動収集（kanko_shinjuku, doorkeeper, regasu_bunka_center, ical） | canonical に書き込み、Assessment・ICS 生成対象 |
| 手動入力（CSV, manual, 急な変更・補正） | canonical に共存、自動上書きされない |

---

## Source 一時停止と完全削除の違い

| 操作 | コマンド | 保持されるもの | 用途 |
|---|---|---|---|
| **一時停止**（推奨） | `events source pause` | URL・設定・SourceEvidence・取得履歴 | メンテ・障害対応 |
| **完全削除** | store_profile から手動削除 | なし | 恒久的に不要なソース |

**一時停止は設定を削除しません。再開時に同じ URL・設定をそのまま再利用できます。**

```bash
# 特定 source を一時停止（カフェ店舗のみ）
python3 market_intelligence/cli.py events source pause \
  --name "Doorkeeper新宿" --store cafe_01 \
  --reason "APIメンテナンス中" --resume-at 2026-08-01

# 全店舗で停止（--store 省略）
python3 market_intelligence/cli.py events source pause \
  --name "Doorkeeper新宿" --reason "構造変更対応中"

# 再開（元の設定を再利用）
python3 market_intelligence/cli.py events source resume \
  --name "Doorkeeper新宿" --store cafe_01

# 全ソースの状態確認
python3 market_intelligence/cli.py events source status
```

---

## イベント非表示と公式中止の違い

| 状態 | status | visibility | 公開ICS | /events query |
|---|---|---|---|---|
| 通常表示 | confirmed | visible（デフォルト） | ✅ | ✅ |
| **店舗側非表示** | **変更しない** | **hidden** | **❌ 除外** | **❌ 除外** |
| 公式中止 | cancelled | visible | ✅ 含まれる | ❌ 除外 |
| 延期 | postponed | visible | ✅ | ✅（警告付き） |

**`cancelled` は主催者が中止を発表した場合のみ。店舗都合の非表示は `visibility=hidden` を使用。**

```bash
# イベントを非表示にする（status は変更しない）
python3 market_intelligence/cli.py events event hide \
  --id evt_XXXXXXXX --reason "重複登録"

# 再表示する
python3 market_intelligence/cli.py events event show --id evt_XXXXXXXX

# 管理用一覧（非表示を含む）
python3 market_intelligence/cli.py events event list --include-hidden

# query で非表示も確認（管理用）
python3 market_intelligence/cli.py events query \
  --store cafe_01 --from 2026-07-13 --to 2026-07-19 --include-hidden --json
```

### 非表示イベントの公開 ICS・Google Calendar 上の扱い

- **公開 ICS から除外されます。** Google Calendar / Apple Calendar への同期対象外になります。
- **【中止】として表示されません。** ICS に含まれないため、カレンダーアプリ上に一切表示されません。
- 管理者は `events event list --include-hidden` で確認できます。

### 次回自動収集との競合防止

- 自動収集（`events collect`）で同じイベントが取得されても `visibility=hidden` は解除されません。
- 収集は `last_seen_at` と `sequence` のみ更新します。visibility は上書きしません。

---

## Rollback（緊急時の戻し方）

### active → shadow に戻す

```bash
# shadow に戻す（canonical への自動書き込みを停止）
echo "no" | python3 market_intelligence/cli.py events mode set --mode shadow
# または直接
python3 -c "
import sys; sys.path.insert(0, '.')
from market_intelligence.storage import JsonStore
from market_intelligence.events.mode import set_mode
store = JsonStore('market_intelligence/data')
set_mode(store, 'shadow')
print('shadow に戻しました')
"
```

### active → manual-only に戻す（外部ソース完全停止）

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from market_intelligence.storage import JsonStore
from market_intelligence.events.mode import set_mode
store = JsonStore('market_intelligence/data')
set_mode(store, 'manual-only')
print('manual-only に切り替えました')
"
```

### 自動ソースだけを一時停止する方法

1. 店舗プロファイルの `event_sources` から対象ソースを削除 or `enabled: false` を追加
2. 次の collect 実行時から対象ソースはスキップされる
3. 既存の自動イベントは削除されない

### 既存自動イベントを削除せず非表示にする方法

```bash
# 対象イベントの status を cancelled に変更（query/ICS から除外される）
python3 -c "
import sys; sys.path.insert(0, '.')
from market_intelligence.storage import JsonStore
store = JsonStore('market_intelligence/data')
store.update_field('event_records', 'evt_XXXXXXXX', 'status', 'cancelled')
print('非表示にしました（データは残ります）')
"
```

### source 障害時の運用

| 状況 | 動作 | 対処 |
|---|---|---|
| 1ソースが失敗 | 他のソースは正常収集。失敗ソースのエラーが errors に記録 | 次回 collect で自動リトライ |
| 全ソースが失敗 | demo データが fallback として使用される | mode を shadow または manual-only に切り替え |
| 連続失敗 | 既存 event_records は削除されない | shadow に戻して原因調査 |

### 手動入力を継続する方法

mode に関わらず、CSV や manual ソースは常に使用可能です。

```bash
# 手動イベントを CSV から収集
python3 market_intelligence/cli.py events collect --no-llm --store cafe_01
# ↑ store_profile の event_sources に csv タイプが設定されていれば収集される
```

active mode でも manual-only でも手動入力機能は削除・無効化されません。

---

## Shadow Mode（参考）— 切り替え前の検証フロー

Shadow mode は、active 切り替え前に品質を検証するための仕組みです。
現在は active mode のため、shadow sync は参照用です。

### 3つのモード

| モード | 書き込み先 | 用途 |
|---|---|---|
| `shadow`（現在） | `shadow_event_records` | 自動収集の品質検証。canonical は変更しない |
| `active` | `event_records`（canonical） | オーナー承認後に切り替え可能 |
| `manual-only` | なし | 外部ソース障害時の緊急退避 |

**active への切り替えにはオーナーの明示的な承認が必要です。**

### Shadow Sync の実行

```bash
# 自動収集（shadow_event_records に書き込む）
python3 market_intelligence/cli.py events sync --mode shadow --no-llm

# 現在のモード確認
python3 market_intelligence/cli.py events mode show

# Shadow vs Canonical 比較レポート
python3 market_intelligence/cli.py events shadow-report

# ソース取得状況
python3 market_intelligence/cli.py events source-status
```

### 自動収集ソース（AUTO_SOURCE_TYPES）

shadow sync で収集される外部ソース:
- `kanko_shinjuku` — 新宿観光振興協会
- `doorkeeper` — Doorkeeper
- `regasu_bunka_center` — 新宿文化センター
- `ical` — ICalendar URL

CSV 手動入力・デモデータは shadow sync では収集されません（手動ソースは canonical のみ）。

### Shadow Sync 結果（2026-07-16 実行）

| 項目 | 件数 |
|---|---|
| 自動収集（shadow） | 22件新規 |
| 比較範囲 shadow | 19件 |
| 比較範囲 canonical | 26件 |
| マッチ（重複判定一致） | 19件 |
| shadow_only（新規候補） | 0件 |
| canonical_only（手動のみ） | 7件 |

→ 既存の手動データ（[DEMO]データ含む7件）は canonical に保持されています。

---

## /events コマンド — Claude Code でのイベント分析

Claude Code 上で `/events` を実行すると、保存済みのイベントデータを検索し、
カフェ・デリバリーそれぞれの需要予測・仕込み・シフト・SNS施策を分析します。

### /events は読み取り専用

以下は自動実行しません（提案として表示するのみ）:
- SNS 投稿・動画生成・広告公開
- 価格変更・営業時間変更・Recommendation 承認
- `git commit` / `git push`

---

### 利用可能な引数

```
/events [日付範囲] [業態] [店舗]
```

**日付範囲（第1引数）**

| 指定 | 意味 |
|---|---|
| `today` | 今日 |
| `tomorrow` | 明日 |
| `week` | 当週の月〜日（過去日も含む。週全体計画用）|
| `weekend` | 直近の土・日 |
| `2026-07-25` | 指定日のみ |
| `2026-07-20 to 2026-07-26` | 指定期間 |
| 省略時 | `week` と同じ |

**week の定義**: 月曜始まり（例: 木曜に実行 → その週の月〜日）。過去日も含めることで週全体の計画が見渡せます。

**weekend の定義**: 直近の土・日（平日に実行 → 次の土日、土日に実行 → 今週の土日）。

**業態（第2引数）**

| 指定 | 意味 |
|---|---|
| `cafe` | カフェ向けのみ |
| `delivery` | デリバリー向けのみ |
| `all` | カフェとデリバリーを別セクションで表示 |
| 省略時 | `all` と同じ |

**店舗（第3引数）**

| 指定 | 解釈 |
|---|---|
| `zstea` / `cafe_01` | カフェ店舗（cafe_01）|
| `delivery_01` | デリバリー店舗（delivery_01）|
| 省略時 | 業態に応じたデフォルト店舗 |

---

### 利用例

```
/events week
/events week cafe
/events week delivery
/events week all
/events weekend
/events weekend cafe
/events today delivery
/events tomorrow
/events 2026-07-25
/events 2026-07-20 to 2026-07-26
/events week cafe zstea
```

---

### 出力内容

| セクション | 内容 |
|---|---|
| イベント概要 | 対象店舗・業態・期間・件数 |
| 重要イベント | 日時・会場・距離・impact score・理由・signals・情報源・取得日時・信頼度 |
| 想定来客傾向 | **事実**（JSON由来）と**推論**（根拠付き、断定なし）を分離して表示 |
| カフェへの示唆 | 仕込み確認項目・シフト検討時間帯・SNS企画案・TikTok Live案 |
| デリバリーへの示唆 | 仕込み確認項目・シフト検討時間帯・広告配信候補・配達リスク |
| 注意事項 | データ品質警告・中止/延期情報・取得失敗の詳細 |

---

### データ更新タイミング

- 自動更新: 毎朝 06:00 JST（GitHub Actions cron）
- 手動更新: GitHub Actions → "Update Market Intelligence Events" → "Run workflow"
- ローカル更新:
  ```bash
  python3 market_intelligence/cli.py events collect --no-llm
  python3 market_intelligence/cli.py events build --no-llm
  ```

---

### 情報不足時の表示

| 状態 | 表示 |
|---|---|
| イベントなし | 「取得データなし（イベント0件）」+ ヒント |
| ソース取得失敗 | 「データ取得に問題がありました」+ warnings 内容 |
| 距離不明 | 「距離不明」（座標未設定の場合）|
| 信頼度が低い | 各イベントに信頼度を表示 |
| 開催確認待ち | 「⚠ 開催確認待ち（tentative）」|
| 延期の可能性 | 「⚠ 延期の可能性あり（postponed）」|
| データが古い | 「⚠ 取得から N 日経過」|

取得失敗を「イベントなし」と表示しません。

---

### 実際に実行されるクエリ

`/events` が内部で実行するコマンド（例）:

```bash
# /events week cafe の場合
python3 market_intelligence/cli.py events query \
  --store cafe_01 \
  --business-unit cafe \
  --from 2026-07-13 \
  --to 2026-07-19 \
  --json

# /events week all の場合（2回実行して別セクションに表示）
python3 market_intelligence/cli.py events query \
  --store cafe_01 --business-unit cafe \
  --from 2026-07-13 --to 2026-07-19 --json

python3 market_intelligence/cli.py events query \
  --store delivery_01 --business-unit delivery \
  --from 2026-07-13 --to 2026-07-19 --json
```

ICS ファイルをその場でパースすることはしません（JSON のみ使用）。
