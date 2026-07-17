"""
Phase 8: Local Market Intelligence 改善テスト

テスト対象:
A. Demo fallback tests:
   - Secret未設定でdemo configが正常生成される
   - トップレベルがlist
   - event_sourcesがlist-of-dicts
   - collectがAttributeErrorを起こさない
   - 不正なdict-keyed形式が明確なエラーになる
   - 文字列event_sourcesが明確なエラーになる

B. Override persistence tests:
   - source pauseがoperational overrideへ保存される
   - clean checkout相当でもpauseが反映される
   - source resumeで元設定を再利用できる
   - event hideがoverrideへ保存される
   - clean checkout相当でもhiddenが維持される
   - 次回collectでhiddenが解除されない

C. Canonical snapshot tests:
   - 前回snapshotあり、一部source失敗
   - 前回snapshotあり、全source失敗
   - 前回snapshotなし、全source失敗
   - 同じ入力でsnapshotが同一

D. Mode tests:
   - active mode
   - shadow mode
   - manual-only mode (collectorsを呼ばない)
"""
from __future__ import annotations
import copy
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
from market_intelligence.events.config_validator import validate_store_profiles
from market_intelligence.events.demo_config import generate_demo_profiles, write_demo_profiles
from market_intelligence.events.snapshot import (
    load_snapshot, save_snapshot, merge_with_snapshot, get_snapshot_source_ids,
    _to_snapshot_records, _filter_by_range,
)
from market_intelligence.overrides.operational_overrides import (
    load_overrides, save_overrides, _empty_overrides,
    apply_source_overrides, apply_event_visibility_overrides,
    add_source_pause, remove_source_pause,
    add_event_hidden, remove_event_hidden,
)
from market_intelligence.events.source_control import (
    pause_source, resume_source, hide_event, show_event,
)
from market_intelligence.events.collect import collect_events

TZ = ZoneInfo("Asia/Tokyo")


# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def make_store(tmp_path: Path) -> JsonStore:
    store = JsonStore(tmp_path)
    store.initialize_schema()
    return store


def make_profile_with_sources(store: JsonStore, store_id: str, sources: list[dict]) -> dict:
    profile = {
        "id": store_id,
        "name": f"[TEST] {store_id}",
        "business_unit": "cafe",
        "latitude": 35.69,
        "longitude": 139.69,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00"},
        "event_sources": sources,
    }
    store.upsert("store_profiles", profile)
    return profile


def make_event_record(uid: str, source_id: str, title: str, starts_at: str) -> dict:
    return {
        "id": f"evt_{uid[:8]}",
        "uid": uid,
        "source_id": source_id,
        "title": title,
        "starts_at": starts_at,
        "ends_at": "",
        "status": "confirmed",
        "confidence": 0.9,
        "content_hash": "testhash",
    }


def future_date(days: int = 30) -> str:
    dt = datetime.now(TZ) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT10:00:00+09:00")


# ─── A. Demo fallback tests ───────────────────────────────────────────────────

