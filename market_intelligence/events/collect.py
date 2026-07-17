"""
イベント収集・正規化・保存処理。
外部Collectorは Phase 2 以降。Phase 1ではdemoとCSVのみ。
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..storage import JsonStore
from ..utils import now_jst_iso, haversine, haversine_meters
from .uid import generate_event_uid
from .impact import compute_impact_score
from .signals import compute_cafe_signals, compute_delivery_signals
from .demo_data import make_demo_raw_events

TZ = ZoneInfo("Asia/Tokyo")


def collect_events(
    store: JsonStore,
    store_id: str | None = None,
    days: int = 90,
    demo: bool = False,
    no_llm: bool = True,
) -> dict:
    """
    イベントを収集してEventRecord, SourceEvidence, StoreEventAssessmentを保存する。

    戻り値:
      "created": int, "updated": int, "assessments": int, "errors": list[str],
      "failed_source_ids": list[str],  # 例外発生したsource
      "zero_result_source_ids": list[str]  # 例外なし・0件返却のauto source（parser変更疑い）
    """
    created = 0
    updated = 0
    assessment_count = 0
    errors: list[str] = []
    failed_source_ids: list[str] = []
    zero_result_source_ids: list[str] = []

    # 対象店舗リスト
    if store_id and store_id != "all":
        profiles = [store.get("store_profiles", store_id)]
        profiles = [p for p in profiles if p]
    else:
        profiles = store.list_all("store_profiles")

    if not profiles:
        errors.append("対象店舗が見つかりません")
        return {"created": created, "updated": updated, "assessments": assessment_count,
                "errors": errors, "failed_source_ids": failed_source_ids,
                "zero_result_source_ids": zero_result_source_ids}

    # rawイベントを収集
    raw_events: list[dict] = []

    if demo:
        raw_events.extend(make_demo_raw_events())
    else:
        # Phase 1: CSV/ICalアダプターから収集（store_profileのevent_sourcesに基づく）
        from .mode import AUTO_SOURCE_TYPES
        for profile in profiles:
            for src in profile.get("event_sources", []):
                if not src.get("enabled", True):
                    print(f"[collect] スキップ（一時停止中）: {src.get('name', '?')}")
                    continue
                src_name = src.get("name", "?")
                src_type = src.get("type", "")
                try:
                    raws = _collect_from_source(src, profile)
                    if len(raws) == 0 and src_type in AUTO_SOURCE_TYPES:
                        # 自動ソースが0件返却: parser変更の可能性
                        if src_name not in zero_result_source_ids:
                            zero_result_source_ids.append(src_name)
                    raw_events.extend(raws)
                except Exception as e:
                    errors.append(f"ソース収集失敗 {src_name}: {str(e)[:80]}")
                    if src_name not in failed_source_ids:
                        failed_source_ids.append(src_name)

        if not raw_events:
            # ソースなしの場合はdemoデータを使う
            print("[collect] イベントソースなし、デモデータを使用します")
            raw_events.extend(make_demo_raw_events())

    # 各rawイベントをEventRecordに変換・保存
    now = datetime.now(TZ)
    cutoff = now + timedelta(days=days)

    processed_uids: set[str] = set()

    for raw in raw_events:
        try:
            # 日時フィルタ
            starts_at = raw.get("starts_at", "")
            if starts_at:
                try:
                    starts_dt = datetime.fromisoformat(starts_at)
                    if starts_dt.tzinfo is None:
                        starts_dt = starts_dt.replace(tzinfo=TZ)
                    if starts_dt > cutoff:
                        continue
                except Exception:
                    pass

            # UID生成
            source_id = raw.get("source_id", "demo")
            title = raw.get("title", "")
            venue = raw.get("venue", "")
            uid = generate_event_uid(source_id, title, starts_at, venue)

            # 重複チェック
            if uid in processed_uids:
                continue
            processed_uids.add(uid)

            # 既存レコード確認（UIDで検索）
            existing = _find_by_uid(store, uid)

            # SourceEvidence作成
            import hashlib
            import json
            raw_str = json.dumps(raw, sort_keys=True, ensure_ascii=False)
            src_hash = hashlib.sha256(raw_str.encode()).hexdigest()[:16]

            evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
            evidence = {
                "id": evidence_id,
                "source_type": "demo" if demo else raw.get("source_type", "manual"),
                "source_name": raw.get("source_id", "demo"),
                "source_url": raw.get("url", ""),
                "external_id": raw.get("external_id", ""),
                "fetched_at": now_jst_iso(),
                "published_at": "",
                "content_hash": src_hash,
                "raw_data": raw,
                "confidence": 1.0 if demo else raw.get("confidence", 0.9),
                "terms_or_access_note": "デモデータ" if demo else "",
                "created_at": now_jst_iso(),
            }

            # EventRecord作成・更新
            lat = raw.get("lat")
            lon = raw.get("lon")

            if existing:
                # 更新: last_seen_at を更新
                store.update_field("event_records", existing["id"], "last_seen_at", now_jst_iso())
                store.update_field("event_records", existing["id"], "sequence",
                                   existing.get("sequence", 0) + 1)
                event_id = existing["id"]
                updated += 1
            else:
                # 新規作成
                event_id = f"evt_{uuid.uuid4().hex[:8]}"
                event_rec = {
                    "id": event_id,
                    "uid": uid,
                    "source_id": source_id,
                    "source_evidence_id": evidence_id,
                    "source_evidence_ids": [evidence_id],
                    "merged_from_source_ids": [],
                    "sequence": 0,
                    "external_id": raw.get("external_id", ""),
                    "title": title,
                    "description": raw.get("description", ""),
                    "category": raw.get("category", "unknown"),
                    "venue_name": raw.get("venue", ""),
                    "address": raw.get("address", ""),
                    "latitude": lat,
                    "longitude": lon,
                    "distance_from_store_km": None,
                    "starts_at": starts_at,
                    "ends_at": raw.get("ends_at", ""),
                    "all_day": raw.get("all_day", False),
                    "expected_audience": raw.get("expected_audience"),
                    "audience_segments": raw.get("audience_segments", []),
                    "estimated_scale": _estimate_scale(raw.get("expected_audience")),
                    "languages": raw.get("languages", ["ja"]),
                    "indoor_or_outdoor": raw.get("indoor_or_outdoor", "unknown"),
                    "weather_sensitivity": raw.get("weather_sensitivity", "unknown"),
                    "official_url": raw.get("url", ""),
                    "status": "confirmed",
                    "confidence": raw.get("confidence", 1.0),
                    "content_hash": src_hash,
                    "first_seen_at": now_jst_iso(),
                    "last_seen_at": now_jst_iso(),
                }
                store.upsert("source_evidence", evidence)
                store.upsert("event_records", event_rec)
                created += 1

            # 各店舗に対してStoreEventAssessmentを計算・保存
            for profile in profiles:
                try:
                    n = _create_assessment(store, uid, event_id, profile, lat, lon, raw)
                    assessment_count += n
                except Exception as e:
                    errors.append(f"Assessment失敗 {uid[:8]}/{profile['id']}: {str(e)[:80]}")

        except Exception as e:
            errors.append(f"イベント処理失敗: {str(e)[:100]}")

    print(f"[collect] 完了: 新規={created} 更新={updated} アセスメント={assessment_count}")

    # 重複排除・マージ
    from .dedup import deduplicate_and_merge
    dedup_result = deduplicate_and_merge(store)
    if dedup_result["merged"] > 0:
        print(f"[collect] 重複マージ: {dedup_result['merged']}件")
    if dedup_result["errors"]:
        for e in dedup_result["errors"]:
            errors.append(e)

    return {"created": created, "updated": updated, "assessments": assessment_count,
            "errors": errors, "failed_source_ids": failed_source_ids,
            "zero_result_source_ids": zero_result_source_ids}


def collect_events_with_snapshot(
    store: JsonStore,
    store_id: str | None = None,
    days: int = 90,
    no_llm: bool = True,
    snapshot: list[dict] | None = None,
) -> dict:
    """
    スナップショットを使ったソース障害対応収集。

    各sourceを試し、失敗したsourceは前回snapshotのデータを保持する。
    全source失敗 + snapshot有り: snapshotを返す (errors あり)
    全source失敗 + snapshot無し: 空 + errors

    戻り値: {
        "created": int, "updated": int, "assessments": int, "errors": list[str],
        "failed_source_ids": list[str], "retained_from_snapshot": int
    }
    """
    from .snapshot import merge_with_snapshot

    snapshot_list = snapshot or []

    # 通常収集を実行（per-source の try/except は collect_events() 内で行われる）
    result = collect_events(
        store=store,
        store_id=store_id,
        days=days,
        demo=False,
        no_llm=no_llm,
    )

    failed_source_ids = set(result.get("failed_source_ids", []))
    retained_count = 0

    if failed_source_ids and snapshot_list:
        # 失敗sourceのイベントをsnapshotから引き継ぐ
        new_events = store.list_all("event_records")
        merged = merge_with_snapshot(
            new_events=new_events,
            failed_source_ids=failed_source_ids,
            snapshot=snapshot_list,
        )
        retained_count = len(merged) - len(new_events)
        if retained_count > 0:
            print(f"[collect_with_snapshot] source障害により {retained_count} 件のsnapshotイベントを保持")
            for ev in merged:
                # snapshotから引き継いだイベントのみupsert
                uid = ev.get("uid", ev.get("id", ""))
                existing = _find_by_uid(store, uid)
                if existing is None:
                    # snapshotにしかないイベントを追加
                    ev_to_store = dict(ev)
                    if "id" not in ev_to_store:
                        import uuid
                        ev_to_store["id"] = f"evt_{uuid.uuid4().hex[:8]}"
                    store.upsert("event_records", ev_to_store)

    result["retained_from_snapshot"] = retained_count
    return result


def _find_by_uid(store: JsonStore, uid: str) -> dict | None:
    """UIDで既存EventRecordを検索する"""
    for ev in store.list_all("event_records"):
        if ev.get("uid") == uid:
            return ev
    return None


def _create_assessment(
    store: JsonStore,
    event_uid: str,
    event_id: str,
    profile: dict,
    event_lat: float | None,
    event_lon: float | None,
    raw: dict,
) -> int:
    """StoreEventAssessmentを計算して保存する。戻り値: 保存したassessment数"""
    from datetime import date

    store_id = profile["id"]
    business_unit = profile.get("business_unit", "cafe")

    # 距離計算
    distance_m = None
    store_lat = profile.get("latitude")
    store_lon = profile.get("longitude")
    if event_lat is not None and event_lon is not None and store_lat and store_lon:
        distance_m = haversine_meters(store_lat, store_lon, event_lat, event_lon)

    # starts_at から date を取得
    starts_at = raw.get("starts_at", "")
    try:
        event_date = date.fromisoformat(starts_at[:10])
    except Exception:
        event_date = date.today()

    category = raw.get("category", "unknown")

    # impact score計算
    impact_score, impact_reasons = compute_impact_score(
        distance_m=distance_m,
        category=category,
        event_date=event_date,
    )

    # operational signals計算
    opening_hours = profile.get("opening_hours", {})
    store_open = opening_hours.get("open", "09:00")
    store_close = opening_hours.get("close", "21:00")
    languages = raw.get("languages", ["ja"])
    ends_at = raw.get("ends_at")

    units_to_assess = []
    if business_unit == "both":
        units_to_assess = ["cafe", "delivery"]
    else:
        units_to_assess = [business_unit]

    count = 0
    for bu in units_to_assess:
        if bu == "cafe":
            op_signals = compute_cafe_signals(
                event_start=starts_at,
                event_end=ends_at,
                store_open=store_open,
                store_close=store_close,
                distance_m=distance_m,
                category=category,
                languages=languages,
            )
        else:  # delivery
            peak = opening_hours.get("peak", [])
            delivery_peak_windows = []
            if len(peak) >= 2:
                delivery_peak_windows = [{"start": peak[0], "end": peak[1]}]
            op_signals = compute_delivery_signals(
                event_start=starts_at,
                event_end=ends_at,
                delivery_peak_windows=delivery_peak_windows,
                distance_m=distance_m,
                delivery_radius_km=profile.get("search_radius_km", 5.0),
                event_lat=event_lat,
                event_lon=event_lon,
                store_lat=store_lat or 0.0,
                store_lon=store_lon or 0.0,
                category=category,
            )

        uid_short = event_uid.split("@")[0][:8]
        sea_id = f"sea_{uid_short}_{store_id}_{bu}"

        assessment = {
            "id": sea_id,
            "event_uid": event_uid,
            "event_id": event_id,
            "store_id": store_id,
            "business_unit": bu,
            "distance_m": distance_m,
            "impact_score": impact_score,
            "impact_reasons": impact_reasons,
            "operational_signals": op_signals,
            "calculated_at": now_jst_iso(),
        }
        store.upsert("store_event_assessments", assessment)
        count += 1

    return count


def _collect_from_source(src: dict, profile: dict) -> list[dict]:
    """店舗のevent_sourceからrawイベントリストを取得する"""
    src_type = src.get("type", "")

    if src_type == "csv":
        from ..adapters import CsvEventAdapter
        adapter = CsvEventAdapter(
            source_name=src.get("name", "csv"),
            csv_path=src["path"],
            store_lat=profile.get("latitude", 0),
            store_lon=profile.get("longitude", 0),
        )
        raws = adapter.fetch()
        result = []
        for raw in raws:
            record, evidence = adapter.normalize(raw)
            result.append({
                "source_id": src.get("name", "csv"),
                "title": record.title,
                "description": record.description,
                "venue": record.venue_name,
                "address": record.address,
                "lat": record.latitude,
                "lon": record.longitude,
                "starts_at": record.starts_at,
                "ends_at": record.ends_at,
                "all_day": record.all_day,
                "category": record.category,
                "languages": record.languages,
                "expected_audience": record.expected_audience,
                "url": record.official_url,
                "confidence": record.confidence,
            })
        return result

    elif src_type == "ical":
        from ..adapters import ICalEventAdapter
        adapter = ICalEventAdapter(
            source_name=src.get("name", "ical"),
            source_url_or_path=src["url"],
            store_lat=profile.get("latitude", 0),
            store_lon=profile.get("longitude", 0),
        )
        raws = adapter.fetch()
        result = []
        for raw in raws:
            record, evidence = adapter.normalize(raw)
            result.append({
                "source_id": src.get("name", "ical"),
                "title": record.title,
                "description": record.description,
                "venue": record.venue_name,
                "address": record.address,
                "lat": record.latitude,
                "lon": record.longitude,
                "starts_at": record.starts_at,
                "ends_at": record.ends_at,
                "all_day": record.all_day,
                "category": record.category,
                "languages": record.languages,
                "expected_audience": record.expected_audience,
                "url": record.official_url,
                "confidence": record.confidence,
            })
        return result

    elif src_type == "doorkeeper":
        from ..adapters import DoorkeeperAdapter
        adapter = DoorkeeperAdapter(
            source_name=src.get("name", "Doorkeeper新宿"),
            keyword=src.get("keyword", "新宿"),
        )
        raws = adapter.fetch()
        result = []
        for raw in raws:
            try:
                record, evidence = adapter.normalize(raw)
                result.append({
                    "source_id": src.get("name", "Doorkeeper新宿"),
                    "source_type": adapter.source_type,
                    "external_id": record.external_id,
                    "title": record.title,
                    "description": record.description,
                    "venue": record.venue_name,
                    "address": record.address,
                    "lat": record.latitude,
                    "lon": record.longitude,
                    "starts_at": record.starts_at,
                    "ends_at": record.ends_at,
                    "all_day": record.all_day,
                    "category": record.category,
                    "languages": record.languages,
                    "expected_audience": record.expected_audience,
                    "url": record.official_url,
                    "confidence": record.confidence,
                })
            except Exception as e:
                print(f"[doorkeeper] normalize失敗: {e}")
        return result

    elif src_type == "kanko_shinjuku":
        from ..adapters import KankoShinjukuAdapter
        adapter = KankoShinjukuAdapter(
            source_name=src.get("name", "新宿観光振興協会"),
            max_pages=src.get("max_pages", 3),
        )
        raws = adapter.fetch()
        result = []
        for raw in raws:
            try:
                record, evidence = adapter.normalize(raw)
                result.append({
                    "source_id": src.get("name", "新宿観光振興協会"),
                    "source_type": adapter.source_type,
                    "external_id": record.external_id,
                    "title": record.title,
                    "description": record.description,
                    "venue": record.venue_name,
                    "address": record.address,
                    "lat": record.latitude,
                    "lon": record.longitude,
                    "starts_at": record.starts_at,
                    "ends_at": record.ends_at,
                    "all_day": record.all_day,
                    "category": record.category,
                    "languages": record.languages,
                    "expected_audience": record.expected_audience,
                    "url": record.official_url,
                    "confidence": record.confidence,
                })
            except Exception as e:
                print(f"[kanko_shinjuku] normalize失敗: {e}")
        return result

    elif src_type == "regasu_bunka_center":
        from ..adapters import RegasuBunkaCenterAdapter
        adapter = RegasuBunkaCenterAdapter()
        adapter.source_name = src.get("name", "新宿文化センター")
        raws = adapter.fetch()
        result = []
        for raw in raws:
            try:
                record, evidence = adapter.normalize(raw)
                result.append({
                    "source_id": src.get("name", "新宿文化センター"),
                    "source_type": adapter.source_type,
                    "external_id": record.external_id,
                    "title": record.title,
                    "description": record.description,
                    "venue": record.venue_name,
                    "address": record.address,
                    "lat": record.latitude,
                    "lon": record.longitude,
                    "starts_at": record.starts_at,
                    "ends_at": record.ends_at,
                    "all_day": record.all_day,
                    "category": record.category,
                    "languages": record.languages,
                    "expected_audience": record.expected_audience,
                    "url": record.official_url,
                    "confidence": record.confidence,
                })
            except Exception as e:
                print(f"[regasu_bunka_center] normalize失敗: {e}")
        return result

    return []


def _estimate_scale(audience: int | None) -> str:
    if audience is None:
        return "unknown"
    if audience >= 10000:
        return "large"
    if audience >= 1000:
        return "medium"
    return "small"
