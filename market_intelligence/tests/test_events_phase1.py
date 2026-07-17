"""
Phase 1 イベントICSフィード機能テスト

テスト項目:
1. 同じ入力でUIDが同じ（uid生成の決定論性）
2. フィールド補完でUIDが変わらない
3. 2回buildしてICS byte列が同じ
4. all-day DTSTART/DTEND（VALUE=DATE, 排他的終了日）
5. timed eventにtimezoneが付く
6. distance計算（既知座標ペア）
7. impact_score（距離・カテゴリ・曜日の組み合わせ）
8. cafe signals（pre_event_walk_in等）
9. delivery signals（post_event_delivery_possible等）
10. SUMMARY に星が付く（impact score=3 → ★★★）
11. GEO プロパティ
12. icalendar ライブラリで再parse可能
13. cafe/delivery/store feedが生成される
14. query JSONが正しい形式で返る
15. LLMモード + APIキーなし → exit code 1
16. --no-llm → APIキーなしで動作
"""
from __future__ import annotations
import os
import sys
import json
import tempfile
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parents[2]


# ─── テスト 1: UID決定論性 ─────────────────────────────────────────────────────

def test_uid_deterministic():
    """同じ入力から常に同じUIDが生成される"""
    from market_intelligence.events.uid import generate_event_uid
    uid1 = generate_event_uid("demo", "新宿花火大会", "2026-08-01", "河川敷公園")
    uid2 = generate_event_uid("demo", "新宿花火大会", "2026-08-01", "河川敷公園")
    assert uid1 == uid2
    assert uid1.endswith("@market-intelligence")
    assert len(uid1) == len("0123456789abcdef") + len("@market-intelligence")


def test_uid_different_for_different_inputs():
    """異なる入力では異なるUIDが生成される"""
    from market_intelligence.events.uid import generate_event_uid
    uid1 = generate_event_uid("demo", "イベントA", "2026-08-01", "会場X")
    uid2 = generate_event_uid("demo", "イベントB", "2026-08-01", "会場X")
    uid3 = generate_event_uid("demo", "イベントA", "2026-08-02", "会場X")
    assert uid1 != uid2
    assert uid1 != uid3


# ─── テスト 2: フィールド補完でUIDが変わらない ────────────────────────────────

def test_uid_stable_after_field_completion():
    """フィールド補完後にUIDを再計算しない"""
    from market_intelligence.events.uid import generate_event_uid

    # 初回生成
    uid = generate_event_uid("demo", "テストイベント", "2026-09-01", "DEMO会場")
    # フィールド補完後も同じ入力なら同じUID
    uid2 = generate_event_uid("demo", "テストイベント", "2026-09-01", "DEMO会場")
    assert uid == uid2

    # 入力が変わっていないのでUIDも変わらない
    # （descriptionやlatなどが追加されても、UIDの入力セットは変わらない）
    uid3 = generate_event_uid("demo", "テストイベント", "2026-09-01T11:00:00+09:00", "DEMO会場")
    # start_date_jstは[:10]を使うのでISOフォーマット違いでも同じ
    assert uid == uid3


# ─── テスト 3: ICS byte列の決定論性 ──────────────────────────────────────────

