"""
Phase 2 イベントコレクター（Doorkeeper / 新宿観光振興協会）のテスト。
外部HTTPは一切行わず、urllib.request.urlopen をモックして使う。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# プロジェクトルートをパスに追加
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ────────────────────────────────────────────────────────────────
# Doorkeeper アダプターのテスト用ヘルパー
# ────────────────────────────────────────────────────────────────

def _make_doorkeeper_raw(
    event_id: int = 196973,
    title: str = "テストイベント",
    starts_at: str = "2026-07-26T00:30:00.000Z",
    ends_at: str = "2026-07-26T09:30:00.000Z",
    venue_name: str = "株式会社SHIFT 新宿第１オフィス",
    address: str = "〒151-0053 東京都渋谷区代々木3-22-7",
    lat=None,
    lon: float = 139.7047394,
    description: str = "<h2>テスト</h2><p>説明文</p>",
    public_url: str = "https://tocfebc.doorkeeper.jp/events/196973",
    participants: int = 7,
    waitlisted: int = 0,
    ticket_limit: int = 18,
) -> dict:
    return {
        "event": {
            "id": event_id,
            "title": title,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "venue_name": venue_name,
            "address": address,
            "lat": lat,
            "long": lon,
            "description": description,
            "public_url": public_url,
            "participants": participants,
            "waitlisted": waitlisted,
            "ticket_limit": ticket_limit,
            "banner": "https://example.com/banner.png",
        }
    }


def _get_doorkeeper_adapter():
    from market_intelligence.adapters.doorkeeper_adapter import DoorkeeperAdapter
    return DoorkeeperAdapter()


# ────────────────────────────────────────────────────────────────
# 1. Doorkeeper normalize 基本テスト
# ────────────────────────────────────────────────────────────────

def test_doorkeeper_normalize_basic():
    """実データに近い dict を normalize() に渡してフィールドを確認する"""
    adapter = _get_doorkeeper_adapter()
    raw = _make_doorkeeper_raw()
    record, evidence = adapter.normalize(raw)

    assert record.title == "テストイベント"
    assert record.category == "community"
    assert record.external_id == "196973"
    assert record.official_url == "https://tocfebc.doorkeeper.jp/events/196973"
    assert record.status == "confirmed"
    assert record.confidence == 0.95
    assert evidence.source_type == "doorkeeper_api"
    assert evidence.confidence == 0.95


# ────────────────────────────────────────────────────────────────
# 2. UTC→JST 変換テスト
# ────────────────────────────────────────────────────────────────

def test_doorkeeper_utc_to_jst():
    """2026-07-26T00:30:00.000Z は 2026-07-26T09:30:00+09:00 になる"""
    adapter = _get_doorkeeper_adapter()
    raw = _make_doorkeeper_raw(
        starts_at="2026-07-26T00:30:00.000Z",
        ends_at="2026-07-26T09:30:00.000Z",
    )
    record, _ = adapter.normalize(raw)

    assert "2026-07-26" in record.starts_at
    assert "09:30" in record.starts_at
    assert "+09:00" in record.starts_at


# ────────────────────────────────────────────────────────────────
# 3. HTML タグ除去テスト
# ────────────────────────────────────────────────────────────────

def test_doorkeeper_html_stripped():
    """description の HTML タグが除去されること"""
    adapter = _get_doorkeeper_adapter()
    raw = _make_doorkeeper_raw(description="<h2>見出し</h2><p>本文テスト</p>")
    record, _ = adapter.normalize(raw)

    assert "<h2>" not in record.description
    assert "<p>" not in record.description
    assert "見出し" in record.description
    assert "本文テスト" in record.description


# ────────────────────────────────────────────────────────────────
# 4. lat/long が null の場合
# ────────────────────────────────────────────────────────────────

def test_doorkeeper_null_lat_lon():
    """lat/long が null の場合 latitude/longitude が None になる"""
    adapter = _get_doorkeeper_adapter()
    raw = _make_doorkeeper_raw(lat=None, lon=None)
    # lon を None にするためにイベントを直接編集
    raw["event"]["long"] = None
    record, _ = adapter.normalize(raw)

    assert record.latitude is None
    assert record.longitude is None


# ────────────────────────────────────────────────────────────────
# 5-8. estimated_scale テスト
# ────────────────────────────────────────────────────────────────

def test_doorkeeper_scale_small():
    """ticket_limit=18 → estimated_scale='small'"""
    adapter = _get_doorkeeper_adapter()
    raw = _make_doorkeeper_raw(ticket_limit=18)
    record, _ = adapter.normalize(raw)
    assert record.estimated_scale == "small"


def test_doorkeeper_scale_medium():
    """ticket_limit=100 → estimated_scale='medium'"""
    adapter = _get_doorkeeper_adapter()
    raw = _make_doorkeeper_raw(ticket_limit=100)
    record, _ = adapter.normalize(raw)
    assert record.estimated_scale == "medium"


def test_doorkeeper_scale_large():
    """ticket_limit=500 → estimated_scale='large'"""
    adapter = _get_doorkeeper_adapter()
    raw = _make_doorkeeper_raw(ticket_limit=500)
    record, _ = adapter.normalize(raw)
    assert record.estimated_scale == "large"


def test_doorkeeper_scale_unknown():
    """ticket_limit=0 → estimated_scale='unknown'"""
    adapter = _get_doorkeeper_adapter()
    raw = _make_doorkeeper_raw(ticket_limit=0)
    record, _ = adapter.normalize(raw)
    assert record.estimated_scale == "unknown"


# ────────────────────────────────────────────────────────────────
# 新宿観光振興協会アダプターのテスト用ヘルパー
# ────────────────────────────────────────────────────────────────

def _make_kanko_raw(
    title: str = "サラバンジ Music Fes 2026",
    raw_date: str = "2026年7月25日(土)",
    categories: list[str] = None,
    description: str = "新宿エイサーまつりとともに沖縄ポップスで盛り上がろう！",
    url: str = "https://www.kanko-shinjuku.jp/event/history/article_5881.html",
) -> dict:
    return {
        "title": title,
        "raw_date": raw_date,
        "categories": categories if categories is not None else ["エンタメ"],
        "description": description,
        "url": url,
    }


def _get_kanko_adapter():
    from market_intelligence.adapters.kanko_shinjuku_adapter import KankoShinjukuAdapter
    return KankoShinjukuAdapter()


# ────────────────────────────────────────────────────────────────
# 9. 単日日付パース
# ────────────────────────────────────────────────────────────────

def test_kanko_parse_single_date():
    """'2026年7月25日(土)' → starts_at に '2026-07-25' が含まれる"""
    adapter = _get_kanko_adapter()
    raw = _make_kanko_raw(raw_date="2026年7月25日(土)")
    record, _ = adapter.normalize(raw)

    assert "2026-07-25" in record.starts_at
    assert "2026-07-25" in record.ends_at
    # デフォルト開始時刻
    assert "11:00:00" in record.starts_at
    assert "+09:00" in record.starts_at


# ────────────────────────────────────────────────────────────────
# 10. 期間日付パース
# ────────────────────────────────────────────────────────────────

def test_kanko_parse_range_date():
    """'2026年8月29日(土)～30日(日)' → starts_at=Aug 29, ends_at=Aug 30"""
    adapter = _get_kanko_adapter()
    raw = _make_kanko_raw(raw_date="2026年8月29日(土)～30日(日)")
    record, _ = adapter.normalize(raw)

    assert "2026-08-29" in record.starts_at
    assert "2026-08-30" in record.ends_at


# ────────────────────────────────────────────────────────────────
# 11-13. カテゴリマッピングテスト
# ────────────────────────────────────────────────────────────────

def test_kanko_category_festival():
    """['まつり・伝統'] → category='festival'"""
    adapter = _get_kanko_adapter()
    raw = _make_kanko_raw(categories=["まつり・伝統"])
    record, _ = adapter.normalize(raw)
    assert record.category == "festival"


def test_kanko_category_culture():
    """['文化'] → category='culture'"""
    adapter = _get_kanko_adapter()
    raw = _make_kanko_raw(categories=["文化"])
    record, _ = adapter.normalize(raw)
    assert record.category == "culture"


def test_kanko_category_unknown():
    """[] → category='local_event'"""
    adapter = _get_kanko_adapter()
    raw = _make_kanko_raw(categories=[])
    record, _ = adapter.normalize(raw)
    assert record.category == "local_event"


# ────────────────────────────────────────────────────────────────
# 14. normalize() の戻り値型
# ────────────────────────────────────────────────────────────────

def test_kanko_normalize_basic():
    """normalize() が (EventRecord, SourceEvidence) を返すこと"""
    from market_intelligence.models.event_record import EventRecord
    from market_intelligence.models.source_evidence import SourceEvidence

    adapter = _get_kanko_adapter()
    raw = _make_kanko_raw()
    result = adapter.normalize(raw)

    assert isinstance(result, tuple)
    assert len(result) == 2
    record, evidence = result
    assert isinstance(record, EventRecord)
    assert isinstance(evidence, SourceEvidence)
    assert record.title == "サラバンジ Music Fes 2026"
    assert evidence.source_type == "html_scrape"


# ────────────────────────────────────────────────────────────────
# 15. confidence テスト
# ────────────────────────────────────────────────────────────────

def test_kanko_confidence():
    """KankoShinjukuAdapter の confidence は 0.85"""
    adapter = _get_kanko_adapter()
    raw = _make_kanko_raw()
    record, evidence = adapter.normalize(raw)

    assert record.confidence == 0.85
    assert evidence.confidence == 0.85


# ────────────────────────────────────────────────────────────────
# 16. Doorkeeper fetch: 空ページで停止
# ────────────────────────────────────────────────────────────────

def test_doorkeeper_fetch_stops_on_empty():
    """ページが空リストのとき次のページを叩かないこと"""
    from market_intelligence.adapters.doorkeeper_adapter import DoorkeeperAdapter
    adapter = DoorkeeperAdapter()

    call_count = 0

    class _FakeResponse:
        def __init__(self, data):
            self._data = json.dumps(data).encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def _fake_urlopen(req, context=None, timeout=None):
        nonlocal call_count
        call_count += 1
        # 1回目だけデータを返し、2回目以降は空リスト
        if call_count == 1:
            return _FakeResponse([_make_doorkeeper_raw()])
        return _FakeResponse([])

    with patch("market_intelligence.adapters.doorkeeper_adapter.urllib.request.urlopen", side_effect=_fake_urlopen):
        results = adapter.fetch()

    # 1ページ目でデータあり、2ページ目で空 → 2回呼ばれて終了
    assert call_count == 2
    assert len(results) == 1


# ────────────────────────────────────────────────────────────────
# 17. KankoShinjuku fetch: max_pages=2 のとき2ページ分叩く
# ────────────────────────────────────────────────────────────────

def test_kanko_fetch_paginates():
    """max_pages=2 のとき2ページ分のURLを叩くこと"""
    from market_intelligence.adapters.kanko_shinjuku_adapter import KankoShinjukuAdapter
    adapter = KankoShinjukuAdapter(max_pages=2)

    # シンプルなHTMLブロックを返すモックHTTPレスポンス
    _MOCK_HTML = """
<html><body>
<div class="event_pickup_box">
  <ul class="category_block">
    <li class="category_e1">エンタメ</li>
  </ul>
  <h3>テストイベント</h3>
  <div class="schedule_block">2026年8月1日(土)</div>
  <p>説明テキスト</p>
  <div class="parts_button3">
    <a href="https://www.kanko-shinjuku.jp/event/article_001.html">詳しく見る</a>
  </div>
</div>
</body></html>
""".encode("utf-8")

    visited_urls: list[str] = []

    class _FakeResponse:
        def read(self):
            return _MOCK_HTML

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def _fake_urlopen(req, context=None, timeout=None):
        visited_urls.append(req.full_url)
        return _FakeResponse()

    with patch("market_intelligence.adapters.kanko_shinjuku_adapter.urllib.request.urlopen", side_effect=_fake_urlopen):
        with patch("market_intelligence.adapters.kanko_shinjuku_adapter.time.sleep"):  # sleep をスキップ
            results = adapter.fetch()

    # 2ページ分のURLが呼ばれる
    assert len(visited_urls) == 2
    assert "/event/-/index.html" in visited_urls[0]
    assert "/event/-vi-20/index.html" in visited_urls[1]
    # 各ページに1件のイベントがある
    assert len(results) == 2
