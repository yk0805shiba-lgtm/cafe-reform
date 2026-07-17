"""
保存済みEventRecordとStoreEventAssessmentを読んでICSを生成する。
外部サイトへアクセスしない。
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..storage import JsonStore
from .ics_builder import build_ics_feed

TZ = ZoneInfo("Asia/Tokyo")

# ICS出力先（ローカルHTTP配信用）
FEEDS_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "docs" / "market-intelligence" / "events"

# フィルタ対象: 過去7日〜未来120日
PAST_DAYS = 7
FUTURE_DAYS = 120


def build_feeds(
    store: JsonStore,
    store_id: str | None = None,
    business_unit: str | None = None,
    output_dir: Path | None = None,
    no_llm: bool = True,
) -> list[Path]:
    """
    保存済みEventRecord + StoreEventAssessmentを読んでICSを生成する。
    戻り値: 生成したICSファイルのパスリスト
    """
    out_dir = output_dir or FEEDS_DIR_DEFAULT
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(TZ)
    from_dt = now - timedelta(days=PAST_DAYS)
    to_dt = now + timedelta(days=FUTURE_DAYS)

    # 全EventRecordを読む
    all_events = store.list_all("event_records")

    # shadow mode 等で event_records が空の場合、canonical_events.json をフォールバックとして使う
    if not all_events:
        canonical_path = Path(__file__).resolve().parents[2] / "state" / "canonical_events.json"
        if canonical_path.exists():
            try:
                all_events = json.loads(canonical_path.read_text(encoding="utf-8"))
                print(f"[events build] canonical_events.json からフォールバック: {len(all_events)} 件")
            except Exception:
                pass

    # 全StoreEventAssessmentを読む
    all_assessments = store.list_all("store_event_assessments")

    # assessment indexを作る: event_uid -> {store_id -> {business_unit -> dict}}
    asm_index: dict[str, dict] = {}
    for asm in all_assessments:
        evt_uid = asm.get("event_uid", "")
        sid = asm.get("store_id", "")
        bu = asm.get("business_unit", "")
        if evt_uid not in asm_index:
            asm_index[evt_uid] = {}
        key = f"{sid}:{bu}"
        asm_index[evt_uid][key] = asm

    # 日付フィルタ
    def in_range(ev: dict) -> bool:
        starts = ev.get("starts_at", "")
        if not starts:
            return False
        try:
            dt = datetime.fromisoformat(starts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            return from_dt <= dt <= to_dt
        except Exception:
            return False

    # 公開 ICS: 非表示イベント（visibility=hidden）は除外する
    # 公式キャンセル（status=cancelled）はICSに含む（status=cancelledがない場合と同様に扱う）
    filtered_events = [
        ev for ev in all_events
        if in_range(ev) and ev.get("visibility", "visible") != "hidden"
    ]

    generated: list[Path] = []

    # 対象ストア・business_unit の組み合わせを収集
    targets: list[tuple[str | None, str | None, str]] = []

    if store_id is None and business_unit is None:
        # 全店舗・全フィード（cafe / delivery / store-all）
        store_profiles = store.list_all("store_profiles")
        for sp in store_profiles:
            sid = sp["id"]
            bu_val = sp.get("business_unit", "cafe")
            if bu_val == "both":
                targets.append((sid, "cafe", f"{sid}_cafe"))
                targets.append((sid, "delivery", f"{sid}_delivery"))
            else:
                targets.append((sid, bu_val, f"{sid}_{bu_val}"))
        # 全体フィード
        targets.append((None, None, "all"))
        targets.append((None, "cafe", "cafe"))
        targets.append((None, "delivery", "delivery"))
    else:
        sid = store_id
        bu = business_unit
        name = "_".join(filter(None, [sid or "all", bu or "all"]))
        targets.append((sid, bu, name))

    for (target_sid, target_bu, feed_name) in targets:
        items = _filter_events_for_feed(
            filtered_events, asm_index, target_sid, target_bu
        )
        if not items:
            # 空フィードも生成（存在チェックのため）
            pass

        ics_path = out_dir / f"{feed_name}.ics"
        calname = _make_calname(target_sid, target_bu, store)
        try:
            build_ics_feed(
                events_with_assessments=items,
                calname=calname,
                store_id=target_sid,
                business_unit=target_bu,
                output_path=ics_path,
            )
            generated.append(ics_path)
        except Exception as e:
            print(f"[ics_service] ICS生成失敗 feed={feed_name}: {e}")

    return generated


def _filter_events_for_feed(
    events: list[dict],
    asm_index: dict[str, dict],
    store_id: str | None,
    business_unit: str | None,
) -> list[dict]:
    """
    指定条件に合うイベント+assessmentペアのリストを返す。
    assessmentが見つからない場合はデフォルト値を使う。
    """
    items: list[dict] = []
    for ev in events:
        uid = ev.get("uid") or ev.get("id", "")
        ev_asms = asm_index.get(uid, {})

        # マッチするassessmentを探す
        matched_asm = None
        if store_id and business_unit:
            key = f"{store_id}:{business_unit}"
            matched_asm = ev_asms.get(key)
        elif store_id:
            # store_id一致で最高スコアのasm
            for key, asm in ev_asms.items():
                if key.startswith(f"{store_id}:"):
                    if matched_asm is None or asm.get("impact_score", 0) > matched_asm.get("impact_score", 0):
                        matched_asm = asm
        elif business_unit:
            # business_unit一致で最高スコアのasm
            for key, asm in ev_asms.items():
                if key.endswith(f":{business_unit}"):
                    if matched_asm is None or asm.get("impact_score", 0) > matched_asm.get("impact_score", 0):
                        matched_asm = asm
        else:
            # 全体: 最高スコアのasm
            for asm in ev_asms.values():
                if matched_asm is None or asm.get("impact_score", 0) > matched_asm.get("impact_score", 0):
                    matched_asm = asm

        # assessmentがない場合はデフォルト値を使う
        if matched_asm is None:
            matched_asm = {
                "impact_score": 0,
                "impact_reasons": ["no_assessment"],
                "operational_signals": [],
                "store_id": store_id or "",
                "business_unit": business_unit or "unknown",
                "distance_m": None,
            }

        items.append({"event": ev, "assessment": matched_asm})

    return items


def _make_calname(store_id: str | None, business_unit: str | None, store: JsonStore) -> str:
    if store_id:
        sp = store.get("store_profiles", store_id)
        if sp:
            name = sp.get("name", store_id)
            if business_unit:
                return f"{name} ({business_unit})"
            return name
    if business_unit:
        return f"Local Events ({business_unit})"
    return "Local Events (All)"
