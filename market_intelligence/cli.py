#!/usr/bin/env python3
"""
Local Market Intelligence CLI
手動実行・データ管理・レポート生成のエントリーポイント。

使い方:
  python3 cli.py init                         # 初期化（マイグレーション）
  python3 cli.py demo                         # デモ実行（APIキー不要）
  python3 cli.py event run --store cafe_01    # 近隣イベントAgent実行
  python3 cli.py event calendar --store cafe_01 --days 30
  python3 cli.py competitor run --store cafe_01
  python3 cli.py competitor add              # 競合登録
  python3 cli.py competitor list             # 競合一覧
  python3 cli.py competitor snapshot --id comp_xxx  # 手動スナップショット
  python3 cli.py recommend list --store cafe_01
  python3 cli.py recommend approve --id rec_xxx
  python3 cli.py recommend reject --id rec_xxx
  python3 cli.py report html --store cafe_01  # HTMLレポート生成
  python3 cli.py status                       # 実行履歴・次回予定
  python3 cli.py events collect [--store cafe_01] [--days 90] [--no-llm] [--demo]
  python3 cli.py events build [--store all] [--no-llm]
  python3 cli.py events query --store cafe_01 [--business-unit cafe] [--from 2026-07-20] [--to 2026-07-26] [--json]
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from market_intelligence import config
from market_intelligence.storage import JsonStore
from market_intelligence.agents import LocalEventAgent, CompetitorAgent
from market_intelligence.llm import LLMProvider
from market_intelligence.utils import now_jst_iso, format_jst


def get_store(override_demo: bool = False) -> JsonStore:
    return JsonStore(config.DATA_DIR)


def get_agents(store: JsonStore):
    llm = LLMProvider() if config.is_llm_available() else None
    return LocalEventAgent(store, llm), CompetitorAgent(store, llm)


# ─── サブコマンド ────────────────────────────────────────────────────────────

def cmd_init(args):
    """スキーマ初期化（マイグレーション相当）"""
    store = get_store()
    store.initialize_schema()
    _seed_demo_stores(store)
    _seed_demo_competitors(store)
    print("[init] 初期化完了。demo modeで確認するには: python3 cli.py demo")


def _seed_demo_stores(store: JsonStore):
    """デモ用店舗プロファイルを初期設定する"""
    stores = [
        {
            "id": "cafe_01",
            "name": "[DEMO] 抹茶カフェ（新宿）",
            "business_unit": "cafe",
            "address": "東京都新宿区西新宿1-1-1",
            "latitude": 35.6895,
            "longitude": 139.6917,
            "timezone": "Asia/Tokyo",
            "search_radius_km": 3.0,
            "languages": ["ja", "en"],
            "target_segments": ["young_adults", "tourists", "couples"],
            "brand_positioning": "抹茶の本格体験と映えを提供する都市型カフェ。20代女性・インバウンド向け。",
            "menu": [
                {"name": "抹茶ラテ", "price": 650},
                {"name": "抹茶フローズン", "price": 700},
                {"name": "抹茶パフェ", "price": 1200},
                {"name": "抹茶テイクアウトカップ", "price": 600},
            ],
            "opening_hours": {"open": "09:00", "close": "21:00", "peak": ["14:00", "17:00"]},
            "delivery_areas": [],
            "enabled": True,
            "created_at": now_jst_iso(),
            "updated_at": now_jst_iso(),
        },
        {
            "id": "delivery_01",
            "name": "[DEMO] デリバリー専門混ぜそば（新宿）",
            "business_unit": "delivery",
            "address": "東京都新宿区西新宿2-2-2",
            "latitude": 35.6880,
            "longitude": 139.6930,
            "timezone": "Asia/Tokyo",
            "search_radius_km": 5.0,
            "languages": ["ja"],
            "target_segments": ["office_workers", "night_workers", "young_adults"],
            "brand_positioning": "深夜まで対応するデリバリー専門混ぜそば。ボリューム・満足感・コスパが強み。",
            "menu": [
                {"name": "混ぜそば（並）", "price": 950},
                {"name": "混ぜそば（大）", "price": 1150},
                {"name": "温玉追い飯セット", "price": 1300},
                {"name": "まぜそばセット（並＋温玉）", "price": 1100},
            ],
            "opening_hours": {"open": "11:00", "close": "03:00", "peak": ["20:00", "01:00"]},
            "delivery_areas": ["新宿区", "渋谷区", "中野区"],
            "enabled": True,
            "created_at": now_jst_iso(),
            "updated_at": now_jst_iso(),
        },
    ]
    for s in stores:
        if not store.exists("store_profiles", s["id"]):
            store.upsert("store_profiles", s)
            print(f"[init] 店舗プロファイルを作成: {s['name']}")


def _seed_demo_competitors(store: JsonStore):
    """デモ用競合プロファイルを初期設定する"""
    comps = [
        {
            "id": "demo_competitor_price_change",
            "name": "[DEMO] 競合混ぜそばA",
            "business_unit": "delivery",
            "category": "mazesoba",
            "address": "東京都新宿区○○町1-1",
            "latitude": 35.6870,
            "longitude": 139.6940,
            "distance_from_store_km": 0.8,
            "official_website_url": "",
            "public_menu_url": "",
            "monitoring_enabled": True,
            "monitoring_frequency": "daily",
            "notes": "デモデータ: 価格変更シナリオ用",
            "created_at": now_jst_iso(),
            "updated_at": now_jst_iso(),
        },
        {
            "id": "demo_competitor_new_set",
            "name": "[DEMO] 競合混ぜそばB",
            "business_unit": "delivery",
            "category": "mazesoba",
            "address": "東京都新宿区△△町2-3",
            "latitude": 35.6860,
            "longitude": 139.6950,
            "distance_from_store_km": 1.2,
            "official_website_url": "",
            "public_menu_url": "",
            "monitoring_enabled": True,
            "monitoring_frequency": "daily",
            "notes": "デモデータ: 新セット追加シナリオ用",
            "created_at": now_jst_iso(),
            "updated_at": now_jst_iso(),
        },
        {
            "id": "demo_competitor_hours_change",
            "name": "[DEMO] 競合混ぜそばC",
            "business_unit": "delivery",
            "category": "mazesoba",
            "address": "東京都新宿区□□町3-4",
            "latitude": 35.6850,
            "longitude": 139.6960,
            "distance_from_store_km": 1.5,
            "official_website_url": "",
            "public_menu_url": "",
            "monitoring_enabled": True,
            "monitoring_frequency": "daily",
            "notes": "デモデータ: 営業時間変更シナリオ用",
            "created_at": now_jst_iso(),
            "updated_at": now_jst_iso(),
        },
    ]
    # 競合Aの「前回スナップショット」（値上げ前）を設定
    prev_snap_a = {
        "id": "snap_demo_prev_a",
        "competitor_id": "demo_competitor_price_change",
        "captured_at": "2026-07-10T08:00:00+09:00",
        "source_evidence_ids": [],
        "menu_items": [{"name": "混ぜそば（並）", "price": 1000}, {"name": "混ぜそば（大）", "price": 1300}],
        "prices": {"混ぜそば（並）": 1000, "混ぜそば（大）": 1300},
        "sets": [],
        "discounts": [],
        "opening_hours": {"open": "11:00", "close": "21:00"},
        "order_availability": True,
        "rating": 4.1,
        "review_count": 225,
        "review_topics": {"味": 40, "量": 30, "価格": 25, "接客": 15},
        "content_hash": "prev_a_hash",
        "status": "success",
        "confidence": 0.9,
    }
    prev_snap_c = {
        "id": "snap_demo_prev_c",
        "competitor_id": "demo_competitor_hours_change",
        "captured_at": "2026-07-10T08:00:00+09:00",
        "source_evidence_ids": [],
        "menu_items": [{"name": "混ぜそば（並）", "price": 950}],
        "prices": {"混ぜそば（並）": 950},
        "sets": [],
        "discounts": [],
        "opening_hours": {"open": "11:00", "close": "21:00"},
        "order_availability": True,
        "rating": 3.9,
        "review_count": 90,
        "review_topics": {"味": 30, "量": 25, "価格": 15},
        "content_hash": "prev_c_hash",
        "status": "success",
        "confidence": 0.9,
    }

    for c in comps:
        if not store.exists("competitor_profiles", c["id"]):
            store.upsert("competitor_profiles", c)
            print(f"[init] 競合プロファイルを作成: {c['name']}")

    if not store.exists("competitor_snapshots", "snap_demo_prev_a"):
        store.upsert("competitor_snapshots", prev_snap_a)
    if not store.exists("competitor_snapshots", "snap_demo_prev_c"):
        store.upsert("competitor_snapshots", prev_snap_c)


def cmd_demo(args):
    """デモ実行（APIキー不要。フィクスチャを使用）"""
    os.environ["LOCAL_INTELLIGENCE_DEMO_MODE"] = "true"
    # config を再読み込みするために module を再利用
    import importlib
    import market_intelligence.config as cfg
    importlib.reload(cfg)

    print("=" * 60)
    print("[DEMO] Local Market Intelligence - デモ実行")
    print("このデータは架空のデモデータです。実在する店舗・競合ではありません。")
    print("=" * 60)

    store = get_store()
    store.initialize_schema()
    _seed_demo_stores(store)
    _seed_demo_competitors(store)

    llm = None
    event_agent = LocalEventAgent(store, llm)
    competitor_agent = CompetitorAgent(store, llm)

    print("\n--- 近隣イベントAgent（デモ）---")
    for store_id in ["cafe_01", "delivery_01"]:
        run = event_agent.run(store_id, trigger_type="demo")
        print(f"  店舗: {store_id} | 状態: {run.status} | 新規: {run.records_created} | 提案: {run.recommendations_created}")

    print("\n--- 競合モニタリングAgent（デモ）---")
    for store_id in ["cafe_01", "delivery_01"]:
        run = competitor_agent.run(store_id, trigger_type="demo")
        print(f"  店舗: {store_id} | 状態: {run.status} | 取得: {run.records_fetched} | 提案: {run.recommendations_created}")

    print("\n--- 販促カレンダー（cafe_01, 30日）---")
    cal = event_agent.get_promotional_calendar("cafe_01", days=30)
    for entry in cal[:3]:
        ev = entry["event"]
        print(f"  [{entry['days_until']}日後] {ev['title']} スコア={entry['score']['total']}")
        for r in entry["recommendations"][:2]:
            print(f"    → [{r['business_unit']}] {r['title']}")

    print("\n--- 競合差分サマリー ---")
    for comp in store.list_all("competitor_profiles"):
        diff = competitor_agent.get_latest_diff(comp["id"])
        if diff:
            print(f"  {comp['name']}: {diff.get('severity', '?')} 変更あり={diff.get('has_changes')}")
            for pc in diff.get("price_changes", []):
                print(f"    価格: {pc['item_name']} {pc['previous_price']}→{pc['current_price']} ({pc['change_rate_pct']:+.1f}%)")

    print("\n--- 提案一覧（draft）---")
    recs = store.list_all("recommendations")
    for r in recs[:5]:
        print(f"  [{r['business_unit']}][{r['urgency']}] {r['title']} (status={r['status']})")

    print("\n--- レポート生成 ---")
    _generate_html_report(store, event_agent, competitor_agent, "cafe_01")
    _generate_html_report(store, event_agent, competitor_agent, "delivery_01")
    print(f"\n[DEMO] 完了。レポートを確認: {config.REPORTS_DIR}/")


def cmd_event(args):
    if args.event_cmd == "run":
        store = get_store()
        event_agent, _ = get_agents(store)
        run = event_agent.run(args.store, trigger_type="manual", lookahead_days=args.days)
        print(f"実行完了: status={run.status} 新規={run.records_created} 更新={run.records_updated} 提案={run.recommendations_created}")
        if run.error_summary:
            print(f"エラー: {run.error_summary}")

    elif args.event_cmd == "calendar":
        store = get_store()
        event_agent, _ = get_agents(store)
        cal = event_agent.get_promotional_calendar(args.store, days=args.days, business_unit=args.unit)
        print(f"販促カレンダー（{args.store}, {args.days}日）")
        print("-" * 60)
        for entry in cal:
            ev = entry["event"]
            print(f"[{entry['days_until']}日後] {ev['title']}")
            print(f"  日時: {format_jst(ev['starts_at'])}")
            print(f"  会場: {ev.get('venue_name', '不明')} / 距離: {ev.get('distance_from_store_km', '?')}km")
            print(f"  スコア: {entry['score']['total']}/100 ({entry['score']['explanation']})")
            for r in entry["recommendations"][:2]:
                print(f"  提案[{r['business_unit']}]: {r['title']}")
            print()


def cmd_competitor(args):
    store = get_store()
    _, competitor_agent = get_agents(store)

    if args.competitor_cmd == "run":
        run = competitor_agent.run(args.store, trigger_type="manual")
        print(f"実行完了: status={run.status} 取得={run.records_fetched} 提案={run.recommendations_created}")

    elif args.competitor_cmd == "list":
        comps = store.list_all("competitor_profiles")
        print(f"競合一覧 ({len(comps)}件)")
        for c in comps:
            last_snap = competitor_agent.get_latest_diff(c["id"])
            status = "差分あり" if last_snap and last_snap.get("has_changes") else "-"
            print(f"  [{c['business_unit']}] {c['name']} | 監視={c.get('monitoring_enabled')} | {status}")

    elif args.competitor_cmd == "add":
        print("競合登録（JSONで入力してください）")
        print('例: {"name":"○○店","business_unit":"delivery","category":"mazesoba","address":"東京都..."}')
        data = json.loads(input("> "))
        c_id = competitor_agent.register_competitor(data)
        print(f"登録完了: {c_id}")

    elif args.competitor_cmd == "snapshot":
        print(f"競合 {args.id} の手動スナップショットを記録します（JSONで入力）")
        data = json.loads(input("> "))
        snap = competitor_agent.record_manual_snapshot(args.id, data)
        print(f"スナップショット保存: {snap.id}")

    elif args.competitor_cmd == "diff":
        diff = competitor_agent.get_latest_diff(args.id)
        if not diff:
            print("差分なし")
            return
        print(f"競合 {args.id} の最新差分 (重要度: {diff.get('severity')})")
        for pc in diff.get("price_changes", []):
            print(f"  価格変更: {pc['item_name']} {pc['previous_price']}→{pc['current_price']} ({pc['change_rate_pct']:+.1f}%)")
        for ni in diff.get("new_items", []):
            print(f"  新商品: {ni.get('name', '?')}")
        for ri in diff.get("removed_items", []):
            print(f"  終売: {ri.get('name', '?')}")
        for sc in diff.get("set_changes", []):
            print(f"  セット変更: {sc}")
        for hc in diff.get("opening_hours_changes", []):
            print(f"  営業時間変更: {hc['previous']} → {hc['current']}")


def cmd_recommend(args):
    store = get_store()

    if args.recommend_cmd == "list":
        filters = {"store_id": args.store} if args.store else {}
        recs = [r for r in store.list_all("recommendations")
                if all(r.get(k) == v for k, v in filters.items())]
        if args.status:
            recs = [r for r in recs if r.get("status") == args.status]
        print(f"提案一覧 ({len(recs)}件)")
        for r in recs:
            print(f"  [{r['id']}][{r['business_unit']}][{r.get('urgency','?')}][{r['status']}] {r['title']}")
            print(f"    {r['summary'][:60]}...")

    elif args.recommend_cmd == "approve":
        actor = args.actor or "cli_user"
        _approve_recommendation(store, args.id, "approved", actor, args.comment or "")

    elif args.recommend_cmd == "reject":
        actor = args.actor or "cli_user"
        _approve_recommendation(store, args.id, "rejected", actor, args.comment or "")


def _approve_recommendation(store: JsonStore, rec_id: str, action: str, actor: str, comment: str):
    rec = store.get("recommendations", rec_id)
    if not rec:
        print(f"提案が見つかりません: {rec_id}")
        return
    store.update_field("recommendations", rec_id, "status", action)
    store.update_field("recommendations", rec_id, "updated_at", now_jst_iso())
    history = {
        "id": f"ah_{rec_id[:8]}_{action}",
        "recommendation_id": rec_id,
        "action": action,
        "actor": actor,
        "comment": comment,
        "created_at": now_jst_iso(),
    }
    store.upsert("approval_history", history)
    print(f"提案を{action}にしました: {rec_id}")
    print("注: 承認されても外部投稿・価格変更は自動実行されません。別途手動で対応してください。")


def cmd_report(args):
    store = get_store()
    llm = LLMProvider() if config.is_llm_available() else None
    event_agent = LocalEventAgent(store, llm)
    competitor_agent = CompetitorAgent(store, llm)
    _generate_html_report(store, event_agent, competitor_agent, args.store)


def cmd_status(args):
    store = get_store()
    runs = sorted(store.list_all("agent_runs"), key=lambda r: r.get("started_at", ""), reverse=True)
    print(f"Agent実行履歴 ({len(runs)}件)")
    for r in runs[:10]:
        print(f"  [{r.get('started_at','?')[:16]}] {r['agent_type']} store={r['store_id']} status={r['status']}")
        if r.get("error_summary"):
            print(f"    エラー: {r['error_summary']}")

    warnings = config.validate_api_keys()
    if warnings:
        print("\n設定警告:")
        for w in warnings:
            print(f"  ⚠ {w}")


# ─── events サブコマンド ──────────────────────────────────────────────────────

def cmd_events(args):
    """events collect / build / query / mode / sync / shadow-report / source-status / source / event / config"""
    if args.events_cmd == "collect":
        _cmd_events_collect(args)
    elif args.events_cmd == "build":
        _cmd_events_build(args)
    elif args.events_cmd == "query":
        _cmd_events_query(args)
    elif args.events_cmd == "mode":
        _cmd_events_mode(args)
    elif args.events_cmd == "sync":
        _cmd_events_sync(args)
    elif args.events_cmd == "shadow-report":
        _cmd_events_shadow_report(args)
    elif args.events_cmd == "source-status":
        _cmd_events_source_status(args)
    elif args.events_cmd == "source":
        _cmd_events_source(args)
    elif args.events_cmd == "event":
        _cmd_events_event(args)
    elif args.events_cmd == "config":
        _cmd_events_config(args)
    else:
        print("サブコマンドを指定してください: collect / build / query / mode / sync / shadow-report / source-status / source / event / config")


def _require_llm_or_no_llm(args):
    """LLMモードのfail-fast: --no-llmなし + APIキー未設定 → exit(1)"""
    no_llm = getattr(args, "no_llm", False)
    if not no_llm and not config.is_llm_available():
        print(
            "[ERROR] ANTHROPIC_API_KEY が未設定です。\n"
            "  LLMなしで動作させるには --no-llm オプションを追加してください。\n"
            "  例: python3 market_intelligence/cli.py events collect --no-llm --demo",
            file=sys.stderr,
        )
        sys.exit(1)


def _cmd_events_collect(args):
    """イベント収集 → EventRecord, SourceEvidence, StoreEventAssessment 保存"""
    _require_llm_or_no_llm(args)

    store = get_store()
    store.initialize_schema()
    _seed_demo_stores(store)

    from market_intelligence.events.collect import collect_events

    demo = getattr(args, "demo", False)
    store_id = getattr(args, "store", None)
    days = getattr(args, "days", 90)

    print(f"[events collect] 開始 store={store_id or 'all'} days={days} demo={demo}")
    result = collect_events(
        store=store,
        store_id=store_id,
        days=days,
        demo=demo,
        no_llm=getattr(args, "no_llm", False),
    )
    print(f"[events collect] 完了: 新規={result['created']} 更新={result['updated']} アセスメント={result['assessments']}")
    if result["errors"]:
        print("[events collect] エラー:")
        for e in result["errors"]:
            print(f"  - {e}")


def _cmd_events_build(args):
    """保存済みデータからICS生成"""
    _require_llm_or_no_llm(args)

    store = get_store()
    from market_intelligence.events.service import build_feeds
    from pathlib import Path

    store_id_arg = getattr(args, "store", "all")
    store_id = None if (not store_id_arg or store_id_arg == "all") else store_id_arg

    print(f"[events build] 開始 store={store_id or 'all'}")
    generated = build_feeds(
        store=store,
        store_id=store_id,
        no_llm=getattr(args, "no_llm", False),
    )
    print(f"[events build] 完了: {len(generated)}件のICSを生成")
    for p in generated:
        print(f"  {p}")


def _cmd_events_query(args):
    """保存済みデータをJSON/テキストで返す（外部アクセスなし）"""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from market_intelligence.events.query import query_events

    TZ = ZoneInfo("Asia/Tokyo")
    now = datetime.now(TZ)

    store = get_store()
    store_id = getattr(args, "store", "cafe_01") or "cafe_01"
    business_unit = getattr(args, "business_unit", "all") or "all"
    from_date = getattr(args, "from_date", None) or now.date().isoformat()
    to_date = getattr(args, "to_date", None) or (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")
    as_json = getattr(args, "json_output", False)
    include_hidden = getattr(args, "include_hidden", False)

    result = query_events(
        store_id=store_id,
        business_unit=business_unit,
        from_date=from_date,
        to_date=to_date,
        store=store,
        include_hidden=include_hidden,
    )

    if as_json:
        # JSON出力時は警告をstderrに退避してstdoutをクリーンに保つ
        for w in result.get("warnings", []):
            print(f"[警告] {w}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_events_text(result)


def _cmd_events_mode(args):
    """
    モード表示 / 変更。

    モード設定は operational_overrides.json に保存される（git追跡対象）。
    変更後は commit/push することで GitHub Actions に反映される。
    """
    from market_intelligence.overrides.operational_overrides import (
        load_overrides, save_overrides, get_collection_mode, set_collection_mode
    )
    from market_intelligence.events.mode import VALID_MODES

    sub = getattr(args, "mode_cmd", "show")
    overrides = load_overrides()

    if sub == "show":
        tracked = get_collection_mode(overrides)
        print(f"追跡モード（operational_overrides.json）: {tracked}")
        print(f"  → GitHub Actions でもこのモードが使用されます")
        print(f"  → 変更後は commit/push が必要です")
    elif sub == "set":
        mode = args.mode
        if mode not in VALID_MODES:
            print(f"[ERROR] 不正なモード: {mode!r}  有効値: {sorted(VALID_MODES)}", file=sys.stderr)
            sys.exit(1)
        if mode == "active":
            print("[警告] active モードでは自動収集が canonical event_records へ直接書き込まれます。")
            print("  初回確認は shadow で行い、問題がないことを確認してから active に変更してください。")
            confirm = input("本当に active モードに変更しますか？ (yes/no): ").strip().lower()
            if confirm != "yes":
                print("キャンセルしました。")
                return
        set_collection_mode(overrides, mode)
        save_overrides(overrides)
        print(f"モードを '{mode}' に変更しました（operational_overrides.json）。")
        print(f"  → Actions への反映: operational_overrides.json を commit/push してください。")


def _cmd_events_sync(args):
    """
    events sync: operational_overrides.json のモードに従ってイベントを収集・同期する。

    モード優先順位:
      1. --mode CLI 引数
      2. operational_overrides.json の collection_mode
      3. デフォルト "shadow"（安全側）

    active  : 自動sourceをcanonical event_records へ書き込む
    shadow  : shadow_event_records へ書き込む（canonical は変更しない）
    manual-only: 外部collectorを実行しない

    全source失敗 かつ canonical snapshot なし → exit code 1
    """
    _require_llm_or_no_llm(args)
    store = get_store()
    store.initialize_schema()
    _seed_demo_stores(store)

    from market_intelligence.events.shadow import shadow_sync
    from market_intelligence.events.collect import collect_events_with_snapshot
    from market_intelligence.overrides.operational_overrides import (
        load_overrides, get_collection_mode,
        apply_source_overrides, apply_event_visibility_overrides
    )
    from market_intelligence.events.snapshot import (
        load_snapshot, save_snapshot, merge_with_snapshot, get_snapshot_source_ids
    )

    store_id = getattr(args, "store", None)
    days = getattr(args, "days", 120)
    no_llm = getattr(args, "no_llm", True)

    # 1. モード解決（CLI > overrides > shadow）
    overrides = load_overrides()
    cli_mode = getattr(args, "mode", "configured")
    if cli_mode and cli_mode != "configured":
        mode = cli_mode
    else:
        mode = get_collection_mode(overrides)
    print(f"[events sync] 収集モード: {mode}")

    # 2. store_profiles に operational_overrides を適用
    profiles = store.list_all("store_profiles")
    if profiles:
        profiles_ov = apply_source_overrides(profiles, overrides)
        for p in profiles_ov:
            store.upsert("store_profiles", p)
        n_ov = len(overrides.get("source_overrides", []))
        if n_ov:
            print(f"[events sync] source_overrides 適用: {n_ov} 件")

    # 3. 前回 canonical snapshot を読み込む
    snapshot = load_snapshot()
    snapshot_count = len(snapshot)
    if snapshot:
        print(f"[events sync] 前回 snapshot: {snapshot_count} 件")

    # 4. モード別収集
    collect_result: dict = {"created": 0, "updated": 0, "assessments": 0,
                            "errors": [], "failed_source_ids": [], "zero_result_source_ids": []}
    comparison: dict | None = None

    if mode == "manual-only":
        print("[events sync] manual-only: 外部 collector をスキップします")

    elif mode == "shadow":
        result = shadow_sync(store=store, store_id=store_id, days=days, no_llm=no_llm)
        collect_result = result["collect"]
        comparison = result["comparison"]

    elif mode == "active":
        collect_result = collect_events_with_snapshot(
            store=store, store_id=store_id, days=days, no_llm=no_llm, snapshot=snapshot
        )

    else:
        print(f"[ERROR] 不明なモード: {mode!r}", file=sys.stderr)
        sys.exit(1)

    # 5. 失敗・0件 ソースの報告
    failed_ids = set(collect_result.get("failed_source_ids", []))
    zero_ids = set(collect_result.get("zero_result_source_ids", []))
    errors = collect_result.get("errors", [])

    for e in errors:
        print(f"  [警告] {e}", file=sys.stderr)

    if failed_ids:
        print(f"[events sync] 収集失敗 source: {', '.join(sorted(failed_ids))}", file=sys.stderr)

    if zero_ids:
        # snapshot に同 source のイベントがあれば "parser変更疑い" として警告
        snap_sources = get_snapshot_source_ids(snapshot)
        suspicious = zero_ids & snap_sources
        if suspicious:
            print(
                f"[events sync] ⚠ 0件返却 source（前回は取得済み、parser変更の可能性）: "
                f"{', '.join(sorted(suspicious))}",
                file=sys.stderr,
            )
            print(f"  → 前回 snapshot のイベントを保持します", file=sys.stderr)
            # 0件source も failed_ids 相当として merge
            failed_ids |= suspicious

    # 6. 全 auto source 失敗 かつ snapshot なし → fail-safe
    if mode != "manual-only":
        current_profiles = store.list_all("store_profiles")
        from market_intelligence.events.mode import AUTO_SOURCE_TYPES
        enabled_auto_sources = {
            src.get("name", src.get("type", ""))
            for p in current_profiles
            for src in p.get("event_sources", [])
            if src.get("enabled", True) and src.get("type", "") in AUTO_SOURCE_TYPES
        }
        all_auto_failed = bool(enabled_auto_sources) and enabled_auto_sources.issubset(
            failed_ids | zero_ids
        )
        if all_auto_failed and snapshot_count == 0:
            print(
                "[ERROR] 全 auto source の取得に失敗し、前回 snapshot もありません。"
                " 空データでの上書きを防ぐため終了します。",
                file=sys.stderr,
            )
            sys.exit(1)

        if all_auto_failed and snapshot_count > 0:
            print(
                f"[events sync] ⚠ 全 auto source 失敗。前回 snapshot {snapshot_count} 件を保持します。",
                file=sys.stderr,
            )

    # 7. event_visibility_overrides を event_records に適用
    vis_ovs = overrides.get("event_visibility_overrides", [])
    if vis_ovs:
        all_events = store.list_all("event_records")
        events_vis = apply_event_visibility_overrides(all_events, overrides)
        applied_count = sum(1 for ev in events_vis if ev.get("visibility") == "hidden")
        for ev in events_vis:
            store.upsert("event_records", ev)
        if applied_count:
            print(f"[events sync] event_visibility_overrides 適用: {applied_count} 件 hidden")

    # 8. canonical snapshot を更新
    #    全 source 失敗 + snapshot あり の場合: snapshot を保持（空で上書きしない）
    events_to_snap = store.list_all("event_records")
    if not events_to_snap and snapshot:
        print(f"[events sync] event_records が空のため、前回 snapshot を保持します")
        events_to_snap = snapshot  # snapshot はそのまま維持

    if events_to_snap:
        save_snapshot(events_to_snap)
        print(f"[events sync] canonical snapshot 更新: {len(events_to_snap)} 件")

    # 9. 結果表示
    print(
        f"[events sync] 完了: 新規={collect_result.get('created', 0)}"
        f" 更新={collect_result.get('updated', 0)}"
        f" アセスメント={collect_result.get('assessments', 0)}"
    )
    if comparison:
        print(f"  shadow件数: {comparison['shadow_total']}  "
              f"canonical件数: {comparison['canonical_total']}  "
              f"マッチ: {len(comparison['matched'])}件")


def _cmd_events_shadow_report(args):
    """shadow vs canonical 比較レポートを表示"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from market_intelligence.events.shadow import compare_shadow_vs_canonical

    store = get_store()
    TZ = ZoneInfo("Asia/Tokyo")

    from_dt = None
    to_dt = None
    if getattr(args, "from_date", None):
        try:
            from_dt = datetime.fromisoformat(args.from_date).replace(tzinfo=TZ)
        except Exception:
            print(f"--from の日付フォーマットが不正です: {args.from_date}", file=sys.stderr)

    if getattr(args, "to_date", None):
        try:
            to_dt = datetime.fromisoformat(args.to_date).replace(tzinfo=TZ)
        except Exception:
            print(f"--to の日付フォーマットが不正です: {args.to_date}", file=sys.stderr)

    comparison = compare_shadow_vs_canonical(store, from_dt=from_dt, to_dt=to_dt)

    if getattr(args, "json_output", False):
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
        return

    print(f"=== Shadow vs Canonical 比較レポート ===")
    print(f"shadow件数: {comparison['shadow_total']}")
    print(f"canonical件数: {comparison['canonical_total']}")
    print(f"マッチ: {len(comparison['matched'])}件")
    print(f"shadow_only（新規候補）: {len(comparison['shadow_only'])}件")
    print(f"canonical_only（手動のみ）: {len(comparison['canonical_only'])}件")

    if comparison["shadow_only"]:
        print("\n【shadow_only イベント（自動収集済み・canonical未収録）】")
        for ev in comparison["shadow_only"][:10]:
            print(f"  {ev.get('starts_at','?')[:10]} {ev.get('title','?')}")
        if len(comparison["shadow_only"]) > 10:
            print(f"  ... 他{len(comparison['shadow_only']) - 10}件")

    if comparison["canonical_only"]:
        print("\n【canonical_only イベント（手動登録・shadow未収録）】")
        for ev in comparison["canonical_only"][:10]:
            print(f"  {ev.get('starts_at','?')[:10]} {ev.get('title','?')}")
        if len(comparison["canonical_only"]) > 10:
            print(f"  ... 他{len(comparison['canonical_only']) - 10}件")

    if comparison["matched"]:
        print(f"\n【マッチしたイベント（上位5件）】")
        for pair in comparison["matched"][:5]:
            print(f"  {pair.get('starts_at','?')[:10]} {pair.get('title','?')}")


