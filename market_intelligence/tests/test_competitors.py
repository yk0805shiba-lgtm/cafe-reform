"""競合モニタリングAgentのテスト"""
import pytest


def _make_snapshot(competitor_id, suffix="", prices=None, menu=None, sets=None, opening_hours=None, order=True, rating=4.0, reviews=100, review_topics=None):
    return {
        "id": f"snap_{competitor_id}_{suffix}",
        "competitor_id": competitor_id,
        "captured_at": "2026-07-14T08:00:00+09:00",
        "source_evidence_ids": [],
        "menu_items": menu or [],
        "prices": prices or {},
        "sets": sets or [],
        "discounts": [],
        "opening_hours": opening_hours or {"open": "11:00", "close": "21:00"},
        "order_availability": order,
        "rating": rating,
        "review_count": reviews,
        "review_topics": review_topics or {},
        "content_hash": f"hash_{suffix}",
        "status": "success",
        "confidence": 0.9,
    }


def test_price_change_detection(store):
    """価格変更を正しく検知する"""
    from market_intelligence.agents import CompetitorAgent
    agent = CompetitorAgent(store, llm=None)

    prev = _make_snapshot("comp_a", "prev", prices={"混ぜそば": 1000}, menu=[{"name": "混ぜそば", "price": 1000}])
    curr_snap = _make_snapshot("comp_a", "curr", prices={"混ぜそば": 1100}, menu=[{"name": "混ぜそば", "price": 1100}])

    from market_intelligence.models import CompetitorSnapshot
    curr = CompetitorSnapshot(**{k: v for k, v in curr_snap.items() if k in CompetitorSnapshot.__dataclass_fields__})
    diff = agent._compute_diff(prev, curr)

    assert len(diff.price_changes) == 1
    pc = diff.price_changes[0]
    assert pc["previous_price"] == 1000
    assert pc["current_price"] == 1100
    assert pc["difference"] == 100
    assert abs(pc["change_rate_pct"] - 10.0) < 0.1


def test_price_change_rate_calculation():
    """価格変更率の計算精度"""
    from market_intelligence.utils import price_change_rate
    assert price_change_rate(1000, 1100) == 10.0
    assert price_change_rate(1100, 1000) == pytest.approx(-9.1, abs=0.1)
    assert price_change_rate(0, 1000) == 0.0


def test_new_item_detection(store):
    """新商品を正しく検知する"""
    from market_intelligence.agents import CompetitorAgent
    from market_intelligence.models import CompetitorSnapshot
    agent = CompetitorAgent(store, llm=None)

    prev = _make_snapshot("comp_b", "prev", menu=[{"name": "混ぜそば", "price": 950}])
    curr_snap = _make_snapshot("comp_b", "curr", menu=[
        {"name": "混ぜそば", "price": 950},
        {"name": "温玉追い飯セット", "price": 1280, "is_new": True},
    ])
    curr = CompetitorSnapshot(**{k: v for k, v in curr_snap.items() if k in CompetitorSnapshot.__dataclass_fields__})
    diff = agent._compute_diff(prev, curr)

    assert len(diff.new_items) == 1
    assert diff.new_items[0]["name"] == "温玉追い飯セット"
    assert len(diff.removed_items) == 0


def test_removed_item_detection(store):
    """販売終了商品を正しく検知する"""
    from market_intelligence.agents import CompetitorAgent
    from market_intelligence.models import CompetitorSnapshot
    agent = CompetitorAgent(store, llm=None)

    prev = _make_snapshot("comp_c", "prev", menu=[
        {"name": "混ぜそば", "price": 950},
        {"name": "季節限定スープ", "price": 200},
    ])
    curr_snap = _make_snapshot("comp_c", "curr", menu=[{"name": "混ぜそば", "price": 950}])
    curr = CompetitorSnapshot(**{k: v for k, v in curr_snap.items() if k in CompetitorSnapshot.__dataclass_fields__})
    diff = agent._compute_diff(prev, curr)

    assert len(diff.removed_items) == 1
    assert diff.removed_items[0]["name"] == "季節限定スープ"


def test_opening_hours_change_detection(store):
    """営業時間変更を検知する（シナリオ6: 21時→23時）"""
    from market_intelligence.agents import CompetitorAgent
    from market_intelligence.models import CompetitorSnapshot
    agent = CompetitorAgent(store, llm=None)

    prev = _make_snapshot("comp_d", "prev", opening_hours={"open": "11:00", "close": "21:00"})
    curr_snap = _make_snapshot("comp_d", "curr", opening_hours={"open": "11:00", "close": "23:00"})
    curr = CompetitorSnapshot(**{k: v for k, v in curr_snap.items() if k in CompetitorSnapshot.__dataclass_fields__})
    diff = agent._compute_diff(prev, curr)

    assert len(diff.opening_hours_changes) == 1
    hc = diff.opening_hours_changes[0]
    assert hc["previous"]["close"] == "21:00"
    assert hc["current"]["close"] == "23:00"


