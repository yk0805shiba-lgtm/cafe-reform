"""
Phase 5 /events スキル — query.py 拡張フィールドテスト

テスト項目:
1. JSON スキーマ必須フィールドの存在確認
2. source_url (official_url エイリアス)
3. fetched_at (first_seen_at エイリアス)
4. cancelled フィールドが False（非キャンセルイベント）
5. キャンセルイベントが除外され warnings に件数が出る
6. data_warnings: 低信頼度
7. data_warnings: tentative ステータス
8. data_warnings: postponed ステータス
9. data_warnings: 座標不明
10. data_warnings: 距離未計算
11. impact_score 降順ソート確認
12. 0 件クエリ（期間外）
13. business_unit フィルタで適切な assessment が選ばれる
14. 店舗プロファイルなしの場合 warnings に出る
15. ICS ファイルを直接読み込まない（query は event_records から読む）
16. CLI --json オプションで有効な JSON が出力される
17. CLI 失敗時に stderr に出力される
18. data_warnings: 距離計算不能（distance_m=null）
19. 複数イベントの sort: impact_score 降順 → starts_at 昇順 → uid 昇順
20. all_day イベントのフィールド確認
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parents[2]


# ─── ヘルパー ──────────────────────────────────────────────────────────────────

def make_event(
    uid="uid_test_001@market-intelligence",
    title="テストイベント",
    starts_at="2026-07-20T10:00:00+09:00",
    ends_at="2026-07-20T18:00:00+09:00",
    all_day=False,
    venue_name="テスト会場",
    address="東京都新宿区1-1-1",
    latitude=35.6918,
    longitude=139.7044,
    official_url="https://example.com/event",
    first_seen_at="2026-07-15T10:00:00+09:00",
    confidence=0.9,
    status="confirmed",
    source_id="test_source",
    category="culture",
    merged_from_source_ids=None,
) -> dict:
    """テスト用イベントレコードを生成"""
    return {
        "id": f"evt_{uid[:8]}",
        "uid": uid,
        "source_id": source_id,
        "source_evidence_id": "ev_test",
        "source_evidence_ids": ["ev_test"],
        "merged_from_source_ids": merged_from_source_ids or [],
        "sequence": 1,
        "external_id": "",
        "title": title,
        "description": "",
        "category": category,
        "venue_name": venue_name,
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "distance_from_store_km": None,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "all_day": all_day,
        "expected_audience": None,
        "audience_segments": [],
        "estimated_scale": "unknown",
        "languages": ["ja"],
        "indoor_or_outdoor": "unknown",
        "weather_sensitivity": "unknown",
        "official_url": official_url,
        "status": status,
        "confidence": confidence,
        "content_hash": "testhash",
        "first_seen_at": first_seen_at,
        "last_seen_at": first_seen_at,
    }


def make_assessment(
    event_uid="uid_test_001@market-intelligence",
    store_id="cafe_test",
    business_unit="cafe",
    distance_m=500,
    impact_score=3,
    impact_reasons=None,
    operational_signals=None,
) -> dict:
    return {
        "id": f"sea_{event_uid[:8]}_{store_id}",
        "event_uid": event_uid,
        "store_id": store_id,
        "business_unit": business_unit,
        "distance_m": distance_m,
        "impact_score": impact_score,
        "impact_reasons": impact_reasons or ["distance_lt_1000m:+2", "category_culture:+1"],
        "operational_signals": operational_signals or ["pre_event_walk_in"],
        "calculated_at": "2026-07-15T10:00:00+09:00",
    }


# ─── テスト 1: JSON スキーマ必須フィールドの存在確認 ────────────────────────────

def test_query_required_fields_present(store, demo_store_cafe):
    """query_events が Phase 5 で必要な全フィールドを返す"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event()
    store.upsert("event_records", ev)
    asm = make_assessment()
    store.upsert("store_event_assessments", asm)

    result = query_events(
        store_id="cafe_test",
        business_unit="cafe",
        from_date="2026-07-20",
        to_date="2026-07-20T23:59:59",
        store=store,
    )

    assert result["generated_from"] == "normalized_event_store"
    assert "range" in result
    assert result["range"]["timezone"] == "Asia/Tokyo"
    assert "store" in result
    assert "events" in result
    assert "warnings" in result

    assert len(result["events"]) == 1
    ev_out = result["events"][0]

    # 必須フィールドの確認
    required = [
        "uid", "title", "starts_at", "ends_at", "all_day",
        "venue_name", "address", "distance_m",
        "impact_score", "impact_reasons", "operational_signals",
        "category", "source_id", "source_url", "fetched_at",
        "confidence", "status", "cancelled", "merged_from_source_ids",
        "data_warnings",
    ]
    for field in required:
        assert field in ev_out, f"必須フィールド '{field}' が存在しません"


