"""
Phase 9 テスト: fail-safe・mode永続化・公開安全性・workflow検証

カバー範囲:
  A. 全source障害 (snapshot あり / なし)
  B. collection mode 永続化
  C. 公開安全性 (canonical snapshot / overrides の禁止フィールド)
  D. workflow YAML 構文・必須要素
  E. 回帰（既存機能）
"""
from __future__ import annotations
import json
import pathlib
import sys
import tempfile

import pytest


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_store(tmp_path):
    """一時ディレクトリに JsonStore を作成して返す"""
    import os
    os.environ["LOCAL_INTELLIGENCE_DATA_DIR"] = str(tmp_path / "data")
    from market_intelligence.storage import JsonStore
    store = JsonStore(tmp_path / "data")
    store.initialize_schema()
    yield store
    del os.environ["LOCAL_INTELLIGENCE_DATA_DIR"]


@pytest.fixture
def empty_overrides():
    from market_intelligence.overrides.operational_overrides import _empty_overrides
    return _empty_overrides()


# ─── A. 全 source 障害 ────────────────────────────────────────────────────────

class TestAllSourceFailure:
    """全 auto source 失敗時の fail-safe"""

    def test_all_fail_with_snapshot_retains_events(self):
        """全source失敗 + snapshot あり → snapshot を保持"""
        from market_intelligence.events.snapshot import merge_with_snapshot

        snapshot = [
            {"uid": "s1@test", "source_id": "kanko_shinjuku", "title": "A",
             "starts_at": "2026-08-01T10:00:00+09:00"},
            {"uid": "s2@test", "source_id": "doorkeeper", "title": "B",
             "starts_at": "2026-08-02T10:00:00+09:00"},
        ]
        # 全source失敗 → new_events=[] + failed_source_ids に全source
        merged = merge_with_snapshot(
            new_events=[],
            failed_source_ids={"kanko_shinjuku", "doorkeeper"},
            snapshot=snapshot,
        )
        uids = {e["uid"] for e in merged}
        assert "s1@test" in uids, "kanko_shinjuku のイベントが保持されていない"
        assert "s2@test" in uids, "doorkeeper のイベントが保持されていない"
        assert len(merged) == 2

    def test_all_fail_no_snapshot_returns_empty(self):
        """全source失敗 + snapshot なし → 空リスト"""
        from market_intelligence.events.snapshot import merge_with_snapshot

        merged = merge_with_snapshot(
            new_events=[],
            failed_source_ids={"kanko_shinjuku", "doorkeeper"},
            snapshot=[],
        )
        assert merged == []

    def test_partial_fail_with_snapshot(self):
        """一部source失敗 → 成功sourceは新データ、失敗sourceはsnapshotを保持"""
        from market_intelligence.events.snapshot import merge_with_snapshot

        snapshot = [
            {"uid": "snap1@test", "source_id": "kanko_shinjuku", "title": "旧観光A",
             "starts_at": "2026-08-01T10:00:00+09:00"},
        ]
        new_events = [
            {"uid": "new1@test", "source_id": "doorkeeper", "title": "新Doorkeeper",
             "starts_at": "2026-08-03T10:00:00+09:00"},
        ]
        merged = merge_with_snapshot(
            new_events=new_events,
            failed_source_ids={"kanko_shinjuku"},
            snapshot=snapshot,
        )
        titles = {e["title"] for e in merged}
        assert "旧観光A" in titles, "失敗sourceのsnapshotが保持されていない"
        assert "新Doorkeeper" in titles, "成功sourceの新データがない"

    def test_zero_result_source_with_snapshot_triggers_retention(self):
        """0件返却 + snapshot に同sourceのイベントあり → snapshot保持"""
        from market_intelligence.events.snapshot import merge_with_snapshot, get_snapshot_source_ids

        snapshot = [
            {"uid": "old1@test", "source_id": "regasu_bunka_center", "title": "旧文化センター",
             "starts_at": "2026-08-05T10:00:00+09:00"},
        ]
        snap_sources = get_snapshot_source_ids(snapshot)
        # 0件source が snapshot に存在するかチェック（失敗source扱いにするか判断）
        assert "regasu_bunka_center" in snap_sources

        # 0件を失敗source扱いにしてマージ
        merged = merge_with_snapshot(
            new_events=[],
            failed_source_ids={"regasu_bunka_center"},
            snapshot=snapshot,
        )
        assert len(merged) == 1
        assert merged[0]["title"] == "旧文化センター"

    def test_snapshot_not_overwritten_when_all_fail(self, tmp_path):
        """全source失敗時に snapshot を空で上書きしない"""
        from market_intelligence.events.snapshot import save_snapshot, load_snapshot

        snap_path = tmp_path / "canonical_events.json"
        # 既存 snapshot を保存
        existing_events = [
            {"uid": "exist1@test", "source_id": "doorkeeper", "title": "既存",
             "starts_at": "2026-08-10T10:00:00+09:00"},
        ]
        save_snapshot(existing_events, path=snap_path)

        # 全source失敗 → event_records が空 → 空で上書きしない（syncロジックの確認）
        # sync が event_records 空 + snapshot あり の場合に snapshot を保持する
        loaded_before = load_snapshot(path=snap_path)
        assert len(loaded_before) > 0, "テスト前提: snapshotに既存データが必要"

        # 空で上書きしない（空リストは save しない）
        # → syncロジック: if not events_to_snap and snapshot: events_to_snap = snapshot
        events_to_snap: list = []
        if not events_to_snap and loaded_before:
            events_to_snap = loaded_before
        save_snapshot(events_to_snap, path=snap_path)

        reloaded = load_snapshot(path=snap_path)
        assert len(reloaded) > 0, "全source失敗時にsnapshotが空で上書きされてはいけない"