def test_severity_classification_high(store):
    """大幅な価格変更はhigh重要度になる"""
    from market_intelligence.scoring import classify_severity
    diff = {
        "price_changes": [
            {"item_name": "混ぜそば", "previous_price": 1000, "current_price": 1150, "change_rate_pct": 15.0}
        ],
        "new_items": [],
        "set_changes": [],
        "opening_hours_changes": [],
        "order_availability_change": None,
    }
    severity = classify_severity(diff, high_threshold=10.0, medium_threshold=5.0)
    assert severity == "high"


def test_severity_classification_medium():
    """小規模な価格変更はmedium重要度になる"""
    from market_intelligence.scoring import classify_severity
    diff = {
        "price_changes": [
            {"item_name": "混ぜそば", "previous_price": 1000, "current_price": 1060, "change_rate_pct": 6.0}
        ],
        "new_items": [],
        "set_changes": [],
        "opening_hours_changes": [],
        "order_availability_change": None,
    }
    severity = classify_severity(diff, high_threshold=10.0, medium_threshold=5.0)
    assert severity == "medium"


def test_no_meaningless_diff_when_unchanged(store):
    """変化がない場合、差分なしとなる"""
    from market_intelligence.agents import CompetitorAgent
    from market_intelligence.models import CompetitorSnapshot
    agent = CompetitorAgent(store, llm=None)

    prev = _make_snapshot("comp_e", "prev", prices={"混ぜそば": 950}, menu=[{"name": "混ぜそば", "price": 950}])
    curr_snap = _make_snapshot("comp_e", "curr", prices={"混ぜそば": 950}, menu=[{"name": "混ぜそば", "price": 950}])
    curr = CompetitorSnapshot(**{k: v for k, v in curr_snap.items() if k in CompetitorSnapshot.__dataclass_fields__})
    diff = agent._compute_diff(prev, curr)

    assert diff.has_changes is False
    assert len(diff.price_changes) == 0
    assert len(diff.new_items) == 0


def test_no_copy_recommendation_in_competitor_strategy():
    """戦略提案に競合コピー・値下げ追従が含まれないことを確認"""
    from market_intelligence.agents.competitor_agent import CompetitorAgent
    from market_intelligence.models import SnapshotDiff

    diff = SnapshotDiff(
        id="test_diff",
        competitor_id="comp_test",
        previous_snapshot_id="prev",
        current_snapshot_id="curr",
        compared_at="2026-07-14T00:00:00+09:00",
        price_changes=[{"item_name": "混ぜそば", "previous_price": 1000, "current_price": 1100, "difference": 100, "change_rate_pct": 10.0}],
        severity="medium",
        has_changes=True,
    )
    competitor = {"id": "comp_test", "name": "テスト競合", "business_unit": "delivery"}
    store_profile = {
        "id": "test_store",
        "business_unit": "delivery",
        "brand_positioning": "ボリューム・満足感が強みの混ぜそば",
        "target_segments": ["office_workers"],
    }

    from market_intelligence.storage import JsonStore
    import tempfile
    tmp = tempfile.mkdtemp()
    store = JsonStore(tmp)
    store.initialize_schema()
    agent = CompetitorAgent(store, llm=None)

    suggestions = agent._rule_based_competitor_suggestions(diff, competitor, store_profile, "delivery")

    all_text = " ".join(s.get("summary", "") for s in suggestions)
    # 単純値下げ追従の文言がないことを確認
    assert "同じ価格にする" not in all_text
    assert "追従" not in all_text or "単純追従" not in all_text


def test_demo_competitor_agent_runs(store, demo_store_delivery):
    """デモモードで競合Agentが正常に実行できる"""
    store.upsert("store_profiles", demo_store_delivery)
    # デモ競合を登録
    comp = {
        "id": "demo_comp_test",
        "name": "[DEMO] テスト競合",
        "business_unit": "delivery",
        "category": "mazesoba",
        "address": "東京都新宿区",
        "monitoring_enabled": True,
        "monitoring_frequency": "daily",
        "created_at": "2026-07-14T00:00:00+09:00",
        "updated_at": "2026-07-14T00:00:00+09:00",
    }
    store.upsert("competitor_profiles", comp)

    from market_intelligence.agents import CompetitorAgent
    agent = CompetitorAgent(store, llm=None)
    run = agent.run("delivery_test", trigger_type="demo")

    assert run.status in ("success", "partial")


def test_competitor_snapshot_persistence(store):
    """スナップショットが正しくストレージに保存される"""
    from market_intelligence.agents import CompetitorAgent
    from market_intelligence.adapters import ManualCompetitorAdapter
    agent = CompetitorAgent(store, llm=None)

    data = {
        "menu_items": [{"name": "テスト商品", "price": 800}],
        "prices": {"テスト商品": 800},
        "sets": [],
        "opening_hours": {"open": "10:00", "close": "22:00"},
    }
    snap = agent.record_manual_snapshot("comp_manual_test", data)
    assert snap.id != ""
    assert store.exists("competitor_snapshots", snap.id)


def test_source_evidence_linked_to_snapshot(store):
    """スナップショットにSourceEvidenceが紐付く"""
    from market_intelligence.agents import CompetitorAgent
    agent = CompetitorAgent(store, llm=None)

    data = {"menu_items": [], "prices": {}}
    snap = agent.record_manual_snapshot("comp_ev_test", data)

    for ev_id in snap.source_evidence_ids:
        evidence = store.get("source_evidence", ev_id)
        assert evidence is not None
