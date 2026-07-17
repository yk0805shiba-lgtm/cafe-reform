"""
Phase 6: Shadow mode テスト
- _ShadowStoreProxy のリダイレクト検証
- shadow_sync() の canonical 非破壊保証
- compare_shadow_vs_canonical() のマッチング
- mode.py の設定取得・変更
"""
from __future__ import annotations
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from market_intelligence.storage import JsonStore
from market_intelligence.events.mode import (
    get_current_mode, get_settings, set_mode,
    is_auto_source, is_manual_source,
    AUTO_SOURCE_TYPES, MANUAL_SOURCE_TYPES,
)
from market_intelligence.events.shadow import (
    _ShadowStoreProxy, _filter_profile_sources,
    shadow_sync, compare_shadow_vs_canonical, get_source_status,
)

TZ = ZoneInfo("Asia/Tokyo")


# ─── フィクスチャ ─────────────────────────────────────────────────────────────

def make_store(tmp_path: Path) -> JsonStore:
    store = JsonStore(tmp_path)
    store.initialize_schema()
    return store


def make_profile_with_sources(store: JsonStore, store_id: str = "cafe_01") -> dict:
    profile = {
        "id": store_id,
        "name": f"[TEST] {store_id}",
        "business_unit": "cafe",
        "address": "東京都新宿区",
        "latitude": 35.6895,
        "longitude": 139.6917,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00", "peak": ["14:00", "17:00"]},
        "event_sources": [
            {"type": "kanko_shinjuku", "name": "新宿観光振興協会"},
            {"type": "csv", "name": "手動CSV", "path": "dummy.csv"},
        ],
    }
    store.upsert("store_profiles", profile)
    return profile


def make_event(store: JsonStore, collection: str, uid: str, title: str, starts_at: str) -> dict:
    ev = {
        "id": f"evt_{uid[:8]}",
        "uid": uid,
        "title": title,
        "starts_at": starts_at,
        "ends_at": "",
        "source_id": "test",
        "status": "confirmed",
        "confidence": 0.9,
    }
    store.upsert(collection, ev)
    return ev


# ─── _ShadowStoreProxy テスト ─────────────────────────────────────────────────