def _cmd_events_source_status(args):
    """自動収集ソースの最終取得状況を表示"""
    from market_intelligence.events.shadow import get_source_status

    store = get_store()
    statuses = get_source_status(store)

    if getattr(args, "json_output", False):
        print(json.dumps(statuses, ensure_ascii=False, indent=2))
        return

    if not statuses:
        print("shadow_source_evidence にデータがありません。先に 'events sync' を実行してください。")
        return

    print(f"=== ソース取得状況 ({len(statuses)}件) ===")
    for s in statuses:
        print(f"  [{s.get('source_type','?')}] {s.get('source_name','?')} 最終取得: {s.get('last_fetched_at','?')[:16]}")


def _cmd_events_source(args):
    """events source pause / resume / status — source の一時停止・再開・状態確認"""
    from market_intelligence.events.source_control import pause_source, resume_source, list_source_status

    sub = getattr(args, "source_cmd", "status")
    store = get_store()

    if sub == "pause":
        store_id = getattr(args, "store", None)
        reason = getattr(args, "reason", "")
        planned_resume_at = getattr(args, "planned_resume_at", None)
        updated = pause_source(
            store,
            source_name=args.name,
            store_id=store_id,
            reason=reason,
            planned_resume_at=planned_resume_at,
        )
        if updated:
            scope = f"店舗 {store_id}" if store_id else "全店舗"
            print(f"[source pause] '{args.name}' を一時停止しました（{scope}）")
            print(f"  対象: {', '.join(updated)}")
            if reason:
                print(f"  理由: {reason}")
            if planned_resume_at:
                print(f"  再開予定（メモ）: {planned_resume_at}（自動再開はしません）")
        else:
            print(f"[source pause] 該当するソースが見つかりませんでした: {args.name}", file=sys.stderr)

    elif sub == "resume":
        store_id = getattr(args, "store", None)
        updated = resume_source(store, source_name=args.name, store_id=store_id)
        if updated:
            scope = f"店舗 {store_id}" if store_id else "全店舗"
            print(f"[source resume] '{args.name}' を再開しました（{scope}）")
            print(f"  対象: {', '.join(updated)}")
        else:
            print(f"[source resume] 該当するソースが見つかりませんでした: {args.name}", file=sys.stderr)

    elif sub == "status":
        store_id = getattr(args, "store", None)
        statuses = list_source_status(store, store_id=store_id)
        if getattr(args, "json_output", False):
            print(json.dumps(statuses, ensure_ascii=False, indent=2))
            return
        if not statuses:
            print("ソース設定が見つかりません。")
            return
        print(f"=== Source 状態一覧 ({len(statuses)}件) ===")
        for s in statuses:
            enabled_str = "✅ 有効" if s["enabled"] else "⏸ 停止中"
            print(f"  [{s['store_id']}] [{s['source_type']}] {s['source_name']} — {enabled_str}")
            if not s["enabled"]:
                print(f"    停止日時: {s.get('paused_at', '?')}")
                if s.get("pause_reason"):
                    print(f"    理由: {s['pause_reason']}")
                planned = s.get("planned_resume_at") or s.get("resume_at")
                if planned:
                    print(f"    再開予定（メモ）: {planned}（自動再開はしません）")