def test_ics_build_idempotent(tmp_path):
    """同じ入力から2回buildしてbyte列が同じ"""
    from market_intelligence.events.ics_builder import build_ics_feed

    events_with_assessments = [
        {
            "event": {
                "id": "evt_test001",
                "uid": "abcdef1234567890@market-intelligence",
                "title": "テストイベント",
                "description": "テスト用",
                "category": "festival",
                "venue_name": "テスト会場",
                "address": "東京都新宿区",
                "latitude": 35.689,
                "longitude": 139.700,
                "starts_at": "2026-08-15T11:00:00+09:00",
                "ends_at": "2026-08-15T17:00:00+09:00",
                "all_day": False,
                "official_url": "",
                "source_id": "demo",
                "first_seen_at": "2026-07-01T09:00:00+09:00",
                "last_seen_at": "2026-07-01T09:00:00+09:00",
                "sequence": 0,
            },
            "assessment": {
                "impact_score": 3,
                "impact_reasons": ["distance_lt_500m:+3"],
                "operational_signals": ["pre_event_walk_in", "takeout_opportunity"],
                "store_id": "cafe_01",
                "business_unit": "cafe",
                "distance_m": 400,
            },
        }
    ]

    out1 = tmp_path / "test1.ics"
    out2 = tmp_path / "test2.ics"

    build_ics_feed(events_with_assessments, "テストフィード", "cafe_01", "cafe", out1)
    build_ics_feed(events_with_assessments, "テストフィード", "cafe_01", "cafe", out2)

    assert out1.read_bytes() == out2.read_bytes(), "同じ入力からは同じbyte列になるべき"


# ─── テスト 4: all-day DTSTART/DTEND ────────────────────────────────────────

def test_ics_all_day_dtstart_dtend(tmp_path):
    """all-day イベントはVALUE=DATE, 終了は排他的終了日（+1day）"""
    from market_intelligence.events.ics_builder import build_ics_feed
    from icalendar import Calendar

    events_with_assessments = [
        {
            "event": {
                "id": "evt_allday001",
                "uid": "allday001@market-intelligence",
                "title": "終日イベント",
                "description": "",
                "category": "festival",
                "venue_name": "公園",
                "address": "東京都新宿区",
                "latitude": None,
                "longitude": None,
                "starts_at": "2026-09-01",
                "ends_at": "2026-09-01",
                "all_day": True,
                "official_url": "",
                "source_id": "demo",
                "first_seen_at": "2026-07-01T09:00:00+09:00",
                "last_seen_at": "2026-07-01T09:00:00+09:00",
                "sequence": 0,
            },
            "assessment": {
                "impact_score": 1,
                "impact_reasons": [],
                "operational_signals": [],
                "store_id": "cafe_01",
                "business_unit": "cafe",
                "distance_m": None,
            },
        }
    ]

    out = tmp_path / "allday.ics"
    build_ics_feed(events_with_assessments, "テスト", "cafe_01", "cafe", out)

    cal = Calendar.from_ical(out.read_bytes())
    for component in cal.walk():
        if component.name == "VEVENT":
            dtstart = component.get("dtstart")
            dtend = component.get("dtend")
            assert dtstart is not None
            assert dtend is not None
            # VALUE=DATE の確認（datetime ではなく date インスタンス）
            from datetime import date as date_type
            assert isinstance(dtstart.dt, date_type) and not isinstance(dtstart.dt, datetime)
            # 排他的終了日: 開始が9/1なら終了は9/2
            from datetime import date
            assert dtend.dt == date(2026, 9, 2)


# ─── テスト 5: timed eventにtimezoneが付く ───────────────────────────────────

def test_ics_timed_event_has_timezone(tmp_path):
    """timed eventのDTSTARTにタイムゾーン情報が付く"""
    from market_intelligence.events.ics_builder import build_ics_feed
    from icalendar import Calendar

    events_with_assessments = [
        {
            "event": {
                "id": "evt_timed001",
                "uid": "timed001@market-intelligence",
                "title": "時刻指定イベント",
                "description": "",
                "category": "concert",
                "venue_name": "ホール",
                "address": "東京都",
                "latitude": 35.68,
                "longitude": 139.70,
                "starts_at": "2026-08-20T18:00:00+09:00",
                "ends_at": "2026-08-20T20:00:00+09:00",
                "all_day": False,
                "official_url": "",
                "source_id": "demo",
                "first_seen_at": "2026-07-01T09:00:00+09:00",
                "last_seen_at": "2026-07-01T09:00:00+09:00",
                "sequence": 0,
            },
            "assessment": {
                "impact_score": 2,
                "impact_reasons": [],
                "operational_signals": [],
                "store_id": "cafe_01",
                "business_unit": "cafe",
                "distance_m": 800,
            },
        }
    ]

    out = tmp_path / "timed.ics"
    build_ics_feed(events_with_assessments, "テスト", "cafe_01", "cafe", out)

    cal = Calendar.from_ical(out.read_bytes())
    for component in cal.walk():
        if component.name == "VEVENT":
            dtstart = component.get("dtstart")
            assert dtstart is not None
            dt = dtstart.dt
            assert isinstance(dt, datetime)
            assert dt.tzinfo is not None, "timed eventのDTSTARTにtzinfoが必要"


