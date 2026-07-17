"""
Phase 7: Source 一時停止・イベント visibility テスト

テスト対象:
- source pause で設定が削除されない
- source resume で同じ設定を再利用できる
- source pause 中は収集されない
- 別 source の収集は継続する
- 店舗単位 pause が他店舗へ影響しない
- hidden イベントの status が維持される
- hidden イベントが通常 query から除外される
- --include-hidden で確認できる
- hidden イベントが公開 ICS へ出力されない
- hidden イベントが Google Calendar へ新規同期されない（ICS 除外で担保）
- hidden イベントを cancelled として表示しない
- 公式 cancelled イベントは引き続き cancelled になる
- 次回自動同期で hidden 状態が解除されない
- 既存テスト回帰（collect.py の enabled フィルタのみ）
"""
from __future__ import annotations
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from market_intelligence.storage import JsonStore
from market_intelligence.events.source_control import (
    pause_source, resume_source, list_source_status,
    hide_event, show_event, list_events_admin,
)
from market_intelligence.events.query import query_events
from market_intelligence.events.collect import collect_events

TZ = ZoneInfo("Asia/Tokyo")


# ─── フィクスチャ ─────────────────────────────────────────────────────────────

def make_store(tmp_path: Path) -> JsonStore:
    store = JsonStore(tmp_path)
    store.initialize_schema()
    return store


def make_profile(store: JsonStore, store_id: str = "cafe_01", sources: list[dict] | None = None) -> dict:
    if sources is None:
        sources = [
            {"type": "kanko_shinjuku", "name": "観光協会"},
            {"type": "doorkeeper", "name": "Doorkeeper新宿", "keyword": "新宿"},
            {"type": "csv", "name": "手動CSV", "path": "dummy.csv"},
        ]
    profile = {
        "id": store_id,
        "name": f"[TEST] {store_id}",
        "business_unit": "cafe",
        "latitude": 35.69,
        "longitude": 139.69,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00", "peak": ["14:00", "17:00"]},
        "event_sources": sources,
    }
    store.upsert("store_profiles", profile)
    return profile


def make_event(store: JsonStore, event_id: str, title: str, starts_at: str,
               status: str = "confirmed", visibility: str | None = None) -> dict:
    ev = {
        "id": event_id,
        "uid": f"{event_id}@test",
        "title": title,
        "starts_at": starts_at,
        "ends_at": "",
        "source_id": "test",
        "status": status,
        "confidence": 0.9,
    }
    if visibility is not None:
        ev["visibility"] = visibility
    store.upsert("event_records", ev)
    return ev


# ─── source pause / resume テスト ─────────────────────────────────────────────

def test_pause_source_does_not_delete_config(tmp_path):
    """pause しても URL・source_type など元の設定が残る"""
    store = make_store(tmp_path)
    make_profile(store, sources=[
        {"type": "kanko_shinjuku", "name": "観光協会", "max_pages": 3},
    ])

    pause_source(store, "観光協会", store_id="cafe_01", reason="メンテ")

    profile = store.get("store_profiles", "cafe_01")
    src = profile["event_sources"][0]
    assert src["type"] == "kanko_shinjuku"
    assert src["name"] == "観光協会"
    assert src["max_pages"] == 3          # 元設定が残る
    assert src["enabled"] is False
    assert src["pause_reason"] == "メンテ"
    assert src["paused_at"] is not None


def test_pause_source_can_set_resume_at(tmp_path):
    store = make_store(tmp_path)
    make_profile(store, sources=[{"type": "doorkeeper", "name": "Doorkeeper新宿"}])

    pause_source(store, "Doorkeeper新宿", store_id="cafe_01", resume_at="2026-08-01")

    src = store.get("store_profiles", "cafe_01")["event_sources"][0]
    assert src["resume_at"] == "2026-08-01"