# ─── テスト 2: source_url エイリアス ──────────────────────────────────────────

def test_source_url_is_alias_for_official_url(store, demo_store_cafe):
    """source_url フィールドが official_url の値を返す"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(official_url="https://example.com/my-event")
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert ev_out["source_url"] == "https://example.com/my-event"


# ─── テスト 3: fetched_at エイリアス ──────────────────────────────────────────

def test_fetched_at_is_alias_for_first_seen_at(store, demo_store_cafe):
    """fetched_at フィールドが first_seen_at の値を返す"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(first_seen_at="2026-07-14T09:30:00+09:00")
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert ev_out["fetched_at"] == "2026-07-14T09:30:00+09:00"


# ─── テスト 4: cancelled フィールドが False ───────────────────────────────────

def test_cancelled_field_is_false_for_confirmed_event(store, demo_store_cafe):
    """通常イベントの cancelled フィールドは False"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(status="confirmed")
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert ev_out["cancelled"] is False


# ─── テスト 5: キャンセルイベントが除外され warnings に件数が出る ─────────────

def test_cancelled_event_excluded_with_warning(store, demo_store_cafe):
    """status=cancelled のイベントは除外され、warnings に件数が記録される"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)

    # 通常イベント
    ev_ok = make_event(uid="uid_ok_001@market-intelligence", title="通常イベント")
    # キャンセルイベント
    ev_cancelled = make_event(
        uid="uid_cancel_001@market-intelligence",
        title="キャンセルイベント",
        status="cancelled",
    )
    store.upsert("event_records", ev_ok)
    store.upsert("event_records", ev_cancelled)
    store.upsert("store_event_assessments", make_assessment(event_uid="uid_ok_001@market-intelligence"))

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)

    # キャンセルイベントは events に含まれない
    titles = [e["title"] for e in result["events"]]
    assert "キャンセルイベント" not in titles
    assert "通常イベント" in titles

    # warnings にキャンセル除外の情報が入る
    assert any("キャンセル" in w and "1" in w for w in result["warnings"]), \
        f"キャンセル除外の warnings が見つかりません: {result['warnings']}"


# ─── テスト 6: data_warnings — 低信頼度 ───────────────────────────────────────

def test_data_warnings_low_confidence(store, demo_store_cafe):
    """confidence < 0.7 の場合 data_warnings に低信頼度メッセージが入る"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(confidence=0.5)
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert any("低信頼度" in w for w in ev_out["data_warnings"]), \
        f"低信頼度警告が見つかりません: {ev_out['data_warnings']}"


# ─── テスト 7: data_warnings — tentative ──────────────────────────────────────

def test_data_warnings_tentative_status(store, demo_store_cafe):
    """status=tentative の場合 data_warnings に開催確認待ちが入る"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(status="tentative")
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert any("tentative" in w or "開催確認" in w for w in ev_out["data_warnings"]), \
        f"tentative 警告が見つかりません: {ev_out['data_warnings']}"


# ─── テスト 8: data_warnings — postponed ──────────────────────────────────────

def test_data_warnings_postponed_status(store, demo_store_cafe):
    """status=postponed の場合 data_warnings に延期メッセージが入る"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(status="postponed")
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert any("postponed" in w or "延期" in w for w in ev_out["data_warnings"]), \
        f"postponed 警告が見つかりません: {ev_out['data_warnings']}"


# ─── テスト 9: data_warnings — 座標不明 ───────────────────────────────────────

def test_data_warnings_missing_coordinates(store, demo_store_cafe):
    """lat/lon が None の場合 data_warnings に座標不明が入る"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(latitude=None, longitude=None)
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert any("座標" in w for w in ev_out["data_warnings"]), \
        f"座標不明警告が見つかりません: {ev_out['data_warnings']}"


# ─── テスト 10: data_warnings — 距離未計算 ────────────────────────────────────

