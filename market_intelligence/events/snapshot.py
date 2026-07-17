"""
Canonical event snapshot: source障害時の前回正常データ保持。
market_intelligence/state/canonical_events.json に保存し、git追跡対象とする。

設計原則:
- volatile fields (fetched_at, runtime IDs) はsnapshotに含めない
- content_hashが変わらない限りupdated_atを更新しない
- 同じイベント内容→同じJSON（決定論的）
- source失敗時は前回snapshotの当該sourceイベントを保持
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")

# snapshotに含める安定フィールド（volatile fieldsを除く）
_SNAPSHOT_FIELDS = [
    "uid", "source_id", "external_id", "title", "description",
    "starts_at", "ends_at", "all_day", "venue_name", "address",
    "latitude", "longitude", "official_url", "category", "status",
    "confidence", "content_hash", "merged_from_source_ids",
    "languages", "expected_audience",
]

DEFAULT_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "state" / "canonical_events.json"

PAST_DAYS = 7
FUTURE_DAYS = 120


def load_snapshot(path: Optional[Path] = None) -> list[dict]:
    """snapshotファイルを読み込む。存在しない場合は空リストを返す。"""
    p = path or DEFAULT_SNAPSHOT_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_snapshot(events: list[dict], path: Optional[Path] = None) -> None:
    """eventリストをsnapshotとして保存する（決定論的ソート）。"""
    p = path or DEFAULT_SNAPSHOT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    snapshot_events = _to_snapshot_records(events)
    # 決定論的ソート: starts_at → uid
    snapshot_events.sort(key=lambda e: (e.get("starts_at", ""), e.get("uid", "")))
    # 期間フィルタ
    snapshot_events = _filter_by_range(snapshot_events)
    p.write_text(
        json.dumps(snapshot_events, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _to_snapshot_records(events: list[dict]) -> list[dict]:
    """EventRecordをsnapshotフィールドのみに絞る。"""
    result = []
    for ev in events:
        rec = {k: ev.get(k) for k in _SNAPSHOT_FIELDS}
        # None値は省略（ファイルサイズ・diff削減）
        rec = {k: v for k, v in rec.items() if v is not None and v != [] and v != ""}
        if rec.get("uid"):
            result.append(rec)
    return result


def _filter_by_range(events: list[dict]) -> list[dict]:
    """過去7日〜未来120日の範囲外イベントを除外する。"""
    now = datetime.now(TZ)
    from_dt = now - timedelta(days=PAST_DAYS)
    to_dt = now + timedelta(days=FUTURE_DAYS)
    result = []
    for ev in events:
        starts = ev.get("starts_at", "")
        if not starts:
            continue
        try:
            dt = datetime.fromisoformat(starts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            if from_dt <= dt <= to_dt:
                result.append(ev)
        except Exception:
            pass
    return result


def merge_with_snapshot(
    new_events: list[dict],
    failed_source_ids: set[str],
    snapshot: list[dict],
) -> list[dict]:
    """
    新規収集イベントと前回snapshotをsource単位でマージする。

    ルール:
    - 成功したsource: 今回の取得結果を使用
    - 失敗したsource: snapshot内の当該sourceイベントを保持
    - 0件成功sourceは警告（ただし0件で削除はしない）
    - snapshotにしかないsource(失敗): そのまま保持

    戻り値: マージ済みEventRecordリスト
    """
    if not failed_source_ids or not snapshot:
        return new_events

    # 成功sourceのUID → event
    new_by_uid: dict[str, dict] = {ev.get("uid", ev.get("id", "")): ev for ev in new_events}

    # 失敗source: snapshotから当該sourceのイベントを引き継ぐ
    retained: list[dict] = []
    for snap_ev in snapshot:
        src = snap_ev.get("source_id", "")
        uid = snap_ev.get("uid", "")
        if src in failed_source_ids:
            # 失敗sourceのsnapshotイベントを保持（ただし成功で取得済みなら不要）
            if uid not in new_by_uid:
                retained.append(snap_ev)

    merged = list(new_events) + retained
    return merged


def get_snapshot_source_ids(snapshot: list[dict]) -> set[str]:
    """snapshotに含まれるsource_idの集合を返す。"""
    return {ev.get("source_id", "") for ev in snapshot if ev.get("source_id")}