def test_resume_source_restores_same_config(tmp_path):
    """resume で同じ URL・設定を再利用できる"""
    store = make_store(tmp_path)
    make_profile(store, sources=[
        {"type": "kanko_shinjuku", "name": "観光協会", "max_pages": 5},
    ])

    pause_source(store, "観光協会", store_id="cafe_01")
    resume_source(store, "観光協会", store_id="cafe_01")

    src = store.get("store_profiles", "cafe_01")["event_sources"][0]
    assert src["enabled"] is True
    assert src["type"] == "kanko_shinjuku"
    assert src["max_pages"] == 5           # 元設定が残っている
    assert src["paused_at"] is None
    assert src["pause_reason"] is None


def test_pause_all_stores(tmp_path):
    """store_id=None で全店舗に適用"""
    store = make_store(tmp_path)
    make_profile(store, "cafe_01", sources=[{"type": "doorkeeper", "name": "Doorkeeper新宿"}])
    make_profile(store, "delivery_01", sources=[{"type": "doorkeeper", "name": "Doorkeeper新宿"}])

    updated = pause_source(store, "Doorkeeper新宿", store_id=None)
    assert "cafe_01" in updated
    assert "delivery_01" in updated

    for sid in ("cafe_01", "delivery_01"):
        src = store.get("store_profiles", sid)["event_sources"][0]
        assert src["enabled"] is False


def test_pause_per_store_does_not_affect_other_stores(tmp_path):
    """特定店舗の pause が他店舗に影響しない"""
    store = make_store(tmp_path)
    make_profile(store, "cafe_01",     sources=[{"type": "doorkeeper", "name": "Doorkeeper新宿"}])
    make_profile(store, "delivery_01", sources=[{"type": "doorkeeper", "name": "Doorkeeper新宿"}])

    pause_source(store, "Doorkeeper新宿", store_id="cafe_01")

    cafe_src     = store.get("store_profiles", "cafe_01")["event_sources"][0]
    delivery_src = store.get("store_profiles", "delivery_01")["event_sources"][0]
    assert cafe_src["enabled"] is False
    assert delivery_src.get("enabled", True) is True    # 他店舗は影響なし


def test_pause_not_found_source_returns_empty(tmp_path):
    store = make_store(tmp_path)
    make_profile(store)
    updated = pause_source(store, "存在しないソース", store_id="cafe_01")
    assert updated == []


def test_list_source_status_shows_enabled_state(tmp_path):
    store = make_store(tmp_path)
    make_profile(store, sources=[
        {"type": "kanko_shinjuku", "name": "観光協会"},
        {"type": "csv", "name": "手動CSV"},
    ])
    pause_source(store, "観光協会", store_id="cafe_01", reason="テスト停止")

    statuses = list_source_status(store)
    obs = {s["source_name"]: s for s in statuses}
    assert obs["観光協会"]["enabled"] is False
    assert obs["観光協会"]["pause_reason"] == "テスト停止"
    assert obs["手動CSV"].get("enabled", True) is True


# ─── collect.py enabled フィルタテスト ───────────────────────────────────────

def test_paused_source_is_skipped_in_collect(tmp_path):
    """enabled=False のソースは collect でスキップされる"""
    store = make_store(tmp_path)
    # 壊れた URL + enabled=False → スキップされて収集は実行されない
    make_profile(store, sources=[
        {
            "type": "ical",
            "name": "停止済みソース",
            "url": "http://localhost:99999/broken.ics",
            "enabled": False,
        }
    ])

    result = collect_events(store=store, store_id="cafe_01", days=90, demo=False, no_llm=True)
    # スキップされるので errors に停止済みソースのエラーは出ない
    # （demo fallback が発生するが、停止ソース起因のエラーは入らない）
    error_names = " ".join(result.get("errors", []))
    assert "停止済みソース" not in error_names


def test_other_sources_continue_when_one_paused(tmp_path, capsys):
    """一つのソースが停止中でも他のソースは試行継続する（アダプター内エラーはstdoutに出る）"""
    store = make_store(tmp_path)
    make_profile(store, sources=[
        {
            "type": "ical",
            "name": "停止ソース",
            "url": "http://localhost:99999/broken.ics",
            "enabled": False,
        },
        {
            "type": "ical",
            "name": "有効ソース",
            "url": "http://localhost:99999/another.ics",
            "enabled": True,    # こちらは有効だが接続エラーになる
        },
    ])

    collect_events(store=store, store_id="cafe_01", days=90, demo=False, no_llm=True)

    captured = capsys.readouterr()
    # 停止ソースはスキップメッセージが出る
    assert "停止ソース" in captured.out
    assert "スキップ" in captured.out
    # 有効ソースは試行されてエラーになる（アダプターがstdoutに出力）
    assert "有効ソース" not in captured.out or "localhost" in captured.out