def _cmd_events_event(args):
    """events event hide / show / list — イベントの非表示制御"""
    from market_intelligence.events.source_control import hide_event, show_event, list_events_admin

    sub = getattr(args, "event_sub_cmd", "list")
    store = get_store()

    if sub == "hide":
        reason = getattr(args, "reason", "")
        by = getattr(args, "by", "cli")
        ok = hide_event(store, event_id=args.id, reason=reason, suppressed_by=by)
        if ok:
            print(f"[event hide] イベントを非表示にしました: {args.id}")
            print("  公開ICS・通常query・Recommendationから除外されます。")
            print("  元の status は変更されていません。--include-hidden で確認できます。")
        else:
            print(f"[event hide] イベントが見つかりません: {args.id}", file=sys.stderr)

    elif sub == "show":
        ok = show_event(store, event_id=args.id)
        if ok:
            print(f"[event show] イベントを再表示しました: {args.id}")
        else:
            print(f"[event show] イベントが見つかりません: {args.id}", file=sys.stderr)

    elif sub == "list":
        include_hidden = getattr(args, "include_hidden", False)
        events = list_events_admin(store, include_hidden=include_hidden)
        if getattr(args, "json_output", False):
            # visibility・suppression フィールドのみ抜粋してJSON出力
            out = [
                {
                    "id": e.get("id", ""),
                    "title": e.get("title", ""),
                    "starts_at": e.get("starts_at", ""),
                    "status": e.get("status", "confirmed"),
                    "visibility": e.get("visibility", "visible"),
                    "suppression_reason": e.get("suppression_reason"),
                    "suppressed_at": e.get("suppressed_at"),
                }
                for e in events
            ]
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return
        hidden_events = [e for e in events if e.get("visibility", "visible") == "hidden"]
        visible_events = [e for e in events if e.get("visibility", "visible") != "hidden"]
        print(f"=== イベント一覧 ===")
        print(f"表示中: {len(visible_events)}件  非表示: {len(hidden_events)}件")
        if include_hidden and hidden_events:
            print("\n【非表示イベント】")
            for e in hidden_events:
                print(f"  [{e.get('id','')}] {e.get('starts_at','?')[:10]} {e.get('title','?')}")
                print(f"    status={e.get('status','confirmed')}  reason={e.get('suppression_reason','')}")


