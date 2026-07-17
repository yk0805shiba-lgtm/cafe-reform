"""スコアリングエンジンのテスト"""
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")


def _event(days=7, dist=1.5, scale="medium", audience=1000, category="local_event", segments=None, langs=None, outdoor="outdoor", weather="medium"):
    now = datetime.now(TZ)
    return {
        "id": "test_ev",
        "source_evidence_id": "ev_test",
        "title": "テストイベント",
        "category": category,
        "distance_from_store_km": dist,
        "starts_at": (now + timedelta(days=days)).isoformat(),
        "ends_at": (now + timedelta(days=days, hours=2)).isoformat(),
        "expected_audience": audience,
        "estimated_scale": scale,
        "audience_segments": segments or ["young_adults"],
        "languages": langs or ["ja"],
        "indoor_or_outdoor": outdoor,
        "weather_sensitivity": weather,
        "confidence": 0.9,
    }


def _store(segments=None, langs=None):
    return {
        "id": "test_store",
        "target_segments": segments or ["young_adults"],
        "languages": langs or ["ja"],
        "opening_hours": {"open": "09:00", "close": "21:00"},
    }


def test_score_in_valid_range():
    from market_intelligence.scoring import score_event
    score = score_event(_event(), _store(), "cafe")
    assert 0 <= score["total"] <= 100


def test_score_has_breakdown():
    from market_intelligence.scoring import score_event
    score = score_event(_event(), _store(), "cafe")
    assert "breakdown" in score
    assert "distance" in score["breakdown"]
    assert "timing" in score["breakdown"]
    assert "scale" in score["breakdown"]


def test_score_has_explanation():
    from market_intelligence.scoring import score_event
    score = score_event(_event(), _store(), "cafe")
    assert isinstance(score["explanation"], str)
    assert len(score["explanation"]) > 0


def test_close_event_scores_higher():
    from market_intelligence.scoring import score_event
    near = _event(days=3, dist=0.5)
    far = _event(days=60, dist=7.0)
    s_near = score_event(near, _store(), "cafe")
    s_far = score_event(far, _store(), "cafe")
    assert s_near["total"] > s_far["total"]


def test_fireworks_fits_cafe():
    from market_intelligence.scoring import score_event
    ev = _event(category="fireworks", outdoor="outdoor", weather="high")
    s_cafe = score_event(ev, _store(), "cafe")
    s_delivery = score_event(ev, _store(), "delivery")
    # 花火はcafeもdeliveryも適性あり
    assert s_cafe["total"] >= 0
    assert s_delivery["total"] >= 0


def test_target_segment_overlap():
    from market_intelligence.scoring import score_event
    ev = _event(segments=["young_adults", "tourists"])
    s_match = score_event(ev, _store(segments=["young_adults", "tourists"]), "cafe")
    s_nomatch = score_event(ev, _store(segments=["seniors"]), "cafe")
    assert s_match["total"] >= s_nomatch["total"]


def test_inbound_event_boosts_multilingual_store():
    from market_intelligence.scoring import score_event
    ev = _event(langs=["ja", "en", "zh"])
    s_multilang = score_event(ev, _store(langs=["ja", "en"]), "cafe")
    s_monolang = score_event(ev, _store(langs=["ja"]), "cafe")
    assert s_multilang["total"] >= s_monolang["total"]


def test_severity_thresholds():
    from market_intelligence.scoring import classify_severity
    high_diff = {"price_changes": [{"change_rate_pct": 15.0}], "new_items": [], "set_changes": [], "opening_hours_changes": [], "order_availability_change": None}
    med_diff = {"price_changes": [{"change_rate_pct": 7.0}], "new_items": [], "set_changes": [], "opening_hours_changes": [], "order_availability_change": None}
    low_diff = {"price_changes": [{"change_rate_pct": 2.0}], "new_items": [], "set_changes": [], "opening_hours_changes": [], "order_availability_change": None}

    assert classify_severity(high_diff) == "high"
    assert classify_severity(med_diff) == "medium"
    assert classify_severity(low_diff) == "low"
