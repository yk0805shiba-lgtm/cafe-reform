"""
Shadow mode イベント収集。
- shadow_event_records に書き込む（canonical の event_records は変更しない）
- AUTO_SOURCE_TYPES のみ収集（手動ソースはスキップ）
"""
from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..storage import JsonStore
from ..utils import now_jst_iso
from .mode import is_auto_source

TZ = ZoneInfo("Asia/Tokyo")

_SHADOW_REDIRECT: dict[str, str] = {
    "event_records": "shadow_event_records",
    "store_event_assessments": "shadow_store_event_assessments",
    "source_evidence": "shadow_source_evidence",
}


class _ShadowStoreProxy:
    """
    JsonStore のプロキシ。
    event_records / store_event_assessments / source_evidence への
    読み書きを shadow_* コレクションにリダイレクトする。
    store_profiles は実コレクションから読むが、auto source のみにフィルタする。
    """

    def __init__(self, real_store: JsonStore):
        self._store = real_store

    def _redir(self, collection: str) -> str:
        return _SHADOW_REDIRECT.get(collection, collection)

    def upsert(self, collection: str, record: dict, key: str = "id") -> bool:
        return self._store.upsert(self._redir(collection), record, key)

    def get(self, collection: str, id: str, key: str = "id"):
        if collection == "store_profiles":
            profile = self._store.get("store_profiles", id, key)
            return _filter_profile_sources(profile) if profile else None
        return self._store.get(self._redir(collection), id, key)

    def list_all(self, collection: str) -> list[dict]:
        if collection == "store_profiles":
            return [_filter_profile_sources(p) for p in self._store.list_all("store_profiles")]
        return self._store.list_all(self._redir(collection))

    def filter(self, collection: str, **kwargs) -> list[dict]:
        if collection == "store_profiles":
            return [_filter_profile_sources(p) for p in self._store.filter("store_profiles", **kwargs)]
        return self._store.filter(self._redir(collection), **kwargs)

    def delete(self, collection: str, id: str, key: str = "id") -> bool:
        return self._store.delete(self._redir(collection), id, key)

    def exists(self, collection: str, id: str, key: str = "id") -> bool:
        return self._store.exists(self._redir(collection), id, key)

    def count(self, collection: str) -> int:
        return self._store.count(self._redir(collection))

    def update_field(self, collection: str, id: str, field: str, value, key: str = "id") -> bool:
        return self._store.update_field(self._redir(collection), id, field, value, key)


def _filter_profile_sources(profile: dict) -> dict:
    """Store profile の event_sources を auto sources のみにフィルタした copy を返す"""
    p = dict(profile)
    p["event_sources"] = [src for src in profile.get("event_sources", []) if is_auto_source(src)]
    return p


def shadow_sync(
    store: JsonStore,
    store_id: str | None = None,
    days: int = 120,
    no_llm: bool = True,
) -> dict:
    """
    AUTO_SOURCE_TYPES のみから shadow_event_records に収集する。
    canonical の event_records は変更しない。

    戻り値: {"collect": {...}, "comparison": {...}, "report_id": str | None}
    """
    proxy = _ShadowStoreProxy(store)

    # auto source が存在するか確認してから収集
    profiles = proxy.list_all("store_profiles")
    if store_id and store_id != "all":
        profiles = [p for p in profiles if p.get("id") == store_id]

    has_auto_sources = any(p.get("event_sources") for p in profiles)
    if not has_auto_sources:
        print("[shadow_sync] 自動収集ソースが設定されていません（AUTO_SOURCE_TYPES に該当するソースなし）")
        result = {"created": 0, "updated": 0, "assessments": 0, "errors": ["自動収集ソースなし"]}
        comparison = compare_shadow_vs_canonical(store)
        return {"collect": result, "comparison": comparison, "report_id": None}

    from .collect import collect_events

    print(f"[shadow_sync] 開始: store={store_id or 'all'} days={days}")
    result = collect_events(
        store=proxy,
        store_id=store_id,
        days=days,
        demo=False,
        no_llm=no_llm,
    )
    print(f"[shadow_sync] 収集完了: 新規={result['created']} 更新={result['updated']}")

    comparison = compare_shadow_vs_canonical(store)
    print(
        f"[shadow_sync] 比較: shadow={comparison['shadow_total']}件 "
        f"canonical={comparison['canonical_total']}件 "
        f"マッチ={len(comparison['matched'])}件 "
        f"shadow_only={len(comparison['shadow_only'])}件"
    )

    report_id = "shadow_rpt_" + now_jst_iso()[:19].replace(":", "").replace("-", "")
    report = {
        "id": report_id,
        "sync_at": now_jst_iso(),
        "store_id": store_id or "all",
        "collect_result": result,
        "comparison_summary": {
            "shadow_total": comparison["shadow_total"],
            "canonical_total": comparison["canonical_total"],
            "matched_count": len(comparison["matched"]),
            "shadow_only_count": len(comparison["shadow_only"]),
            "canonical_only_count": len(comparison["canonical_only"]),
        },
    }
    store.upsert("shadow_reports", report)

    return {"collect": result, "comparison": comparison, "report_id": report_id}