class TestDemoFallback:

    def test_generate_demo_profiles_returns_list(self):
        """generate_demo_profiles() はリストを返す"""
        profiles = generate_demo_profiles()
        assert isinstance(profiles, list)

    def test_generate_demo_profiles_top_level_is_list(self):
        """トップレベルがlist-of-dictsである"""
        profiles = generate_demo_profiles()
        assert len(profiles) >= 2
        for p in profiles:
            assert isinstance(p, dict), f"期待: dict, 実際: {type(p)}"

    def test_demo_profiles_have_required_fields(self):
        """各プロファイルに必須フィールドが含まれる"""
        profiles = generate_demo_profiles()
        for p in profiles:
            assert "id" in p
            assert "business_unit" in p
            assert "event_sources" in p
            assert p["business_unit"] in ("cafe", "delivery", "both")

    def test_demo_profiles_event_sources_are_list_of_dicts(self):
        """event_sources がlist-of-dictsである（文字列ではない）"""
        profiles = generate_demo_profiles()
        for p in profiles:
            sources = p.get("event_sources", [])
            assert isinstance(sources, list), f"event_sources must be list, got {type(sources)}"
            for src in sources:
                assert isinstance(src, dict), (
                    f"event source must be dict (not string), got {type(src).__name__}: {src!r}"
                )
                assert "type" in src, f"source missing 'type': {src}"

    def test_demo_profiles_latitude_longitude_fields(self):
        """プロファイルが latitude/longitude フィールドを使う（lat/lon ではない）"""
        profiles = generate_demo_profiles()
        for p in profiles:
            assert "latitude" in p, f"latitude フィールドが必要: {p}"
            assert "longitude" in p, f"longitude フィールドが必要: {p}"
            assert "lat" not in p, "lat は使わない（latitude を使用）"
            assert "lon" not in p, "lon は使わない（longitude を使用）"

    def test_demo_profiles_pass_validation(self):
        """generate_demo_profiles() のバリデーションエラーが 0 件"""
        profiles = generate_demo_profiles()
        errors = validate_store_profiles(profiles)
        assert errors == [], f"バリデーションエラー: {errors}"

    def test_write_demo_profiles_creates_file(self, tmp_path):
        """write_demo_profiles() がファイルを作成する"""
        out = tmp_path / "store_profiles.json"
        write_demo_profiles(out)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_demo_profiles_collect_no_attribute_error(self, tmp_path):
        """demo profile の event_sources で collect_events が AttributeError を起こさない"""
        store = make_store(tmp_path)
        profiles = generate_demo_profiles()
        for p in profiles:
            # demo source だけ有効にして collect してもエラーにならない
            p_test = copy.deepcopy(p)
            # demo type source のみに絞る（外部接続なし）
            p_test["event_sources"] = [
                src for src in p_test["event_sources"]
                if src.get("type") == "demo"
            ]
            store.upsert("store_profiles", p_test)
        # collect_events 実行 → AttributeError が起きないことを確認
        result = collect_events(store=store, store_id=None, days=90, demo=False, no_llm=True)
        assert "errors" in result
        # エラーに AttributeError が含まれないこと
        for err in result["errors"]:
            assert "AttributeError" not in err, f"AttributeError が発生した: {err}"

    def test_invalid_dict_keyed_format_gives_error(self):
        """dict-keyed形式（旧バグ）のstore_profilesは明確なエラーになる"""
        bad_data = {
            "cafe_01": {
                "id": "cafe_01",
                "name": "Cafe",
                "business_unit": "cafe",
                "event_sources": ["demo"],
            }
        }
        errors = validate_store_profiles(bad_data)
        assert len(errors) > 0, "dict-keyed形式はエラーになるべき"
        assert any("list" in e for e in errors), f"listであるべきというエラーが期待される: {errors}"

    def test_string_event_sources_gives_error(self):
        """文字列のevent_sourcesは明確なエラーになる（旧バグ）"""
        bad_data = [
            {
                "id": "cafe_01",
                "name": "Cafe",
                "business_unit": "cafe",
                "event_sources": ["demo", "kanko_shinjuku"],  # 文字列リスト
            }
        ]
        errors = validate_store_profiles(bad_data)
        assert len(errors) > 0, "文字列event_sourcesはエラーになるべき"
        assert any("object" in e or "expected" in e or "dict" in e.lower() for e in errors), \
            f"event sourceはdictであるべきというエラーが期待される: {errors}"


# ─── B. Override persistence tests ───────────────────────────────────────────