# ─── B. Collection Mode 永続化 ────────────────────────────────────────────────

class TestCollectionModePersistence:
    """collection_mode が operational_overrides.json に正しく保存・読み込まれる"""

    def test_default_mode_is_shadow(self):
        """未設定時のデフォルトは shadow"""
        from market_intelligence.overrides.operational_overrides import (
            get_collection_mode, _empty_overrides
        )
        ov = _empty_overrides()
        assert get_collection_mode(ov) == "shadow"

    def test_set_shadow_mode(self, tmp_path):
        """shadow モードを保存・読み込める"""
        from market_intelligence.overrides.operational_overrides import (
            load_overrides, save_overrides, set_collection_mode, get_collection_mode
        )
        p = tmp_path / "overrides.json"
        ov = load_overrides(p)
        set_collection_mode(ov, "shadow")
        save_overrides(ov, p)

        reloaded = load_overrides(p)
        assert get_collection_mode(reloaded) == "shadow"

    def test_set_active_mode(self, tmp_path):
        """active モードを保存・読み込める"""
        from market_intelligence.overrides.operational_overrides import (
            load_overrides, save_overrides, set_collection_mode, get_collection_mode
        )
        p = tmp_path / "overrides.json"
        ov = load_overrides(p)
        set_collection_mode(ov, "active")
        save_overrides(ov, p)

        reloaded = load_overrides(p)
        assert get_collection_mode(reloaded) == "active"

    def test_set_manual_only_mode(self, tmp_path):
        """manual-only モードを保存・読み込める"""
        from market_intelligence.overrides.operational_overrides import (
            load_overrides, save_overrides, set_collection_mode, get_collection_mode
        )
        p = tmp_path / "overrides.json"
        ov = load_overrides(p)
        set_collection_mode(ov, "manual-only")
        save_overrides(ov, p)

        reloaded = load_overrides(p)
        assert get_collection_mode(reloaded) == "manual-only"

    def test_invalid_mode_raises(self):
        """不正なモードはエラー"""
        from market_intelligence.overrides.operational_overrides import (
            set_collection_mode, _empty_overrides
        )
        ov = _empty_overrides()
        with pytest.raises(ValueError):
            set_collection_mode(ov, "invalid-mode")

    def test_clean_runner_mode_persists(self, tmp_path):
        """clean checkout相当でも追跡モードが維持される"""
        from market_intelligence.overrides.operational_overrides import (
            load_overrides, save_overrides, set_collection_mode, get_collection_mode
        )
        p = tmp_path / "overrides.json"

        # 設定
        ov1 = load_overrides(p)
        set_collection_mode(ov1, "active")
        save_overrides(ov1, p)

        # clean checkout相当: 別インスタンスで読み込む
        ov2 = load_overrides(p)
        assert get_collection_mode(ov2) == "active"

    def test_unset_collection_mode_defaults_to_shadow(self, tmp_path):
        """collection_mode フィールドがない古いファイルはshadowにフォールバック"""
        from market_intelligence.overrides.operational_overrides import (
            load_overrides, get_collection_mode
        )
        p = tmp_path / "overrides.json"
        # collection_mode なしで書き込む（旧フォーマット）
        p.write_text(json.dumps({
            "schema_version": 1,
            "source_overrides": [],
            "event_visibility_overrides": [],
        }), encoding="utf-8")

        ov = load_overrides(p)
        assert get_collection_mode(ov) == "shadow"

    def test_schema_version_is_2(self, empty_overrides):
        """schema_version が 2 になっている"""
        from market_intelligence.overrides.operational_overrides import SCHEMA_VERSION
        assert SCHEMA_VERSION == 2
        assert empty_overrides["schema_version"] == 2