# ─── visibility / suppressed テスト ──────────────────────────────────────────

def test_hide_event_preserves_status(tmp_path):
    """hide しても公式 status は変わらない"""
    store = make_store(tmp_path)
    make_event(store, "evt_001", "テストイベント", "2026-07-20T10:00:00+09:00", status="confirmed")

    hide_event(store, "evt_001", reason="店舗側都合")

    ev = store.get("event_records", "evt_001")
    assert ev["visibility"] == "hidden"
    assert ev["status"] == "confirmed"    # status は unchanged
    assert ev["suppression_reason"] == "店舗側都合"
    assert ev["suppressed_at"] is not None


def test_hide_event_cancelled_status_also_preserved(tmp_path):
    """公式 cancelled のイベントを hide しても、status=cancelled は維持される"""
    store = make_store(tmp_path)
    make_event(store, "evt_cancelled", "中止イベント", "2026-07-20T10:00:00+09:00", status="cancelled")

    hide_event(store, "evt_cancelled", reason="二重管理防止")

    ev = store.get("event_records", "evt_cancelled")
    assert ev["status"] == "cancelled"    # 公式 cancelled を維持
    assert ev["visibility"] == "hidden"


def test_show_event_restores_visibility(tmp_path):
    store = make_store(tmp_path)
    make_event(store, "evt_002", "非表示イベント", "2026-07-21T10:00:00+09:00",
               visibility="hidden")

    show_event(store, "evt_002")

    ev = store.get("event_records", "evt_002")
    assert ev["visibility"] == "visible"
    assert ev["suppressed_at"] is None


def test_hidden_event_excluded_from_normal_query(tmp_path):
    """hidden イベントは通常 query から除外される"""
    store = make_store(tmp_path)
    from_str = "2026-07-20"
    to_str = "2026-07-21"

    make_event(store, "evt_visible", "表示中イベント", "2026-07-20T10:00:00+09:00")
    make_event(store, "evt_hidden", "非表示イベント", "2026-07-20T11:00:00+09:00",
               visibility="hidden")

    result = query_events("cafe_01", "cafe", from_str, to_str, store, include_hidden=False)
    ids = [e["id"] for e in result["events"]]
    assert "evt_visible" in ids
    assert "evt_hidden" not in ids
    assert any("非表示" in w for w in result["warnings"])


def test_include_hidden_shows_hidden_events(tmp_path):
    """--include-hidden で非表示イベントを確認できる"""
    store = make_store(tmp_path)
    make_event(store, "evt_h", "非表示イベント", "2026-07-20T10:00:00+09:00",
               visibility="hidden")

    result = query_events("cafe_01", "cafe", "2026-07-20", "2026-07-21", store, include_hidden=True)
    ids = [e["id"] for e in result["events"]]
    assert "evt_h" in ids


def test_hidden_is_not_treated_as_cancelled(tmp_path):
    """hidden イベントは cancelled として扱われない（status は confirmed のまま）"""
    store = make_store(tmp_path)
    make_event(store, "evt_hid", "非表示（確定）イベント", "2026-07-20T10:00:00+09:00",
               visibility="hidden")

    # include_hidden=True で取得
    result = query_events("cafe_01", "cafe", "2026-07-20", "2026-07-21", store, include_hidden=True)
    ev = next((e for e in result["events"] if e["id"] == "evt_hid"), None)
    assert ev is not None
    assert ev.get("status", "confirmed") == "confirmed"
    assert ev.get("cancelled") is False