class TestOverridePersistence:

    def test_source_pause_writes_to_overrides(self, tmp_path):
        """source pause が operational_overrides に保存される"""
        # overrides を tmp_path 上の独立したファイルでテスト
        from market_intelligence.overrides.operational_overrides import (
            DEFAULT_OVERRIDES_PATH, load_overrides, save_overrides, add_source_pause
        )
        override_path = tmp_path / "test_overrides.json"

        overrides = _empty_overrides()
        add_source_pause(
            overrides,
            store_id="cafe_01",
            source_key="Doorkeeper新宿",
            reason_code="maintenance",
            planned_resume_at="2026-09-01",
        )
        save_overrides(overrides, path=override_path)

        loaded = load_overrides(path=override_path)
        src_ovs = loaded["source_overrides"]
        assert len(src_ovs) == 1
        ov = src_ovs[0]
        assert ov["store_id"] == "cafe_01"
        assert ov["source_key"] == "Doorkeeper新宿"
        assert ov["enabled"] is False
        assert ov["pause_reason_code"] == "maintenance"
        assert ov["planned_resume_at"] == "2026-09-01"
        # resume_at は planned_resume_at に統一（旧フィールドは存在しない）
        assert "resume_at" not in ov

    def test_clean_checkout_source_pause_reflected(self, tmp_path):
        """clean checkout相当でもoverrideが反映される"""
        override_path = tmp_path / "overrides.json"

        # overrides ファイルに pause を書き込む（Actions run 1 相当）
        overrides = _empty_overrides()
        add_source_pause(overrides, store_id="cafe_01", source_key="観光協会", reason_code="manual_pause")
        save_overrides(overrides, path=override_path)

        # store_profiles にプロファイルを設定
        profiles = [
            {
                "id": "cafe_01",
                "business_unit": "cafe",
                "event_sources": [
                    {"type": "kanko_shinjuku", "name": "観光協会", "enabled": True},
                ],
            }
        ]

        # clean checkout 相当: overrides を再度読み込んで適用（Actions run 2 相当）
        loaded_overrides = load_overrides(path=override_path)
        result_profiles = apply_source_overrides(profiles, loaded_overrides)

        src = result_profiles[0]["event_sources"][0]
        assert src["enabled"] is False, "pause が反映されていない"

    def test_source_resume_removes_override(self, tmp_path):
        """source resume で override エントリが削除される"""
        override_path = tmp_path / "overrides.json"

        overrides = _empty_overrides()
        add_source_pause(overrides, store_id="cafe_01", source_key="観光協会")
        save_overrides(overrides, path=override_path)

        # resume
        loaded = load_overrides(path=override_path)
        changed = remove_source_pause(loaded, store_id="cafe_01", source_key="観光協会")
        assert changed is True
        save_overrides(loaded, path=override_path)

        # 再読み込み
        final = load_overrides(path=override_path)
        assert final["source_overrides"] == []

    def test_source_pause_source_config_preserved(self, tmp_path):
        """source pause でも元の source 設定（max_pages等）が削除されない"""
        store = make_store(tmp_path)
        make_profile_with_sources(store, "cafe_01", [
            {"type": "kanko_shinjuku", "name": "観光協会", "enabled": True, "max_pages": 5},
        ])

        pause_source(store, "観光協会", store_id="cafe_01", reason_code="manual_pause")

        src = store.get("store_profiles", "cafe_01")["event_sources"][0]
        assert src["type"] == "kanko_shinjuku"
        assert src["max_pages"] == 5  # 元設定が保持される
        assert src["enabled"] is False

    def test_source_resume_reuses_original_config(self, tmp_path):
        """source resume で元の設定を再利用できる"""
        store = make_store(tmp_path)
        make_profile_with_sources(store, "cafe_01", [
            {"type": "kanko_shinjuku", "name": "観光協会", "enabled": True, "max_pages": 5},
        ])

        pause_source(store, "観光協会", store_id="cafe_01")
        resume_source(store, "観光協会", store_id="cafe_01")

        src = store.get("store_profiles", "cafe_01")["event_sources"][0]
        assert src["enabled"] is True
        assert src["max_pages"] == 5  # 元設定がそのまま使える
        assert src["paused_at"] is None
        assert src["pause_reason"] is None

    def test_event_hide_writes_to_overrides(self, tmp_path):
        """event hide が operational_overrides に保存される"""
        override_path = tmp_path / "overrides.json"

        overrides = _empty_overrides()
        add_event_hidden(
            overrides,
            event_uid="test-uid-001@test",
            reason_code="duplicate",
        )
        save_overrides(overrides, path=override_path)

        loaded = load_overrides(path=override_path)
        vis_ovs = loaded["event_visibility_overrides"]
        assert len(vis_ovs) == 1
        ov = vis_ovs[0]
        assert ov["event_uid"] == "test-uid-001@test"
        assert ov["visibility"] == "hidden"
        assert ov["suppression_reason_code"] == "duplicate"

    def test_clean_checkout_event_hidden_maintained(self, tmp_path):
        """clean checkout相当でもevent hiddenが維持される"""
        override_path = tmp_path / "overrides.json"

        overrides = _empty_overrides()
        add_event_hidden(overrides, event_uid="evt-uid-001@test", reason_code="manual_review")
        save_overrides(overrides, path=override_path)

        events = [
            {"id": "evt_001", "uid": "evt-uid-001@test", "title": "テストイベント", "status": "confirmed"},
            {"id": "evt_002", "uid": "evt-uid-002@test", "title": "別イベント", "status": "confirmed"},
        ]

        loaded_overrides = load_overrides(path=override_path)
        result_events = apply_event_visibility_overrides(events, loaded_overrides)

        ev1 = next(e for e in result_events if e["uid"] == "evt-uid-001@test")
        ev2 = next(e for e in result_events if e["uid"] == "evt-uid-002@test")
        assert ev1["visibility"] == "hidden"
        assert ev2.get("visibility", "visible") != "hidden"

    def test_next_collect_does_not_clear_hidden(self, tmp_path):
        """次回collect後もhiddenが解除されない"""
        store = make_store(tmp_path)
        make_profile_with_sources(store, "cafe_01", [])

        # デモデータで収集して既存レコードを作成
        collect_events(store=store, store_id="cafe_01", days=90, demo=True, no_llm=True)
        events = store.list_all("event_records")
        if not events:
            pytest.skip("デモイベントがないためスキップ")

        target = events[0]
        store.update_field("event_records", target["id"], "visibility", "hidden")
        store.update_field("event_records", target["id"], "suppression_reason", "テスト非表示")

        # 再収集（update になる）
        collect_events(store=store, store_id="cafe_01", days=90, demo=True, no_llm=True)

        updated = store.get("event_records", target["id"])
        assert updated["visibility"] == "hidden", "hidden が解除されてはいけない"
        assert updated["suppression_reason"] == "テスト非表示"

    def test_backward_compat_resume_at_to_planned_resume_at(self, tmp_path):
        """resume_at フィールドを backward compat で planned_resume_at に変換する"""
        override_path = tmp_path / "overrides.json"

        # 旧フォーマット（resume_at）で保存
        old_data = {
            "schema_version": 1,
            "source_overrides": [
                {
                    "store_id": "cafe_01",
                    "source_key": "観光協会",
                    "enabled": False,
                    "resume_at": "2026-09-01",  # 旧フィールド名
                }
            ],
            "event_visibility_overrides": [],
        }
        override_path.write_text(json.dumps(old_data), encoding="utf-8")

        # 読み込んで backward compat 変換が適用される
        loaded = load_overrides(path=override_path)
        ov = loaded["source_overrides"][0]
        assert "planned_resume_at" in ov, "planned_resume_at に変換されるべき"
        assert ov["planned_resume_at"] == "2026-09-01"
        assert "resume_at" not in ov, "resume_at は削除されるべき"