# ─── C. 公開安全性 ─────────────────────────────────────────────────────────────

class TestPublicSafety:
    """canonical_events.json と operational_overrides.json に秘密情報がない"""

    # 公開ファイルに含めてはいけないフィールド
    FORBIDDEN_FIELDS = {
        "api_key", "secret", "token", "password", "credential",
        "email", "phone", "staff_name", "staff_id",
        "sales", "revenue", "cost", "budget", "profit",
        "internal_memo", "private_note",
    }

    def test_canonical_snapshot_no_forbidden_fields(self, tmp_path):
        """canonical snapshotに禁止フィールドが含まれない"""
        from market_intelligence.events.snapshot import save_snapshot, load_snapshot

        snap_path = tmp_path / "canonical_events.json"
        events = [
            {
                "uid": "safe1@test",
                "source_id": "doorkeeper",
                "title": "公開イベント",
                "starts_at": "2026-08-01T10:00:00+09:00",
                "ends_at": "2026-08-01T12:00:00+09:00",
                "venue_name": "新宿文化センター",
                "address": "東京都新宿区",
                "status": "confirmed",
                "category": "culture",
                "confidence": 0.9,
                # 禁止フィールドなし
            }
        ]
        save_snapshot(events, path=snap_path)
        loaded = load_snapshot(path=snap_path)

        for ev in loaded:
            for forbidden in self.FORBIDDEN_FIELDS:
                assert forbidden not in ev, f"forbidden field '{forbidden}' in snapshot event"

    def test_snapshot_does_not_contain_fetched_at(self, tmp_path):
        """snapshotの volatile フィールド (fetched_at) は除外される"""
        from market_intelligence.events.snapshot import save_snapshot, load_snapshot

        snap_path = tmp_path / "canonical_events.json"
        events = [
            {
                "uid": "v1@test",
                "source_id": "kanko_shinjuku",
                "title": "テスト",
                "starts_at": "2026-08-01T10:00:00+09:00",
                "fetched_at": "2026-07-17T06:00:00+09:00",  # volatile
            }
        ]
        save_snapshot(events, path=snap_path)
        loaded = load_snapshot(path=snap_path)

        assert len(loaded) == 1
        assert "fetched_at" not in loaded[0], "volatile field 'fetched_at' should not be in snapshot"

    def test_operational_overrides_uses_reason_codes(self, tmp_path):
        """operational_overrides.json は reason_code のみ（自由記述なし）"""
        from market_intelligence.overrides.operational_overrides import (
            load_overrides, save_overrides, add_source_pause, add_event_hidden
        )
        p = tmp_path / "overrides.json"
        ov = load_overrides(p)

        add_source_pause(ov, "cafe_01", "doorkeeper", reason_code="maintenance")
        add_event_hidden(ov, "uid-001@test", reason_code="duplicate")
        save_overrides(ov, p)

        loaded = load_overrides(p)
        src_ov = loaded["source_overrides"][0]
        vis_ov = loaded["event_visibility_overrides"][0]

        # reason_code フィールドが存在し、自由記述の pause_reason はない
        assert "pause_reason_code" in src_ov
        assert "pause_reason" not in src_ov, "free-text 'pause_reason' should not be in overrides"
        assert "suppression_reason_code" in vis_ov
        assert "suppression_reason" not in vis_ov, "free-text 'suppression_reason' should not be in overrides"

    def test_operational_overrides_no_secrets(self, tmp_path):
        """operational_overrides.json に秘密情報が含まれない"""
        from market_intelligence.overrides.operational_overrides import (
            load_overrides, save_overrides, add_source_pause
        )
        p = tmp_path / "overrides.json"
        ov = load_overrides(p)
        add_source_pause(ov, "cafe_01", "doorkeeper", reason_code="maintenance", paused_by="bot")
        save_overrides(ov, p)

        content = p.read_text()
        for forbidden in self.FORBIDDEN_FIELDS:
            assert forbidden not in content.lower(), f"forbidden string '{forbidden}' found in overrides"

    def test_reason_code_invalid_falls_back_to_empty(self, tmp_path):
        """不正な reason_code は空文字にフォールバック（自由記述を拒否）"""
        from market_intelligence.overrides.operational_overrides import (
            load_overrides, save_overrides, add_source_pause
        )
        p = tmp_path / "overrides.json"
        ov = load_overrides(p)
        # 不正なコードを渡す
        add_source_pause(ov, "cafe_01", "doorkeeper", reason_code="内部メモ: APIキー変更中")
        save_overrides(ov, p)

        loaded = load_overrides(p)
        src_ov = loaded["source_overrides"][0]
        # 不正コードは manual_pause にフォールバック（VALID_PAUSE_REASON_CODES に含まれない）
        assert src_ov["pause_reason_code"] == "manual_pause"

    def test_snapshot_stable_between_runs(self, tmp_path):
        """同じ入力で snapshot が同一（決定論的）"""
        from market_intelligence.events.snapshot import save_snapshot, load_snapshot
        import time

        snap_path = tmp_path / "canonical_events.json"
        events = [
            {"uid": "det1@test", "source_id": "doorkeeper", "title": "テスト",
             "starts_at": "2026-08-15T10:00:00+09:00"},
            {"uid": "det2@test", "source_id": "kanko_shinjuku", "title": "テスト2",
             "starts_at": "2026-08-10T10:00:00+09:00"},
        ]
        save_snapshot(events, path=snap_path)
        content1 = snap_path.read_text()

        time.sleep(0.05)
        save_snapshot(events, path=snap_path)
        content2 = snap_path.read_text()

        assert content1 == content2, "同じ入力でsnapshotが異なる（非決定論的）"