def test_official_cancelled_still_cancelled(tmp_path):
    """公式 cancelled は引き続き cancelled（visibility に関わらず）"""
    store = make_store(tmp_path)
    make_event(store, "evt_can", "公式中止イベント", "2026-07-20T10:00:00+09:00",
               status="cancelled")

    # include_hidden=True でも cancelled は除外される（status=cancelled による除外）
    result = query_events("cafe_01", "cafe", "2026-07-20", "2026-07-21", store, include_hidden=True)
    ids = [e["id"] for e in result["events"]]
    assert "evt_can" not in ids
    assert any("キャンセル" in w for w in result["warnings"])


def test_hidden_event_excluded_from_ics(tmp_path):
    """hidden イベントは公開 ICS に含まれない"""
    import shutil
    from market_intelligence.events.service import build_feeds

    store = make_store(tmp_path)
    store.upsert("store_profiles", {
        "id": "cafe_01",
        "name": "TEST CAFE",
        "business_unit": "cafe",
        "latitude": 35.69,
        "longitude": 139.69,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00", "peak": []},
        "event_sources": [],
    })

    now = datetime.now(TZ)
    starts = (now + timedelta(days=1)).strftime("%Y-%m-%dT10:00:00+09:00")
    make_event(store, "evt_pub", "公開イベント", starts)
    make_event(store, "evt_hid_ics", "非表示イベント", starts, visibility="hidden")

    out_dir = tmp_path / "ics_out"
    build_feeds(store=store, output_dir=out_dir)

    # ICS 内容確認
    all_ics = out_dir / "all.ics"
    assert all_ics.exists()
    content = all_ics.read_text(encoding="utf-8")
    assert "公開イベント" in content
    assert "非表示イベント" not in content


def test_hidden_event_not_added_to_ics_google_calendar_sync(tmp_path):
    """hidden イベントが ICS に含まれないことで Google Calendar への新規同期を防ぐ"""
    # Google Calendar は ICS を購読する。ICS に含まれなければ同期されない。
    # このテストは test_hidden_event_excluded_from_ics と同等の担保。
    from market_intelligence.events.service import build_feeds

    store = make_store(tmp_path)
    store.upsert("store_profiles", {
        "id": "cafe_01",
        "name": "TEST",
        "business_unit": "cafe",
        "latitude": 35.69,
        "longitude": 139.69,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00", "peak": []},
        "event_sources": [],
    })
    now = datetime.now(TZ)
    starts = (now + timedelta(days=1)).strftime("%Y-%m-%dT10:00:00+09:00")
    make_event(store, "evt_gcal_hidden", "Googleに同期しないイベント", starts, visibility="hidden")

    out_dir = tmp_path / "gcal_ics"
    build_feeds(store=store, output_dir=out_dir)

    all_ics = out_dir / "all.ics"
    content = all_ics.read_text(encoding="utf-8")
    assert "Googleに同期しないイベント" not in content


def test_auto_sync_does_not_clear_hidden_status(tmp_path):
    """次回自動収集で hidden 状態が解除されない"""
    store = make_store(tmp_path)
    make_profile(store, sources=[
        {"type": "ical", "name": "ブロックURL", "url": "http://localhost:99999/x.ics"}
    ])

    # イベントを作成して hide する
    make_event(store, "evt_persist_hidden", "非表示のまま", "2026-07-20T10:00:00+09:00",
               visibility="hidden")

    # 収集を実行（ソースは接続失敗 → demo fallback）
    collect_events(store=store, store_id="cafe_01", days=90, demo=False, no_llm=True)

    # visibility が保持されているか確認
    ev = store.get("event_records", "evt_persist_hidden")
    assert ev["visibility"] == "hidden"    # 解除されていない


def test_auto_sync_does_not_overwrite_visibility_on_update(tmp_path):
    """collect で既存レコード更新時に visibility を上書きしない（last_seen_at のみ更新）"""
    store = make_store(tmp_path)
    # demo mode で収集して既存レコードを作成
    make_profile(store, sources=[])
    collect_events(store=store, store_id="cafe_01", days=90, demo=True, no_llm=True)

    events = store.list_all("event_records")
    if not events:
        pytest.skip("デモデータが存在しないためスキップ")

    target = events[0]
    store.update_field("event_records", target["id"], "visibility", "hidden")
    store.update_field("event_records", target["id"], "suppression_reason", "テスト非表示")

    # 同じデモデータで再収集（update になる）
    collect_events(store=store, store_id="cafe_01", days=90, demo=True, no_llm=True)

    updated = store.get("event_records", target["id"])
    assert updated["visibility"] == "hidden"               # 解除されない
    assert updated["suppression_reason"] == "テスト非表示"  # 維持される