# ─── C. Canonical snapshot tests ─────────────────────────────────────────────

class TestCanonicalSnapshot:

    def test_save_and_load_snapshot(self, tmp_path):
        """snapshot の保存・読み込みが正常に動作する"""
        snapshot_path = tmp_path / "canonical_events.json"
        events = [
            make_event_record("uid-001@test", "kanko_shinjuku", "イベント1", future_date(10)),
            make_event_record("uid-002@test", "doorkeeper", "イベント2", future_date(20)),
        ]

        save_snapshot(events, path=snapshot_path)
        loaded = load_snapshot(path=snapshot_path)

        assert isinstance(loaded, list)
        assert len(loaded) == 2
        uids = {e.get("uid") for e in loaded}
        assert "uid-001@test" in uids
        assert "uid-002@test" in uids

    def test_snapshot_excludes_volatile_fields(self, tmp_path):
        """snapshotに volatile fields (first_seen_at, last_seen_at等) が含まれない"""
        snapshot_path = tmp_path / "canonical_events.json"
        events = [
            {
                "id": "evt_001",
                "uid": "uid-001@test",
                "source_id": "kanko_shinjuku",
                "title": "テスト",
                "starts_at": future_date(10),
                "first_seen_at": "2026-07-01T00:00:00+09:00",
                "last_seen_at": "2026-07-15T00:00:00+09:00",
                "content_hash": "abc123",
                "status": "confirmed",
            }
        ]

        save_snapshot(events, path=snapshot_path)
        loaded = load_snapshot(path=snapshot_path)
        ev = loaded[0]

        # volatile fields は除外される
        assert "first_seen_at" not in ev
        assert "last_seen_at" not in ev
        assert "id" not in ev  # id（内部ID）は除外
        # 安定フィールドは含まれる
        assert ev.get("uid") == "uid-001@test"
        assert ev.get("title") == "テスト"
        assert ev.get("content_hash") == "abc123"

    def test_merge_failed_source_retains_snapshot_events(self):
        """一部source失敗時にsnapshotのイベントが保持される"""
        new_events = [
            make_event_record("uid-001@test", "doorkeeper", "Doorkeepイベント", future_date(10)),
        ]
        snapshot = [
            make_event_record("uid-002@test", "kanko_shinjuku", "観光協会イベント", future_date(20)),
            make_event_record("uid-001@test", "doorkeeper", "Doorkeepイベント（旧）", future_date(10)),
        ]
        failed_source_ids = {"kanko_shinjuku"}  # kanko_shinjuku が失敗

        merged = merge_with_snapshot(new_events, failed_source_ids, snapshot)

        uids = {e.get("uid", e.get("id", "")) for e in merged}
        assert "uid-001@test" in uids, "成功sourceのイベントが含まれる"
        assert "uid-002@test" in uids, "失敗sourceのsnapshotイベントが保持される"
        # uid-001@test は new_events のものが優先される（重複しない）
        assert sum(1 for e in merged if e.get("uid") == "uid-001@test") == 1

    def test_merge_all_sources_failed_with_snapshot(self):
        """全source失敗 + snapshot有り: snapshotを返す"""
        new_events = []
        snapshot = [
            make_event_record("uid-001@test", "kanko_shinjuku", "観光協会イベント", future_date(10)),
            make_event_record("uid-002@test", "doorkeeper", "Doorkeepイベント", future_date(20)),
        ]
        failed_source_ids = {"kanko_shinjuku", "doorkeeper"}

        merged = merge_with_snapshot(new_events, failed_source_ids, snapshot)

        assert len(merged) == 2
        uids = {e.get("uid") for e in merged}
        assert "uid-001@test" in uids
        assert "uid-002@test" in uids

    def test_merge_all_sources_failed_no_snapshot(self):
        """全source失敗 + snapshot無し: 空リストを返す"""
        new_events = []
        snapshot = []
        failed_source_ids = {"kanko_shinjuku", "doorkeeper"}

        merged = merge_with_snapshot(new_events, failed_source_ids, snapshot)
        assert merged == []

    def test_merge_no_failed_sources(self):
        """failed_source_ids が空の場合は new_events をそのまま返す"""
        new_events = [
            make_event_record("uid-001@test", "kanko_shinjuku", "イベント1", future_date(10)),
        ]
        snapshot = [
            make_event_record("uid-999@test", "old_source", "古いイベント", future_date(15)),
        ]
        failed_source_ids: set[str] = set()

        merged = merge_with_snapshot(new_events, failed_source_ids, snapshot)
        # 失敗なし: new_events のみ
        assert merged == new_events

    def test_snapshot_is_deterministic(self, tmp_path):
        """同じ入力でsnapshotが同一（決定論的）"""
        snap1 = tmp_path / "snap1.json"
        snap2 = tmp_path / "snap2.json"

        events = [
            make_event_record("uid-002@test", "doorkeeper", "イベントB", future_date(20)),
            make_event_record("uid-001@test", "kanko_shinjuku", "イベントA", future_date(10)),
        ]

        save_snapshot(events, path=snap1)
        save_snapshot(events, path=snap2)

        assert snap1.read_text(encoding="utf-8") == snap2.read_text(encoding="utf-8")

    def test_snapshot_sorted_by_starts_at_then_uid(self, tmp_path):
        """snapshotは starts_at → uid の順でソートされる"""
        snapshot_path = tmp_path / "canonical_events.json"
        events = [
            make_event_record("uid-b@test", "src", "イベントB", future_date(20)),
            make_event_record("uid-a@test", "src", "イベントA", future_date(10)),
        ]

        save_snapshot(events, path=snapshot_path)
        loaded = load_snapshot(path=snapshot_path)

        starts = [e.get("starts_at", "") for e in loaded]
        assert starts == sorted(starts), f"starts_atでソートされていない: {starts}"

    def test_snapshot_filters_past_events(self, tmp_path):
        """過去7日より前のイベントはsnapshotから除外される"""
        snapshot_path = tmp_path / "canonical_events.json"
        old_date = (datetime.now(TZ) - timedelta(days=30)).strftime("%Y-%m-%dT10:00:00+09:00")
        future = future_date(10)

        events = [
            make_event_record("uid-old@test", "src", "古いイベント", old_date),
            make_event_record("uid-future@test", "src", "将来イベント", future),
        ]

        save_snapshot(events, path=snapshot_path)
        loaded = load_snapshot(path=snapshot_path)

        uids = {e.get("uid") for e in loaded}
        assert "uid-old@test" not in uids, "古いイベントは除外される"
        assert "uid-future@test" in uids, "将来イベントは含まれる"

    def test_load_snapshot_nonexistent_returns_empty(self, tmp_path):
        """存在しないsnapshotファイルは空リストを返す"""
        result = load_snapshot(path=tmp_path / "nonexistent.json")
        assert result == []

    def test_get_snapshot_source_ids(self):
        """get_snapshot_source_ids がsource_idセットを返す"""
        snapshot = [
            {"uid": "uid-001@test", "source_id": "kanko_shinjuku"},
            {"uid": "uid-002@test", "source_id": "doorkeeper"},
            {"uid": "uid-003@test", "source_id": "kanko_shinjuku"},  # 重複
            {"uid": "uid-004@test"},  # source_id なし
        ]
        ids = get_snapshot_source_ids(snapshot)
        assert ids == {"kanko_shinjuku", "doorkeeper"}