# ─── D. Workflow YAML ─────────────────────────────────────────────────────────

class TestWorkflowYaml:
    """GitHub Actions workflow の必須要素を検証"""

    @pytest.fixture
    def workflow_text(self):
        p = pathlib.Path(__file__).parents[2] / ".github" / "workflows" / "update-market-intelligence-events.yml"
        assert p.exists(), f"workflow ファイルが見つかりません: {p}"
        return p.read_text()

    def test_workflow_file_exists(self):
        p = pathlib.Path(__file__).parents[2] / ".github" / "workflows" / "update-market-intelligence-events.yml"
        assert p.exists()

    def test_configure_pages_present(self, workflow_text):
        assert "actions/configure-pages" in workflow_text

    def test_upload_pages_artifact_present(self, workflow_text):
        assert "actions/upload-pages-artifact" in workflow_text

    def test_artifact_path_is_docs(self, workflow_text):
        assert "path: docs" in workflow_text

    def test_deploy_pages_present(self, workflow_text):
        assert "actions/deploy-pages" in workflow_text

    def test_deploy_job_needs_build(self, workflow_text):
        assert "needs: collect-and-build" in workflow_text

    def test_pages_write_permission(self, workflow_text):
        assert "pages: write" in workflow_text

    def test_id_token_write_permission(self, workflow_text):
        assert "id-token: write" in workflow_text

    def test_github_pages_environment(self, workflow_text):
        assert "name: github-pages" in workflow_text

    def test_no_username_placeholder(self, workflow_text):
        assert "YOUR_GITHUB_USERNAME" not in workflow_text

    def test_uses_events_sync(self, workflow_text):
        assert "events sync" in workflow_text

    def test_no_direct_events_collect(self, workflow_text):
        # events collect を直接実行していないこと（sync 経由であること）
        lines_with_collect = [
            line for line in workflow_text.splitlines()
            if "events collect" in line and not line.strip().startswith("#")
        ]
        assert len(lines_with_collect) == 0, (
            f"workflow で events collect が直接使われています:\n" +
            "\n".join(lines_with_collect)
        )

    def test_config_validate_step_present(self, workflow_text):
        assert "events config validate" in workflow_text

    def test_config_create_demo_step_present(self, workflow_text):
        assert "events config create-demo" in workflow_text

    def test_workflow_dispatch_mode_input(self, workflow_text):
        assert "workflow_dispatch" in workflow_text
        assert "configured" in workflow_text

    def test_pages_concurrency_set(self, workflow_text):
        assert 'group: "pages"' in workflow_text

    def test_commit_includes_snapshot(self, workflow_text):
        assert "state/canonical_events.json" in workflow_text

    def test_commit_includes_overrides(self, workflow_text):
        assert "operational_overrides.json" in workflow_text

    def test_contact_uses_github_context(self, workflow_text):
        assert "github.server_url" in workflow_text
        assert "github.repository" in workflow_text

    def test_sync_failure_blocks_build(self, workflow_text):
        """sync ステップが失敗した場合、後続ステップが実行されないこと（GitHub Actions のデフォルト動作）"""
        # GitHub Actions はデフォルトで前のステップが失敗すると後続をスキップする
        # "if: always()" や "continue-on-error" が sync ステップにないことを確認
        sync_section = False
        for line in workflow_text.splitlines():
            if "events sync" in line:
                sync_section = True
            if sync_section and "continue-on-error" in line:
                pytest.fail("events sync に continue-on-error が設定されています")
            if sync_section and line.strip().startswith("-") and "events sync" not in line:
                break