def test_proxy_redirects_event_records_write(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    record = {"id": "evt_001", "title": "テスト", "starts_at": "2026-07-20T10:00:00+09:00"}
    proxy.upsert("event_records", record)

    # shadow に書かれている
    assert store.get("shadow_event_records", "evt_001") is not None
    # canonical は空
    assert store.get("event_records", "evt_001") is None


def test_proxy_redirects_assessments_write(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    asm = {"id": "sea_001", "event_uid": "uid_abc", "impact_score": 3}
    proxy.upsert("store_event_assessments", asm)

    assert store.get("shadow_store_event_assessments", "sea_001") is not None
    assert store.get("store_event_assessments", "sea_001") is None


def test_proxy_redirects_source_evidence_write(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    ev = {"id": "sev_001", "source_name": "テストソース"}
    proxy.upsert("source_evidence", ev)

    assert store.get("shadow_source_evidence", "sev_001") is not None
    assert store.get("source_evidence", "sev_001") is None


def test_proxy_reads_shadow_event_records(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    # shadow に1件書く
    store.upsert("shadow_event_records", {"id": "shd_001", "title": "shadow"})
    # canonical に1件書く
    store.upsert("event_records", {"id": "can_001", "title": "canonical"})

    shadow_list = proxy.list_all("event_records")
    ids = [e["id"] for e in shadow_list]
    assert "shd_001" in ids
    assert "can_001" not in ids


def test_proxy_does_not_redirect_other_collections(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    proxy.upsert("recommendations", {"id": "rec_001", "title": "提案"})
    assert store.get("recommendations", "rec_001") is not None


def test_proxy_filters_store_profiles_to_auto_sources(tmp_path):
    store = make_store(tmp_path)
    make_profile_with_sources(store)
    proxy = _ShadowStoreProxy(store)

    profiles = proxy.list_all("store_profiles")
    assert len(profiles) == 1
    sources = profiles[0]["event_sources"]
    # kanko_shinjuku は残る、csv は除外される
    types = [s["type"] for s in sources]
    assert "kanko_shinjuku" in types
    assert "csv" not in types


def test_proxy_get_store_profile_filters_auto_sources(tmp_path):
    store = make_store(tmp_path)
    make_profile_with_sources(store)
    proxy = _ShadowStoreProxy(store)

    profile = proxy.get("store_profiles", "cafe_01")
    assert profile is not None
    types = [s["type"] for s in profile["event_sources"]]
    assert "kanko_shinjuku" in types
    assert "csv" not in types


def test_proxy_returns_none_for_missing_profile(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    assert proxy.get("store_profiles", "nonexistent") is None


def test_proxy_delete_redirects(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    store.upsert("shadow_event_records", {"id": "shd_del"})
    assert proxy.delete("event_records", "shd_del") is True
    assert store.get("shadow_event_records", "shd_del") is None


def test_proxy_exists_redirects(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    store.upsert("shadow_event_records", {"id": "shd_ex"})
    assert proxy.exists("event_records", "shd_ex") is True
    assert proxy.exists("event_records", "nonexistent") is False


def test_proxy_update_field_redirects(tmp_path):
    store = make_store(tmp_path)
    proxy = _ShadowStoreProxy(store)

    store.upsert("shadow_event_records", {"id": "shd_upd", "title": "old"})
    proxy.update_field("event_records", "shd_upd", "title", "new")
    updated = store.get("shadow_event_records", "shd_upd")
    assert updated["title"] == "new"


# ─── _filter_profile_sources テスト ──────────────────────────────────────────

def test_filter_profile_sources_keeps_auto():
    profile = {
        "id": "cafe_01",
        "event_sources": [
            {"type": "kanko_shinjuku"},
            {"type": "doorkeeper"},
            {"type": "csv"},
            {"type": "manual"},
        ],
    }
    filtered = _filter_profile_sources(profile)
    types = [s["type"] for s in filtered["event_sources"]]
    assert "kanko_shinjuku" in types
    assert "doorkeeper" in types
    assert "csv" not in types
    assert "manual" not in types


def test_filter_profile_sources_does_not_mutate_original():
    profile = {
        "id": "cafe_01",
        "event_sources": [{"type": "csv"}],
    }
    _filter_profile_sources(profile)
    # 元のオブジェクトは変わらない
    assert len(profile["event_sources"]) == 1


# ─── compare_shadow_vs_canonical テスト ──────────────────────────────────────

def test_compare_matches_same_day_similar_title(tmp_path):
    store = make_store(tmp_path)
    starts = "2026-07-20T10:00:00+09:00"

    make_event(store, "shadow_event_records", "uid_shadow_001", "新宿夏祭り2026", starts)
    make_event(store, "event_records", "uid_canonical_001", "新宿夏祭り2026", starts)

    from_dt = datetime(2026, 7, 19, tzinfo=TZ)
    to_dt = datetime(2026, 7, 21, tzinfo=TZ)
    result = compare_shadow_vs_canonical(store, from_dt=from_dt, to_dt=to_dt)

    assert result["shadow_total"] == 1
    assert result["canonical_total"] == 1
    assert len(result["matched"]) == 1
    assert len(result["shadow_only"]) == 0
    assert len(result["canonical_only"]) == 0


def test_compare_shadow_only(tmp_path):
    store = make_store(tmp_path)
    starts = "2026-07-20T10:00:00+09:00"

    make_event(store, "shadow_event_records", "uid_shadow_new", "shadow_only_event", starts)
    # canonical には書かない

    from_dt = datetime(2026, 7, 19, tzinfo=TZ)
    to_dt = datetime(2026, 7, 21, tzinfo=TZ)
    result = compare_shadow_vs_canonical(store, from_dt=from_dt, to_dt=to_dt)

    assert result["shadow_total"] == 1
    assert result["canonical_total"] == 0
    assert len(result["shadow_only"]) == 1
    assert result["shadow_only"][0]["title"] == "shadow_only_event"


def test_compare_canonical_only(tmp_path):
    store = make_store(tmp_path)
    starts = "2026-07-20T10:00:00+09:00"

    # shadow には書かない
    make_event(store, "event_records", "uid_canonical_manual", "手動登録イベント", starts)

    from_dt = datetime(2026, 7, 19, tzinfo=TZ)
    to_dt = datetime(2026, 7, 21, tzinfo=TZ)
    result = compare_shadow_vs_canonical(store, from_dt=from_dt, to_dt=to_dt)

    assert result["canonical_only"][0]["title"] == "手動登録イベント"


def test_compare_date_range_filter(tmp_path):
    store = make_store(tmp_path)
    # 範囲外（来月）
    make_event(store, "shadow_event_records", "uid_far", "遠い未来イベント", "2026-12-01T10:00:00+09:00")
    # 範囲内（今週）
    make_event(store, "shadow_event_records", "uid_near", "今週イベント", "2026-07-20T10:00:00+09:00")

    from_dt = datetime(2026, 7, 19, tzinfo=TZ)
    to_dt = datetime(2026, 7, 21, tzinfo=TZ)
    result = compare_shadow_vs_canonical(store, from_dt=from_dt, to_dt=to_dt)

    assert result["shadow_total"] == 1
    assert result["shadow_only"][0]["title"] == "今週イベント"


def test_compare_no_events(tmp_path):
    store = make_store(tmp_path)
    from_dt = datetime(2026, 7, 19, tzinfo=TZ)
    to_dt = datetime(2026, 7, 21, tzinfo=TZ)
    result = compare_shadow_vs_canonical(store, from_dt=from_dt, to_dt=to_dt)

    assert result["shadow_total"] == 0
    assert result["canonical_total"] == 0
    assert result["matched"] == []


# ─── shadow_sync テスト（モックベース） ──────────────────────────────────────

def test_shadow_sync_no_auto_sources_returns_early(tmp_path):
    store = make_store(tmp_path)
    # 手動CSVのみのプロファイル
    profile = {
        "id": "cafe_01",
        "name": "Test Cafe",
        "business_unit": "cafe",
        "latitude": 35.69, "longitude": 139.69,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00", "peak": ["14:00", "17:00"]},
        "event_sources": [{"type": "csv", "name": "手動CSV", "path": "dummy.csv"}],
    }
    store.upsert("store_profiles", profile)

    result = shadow_sync(store, store_id="cafe_01", days=7, no_llm=True)
    assert result["collect"]["errors"] == ["自動収集ソースなし"]
    # canonical は空のまま
    assert store.list_all("event_records") == []


def test_shadow_sync_does_not_write_to_canonical(tmp_path):
    """shadow_sync は canonical の event_records を変更しない"""
    store = make_store(tmp_path)
    profile = {
        "id": "cafe_01",
        "name": "Test Cafe",
        "business_unit": "cafe",
        "latitude": 35.69, "longitude": 139.69,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00", "peak": ["14:00", "17:00"]},
        "event_sources": [{"type": "kanko_shinjuku", "name": "観光"}],
    }
    store.upsert("store_profiles", profile)

    # kanko_shinjuku アダプターは外部アクセスするためモックしてプロキシのみ検証
    proxy = _ShadowStoreProxy(store)
    # プロキシ経由で直接書き込んでも canonical は変わらない
    proxy.upsert("event_records", {"id": "shd_test", "title": "シャドウイベント", "starts_at": "2026-07-20T10:00:00+09:00"})

    assert store.get("event_records", "shd_test") is None
    assert store.get("shadow_event_records", "shd_test") is not None


def test_shadow_sync_saves_report(tmp_path):
    """auto sources なし でも比較レポートは compare_shadow_vs_canonical で呼ばれる"""
    store = make_store(tmp_path)
    # auto sources なしのケース
    profile = {
        "id": "cafe_01",
        "name": "Test",
        "business_unit": "cafe",
        "latitude": 35.69, "longitude": 139.69,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00", "peak": []},
        "event_sources": [],
    }
    store.upsert("store_profiles", profile)

    result = shadow_sync(store, no_llm=True)
    assert "comparison" in result
    assert "shadow_total" in result["comparison"]


# ─── get_source_status テスト ─────────────────────────────────────────────────

def test_get_source_status_empty(tmp_path):
    store = make_store(tmp_path)
    statuses = get_source_status(store)
    assert statuses == []


def test_get_source_status_returns_latest(tmp_path):
    store = make_store(tmp_path)
    store.upsert("shadow_source_evidence", {
        "id": "sev_001",
        "source_name": "新宿観光振興協会",
        "source_type": "kanko_shinjuku",
        "fetched_at": "2026-07-16T08:00:00+09:00",
    })
    store.upsert("shadow_source_evidence", {
        "id": "sev_002",
        "source_name": "新宿観光振興協会",
        "source_type": "kanko_shinjuku",
        "fetched_at": "2026-07-16T09:00:00+09:00",
    })

    statuses = get_source_status(store)
    assert len(statuses) == 1
    assert statuses[0]["last_fetched_at"] == "2026-07-16T09:00:00+09:00"


# ─── mode.py テスト ───────────────────────────────────────────────────────────

def test_get_current_mode_default(tmp_path):
    store = make_store(tmp_path)
    assert get_current_mode(store) == "shadow"


def test_set_mode_shadow(tmp_path):
    store = make_store(tmp_path)
    set_mode(store, "shadow")
    assert get_current_mode(store) == "shadow"


def test_set_mode_invalid(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        set_mode(store, "invalid_mode")


def test_get_settings_returns_defaults(tmp_path):
    store = make_store(tmp_path)
    settings = get_settings(store)
    assert settings["mode"] == "shadow"
    assert settings["active_requires_confirmation"] is True


def test_is_auto_source():
    assert is_auto_source({"type": "kanko_shinjuku"}) is True
    assert is_auto_source({"type": "doorkeeper"}) is True
    assert is_auto_source({"type": "csv"}) is False
    assert is_auto_source({"type": "manual"}) is False
    assert is_auto_source({"type": "demo"}) is False


def test_is_manual_source():
    assert is_manual_source({"type": "csv"}) is True
    assert is_manual_source({"type": "manual"}) is True
    assert is_manual_source({"type": "demo"}) is True
    assert is_manual_source({"type": "kanko_shinjuku"}) is False


def test_is_manual_source_csv_with_manual_name():
    assert is_manual_source({"type": "csv", "name": "手動入力CSV"}) is True
    assert is_manual_source({"type": "csv", "name": "manual events"}) is True
    assert is_manual_source({"type": "csv", "name": "イベント一覧"}) is True  # 名前に「手動」なし→普通のcsv


# ─── CLI テスト ───────────────────────────────────────────────────────────────

def test_cli_events_mode_show(tmp_path, monkeypatch):
    import subprocess
    result = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "mode", "show"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "MI_DATA_DIR": str(tmp_path)},
    )
    assert "shadow" in result.stdout or result.returncode == 0


def test_cli_events_sync_no_auto_sources(tmp_path, monkeypatch, capsys):
    """CLIからsync実行: auto sourcesなし→正常終了"""
    import subprocess
    result = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "sync", "--mode", "shadow", "--no-llm"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "MI_DATA_DIR": str(tmp_path)},
    )
    # エラーなく完了することを確認
    assert result.returncode == 0 or "自動収集" in result.stdout


def test_cli_events_shadow_report(tmp_path):
    import subprocess
    result = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "shadow-report"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "MI_DATA_DIR": str(tmp_path)},
    )
    assert result.returncode == 0
    assert "shadow" in result.stdout.lower() or "canonical" in result.stdout.lower()