# ─── テスト 6: distance計算 ──────────────────────────────────────────────────

def test_haversine_meters_known_pair():
    """新宿〜渋谷の距離がおおよそ正しい"""
    from market_intelligence.utils import haversine_meters
    # 新宿駅(35.6895, 139.6917) 〜 渋谷駅(35.6585, 139.7013) ≒ 3.7km
    dist = haversine_meters(35.6895, 139.6917, 35.6585, 139.7013)
    assert isinstance(dist, int)
    assert 3000 < dist < 4500, f"期待値3000-4500m、実際: {dist}"


def test_haversine_meters_zero_distance():
    """同一座標は距離0"""
    from market_intelligence.utils import haversine_meters
    assert haversine_meters(35.689, 139.700, 35.689, 139.700) == 0


# ─── テスト 7: impact_score ──────────────────────────────────────────────────

def test_impact_score_near_festival_weekend():
    """500m以内のfestivalで土曜 → score >= 3+2+1 = 6 → clip 5"""
    from market_intelligence.events.impact import compute_impact_score
    # 土曜日を探す
    d = date(2026, 8, 1)
    while d.weekday() != 5:  # 土曜
        d += timedelta(days=1)
    score, reasons = compute_impact_score(400, "festival", d)
    assert score == 5, f"clip後5のはず: score={score}, reasons={reasons}"
    assert "clipped_to_5" in " ".join(reasons) or score == 5


def test_impact_score_far_unknown():
    """2000m以上 + unknownカテゴリ + 平日 → score = 0"""
    from market_intelligence.events.impact import compute_impact_score
    # 平日を探す
    d = date(2026, 8, 3)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    score, reasons = compute_impact_score(3000, "unknown", d)
    assert score == 0, f"score={score}, reasons={reasons}"


def test_impact_score_medium_range():
    """1000m未満 + exhibitionカテゴリ + 平日 → score = 2+1+0 = 3"""
    from market_intelligence.events.impact import compute_impact_score
    d = date(2026, 8, 3)  # 月曜
    while d.weekday() >= 5:
        d += timedelta(days=1)
    score, reasons = compute_impact_score(800, "exhibition", d)
    assert score == 3, f"score={score}, reasons={reasons}"
    assert any("distance_lt_1000m" in r for r in reasons)
    assert any("category_exhibition" in r for r in reasons)


# ─── テスト 8: cafe signals ──────────────────────────────────────────────────

def test_cafe_signal_pre_event_walk_in():
    """イベント開始前1〜3時間が営業時間内 → pre_event_walk_in"""
    from market_intelligence.events.signals import compute_cafe_signals
    # 14:00開始、09:00-21:00営業 → 11:00〜13:00が前走り時間 → 営業時間内
    signals = compute_cafe_signals(
        event_start="2026-08-15T14:00:00+09:00",
        event_end="2026-08-15T18:00:00+09:00",
        store_open="09:00",
        store_close="21:00",
        distance_m=500,
        category="festival",
        languages=["ja"],
    )
    assert "pre_event_walk_in" in signals


def test_cafe_signal_during_event_walk_in():
    """イベント時間が営業時間と60分以上重なる → during_event_walk_in"""
    from market_intelligence.events.signals import compute_cafe_signals
    signals = compute_cafe_signals(
        event_start="2026-08-15T10:00:00+09:00",
        event_end="2026-08-15T15:00:00+09:00",
        store_open="09:00",
        store_close="21:00",
        distance_m=500,
        category="market",
        languages=["ja"],
    )
    assert "during_event_walk_in" in signals