def _cmd_events_config(args):
    """events config create-demo / validate — store_profiles.json の生成・検証"""
    sub = getattr(args, "config_cmd", None)

    if sub == "create-demo":
        from market_intelligence.events.demo_config import write_demo_profiles
        from pathlib import Path as _Path

        output_arg = getattr(args, "output", None)
        if output_arg:
            output_path = _Path(output_arg)
        else:
            output_path = _Path(config.DATA_DIR) / "store_profiles.json"

        try:
            write_demo_profiles(output_path)
            print(f"[events config create-demo] デモプロファイルを生成しました: {output_path}")
        except Exception as e:
            print(f"[ERROR] デモプロファイルの生成に失敗しました: {e}", file=sys.stderr)
            sys.exit(1)

    elif sub == "validate":
        from market_intelligence.events.config_validator import validate_store_profiles
        from pathlib import Path as _Path
        import json as _json

        file_arg = getattr(args, "file", None)
        if file_arg:
            file_path = _Path(file_arg)
        else:
            file_path = _Path(config.DATA_DIR) / "store_profiles.json"

        if not file_path.exists():
            print(f"[ERROR] ファイルが見つかりません: {file_path}", file=sys.stderr)
            sys.exit(1)

        try:
            data = _json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[ERROR] JSONパース失敗: {e}", file=sys.stderr)
            sys.exit(1)

        errors = validate_store_profiles(data)
        if errors:
            print(f"[events config validate] バリデーションエラー ({len(errors)}件):", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)
        else:
            profile_count = len(data) if isinstance(data, list) else 0
            print(f"[events config validate] OK: {file_path} ({profile_count}件のプロファイル)")

    else:
        print("サブコマンドを指定してください: create-demo / validate")