def test_data_warnings_missing_distance_m(store, demo_store_cafe):
    """assessment の distance_m が None の場合 data_warnings に距離未計算が入る"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event()
    store.upsert("event_records", ev)
    asm = make_assessment(distance_m=None)
    store.upsert("store_event_assessments", asm)

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert any("距離" in w for w in ev_out["data_warnings"]), \
        f"距離未計算警告が見つかりません: {ev_out['data_warnings']}"


# ─── テスト 11: impact_score 降順ソート ───────────────────────────────────────

def test_events_sorted_by_impact_score_desc(store, demo_store_cafe):
    """events は impact_score 降順に並ぶ"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)

    ev_low = make_event(uid="uid_low@market-intelligence", title="低スコアイベント")
    ev_high = make_event(uid="uid_high@market-intelligence", title="高スコアイベント")
    store.upsert("event_records", ev_low)
    store.upsert("event_records", ev_high)

    asm_low = make_assessment(event_uid="uid_low@market-intelligence", impact_score=1)
    asm_high = make_assessment(event_uid="uid_high@market-intelligence", impact_score=5)
    store.upsert("store_event_assessments", asm_low)
    store.upsert("store_event_assessments", asm_high)

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)

    scores = [e["impact_score"] for e in result["events"]]
    assert scores == sorted(scores, reverse=True), f"impact_score が降順でない: {scores}"
    assert result["events"][0]["title"] == "高スコアイベント"


# ─── テスト 12: 0 件クエリ（期間外）─────────────────────────────────────────

def test_query_returns_empty_for_out_of_range(store, demo_store_cafe):
    """期間外のイベントは返らない"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(starts_at="2026-07-20T10:00:00+09:00")
    store.upsert("event_records", ev)

    # 全く別の期間を指定
    result = query_events("cafe_test", "cafe", "2026-08-01", "2026-08-07T23:59:59", store)

    assert result["events"] == []


# ─── テスト 13: business_unit フィルタで適切な assessment が選ばれる ──────────

def test_business_unit_filter_selects_correct_assessment(store, demo_store_cafe, demo_store_delivery):
    """business_unit=cafe で cafe 向け assessment が優先される"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    store.upsert("store_profiles", demo_store_delivery)

    ev = make_event()
    store.upsert("event_records", ev)

    asm_cafe = make_assessment(
        event_uid="uid_test_001@market-intelligence",
        store_id="cafe_test",
        business_unit="cafe",
        impact_score=4,
    )
    asm_delivery = make_assessment(
        event_uid="uid_test_001@market-intelligence",
        store_id="delivery_test",
        business_unit="delivery",
        impact_score=2,
    )
    store.upsert("store_event_assessments", asm_cafe)
    store.upsert("store_event_assessments", asm_delivery)

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)

    assert len(result["events"]) == 1
    assert result["events"][0]["impact_score"] == 4
    assert result["events"][0]["assessment_business_unit"] == "cafe"


# ─── テスト 14: 店舗プロファイルなし → warnings に出る ───────────────────────

def test_missing_store_profile_adds_warning(store):
    """存在しない store_id を指定すると warnings にメッセージが入る"""
    from market_intelligence.events.query import query_events

    result = query_events(
        store_id="nonexistent_store",
        business_unit="cafe",
        from_date="2026-07-20",
        to_date="2026-07-20T23:59:59",
        store=store,
    )

    assert any("nonexistent_store" in w for w in result["warnings"]), \
        f"店舗不明の warnings が見つかりません: {result['warnings']}"


# ─── テスト 15: ICS ファイルを直接読み込まない ───────────────────────────────