# ─── D. Mode tests ────────────────────────────────────────────────────────────

class TestModeSelection:

    def test_shadow_mode_is_default(self, tmp_path):
        """デフォルトモードはshadow"""
        store = make_store(tmp_path)
        from market_intelligence.events.mode import get_current_mode
        mode = get_current_mode(store)
        assert mode == "shadow"

    def test_set_shadow_mode(self, tmp_path):
        """shadow モードを設定できる"""
        store = make_store(tmp_path)
        from market_intelligence.events.mode import set_mode, get_current_mode
        set_mode(store, "shadow")
        assert get_current_mode(store) == "shadow"

    def test_set_active_mode(self, tmp_path):
        """active モードを設定できる"""
        store = make_store(tmp_path)
        from market_intelligence.events.mode import set_mode, get_current_mode
        set_mode(store, "active")
        assert get_current_mode(store) == "active"

    def test_set_manual_only_mode(self, tmp_path):
        """manual-only モードを設定できる"""
        store = make_store(tmp_path)
        from market_intelligence.events.mode import set_mode, get_current_mode
        set_mode(store, "manual-only")
        assert get_current_mode(store) == "manual-only"

    def test_invalid_mode_raises(self, tmp_path):
        """不正なモードは ValueError を起こす"""
        store = make_store(tmp_path)
        from market_intelligence.events.mode import set_mode
        with pytest.raises(ValueError):
            set_mode(store, "invalid_mode")

    def test_auto_source_types(self):
        """AUTO_SOURCE_TYPES が正しく定義されている"""
        from market_intelligence.events.mode import AUTO_SOURCE_TYPES, is_auto_source
        assert "kanko_shinjuku" in AUTO_SOURCE_TYPES
        assert "doorkeeper" in AUTO_SOURCE_TYPES
        assert "regasu_bunka_center" in AUTO_SOURCE_TYPES
        assert is_auto_source({"type": "kanko_shinjuku"}) is True
        assert is_auto_source({"type": "demo"}) is False

    def test_manual_source_types(self):
        """MANUAL_SOURCE_TYPES が正しく定義されている"""
        from market_intelligence.events.mode import MANUAL_SOURCE_TYPES, is_manual_source
        assert "demo" in MANUAL_SOURCE_TYPES
        assert "manual" in MANUAL_SOURCE_TYPES
        assert is_manual_source({"type": "demo"}) is True
        assert is_manual_source({"type": "kanko_shinjuku"}) is False

    def test_paused_source_skipped_in_collect(self, tmp_path):
        """enabled=False のsourceはcollectでスキップされる（mode非依存）"""
        store = make_store(tmp_path)
        make_profile_with_sources(store, "cafe_01", [
            {
                "type": "ical",
                "name": "停止済みソース",
                "url": "http://localhost:99999/broken.ics",
                "enabled": False,
            }
        ])

        result = collect_events(store=store, store_id="cafe_01", days=90, demo=False, no_llm=True)
        error_text = " ".join(result.get("errors", []))
        assert "停止済みソース" not in error_text, "停止ソースのエラーは出てはいけない"