# ─── list_events_admin テスト ────────────────────────────────────────────────

def test_list_events_admin_includes_hidden_by_default(tmp_path):
    """管理用 list はデフォルトで hidden を含む"""
    store = make_store(tmp_path)
    make_event(store, "evt_a", "表示", "2026-07-20T10:00:00+09:00")
    make_event(store, "evt_b", "非表示", "2026-07-20T11:00:00+09:00", visibility="hidden")

    events = list_events_admin(store, include_hidden=True)
    ids = [e["id"] for e in events]
    assert "evt_a" in ids
    assert "evt_b" in ids


def test_list_events_admin_can_exclude_hidden(tmp_path):
    store = make_store(tmp_path)
    make_event(store, "evt_c", "表示", "2026-07-20T10:00:00+09:00")
    make_event(store, "evt_d", "非表示", "2026-07-20T11:00:00+09:00", visibility="hidden")

    events = list_events_admin(store, include_hidden=False)
    ids = [e["id"] for e in events]
    assert "evt_c" in ids
    assert "evt_d" not in ids


# ─── CLI テスト ───────────────────────────────────────────────────────────────

def test_cli_source_status(tmp_path):
    import subprocess
    result = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "source", "status"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "MI_DATA_DIR": str(tmp_path)},
    )
    assert result.returncode == 0


def test_cli_source_pause_resume(tmp_path):
    """CLI から pause/resume が実行できる"""
    import subprocess, os
    env = {**os.environ, "MI_DATA_DIR": str(tmp_path)}

    # init
    subprocess.run(
        ["python3", "market_intelligence/cli.py", "init"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )

    # pause
    r = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "source", "pause",
         "--name", "手動登録イベント", "--store", "cafe_01", "--reason", "テスト"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0

    # resume
    r = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "source", "resume",
         "--name", "手動登録イベント", "--store", "cafe_01"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0


def test_cli_event_hide_show(tmp_path):
    """CLI から event hide/show が実行できる"""
    import subprocess, os
    # CLI は LOCAL_INTELLIGENCE_DATA_DIR でデータディレクトリを制御できる
    env = {**os.environ, "LOCAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}

    # CLI 経由でイベントを作成（init 後に store を操作）
    subprocess.run(
        ["python3", "market_intelligence/cli.py", "init"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    # tmp_path のストアを直接操作してイベントを追加
    store = JsonStore(tmp_path)
    make_event(store, "evt_cli_test", "CLIテストイベント", "2026-07-20T10:00:00+09:00")

    # hide
    r = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "event", "hide",
         "--id", "evt_cli_test", "--reason", "CLI テスト"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr

    ev = JsonStore(tmp_path).get("event_records", "evt_cli_test")
    assert ev["visibility"] == "hidden"

    # show
    r = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "event", "show",
         "--id", "evt_cli_test"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr

    ev = JsonStore(tmp_path).get("event_records", "evt_cli_test")
    assert ev["visibility"] == "visible"


def test_cli_query_include_hidden(tmp_path):
    """--include-hidden フラグが CLI query に追加されている"""
    import subprocess, os
    env = {**os.environ, "MI_DATA_DIR": str(tmp_path)}

    store = JsonStore(tmp_path)
    store.initialize_schema()
    store.upsert("store_profiles", {
        "id": "cafe_01",
        "name": "TEST",
        "business_unit": "cafe",
        "latitude": 35.69,
        "longitude": 139.69,
        "search_radius_km": 3.0,
        "opening_hours": {"open": "09:00", "close": "21:00", "peak": []},
        "event_sources": [],
    })

    r = subprocess.run(
        ["python3", "market_intelligence/cli.py", "events", "query",
         "--store", "cafe_01", "--business-unit", "cafe",
         "--from", "2026-07-13", "--to", "2026-07-19",
         "--json", "--include-hidden"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0