def test_cafe_signal_takeout_opportunity():
    """festival + 1500m未満 → takeout_opportunity"""
    from market_intelligence.events.signals import compute_cafe_signals
    signals = compute_cafe_signals(
        event_start="2026-08-15T11:00:00+09:00",
        event_end="2026-08-15T17:00:00+09:00",
        store_open="09:00",
        store_close="21:00",
        distance_m=1000,
        category="festival",
        languages=["ja"],
    )
    assert "takeout_opportunity" in signals


def test_cafe_signal_inbound():
    """en言語あり → inbound_language_support_possible"""
    from market_intelligence.events.signals import compute_cafe_signals
    signals = compute_cafe_signals(
        event_start="2026-08-15T11:00:00+09:00",
        event_end="2026-08-15T17:00:00+09:00",
        store_open="09:00",
        store_close="21:00",
        distance_m=500,
        category="festival",
        languages=["ja", "en"],
    )
    assert "inbound_language_support_possible" in signals


def test_cafe_signal_daytime_peak():
    """11:00〜17:00にイベントが60分以上重なる → daytime_peak_possible"""
    from market_intelligence.events.signals import compute_cafe_signals
    signals = compute_cafe_signals(
        event_start="2026-08-15T10:00:00+09:00",
        event_end="2026-08-15T16:00:00+09:00",
        store_open="09:00",
        store_close="21:00",
        distance_m=500,
        category="festival",
        languages=["ja"],
    )
    assert "daytime_peak_possible" in signals


# ─── テスト 9: delivery signals ──────────────────────────────────────────────

def test_delivery_signal_post_event():
    """イベント終了がpeak window前後30分以内 → post_event_delivery_possible"""
    from market_intelligence.events.signals import compute_delivery_signals
    signals = compute_delivery_signals(
        event_start="2026-08-15T18:00:00+09:00",
        event_end="2026-08-15T20:30:00+09:00",
        delivery_peak_windows=[{"start": "20:00", "end": "01:00"}],
        distance_m=1000,
        delivery_radius_km=5.0,
        event_lat=35.69,
        event_lon=139.70,
        store_lat=35.689,
        store_lon=139.700,
        category="festival",
    )
    assert "post_event_delivery_possible" in signals


def test_delivery_signal_evening_peak():
    """18:00以降終了 → evening_peak_possible"""
    from market_intelligence.events.signals import compute_delivery_signals
    signals = compute_delivery_signals(
        event_start="2026-08-15T15:00:00+09:00",
        event_end="2026-08-15T19:00:00+09:00",
        delivery_peak_windows=[],
        distance_m=1000,
        delivery_radius_km=5.0,
        event_lat=None,
        event_lon=None,
        store_lat=35.689,
        store_lon=139.700,
        category="concert",
    )
    assert "evening_peak_possible" in signals


def test_delivery_signal_late_event():
    """21:00以降終了 → late_event_end"""
    from market_intelligence.events.signals import compute_delivery_signals
    signals = compute_delivery_signals(
        event_start="2026-08-15T18:00:00+09:00",
        event_end="2026-08-15T22:00:00+09:00",
        delivery_peak_windows=[],
        distance_m=1000,
        delivery_radius_km=5.0,
        event_lat=None,
        event_lon=None,
        store_lat=35.689,
        store_lon=139.700,
        category="concert",
    )
    assert "late_event_end" in signals