# ─── E. Config Validator tests ───────────────────────────────────────────────

class TestConfigValidator:

    def test_valid_profiles_no_errors(self):
        """有効なプロファイルはエラーなし"""
        profiles = [
            {
                "id": "cafe_01",
                "business_unit": "cafe",
                "event_sources": [
                    {"type": "doorkeeper", "name": "Doorkeeper", "enabled": True},
                ],
            }
        ]
        errors = validate_store_profiles(profiles)
        assert errors == []

    def test_invalid_business_unit_error(self):
        """不正な business_unit はエラー"""
        profiles = [
            {
                "id": "cafe_01",
                "business_unit": "restaurant",  # 不正
                "event_sources": [],
            }
        ]
        errors = validate_store_profiles(profiles)
        assert any("business_unit" in e for e in errors)

    def test_missing_id_error(self):
        """id が欠けているとエラー"""
        profiles = [{"business_unit": "cafe", "event_sources": []}]
        errors = validate_store_profiles(profiles)
        assert any("id" in e for e in errors)

    def test_duplicate_store_id_error(self):
        """重複した store id はエラー"""
        profiles = [
            {"id": "cafe_01", "business_unit": "cafe", "event_sources": []},
            {"id": "cafe_01", "business_unit": "delivery", "event_sources": []},
        ]
        errors = validate_store_profiles(profiles)
        assert any("duplicate" in e.lower() for e in errors)

    def test_unknown_source_type_error(self):
        """不明な source type はエラー"""
        profiles = [
            {
                "id": "cafe_01",
                "business_unit": "cafe",
                "event_sources": [{"type": "unknown_type_xyz", "name": "test", "enabled": True}],
            }
        ]
        errors = validate_store_profiles(profiles)
        assert any("unknown_type_xyz" in e for e in errors)

    def test_string_source_in_event_sources_error(self):
        """event_sources の文字列要素はエラー"""
        profiles = [
            {
                "id": "cafe_01",
                "business_unit": "cafe",
                "event_sources": ["doorkeeper"],  # 文字列
            }
        ]
        errors = validate_store_profiles(profiles)
        assert len(errors) > 0

    def test_dict_keyed_top_level_error(self):
        """dict-keyed トップレベルはエラー"""
        bad_data = {"cafe_01": {"id": "cafe_01", "business_unit": "cafe", "event_sources": []}}
        errors = validate_store_profiles(bad_data)
        assert len(errors) > 0
        assert any("list" in e for e in errors)

    def test_enabled_non_bool_error(self):
        """enabled が bool でない場合はエラー"""
        profiles = [
            {
                "id": "cafe_01",
                "business_unit": "cafe",
                "event_sources": [{"type": "doorkeeper", "name": "DK", "enabled": "true"}],  # 文字列
            }
        ]
        errors = validate_store_profiles(profiles)
        assert any("bool" in e for e in errors)