def _print_events_text(result: dict) -> None:
    """イベントクエリ結果をテキスト形式で表示する"""
    store_info = result.get("store", {})
    rng = result.get("range", {})
    events = result.get("events", [])
    warnings = result.get("warnings", [])

    print(f"=== イベント一覧 ===")
    print(f"店舗: {store_info.get('name', '?')} ({store_info.get('business_unit', '?')})")
    print(f"期間: {rng.get('from', '?')[:10]} 〜 {rng.get('to', '?')[:10]}")
    print(f"件数: {len(events)}件")
    print()

    if not events:
        print("（イベントなし）")
        print("ヒント: 先に 'events collect --demo --no-llm' を実行してください。")
        return

    for ev in events:
        score = ev.get("impact_score", 0)
        stars = "★" * score if score > 0 else "☆"
        print(f"[{stars}] {ev.get('title', '?')}")
        print(f"  日時: {ev.get('starts_at', '?')[:16]} 〜 {(ev.get('ends_at') or '')[:16]}")
        print(f"  会場: {ev.get('venue_name', '?')}")
        if ev.get("distance_m") is not None:
            print(f"  距離: {ev['distance_m']}m")
        print(f"  カテゴリ: {ev.get('category', '?')}")
        signals = ev.get("operational_signals", [])
        if signals:
            print(f"  シグナル: {', '.join(signals)}")
        print()

    if warnings:
        print("注意:")
        for w in warnings:
            print(f"  - {w}")