def test_delivery_signal_area_overlap():
    """会場が配達圏内 → delivery_area_overlap"""
    from market_intelligence.events.signals import compute_delivery_signals
    # 同一座標ならdistance=0km < delivery_radius_km
    signals = compute_delivery_signals(
        event_start="2026-08-15T18:00:00+09:00",
        event_end="2026-08-15T20:00:00+09:00",
        delivery_peak_windows=[],
        distance_m=0,
        delivery_radius_km=5.0,
        event_lat=35.689,
        event_lon=139.700,
        store_lat=35.689,
        store_lon=139.700,
        category="sports",
    )
    assert "delivery_area_overlap" in signals


# ─── テスト 10: SUMMARY に星が付く ──────────────────────────────────────────

def test_ics_summary_has_stars(tmp_path):
    """impact_score=3 → SUMMARYに★★★が付く"""
    from market_intelligence.events.ics_builder import build_ics_feed
    from icalendar import Calendar

    ev = {
        "id": "evt_star001",
        "uid": "star001@market-intelligence",
        "title": "★テストイベント",
        "description": "",
        "category": "festival",
        "venue_name": "テスト会場",
        "address": "東京都",
        "latitude": None,
        "longitude": None,
        "starts_at": "2026-09-01T11:00:00+09:00",
        "ends_at": "2026-09-01T17:00:00+09:00",
        "all_day": False,
        "official_url": "",
        "source_id": "demo",
        "first_seen_at": "2026-07-01T09:00:00+09:00",
        "last_seen_at": "2026-07-01T09:00:00+09:00",
        "sequence": 0,
    }
    asm = {
        "impact_score": 3,
        "impact_reasons": [],
        "operational_signals": [],
        "store_id": "cafe_01",
        "business_unit": "cafe",
        "distance_m": 400,
    }
    out = tmp_path / "stars.ics"
    build_ics_feed([{"event": ev, "assessment": asm}], "テスト", "cafe_01", "cafe", out)

    cal = Calendar.from_ical(out.read_bytes())
    for component in cal.walk():
        if component.name == "VEVENT":
            summary = str(component.get("summary", ""))
            assert "★★★" in summary, f"★★★が含まれるべき: {summary}"


def test_ics_summary_zero_score_has_hollow_star(tmp_path):
    """impact_score=0 → ☆が付く"""
    from market_intelligence.events.ics_builder import build_ics_feed
    from icalendar import Calendar

    ev = {
        "id": "evt_star002",
        "uid": "star002@market-intelligence",
        "title": "低スコアイベント",
        "description": "",
        "category": "unknown",
        "venue_name": "",
        "address": "",
        "latitude": None,
        "longitude": None,
        "starts_at": "2026-09-10T11:00:00+09:00",
        "ends_at": "2026-09-10T13:00:00+09:00",
        "all_day": False,
        "official_url": "",
        "source_id": "demo",
        "first_seen_at": "2026-07-01T09:00:00+09:00",
        "last_seen_at": "2026-07-01T09:00:00+09:00",
        "sequence": 0,
    }
    asm = {"impact_score": 0, "impact_reasons": [], "operational_signals": [], "store_id": "cafe_01", "business_unit": "cafe", "distance_m": None}
    out = tmp_path / "hollow.ics"
    build_ics_feed([{"event": ev, "assessment": asm}], "テスト", "cafe_01", "cafe", out)

    cal = Calendar.from_ical(out.read_bytes())
    for component in cal.walk():
        if component.name == "VEVENT":
            summary = str(component.get("summary", ""))
            assert "☆" in summary, f"☆が含まれるべき: {summary}"


# ─── テスト 11: GEO プロパティ ───────────────────────────────────────────────