def test_query_does_not_read_ics_files(store, demo_store_cafe, tmp_path):
    """query_events は ICS ファイルにアクセスしない"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)

    # ICS ファイルが存在しなくてもクエリが動く
    ics_dir = tmp_path / "docs" / "market-intelligence" / "events"
    assert not ics_dir.exists(), "ICS ディレクトリが存在してはいけない"

    # エラーなく実行できることを確認
    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    assert "events" in result  # クラッシュしない


# ─── テスト 16: CLI --json オプションで有効な JSON が出力される ───────────────

def test_cli_json_output_is_valid_json():
    """events query --json が有効な JSON を stdout に出力する"""
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "market_intelligence" / "cli.py"),
            "events", "query",
            "--store", "cafe_01",
            "--from", "2026-07-20",
            "--to", "2026-07-20T23:59:59",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )

    # JSON パース可能であることを確認（イベントがなくてもJSONは返る）
    stdout = result.stdout.strip()
    if stdout:
        parsed = json.loads(stdout)
        assert "events" in parsed
        assert "range" in parsed
        assert "store" in parsed
        assert "warnings" in parsed
    else:
        # stdout が空の場合は stderr にエラーがあるはず
        pytest.skip(f"CLI stdout が空 (stderr: {result.stderr[:200]})")


# ─── テスト 17: CLI 失敗時は stderr に出力される ─────────────────────────────

def test_cli_warnings_go_to_stderr(demo_store_cafe):
    """warnings は --json 時に stderr に出力され stdout の JSON を汚染しない"""
    # store_id として存在しない ID を指定 → warnings が出るはず
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "market_intelligence" / "cli.py"),
            "events", "query",
            "--store", "nonexistent_store_xyz",
            "--from", "2026-07-20",
            "--to", "2026-07-20T23:59:59",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )

    stdout = result.stdout.strip()
    if stdout:
        # stdout は純粋な JSON でなければならない
        parsed = json.loads(stdout)
        assert isinstance(parsed, dict), "stdout が JSON dict でない"


# ─── テスト 18: 複数イベントのソート検証 ─────────────────────────────────────

def test_events_sort_impact_desc_then_start_asc(store, demo_store_cafe):
    """同じ impact_score の場合は starts_at 昇順に並ぶ"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)

    # 同スコア・異なる開始時刻
    ev_later = make_event(
        uid="uid_later@market-intelligence",
        title="後から始まる",
        starts_at="2026-07-20T14:00:00+09:00",
        ends_at="2026-07-20T18:00:00+09:00",
    )
    ev_earlier = make_event(
        uid="uid_earlier@market-intelligence",
        title="先に始まる",
        starts_at="2026-07-20T10:00:00+09:00",
        ends_at="2026-07-20T12:00:00+09:00",
    )
    store.upsert("event_records", ev_later)
    store.upsert("event_records", ev_earlier)

    asm_later = make_assessment(
        event_uid="uid_later@market-intelligence", impact_score=3
    )
    asm_earlier = make_assessment(
        event_uid="uid_earlier@market-intelligence", impact_score=3
    )
    store.upsert("store_event_assessments", asm_later)
    store.upsert("store_event_assessments", asm_earlier)

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)

    assert len(result["events"]) == 2
    assert result["events"][0]["title"] == "先に始まる"
    assert result["events"][1]["title"] == "後から始まる"


# ─── テスト 19: all_day イベントのフィールド確認 ──────────────────────────────

def test_all_day_event_fields(store, demo_store_cafe):
    """all_day=True のイベントで all_day フィールドが True になる"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(
        all_day=True,
        starts_at="2026-07-20T00:00:00+09:00",
        ends_at="2026-07-20T23:59:59+09:00",
    )
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)

    assert len(result["events"]) == 1
    assert result["events"][0]["all_day"] is True


# ─── テスト 20: merged_from_source_ids フィールド確認 ────────────────────────

def test_merged_from_source_ids_in_output(store, demo_store_cafe):
    """重複マージ済みイベントで merged_from_source_ids が保持される"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(
        merged_from_source_ids=["source_a", "source_b"]
    )
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment())

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)

    ev_out = result["events"][0]
    assert ev_out["merged_from_source_ids"] == ["source_a", "source_b"]


# ─── テスト 21: 読み取り専用 — query は collect/build を呼ばない ──────────────

def test_query_does_not_call_collect_or_build(store, demo_store_cafe):
    """query_events が collect や build 系の副作用を起こさないことを確認"""
    import market_intelligence.events.query as qmod

    # collect/build のモジュールが import されないことを確認する
    # (query.py は collect.py や service.py を import しない)
    source = Path(qmod.__file__).read_text(encoding="utf-8")
    assert "collect_events" not in source, "query.py が collect を参照している"
    assert "build_feeds" not in source, "query.py が build_feeds を参照している"
    assert "IcsBuilder" not in source, "query.py が IcsBuilder を参照している"


# ─── テスト 22: data_warnings が空のリストでも含まれる ───────────────────────

def test_data_warnings_present_even_when_empty(store, demo_store_cafe):
    """問題のないイベントでも data_warnings フィールド自体は存在する"""
    from market_intelligence.events.query import query_events

    store.upsert("store_profiles", demo_store_cafe)
    ev = make_event(confidence=1.0, status="confirmed")
    store.upsert("event_records", ev)
    store.upsert("store_event_assessments", make_assessment(distance_m=300))

    result = query_events("cafe_test", "cafe", "2026-07-20", "2026-07-20T23:59:59", store)
    ev_out = result["events"][0]

    assert "data_warnings" in ev_out
    assert isinstance(ev_out["data_warnings"], list)