# ─── F. Override apply tests ─────────────────────────────────────────────────

class TestOverrideApply:

    def test_apply_source_overrides_disables_source(self):
        """apply_source_overrides が enabled を False に設定する"""
        profiles = [
            {
                "id": "cafe_01",
                "event_sources": [
                    {"type": "kanko_shinjuku", "name": "観光協会", "enabled": True},
                ],
            }
        ]
        overrides = _empty_overrides()
        add_source_pause(overrides, store_id="cafe_01", source_key="観光協会")

        result = apply_source_overrides(profiles, overrides)
        src = result[0]["event_sources"][0]
        assert src["enabled"] is False

    def test_apply_source_overrides_does_not_delete_config(self):
        """apply_source_overrides が元の source 設定を保持する"""
        profiles = [
            {
                "id": "cafe_01",
                "event_sources": [
                    {"type": "kanko_shinjuku", "name": "観光協会", "enabled": True, "max_pages": 5},
                ],
            }
        ]
        overrides = _empty_overrides()
        add_source_pause(overrides, store_id="cafe_01", source_key="観光協会")

        result = apply_source_overrides(profiles, overrides)
        src = result[0]["event_sources"][0]
        assert src["max_pages"] == 5  # 元設定が保持される

    def test_apply_event_visibility_overrides_hides_event(self):
        """apply_event_visibility_overrides が visibility を hidden に設定する"""
        events = [
            {"id": "evt_001", "uid": "uid-001@test", "title": "テスト", "status": "confirmed"},
        ]
        overrides = _empty_overrides()
        add_event_hidden(overrides, event_uid="uid-001@test", reason_code="manual_review")

        result = apply_event_visibility_overrides(events, overrides)
        assert result[0]["visibility"] == "hidden"
        assert result[0]["suppression_reason_code"] == "manual_review"

    def test_apply_event_visibility_overrides_does_not_change_status(self):
        """visibility hidden は status を変更しない"""
        events = [
            {"id": "evt_001", "uid": "uid-001@test", "title": "テスト", "status": "confirmed"},
        ]
        overrides = _empty_overrides()
        add_event_hidden(overrides, event_uid="uid-001@test")

        result = apply_event_visibility_overrides(events, overrides)
        assert result[0]["status"] == "confirmed"  # status は変わらない

    def test_apply_all_store_source_override(self):
        """store_id='all' の override は全店舗に適用される"""
        profiles = [
            {
                "id": "cafe_01",
                "event_sources": [{"type": "doorkeeper", "name": "Doorkeeper", "enabled": True}],
            },
            {
                "id": "delivery_01",
                "event_sources": [{"type": "doorkeeper", "name": "Doorkeeper", "enabled": True}],
            },
        ]
        overrides = _empty_overrides()
        add_source_pause(overrides, store_id="all", source_key="Doorkeeper")

        result = apply_source_overrides(profiles, overrides)
        for p in result:
            src = p["event_sources"][0]
            assert src["enabled"] is False, f"store {p['id']} の Doorkeeper が停止されていない"