def test_ics_geo_property(tmp_path):
    """lat/lonが存在するイベントにGEOプロパティが付く"""
    from market_intelligence.events.ics_builder import build_ics_feed
    from icalendar import Calendar

    ev = {
        "id": "evt_geo001",
        "uid": "geo001@market-intelligence",
        "title": "GEOテスト",
        "description": "",
        "category": "festival",
        "venue_name": "会場",
        "address": "",
        "latitude": 35.6852,
        "longitude": 139.7100,
        "starts_at": "2026-09-01T11:00:00+09:00",
        "ends_at": "2026-09-01T17:00:00+09:00",
        "all_day": False,
        "official_url": "",
        "source_id": "demo",
        "first_seen_at": "2026-07-01T09:00:00+09:00",
        "last_seen_at": "2026-07-01T09:00:00+09:00",
        "sequence": 0,
    }
    asm = {"impact_score": 2, "impact_reasons": [], "operational_signals": [], "store_id": "cafe_01", "business_unit": "cafe", "distance_m": 500}
    out = tmp_path / "geo.ics"
    build_ics_feed([{"event": ev, "assessment": asm}], "テスト", "cafe_01", "cafe", out)

    cal = Calendar.from_ical(out.read_bytes())
    for component in cal.walk():
        if component.name == "VEVENT":
            geo = component.get("geo")
            assert geo is not None, "GEOプロパティが付くべき"


def test_ics_no_geo_when_no_coordinates(tmp_path):
    """lat/lonがNoneのイベントにはGEOプロパティが付かない"""
    from market_intelligence.events.ics_builder import build_ics_feed
    from icalendar import Calendar

    ev = {
        "id": "evt_nogeo001",
        "uid": "nogeo001@market-intelligence",
        "title": "座標なしイベント",
        "description": "",
        "category": "festival",
        "venue_name": "会場",
        "address": "",
        "latitude": None,
        "longitude": None,
        "starts_at": "2026-09-05T11:00:00+09:00",
        "ends_at": "2026-09-05T17:00:00+09:00",
        "all_day": False,
        "official_url": "",
        "source_id": "demo",
        "first_seen_at": "2026-07-01T09:00:00+09:00",
        "last_seen_at": "2026-07-01T09:00:00+09:00",
        "sequence": 0,
    }
    asm = {"impact_score": 1, "impact_reasons": [], "operational_signals": [], "store_id": "cafe_01", "business_unit": "cafe", "distance_m": None}
    out = tmp_path / "nogeo.ics"
    build_ics_feed([{"event": ev, "assessment": asm}], "テスト", "cafe_01", "cafe", out)

    cal = Calendar.from_ical(out.read_bytes())
    for component in cal.walk():
        if component.name == "VEVENT":
            geo = component.get("geo")
            assert geo is None, "座標なしのイベントにGEOは付かないべき"


# ─── テスト 12: icalendar ライブラリで再parse可能 ─────────────────────────────

def test_ics_parseable_by_icalendar(tmp_path):
    """生成したICSがicalendarライブラリで再parseできる"""
    from market_intelligence.events.ics_builder import build_ics_feed
    from icalendar import Calendar

    ev = {
        "id": "evt_parse001",
        "uid": "parse001@market-intelligence",
        "title": "Parseテスト",
        "description": "説明\n複数行",
        "category": "festival",
        "venue_name": "テスト会場",
        "address": "東京都新宿区",
        "latitude": 35.689,
        "longitude": 139.700,
        "starts_at": "2026-08-20T11:00:00+09:00",
        "ends_at": "2026-08-20T17:00:00+09:00",
        "all_day": False,
        "official_url": "https://example.com",
        "source_id": "demo",
        "first_seen_at": "2026-07-01T09:00:00+09:00",
        "last_seen_at": "2026-07-01T09:00:00+09:00",
        "sequence": 0,
        "merged_from_source_ids": ["src_a", "src_b"],
    }
    asm = {
        "impact_score": 3,
        "impact_reasons": ["distance_lt_500m:+3"],
        "operational_signals": ["pre_event_walk_in", "takeout_opportunity"],
        "store_id": "cafe_01",
        "business_unit": "cafe",
        "distance_m": 300,
    }
    out = tmp_path / "parseable.ics"
    build_ics_feed([{"event": ev, "assessment": asm}], "テストフィード", "cafe_01", "cafe", out)

    # icalendarで再parse
    content = out.read_bytes()
    cal = Calendar.from_ical(content)
    vevents = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(vevents) == 1
    assert str(vevents[0].get("uid")) == "parse001@market-intelligence"
    assert str(vevents[0].get("x-impact-score")) == "3"