def _generate_html_report(store, event_agent, competitor_agent, store_id: str):
    """HTMLレポートを生成する"""
    from market_intelligence.reports import generate_dashboard_html
    store_profile = store.get("store_profiles", store_id)
    if not store_profile:
        print(f"店舗が見つかりません: {store_id}")
        return
    html = generate_dashboard_html(store, event_agent, competitor_agent, store_profile)
    out = config.REPORTS_DIR / f"dashboard_{store_id}.html"
    out.write_text(html, encoding="utf-8")
    print(f"HTMLレポート生成: {out}")

    # docs/ にもコピー（既存のdocsフォルダに合わせる）
    docs_dir = ROOT.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    docs_out = docs_dir / f"market-intelligence-{store_id}.html"
    docs_out.write_text(html, encoding="utf-8")
    print(f"docsにもコピー: {docs_out}")


# ─── メインパーサー ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Local Market Intelligence CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init", help="初期化（マイグレーション）")
    sub.add_parser("demo", help="デモ実行（APIキー不要）")

    # event
    ep = sub.add_parser("event", help="近隣イベントAgent")
    esub = ep.add_subparsers(dest="event_cmd")
    er = esub.add_parser("run"); er.add_argument("--store", required=True); er.add_argument("--days", type=int, default=90)
    ec = esub.add_parser("calendar"); ec.add_argument("--store", required=True); ec.add_argument("--days", type=int, default=30); ec.add_argument("--unit", choices=["cafe","delivery","both"])

    # competitor
    cp_p = sub.add_parser("competitor", help="競合モニタリングAgent")
    csub = cp_p.add_subparsers(dest="competitor_cmd")
    cr = csub.add_parser("run"); cr.add_argument("--store", required=True)
    csub.add_parser("list")
    csub.add_parser("add")
    csnap = csub.add_parser("snapshot"); csnap.add_argument("--id", required=True)
    cdiff = csub.add_parser("diff"); cdiff.add_argument("--id", required=True)

    # recommend
    rp = sub.add_parser("recommend", help="提案管理")
    rsub = rp.add_subparsers(dest="recommend_cmd")
    rl = rsub.add_parser("list"); rl.add_argument("--store"); rl.add_argument("--status")
    ra = rsub.add_parser("approve"); ra.add_argument("--id", required=True); ra.add_argument("--actor"); ra.add_argument("--comment")
    rr = rsub.add_parser("reject"); rr.add_argument("--id", required=True); rr.add_argument("--actor"); rr.add_argument("--comment")

    # report
    rpt = sub.add_parser("report", help="レポート生成")
    rsub2 = rpt.add_subparsers(dest="report_cmd")
    rh = rsub2.add_parser("html"); rh.add_argument("--store", required=True)

    sub.add_parser("status", help="実行履歴")

    # events（Phase 1: イベントICSフィード）
    evs_p = sub.add_parser("events", help="近隣イベントICSフィード管理")
    evs_sub = evs_p.add_subparsers(dest="events_cmd")

    # events collect
    evc = evs_sub.add_parser("collect", help="イベント収集・保存")
    evc.add_argument("--store", default=None, help="店舗ID（省略時は全店舗）")
    evc.add_argument("--days", type=int, default=90, help="先読み日数（デフォルト90）")
    evc.add_argument("--no-llm", dest="no_llm", action="store_true", help="LLMを使わずに動作")
    evc.add_argument("--demo", action="store_true", help="デモデータを使用")

    # events build
    evb = evs_sub.add_parser("build", help="保存済みデータからICS生成")
    evb.add_argument("--store", default="all", help="店舗ID（all=全店舗）")
    evb.add_argument("--no-llm", dest="no_llm", action="store_true", help="LLMを使わずに動作")

    # events query
    evq = evs_sub.add_parser("query", help="保存済みデータをJSON/テキストで返す")
    evq.add_argument("--store", required=True, help="店舗ID")
    evq.add_argument("--business-unit", dest="business_unit", default="all",
                     choices=["cafe", "delivery", "both", "all"], help="業態フィルタ")
    evq.add_argument("--from", dest="from_date", default=None, help="開始日 YYYY-MM-DD")
    evq.add_argument("--to", dest="to_date", default=None, help="終了日 YYYY-MM-DD")
    evq.add_argument("--json", dest="json_output", action="store_true", help="JSON形式で出力")
    evq.add_argument("--include-hidden", dest="include_hidden", action="store_true",
                     help="非表示イベント（visibility=hidden）を含める（管理用）")

    # events mode
    evm_p = evs_sub.add_parser("mode", help="収集モードの表示・変更")
    evm_sub = evm_p.add_subparsers(dest="mode_cmd")
    evm_sub.add_parser("show")
    evm_set = evm_sub.add_parser("set", help="収集モードを変更（operational_overrides.json に保存）")
    evm_set.add_argument("--mode", required=True, choices=["shadow", "active", "manual-only"])

    # events sync
    evs2 = evs_sub.add_parser(
        "sync",
        help="operational_overrides.json のモードに従ってイベントを収集・同期する",
    )
    evs2.add_argument(
        "--mode", default="configured",
        choices=["configured", "shadow", "active", "manual-only"],
        help=(
            "収集モード。'configured'（デフォルト）= operational_overrides.json の値を使用。"
            " それ以外は明示指定（設定ファイルは更新しない）。"
        ),
    )
    evs2.add_argument("--store", default=None, help="店舗ID（省略時は全店舗）")
    evs2.add_argument("--days", type=int, default=120, help="先読み日数（デフォルト120）")
    evs2.add_argument("--no-llm", dest="no_llm", action="store_true", default=True, help="LLMを使わずに動作")

    # events shadow-report
    evsr = evs_sub.add_parser("shadow-report", help="shadow vs canonical 比較レポート")
    evsr.add_argument("--from", dest="from_date", default=None, help="開始日 YYYY-MM-DD")
    evsr.add_argument("--to", dest="to_date", default=None, help="終了日 YYYY-MM-DD")
    evsr.add_argument("--json", dest="json_output", action="store_true", help="JSON形式で出力")

    # events source-status
    evss = evs_sub.add_parser("source-status", help="自動収集ソースの最終取得状況")
    evss.add_argument("--json", dest="json_output", action="store_true", help="JSON形式で出力")

    # events source (pause / resume / status)
    evsrc_p = evs_sub.add_parser("source", help="source の一時停止・再開・状態確認")
    evsrc_sub = evsrc_p.add_subparsers(dest="source_cmd")

    evsrc_pause = evsrc_sub.add_parser("pause", help="source を一時停止（設定は削除しない）")
    evsrc_pause.add_argument("--name", required=True, help="source名（例: Doorkeeper新宿）")
    evsrc_pause.add_argument("--store", default=None, help="店舗ID（省略時は全店舗）")
    evsrc_pause.add_argument("--reason", default="", help="停止理由")
    evsrc_pause.add_argument("--planned-resume-at", dest="planned_resume_at", default=None,
                             help="再開予定日 YYYY-MM-DD（メモのみ。自動再開はしません）")
    # 後方互換のため --resume-at も受け付ける（非推奨）
    evsrc_pause.add_argument("--resume-at", dest="planned_resume_at", default=None,
                             help=argparse.SUPPRESS)

    evsrc_resume = evsrc_sub.add_parser("resume", help="停止中の source を再開")
    evsrc_resume.add_argument("--name", required=True, help="source名")
    evsrc_resume.add_argument("--store", default=None, help="店舗ID（省略時は全店舗）")

    evsrc_status = evsrc_sub.add_parser("status", help="全 source の状態一覧")
    evsrc_status.add_argument("--store", default=None, help="店舗ID（省略時は全店舗）")
    evsrc_status.add_argument("--json", dest="json_output", action="store_true")

    # events event (hide / show / list)
    evevt_p = evs_sub.add_parser("event", help="イベントの非表示制御（visibility）")
    evevt_sub = evevt_p.add_subparsers(dest="event_sub_cmd")

    evevt_hide = evevt_sub.add_parser("hide", help="イベントを非表示にする（status は変更しない）")
    evevt_hide.add_argument("--id", required=True, help="イベントID（evt_xxx）")
    evevt_hide.add_argument("--reason", default="", help="非表示理由")
    evevt_hide.add_argument("--by", default="cli", help="操作者")

    evevt_show = evevt_sub.add_parser("show", help="非表示イベントを再表示する")
    evevt_show.add_argument("--id", required=True, help="イベントID（evt_xxx）")

    evevt_list = evevt_sub.add_parser("list", help="イベント一覧（visibility 状態付き）")
    evevt_list.add_argument("--include-hidden", dest="include_hidden", action="store_true",
                            help="非表示イベントも含めて表示")
    evevt_list.add_argument("--json", dest="json_output", action="store_true")

    # events config
    evcfg_p = evs_sub.add_parser("config", help="store_profiles.json の生成・検証")
    evcfg_sub = evcfg_p.add_subparsers(dest="config_cmd")

    evcfg_demo = evcfg_sub.add_parser("create-demo", help="デモ用 store_profiles.json を生成")
    evcfg_demo.add_argument("--output", default=None,
                            help="出力先パス（省略時は market_intelligence/data/store_profiles.json）")

    evcfg_validate = evcfg_sub.add_parser("validate", help="store_profiles.json のスキーマ検証")
    evcfg_validate.add_argument("--file", default=None,
                                help="検証するファイルパス（省略時は market_intelligence/data/store_profiles.json）")

    args = parser.parse_args()

    # APIキー警告（クラッシュさせない）
    for w in config.validate_api_keys():
        print(f"[警告] {w}", file=sys.stderr)

    dispatch = {
        "init": cmd_init,
        "demo": cmd_demo,
        "event": cmd_event,
        "events": cmd_events,
        "competitor": cmd_competitor,
        "recommend": cmd_recommend,
        "report": cmd_report,
        "status": cmd_status,
    }

    if args.cmd in dispatch:
        dispatch[args.cmd](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
