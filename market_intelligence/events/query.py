"""
保存済み正規化データを読む。外部サイトへアクセスしない。
CLIから呼ばれてJSONを返す。
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from ..storage import JsonStore

TZ = ZoneInfo("Asia/Tokyo")


def query_events(
    store_id: str,
    business_unit: str,  # "cafe" | "delivery" | "both" | "all"
    from_date: str,
    to_date: str,
    store: JsonStore,
    include_hidden: bool = False,
) -> dict:
    """
    保存済み正規化データを読む。外部サイトへアクセスしない。

    返却形式:
    {
      "generated_from": "normalized_event_store",
      "range": {"from": "...", "to": "...", "timezone": "Asia/Tokyo"},
      "store": {"id": "...", "name": "...", "business_unit": "..."},
      "events": [...impact_score降順, start昇順, uid昇順...],
      "warnings": []
    }

    各イベントに含まれるフィールド（Phase 5追加分を含む）:
      uid, title, starts_at, ends_at, all_day, venue_name, address,
      distance_m, impact_score, impact_reasons, operational_signals,
      category, source_id, source_url, fetched_at, confidence,
      status, cancelled, merged_from_source_ids, data_warnings
    """
    warnings: list[str] = []

    # 店舗プロファイル取得
    store_profile = None
    store_name = store_id
    actual_bu = business_unit

    if store_id and store_id != "all":
        store_profile = store.get("store_profiles", store_id)
        if store_profile:
            store_name = store_profile.get("name", store_id)
            if actual_bu in ("all", "both") or not actual_bu:
                actual_bu = store_profile.get("business_unit", "cafe")
        else:
            warnings.append(f"店舗プロファイルが見つかりません: {store_id}")

    # 日付パース
    try:
        from_dt = datetime.fromisoformat(from_date)
        if from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=TZ)
    except Exception:
        from_dt = datetime.now(TZ)
        warnings.append(f"from_date のパース失敗: {from_date}")

    try:
        to_dt = datetime.fromisoformat(to_date)
        if to_dt.tzinfo is None:
            to_dt = to_dt.replace(tzinfo=TZ)
    except Exception:
        from datetime import timedelta
        to_dt = datetime.now(TZ) + timedelta(days=7)
        warnings.append(f"to_date のパース失敗: {to_date}")

    # EventRecord + assessment を結合
    all_events = store.list_all("event_records")
    all_assessments = store.list_all("store_event_assessments")

    # assessment index: event_uid -> list[dict]
    asm_by_uid: dict[str, list[dict]] = {}
    for asm in all_assessments:
        uid = asm.get("event_uid", "")
        if uid not in asm_by_uid:
            asm_by_uid[uid] = []
        asm_by_uid[uid].append(asm)

    result_events: list[dict] = []
    cancelled_count = 0
    hidden_count = 0

    for ev in all_events:
        # 日付フィルタ
        starts_raw = ev.get("starts_at", "")
        if not starts_raw:
            continue
        try:
            starts_dt = datetime.fromisoformat(starts_raw)
            if starts_dt.tzinfo is None:
                starts_dt = starts_dt.replace(tzinfo=TZ)
        except Exception:
            continue

        if not (from_dt <= starts_dt <= to_dt):
            continue

        # 公式キャンセル済みはカウントして除外
        if ev.get("status") == "cancelled":
            cancelled_count += 1
            continue

        # 店舗側の非表示（visibility=hidden）は通常クエリから除外
        if not include_hidden and ev.get("visibility", "visible") == "hidden":
            hidden_count += 1
            continue

        uid = ev.get("uid") or ev.get("id", "")
        ev_asms = asm_by_uid.get(uid, [])

        # 対象business_unitに合うassessmentを探す
        matched_asm = _find_best_assessment(ev_asms, store_id, business_unit)

        event_entry = dict(ev)
        event_entry["_assessment"] = matched_asm or {
            "impact_score": 0,
            "impact_reasons": ["no_assessment"],
            "operational_signals": [],
            "distance_m": None,
        }
        result_events.append(event_entry)

    if cancelled_count > 0:
        warnings.append(f"キャンセル済みイベントを {cancelled_count} 件除外しました（status=cancelled）")
    if hidden_count > 0:
        warnings.append(f"非表示イベントを {hidden_count} 件除外しました（visibility=hidden）。--include-hidden で確認できます")

    # sort: impact_score降順 → start昇順 → uid昇順
    result_events.sort(
        key=lambda e: (
            -e["_assessment"].get("impact_score", 0),
            e.get("starts_at", ""),
            e.get("uid") or e.get("id", ""),
        )
    )

    # _assessment をフラット化してeventに含める
    output_events = []
    for entry in result_events:
        asm = entry.pop("_assessment")
        confidence = entry.get("confidence", 1.0)
        status = entry.get("status", "confirmed")

        # per-event の data_warnings（品質上の注意点）
        data_warnings: list[str] = []
        if confidence < 0.7:
            data_warnings.append(f"低信頼度: {confidence:.2f}（情報が不完全な可能性があります）")
        elif confidence < 0.9:
            data_warnings.append(f"信頼度: {confidence:.2f}（一部情報が不確かな場合があります）")
        if status == "tentative":
            data_warnings.append("開催確認待ち（tentative）: 最新情報をご確認ください")
        elif status == "postponed":
            data_warnings.append("延期の可能性あり（postponed）: 公式情報をご確認ください")
        if entry.get("latitude") is None or entry.get("longitude") is None:
            data_warnings.append("座標不明: 距離計算が正確でない可能性があります")
        if asm.get("distance_m") is None:
            data_warnings.append("距離未計算: 店舗座標またはイベント座標が未設定です")

        output_events.append({
            **entry,
            # assessment フラット化
            "impact_score": asm.get("impact_score", 0),
            "impact_reasons": asm.get("impact_reasons", []),
            "operational_signals": asm.get("operational_signals", []),
            "distance_m": asm.get("distance_m"),
            "assessment_store_id": asm.get("store_id", ""),
            "assessment_business_unit": asm.get("business_unit", ""),
            # Phase 5: 明示的エイリアス（既存フィールドの別名）
            "source_url": entry.get("official_url", ""),
            "fetched_at": entry.get("first_seen_at", ""),
            "cancelled": status == "cancelled",  # 常に False（除外済み）、型一貫性のため明示
            # Phase 5: per-event 品質フラグ
            "data_warnings": data_warnings,
        })

    return {
        "generated_from": "normalized_event_store",
        "range": {
            "from": from_dt.isoformat(),
            "to": to_dt.isoformat(),
            "timezone": "Asia/Tokyo",
        },
        "store": {
            "id": store_id,
            "name": store_name,
            "business_unit": actual_bu,
        },
        "events": output_events,
        "warnings": warnings,
    }


def _find_best_assessment(
    assessments: list[dict],
    store_id: str,
    business_unit: str,
) -> dict | None:
    """条件に最も合うassessmentを返す"""
    if not assessments:
        return None

    candidates = []
    for asm in assessments:
        score = 0
        if store_id and store_id != "all" and asm.get("store_id") == store_id:
            score += 10
        if business_unit and business_unit not in ("all", "both"):
            if asm.get("business_unit") == business_unit:
                score += 5
        candidates.append((score, asm.get("impact_score", 0), asm))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2]