# ─── テスト 13: cafe/delivery/store feedが生成される ─────────────────────────

def test_build_feeds_generates_files(store, demo_store_cafe, demo_store_delivery, tmp_path):
    """build_feedsがICSファイルを生成する"""
    from market_intelligence.events.service import build_feeds

    store.upsert("store_profiles", demo_store_cafe)
    store.upsert("store_profiles", demo_store_delivery)

    # テスト用EventRecordを保存
    ev = {
        "id": "evt_feed001",
        "uid": "feed001@market-intelligence",
        "source_id": "demo",
        "source_evidence_id": "ev_test001",
        "title": "フィードテストイベント",
        "description": "",
        "category": "festival",
        "venue_name": "テスト会場",
        "address": "東京都新宿区",
        "latitude": 35.689,
        "longitude": 139.700,
        "distance_from_store_km": 0.5,
        "starts_at": "2026-08-20T11:00:00+09:00",
        "ends_at": "2026-08-20T17:00:00+09:00",
        "all_day": False,
        "expected_audience": 3000,
        "audience_segments": [],
        "estimated_scale": "medium",
        "languages": ["ja"],
        "indoor_or_outdoor": "outdoor",
        "weather_sensitivity": "medium",
        "official_url": "",
        "status": "confirmed",
        "confidence": 1.0,
        "content_hash": "test",
        "first_seen_at": "2026-07-01T09:00:00+09:00",
        "last_seen_at": "2026-07-01T09:00:00+09:00",
        "sequence": 0,
        "merged_from_source_ids": [],
        "source_evidence_ids": [],
    }
    store.upsert("event_records", ev)

    generated = build_feeds(store=store, output_dir=tmp_path)
    assert len(generated) > 0, "ICSファイルが生成されるべき"
    for p in generated:
        assert p.exists(), f"ファイルが存在するべき: {p}"
        assert p.suffix == ".ics"


# ─── テスト 14: query JSONが正しい形式で返る ─────────────────────────────────