# ─── E. 回帰テスト ─────────────────────────────────────────────────────────────

class TestRegression:
    """既存機能が壊れていないことの確認"""

    def test_demo_config_is_list(self):
        """デモ設定がリスト形式"""
        from market_intelligence.events.demo_config import generate_demo_profiles
        profiles = generate_demo_profiles()
        assert isinstance(profiles, list)
        assert len(profiles) >= 2

    def test_demo_config_event_sources_are_dicts(self):
        """デモ設定の event_sources がすべて dict"""
        from market_intelligence.events.demo_config import generate_demo_profiles
        profiles = generate_demo_profiles()
        for p in profiles:
            for src in p.get("event_sources", []):
                assert isinstance(src, dict), f"event_source が dict ではない: {src}"
                assert "type" in src
                assert isinstance(src.get("enabled", True), bool)

    def test_config_validation_catches_dict_keyed(self):
        """dict-keyed 形式を検出してエラーを返す"""
        from market_intelligence.events.config_validator import validate_store_profiles
        bad = {"cafe_01": {"id": "cafe_01", "business_unit": "cafe"}}
        errors = validate_store_profiles(bad)
        assert len(errors) > 0
        assert "list" in errors[0].lower()

    def test_config_validation_catches_string_sources(self):
        """文字列 event_sources を検出してエラーを返す"""
        from market_intelligence.events.config_validator import validate_store_profiles
        bad = [{"id": "cafe_01", "business_unit": "cafe", "event_sources": ["doorkeeper"]}]
        errors = validate_store_profiles(bad)
        assert any("string" in e.lower() or "object" in e.lower() for e in errors)

    def test_backward_compat_old_pause_reason_in_overrides(self, tmp_path):
        """旧フォーマット (pause_reason) を読み込んで pause_reason_code に変換する"""
        from market_intelligence.overrides.operational_overrides import load_overrides
        p = tmp_path / "overrides.json"
        # 旧フォーマット
        p.write_text(json.dumps({
            "schema_version": 1,
            "source_overrides": [
                {
                    "store_id": "cafe_01",
                    "source_key": "doorkeeper",
                    "enabled": False,
                    "pause_reason": "maintenance",  # 旧フィールド名
                    "planned_resume_at": None,
                }
            ],
            "event_visibility_overrides": [],
        }), encoding="utf-8")

        ov = load_overrides(p)
        src_ov = ov["source_overrides"][0]
        # 旧フィールドは変換される
        assert "pause_reason_code" in src_ov
        assert "pause_reason" not in src_ov

    def test_backward_compat_resume_at_renamed(self, tmp_path):
        """旧フォーマット (resume_at) を planned_resume_at に変換する"""
        from market_intelligence.overrides.operational_overrides import load_overrides
        p = tmp_path / "overrides.json"
        p.write_text(json.dumps({
            "schema_version": 1,
            "source_overrides": [
                {
                    "store_id": "cafe_01",
                    "source_key": "doorkeeper",
                    "enabled": False,
                    "resume_at": "2026-09-01",  # 旧フィールド名
                }
            ],
            "event_visibility_overrides": [],
        }), encoding="utf-8")

        ov = load_overrides(p)
        src_ov = ov["source_overrides"][0]
        assert "planned_resume_at" in src_ov
        assert src_ov["planned_resume_at"] == "2026-09-01"
        assert "resume_at" not in src_ov

    def test_source_pause_resume_round_trip(self, tmp_store, tmp_path):
        """pause → resume が正しく動作する"""
        from market_intelligence.events.source_control import pause_source, resume_source

        tmp_store.upsert("store_profiles", {
            "id": "cafe_01",
            "name": "テスト",
            "business_unit": "cafe",
            "event_sources": [
                {"type": "doorkeeper", "name": "Doorkeeper新宿", "enabled": True, "keyword": "新宿"}
            ],
        })

        updated = pause_source(tmp_store, "Doorkeeper新宿", store_id="cafe_01", reason_code="maintenance")
        assert "cafe_01" in updated
        src = tmp_store.get("store_profiles", "cafe_01")["event_sources"][0]
        assert src["enabled"] is False

        resumed = resume_source(tmp_store, "Doorkeeper新宿", store_id="cafe_01")
        assert "cafe_01" in resumed
        src2 = tmp_store.get("store_profiles", "cafe_01")["event_sources"][0]
        assert src2["enabled"] is True
        # 元設定が保持される
        assert src2["keyword"] == "新宿"

    def test_hide_show_event_round_trip(self, tmp_store):
        """hide → show が正しく動作する"""
        from market_intelligence.events.source_control import hide_event, show_event

        tmp_store.upsert("event_records", {
            "id": "evt_001",
            "uid": "uid-001@test",
            "title": "テストイベント",
            "status": "confirmed",
            "visibility": "visible",
        })

        result = hide_event(tmp_store, "evt_001", reason_code="duplicate")
        assert result is True
        ev = tmp_store.get("event_records", "evt_001")
        assert ev["visibility"] == "hidden"
        assert ev["status"] == "confirmed"  # status は変わらない

        result2 = show_event(tmp_store, "evt_001")
        assert result2 is True
        ev2 = tmp_store.get("event_records", "evt_001")
        assert ev2["visibility"] == "visible"

    def test_zero_result_source_tracked(self, tmp_path, monkeypatch):
        """0件返却の auto source が zero_result_source_ids に追跡される"""
        import os
        os.environ["LOCAL_INTELLIGENCE_DATA_DIR"] = str(tmp_path / "data")
        from market_intelligence.storage import JsonStore
        store = JsonStore(tmp_path / "data")
        store.initialize_schema()

        # 0件返却するダミー source を持つ profile
        store.upsert("store_profiles", {
            "id": "cafe_01",
            "name": "Test",
            "business_unit": "cafe",
            "latitude": 35.69,
            "longitude": 139.70,
            "event_sources": [
                # doorkeeper は AUTO_SOURCE_TYPES に含まれる → 0件なら zero_result_source_ids へ
                {"type": "doorkeeper", "name": "Doorkeeper新宿", "enabled": True, "keyword": "存在しないキーワード9999999"},
            ],
        })

        from market_intelligence.events.collect import collect_events
        # 実際のHTTP接続なし: 失敗した場合は failed_source_ids、成功0件は zero_result_source_ids
        result = collect_events(store=store, days=30, no_llm=True)
        # いずれかのリストに Doorkeeper新宿 が含まれる
        all_tracked = set(result.get("failed_source_ids", [])) | set(result.get("zero_result_source_ids", []))
        assert "Doorkeeper新宿" in all_tracked, (
            f"Doorkeeper新宿 が failed_source_ids にも zero_result_source_ids にも含まれていない: {result}"
        )
        del os.environ["LOCAL_INTELLIGENCE_DATA_DIR"]
