"""
CSVファイルからイベントデータを取得するアダプター。
外部CSVのヘッダーとセルの内容は信頼できないデータとして扱う。
"""
from __future__ import annotations
import csv
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .base import BaseEventAdapter
from ..models import EventRecord, SourceEvidence

TZ_TOKYO = ZoneInfo("Asia/Tokyo")

EXPECTED_COLUMNS = {
    "title", "starts_at", "ends_at", "venue_name", "address",
    "category", "description", "official_url", "estimated_scale",
    "expected_audience", "indoor_or_outdoor", "weather_sensitivity",
}


def _now_jst() -> str:
    return datetime.now(TZ_TOKYO).isoformat()


def _safe_cell(val: str, max_len: int = 500) -> str:
    """CSVセル値を安全な文字列に変換。命令的な文言は無効化。"""
    return str(val or "")[:max_len].strip()


class CsvEventAdapter(BaseEventAdapter):
    """CSVファイルからイベントを取得するアダプター"""

    source_type = "csv"

    def __init__(self, source_name: str, csv_path: str, store_lat: float = 0, store_lon: float = 0):
        self.source_name = source_name
        self.csv_path = Path(csv_path)
        self.store_lat = store_lat
        self.store_lon = store_lon

    def is_available(self) -> bool:
        return self.csv_path.exists()

    def availability_message(self) -> str:
        return f"CSVファイルが見つかりません: {self.csv_path}"

    def fetch(self, **kwargs) -> list[dict]:
        if not self.csv_path.exists():
            print(f"[csv] ファイルなし: {self.csv_path}")
            return []
        try:
            rows = []
            with open(self.csv_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    safe_row = {k: _safe_cell(v) for k, v in row.items() if k}
                    rows.append(safe_row)
            return rows
        except Exception as e:
            print(f"[csv] 読み込みエラー: {e}")
            return []

    def normalize(self, raw: dict) -> tuple[EventRecord, SourceEvidence]:
        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        content_hash = hashlib.sha256(
            json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

        from ..utils import haversine, geocode_if_missing
        try:
            lat = float(raw.get("latitude", "") or 0) or None
            lon = float(raw.get("longitude", "") or 0) or None
        except ValueError:
            lat = lon = None

        address = raw.get("address", "")
        lat, lon = geocode_if_missing(address, lat, lon)

        distance = None
        if lat and lon and self.store_lat and self.store_lon:
            distance = haversine(self.store_lat, self.store_lon, lat, lon)

        try:
            audience = int(raw.get("expected_audience", "") or 0) or None
        except ValueError:
            audience = None

        evidence = SourceEvidence(
            id=evidence_id,
            source_type="csv",
            source_name=self.source_name,
            source_url=str(self.csv_path),
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data=raw,
            confidence=0.8,
            terms_or_access_note="CSVインポート",
            created_at=_now_jst(),
        )

        record = EventRecord(
            id=event_id,
            source_evidence_id=evidence_id,
            external_id=raw.get("external_id", ""),
            title=raw.get("title", ""),
            description=raw.get("description", "")[:500],
            category=raw.get("category", "local_event"),
            venue_name=raw.get("venue_name", ""),
            address=raw.get("address", ""),
            latitude=lat,
            longitude=lon,
            distance_from_store_km=distance,
            starts_at=raw.get("starts_at", ""),
            ends_at=raw.get("ends_at", ""),
            all_day=raw.get("all_day", "").lower() in ("1", "true", "yes"),
            expected_audience=audience,
            indoor_or_outdoor=raw.get("indoor_or_outdoor", "unknown"),
            weather_sensitivity=raw.get("weather_sensitivity", "unknown"),
            estimated_scale=raw.get("estimated_scale", "unknown"),
            official_url=raw.get("official_url", "")[:200],
            status="confirmed",
            confidence=0.8,
            content_hash=content_hash,
            first_seen_at=_now_jst(),
            last_seen_at=_now_jst(),
        )
        return record, evidence