def test_query_json_format(store, demo_store_cafe):
    """query_events が正しいJSON形式を返す"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)

    result = query_events(
        store_id="cafe_test",
        business_unit="cafe",
        from_date="2026-07-01",
        to_date="2026-12-31",
        store=store,
    )

    assert "generated_from" in result
    assert result["generated_from"] == "normalized_event_store"
    assert "range" in result
    assert "from" in result["range"]
    assert "to" in result["range"]
    assert "timezone" in result["range"]
    assert result["range"]["timezone"] == "Asia/Tokyo"
    assert "store" in result
    assert "id" in result["store"]
    assert "events" in result
    assert isinstance(result["events"], list)
    assert "warnings" in result
    assert isinstance(result["warnings"], list)


def test_query_events_sorted_by_impact(store, demo_store_cafe):
    """queryの結果はimpact_score降順でソートされる"""
    from market_intelligence.events.query import query_events
    from datetime import datetime
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Tokyo")
    store.upsert("store_profiles", demo_store_cafe)

    # 2つのイベントを保存（impact_scoreが異なるassessment付き）
    now = datetime.now(TZ)

    for i, (uid, score) in enumerate([("uid001", 5), ("uid002", 1)]):
        ev = {
            "id": f"evt_{uid}",
            "uid": f"{uid}@market-intelligence",
            "source_id": "demo",
            "source_evidence_id": f"ev_{uid}",
            "title": f"イベント{i+1}",
            "description": "",
            "category": "festival",
            "venue_name": "",
            "address": "",
            "latitude": None,
            "longitude": None,
            "distance_from_store_km": None,
            "starts_at": (now + timedelta(days=7)).isoformat(),
            "ends_at": (now + timedelta(days=7, hours=2)).isoformat(),
            "all_day": False,
            "expected_audience": None,
            "audience_segments": [],
            "estimated_scale": "unknown",
            "languages": ["ja"],
            "indoor_or_outdoor": "unknown",
            "weather_sensitivity": "unknown",
            "official_url": "",
            "status": "confirmed",
            "confidence": 1.0,
            "content_hash": uid,
            "first_seen_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "sequence": 0,
            "merged_from_source_ids": [],
            "source_evidence_ids": [],
        }
        asm = {
            "id": f"sea_{uid}_cafe_test_cafe",
            "event_uid": f"{uid}@market-intelligence",
            "event_id": f"evt_{uid}",
            "store_id": "cafe_test",
            "business_unit": "cafe",
            "distance_m": 500,
            "impact_score": score,
            "impact_reasons": [],
            "operational_signals": [],
            "calculated_at": now.isoformat(),
        }
        store.upsert("event_records", ev)
        store.upsert("store_event_assessments", asm)

    result = query_events(
        store_id="cafe_test",
        business_unit="cafe",
        from_date=(now - timedelta(days=1)).date().isoformat(),
        to_date=(now + timedelta(days=30)).date().isoformat(),
        store=store,
    )

    events = result["events"]
    assert len(events) == 2
    assert events[0]["impact_score"] >= events[1]["impact_score"], "impact_score降順のはず"


# ─── テスト 15: LLMモード + APIキーなし → exit code 1 ────────────────────────

def test_events_collect_no_api_key_exits(tmp_path, monkeypatch):
    """ANTHROPIC_API_KEY未設定 + --no-llm なし → sys.exit(1)"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # CLIのfail-fast関数を直接テスト
    import argparse
    from market_intelligence import config as cfg

    # APIキーを確実に未設定状態にする
    original_key = cfg.LLM_API_KEY
    cfg.LLM_API_KEY = ""

    try:
        # argsオブジェクトを模擬
        args = argparse.Namespace(no_llm=False)

        # is_llm_available()がFalseを返すことを確認
        assert not cfg.is_llm_available()

        # sys.exit(1)が呼ばれることを確認
        with pytest.raises(SystemExit) as exc_info:
            from market_intelligence.cli import _require_llm_or_no_llm
            _require_llm_or_no_llm(args)

        assert exc_info.value.code == 1
    finally:
        cfg.LLM_API_KEY = original_key


# ─── テスト 16: --no-llm → APIキーなしで動作 ────────────────────────────────

def test_events_collect_no_llm_flag_works(store, demo_store_cafe, tmp_path, monkeypatch):
    """--no-llm指定時はAPIキーなしでも動作する"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    store.upsert("store_profiles", demo_store_cafe)

    from market_intelligence.events.collect import collect_events

    result = collect_events(
        store=store,
        store_id="cafe_test",
        days=90,
        demo=True,
        no_llm=True,
    )

    # エラーなしで完了するはず
    assert result["created"] >= 0
    assert result["updated"] >= 0
    # demo=TrueでAPIキーなしでも動作する


def test_collect_demo_creates_events(store, demo_store_cafe):
    """collect --demo でイベントとassessmentが保存される"""
    store.upsert("store_profiles", demo_store_cafe)

    from market_intelligence.events.collect import collect_events

    result = collect_events(
        store=store,
        store_id="cafe_test",
        days=90,
        demo=True,
        no_llm=True,
    )

    assert result["created"] > 0, "デモイベントが作成されるべき"
    assert result["assessments"] > 0, "アセスメントが作成されるべき"

    # EventRecordが保存されている
    records = store.list_all("event_records")
    assert len(records) > 0

    # uidが設定されている
    for rec in records:
        assert rec.get("uid"), f"uidが設定されているべき: {rec.get('id')}"
        assert "@market-intelligence" in rec["uid"]

    # StoreEventAssessmentが保存されている
    assessments = store.list_all("store_event_assessments")
    assert len(assessments) > 0
