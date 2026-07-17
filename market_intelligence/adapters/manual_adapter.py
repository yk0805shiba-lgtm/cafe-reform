"""
手動登録アダプター。
管理画面やCLIから直接入力されたイベント・競合情報を扱う。
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .base import BaseEventAdapter, BaseCompetitorAdapter
from ..models import EventRecord, SourceEvidence, CompetitorSnapshot

TZ_TOKYO = ZoneInfo("Asia/Tokyo")


def _now_jst() -> str:
    return datetime.now(TZ_TOKYO).isoformat()


def _content_hash(data: dict) -> str:
    s = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


class ManualEventAdapter(BaseEventAdapter):
    """手動入力されたイベントデータを正規化するアダプター"""

    source_type = "manual"
    source_name = "手動登録"

    def fetch(self, events: list[dict] = None, **kwargs) -> list[dict]:
        return events or []

    def normalize(self, raw: dict) -> tuple[EventRecord, SourceEvidence]:
        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        event_id = raw.get("id") or f"evt_{uuid.uuid4().hex[:8]}"
        content_hash = _content_hash(raw)

        evidence = SourceEvidence(
            id=evidence_id,
            source_type="manual",
            source_name="手動登録",
            source_url=raw.get("official_url", ""),
            external_id=raw.get("external_id", ""),
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data=raw,
            confidence=1.0,
            terms_or_access_note="手動登録データ",
            created_at=_now_jst(),
        )

        record = EventRecord(
            id=event_id,
            source_evidence_id=evidence_id,
            external_id=raw.get("external_id", ""),
            title=raw.get("title", ""),
            description=raw.get("description", ""),
            category=raw.get("category", "local_event"),
            venue_name=raw.get("venue_name", ""),
            address=raw.get("address", ""),
            latitude=raw.get("latitude"),
            longitude=raw.get("longitude"),
            distance_from_store_km=raw.get("distance_from_store_km"),
            starts_at=raw.get("starts_at", ""),
            ends_at=raw.get("ends_at", ""),
            all_day=raw.get("all_day", False),
            expected_audience=raw.get("expected_audience"),
            audience_segments=raw.get("audience_segments", []),
            estimated_scale=raw.get("estimated_scale", "unknown"),
            languages=raw.get("languages", ["ja"]),
            indoor_or_outdoor=raw.get("indoor_or_outdoor", "unknown"),
            weather_sensitivity=raw.get("weather_sensitivity", "unknown"),
            official_url=raw.get("official_url", ""),
            status=raw.get("status", "confirmed"),
            confidence=1.0,
            content_hash=content_hash,
            first_seen_at=_now_jst(),
            last_seen_at=_now_jst(),
        )
        return record, evidence


class ManualCompetitorAdapter(BaseCompetitorAdapter):
    """手動入力された競合スナップショットを正規化するアダプター"""

    source_type = "manual"
    source_name = "手動記録"

    def fetch(self, competitor_id: str, data: dict = None, **kwargs) -> dict:
        return data or {}

    def to_snapshot(self, raw: dict, competitor_id: str) -> tuple[CompetitorSnapshot, SourceEvidence]:
        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
        content_hash = _content_hash(raw)

        evidence = SourceEvidence(
            id=evidence_id,
            source_type="manual",
            source_name="手動記録",
            source_url="",
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data=raw,
            confidence=1.0,
            terms_or_access_note="手動記録データ",
            created_at=_now_jst(),
        )

        snapshot = CompetitorSnapshot(
            id=snapshot_id,
            competitor_id=competitor_id,
            captured_at=_now_jst(),
            source_evidence_ids=[evidence_id],
            menu_items=raw.get("menu_items", []),
            prices=raw.get("prices", {}),
            sets=raw.get("sets", []),
            discounts=raw.get("discounts", []),
            opening_hours=raw.get("opening_hours", {}),
            order_availability=raw.get("order_availability"),
            rating=raw.get("rating"),
            review_count=raw.get("review_count"),
            review_topics=raw.get("review_topics", {}),
            content_hash=content_hash,
            status="success",
            confidence=1.0,
        )
        return snapshot, evidence