def compare_shadow_vs_canonical(
    store: JsonStore,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> dict:
    """
    shadow_event_records と canonical event_records を比較する。
    is_duplicate_candidate でマッチング（同日 + タイトル類似度 > 0.85）。

    戻り値:
    {
      "shadow_total": int,
      "canonical_total": int,
      "matched": [{"shadow_id": ..., "canonical_id": ..., "title": ..., "starts_at": ...}],
      "shadow_only": [{"id": ..., "title": ..., "starts_at": ...}],
      "canonical_only": [{"id": ..., "title": ..., "starts_at": ...}],
    }
    """
    from .dedup import is_duplicate_candidate

    now = datetime.now(TZ)
    if from_dt is None:
        from_dt = now - timedelta(days=7)
    if to_dt is None:
        to_dt = now + timedelta(days=120)

    def _in_range(ev: dict) -> bool:
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

    shadow_all = [e for e in store.list_all("shadow_event_records") if _in_range(e)]
    canonical_all = [e for e in store.list_all("event_records") if _in_range(e)]

    matched_shadow_ids: set[str] = set()
    matched_canonical_ids: set[str] = set()
    matched_pairs: list[dict] = []

    for s_ev in shadow_all:
        s_id = s_ev.get("id") or s_ev.get("uid", "")
        if s_id in matched_shadow_ids:
            continue
        for c_ev in canonical_all:
            c_id = c_ev.get("id") or c_ev.get("uid", "")
            if c_id in matched_canonical_ids:
                continue
            if is_duplicate_candidate(s_ev, c_ev):
                matched_shadow_ids.add(s_id)
                matched_canonical_ids.add(c_id)
                matched_pairs.append({
                    "shadow_id": s_id,
                    "canonical_id": c_id,
                    "title": s_ev.get("title", ""),
                    "starts_at": s_ev.get("starts_at", ""),
                })
                break

    shadow_only = [
        {"id": e.get("id", ""), "title": e.get("title", ""), "starts_at": e.get("starts_at", "")}
        for e in shadow_all
        if (e.get("id") or e.get("uid", "")) not in matched_shadow_ids
    ]
    canonical_only = [
        {"id": e.get("id", ""), "title": e.get("title", ""), "starts_at": e.get("starts_at", "")}
        for e in canonical_all
        if (e.get("id") or e.get("uid", "")) not in matched_canonical_ids
    ]

    return {
        "shadow_total": len(shadow_all),
        "canonical_total": len(canonical_all),
        "matched": matched_pairs,
        "shadow_only": shadow_only,
        "canonical_only": canonical_only,
    }


def get_source_status(store: JsonStore) -> list[dict]:
    """各自動収集ソースの最終取得状況（shadow_source_evidence から集計）を返す"""
    evidence_list = store.list_all("shadow_source_evidence")
    source_map: dict[str, dict] = {}

    for ev in evidence_list:
        sname = ev.get("source_name", "")
        fetched_at = ev.get("fetched_at", "")
        if not sname:
            continue
        if sname not in source_map or fetched_at > source_map[sname]["last_fetched_at"]:
            source_map[sname] = {
                "source_name": sname,
                "source_type": ev.get("source_type", ""),
                "last_fetched_at": fetched_at,
            }

    return list(source_map.values())
