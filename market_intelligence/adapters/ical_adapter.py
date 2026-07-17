"""
ICS / iCalendar形式のイベントデータを取得するアダプター。
ファイルパスまたはURLを受け付ける。
外部コンテンツはすべて信頼できないデータとして扱う。
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .base import BaseEventAdapter
from ..models import EventRecord, SourceEvidence

TZ_TOKYO = ZoneInfo("Asia/Tokyo")


def _now_jst() -> str:
    return datetime.now(TZ_TOKYO).isoformat()


def _safe_str(val) -> str:
    """ical値を安全に文字列化する。外部コンテンツは100文字に制限。"""
    if val is None:
        return ""
    s = str(val)[:500]
    # 外部コンテンツ内の潜在的な命令を無効化するため、改行と制御文字を除去
    s = s.replace("\x00", "").replace("\r", " ").replace("\n", " ")
    return s


class ICalEventAdapter(BaseEventAdapter):
    """ICS/iCalendarファイルまたはURLからイベントを取得するアダプター"""

    source_type = "ical"

    def __init__(self, source_name: str, source_url_or_path: str, store_lat: float = 0, store_lon: float = 0):
        self.source_name = source_name
        self.source_url_or_path = source_url_or_path
        self.store_lat = store_lat
        self.store_lon = store_lon

    def is_available(self) -> bool:
        try:
            import icalendar
            return True
        except ImportError:
            return False

    def availability_message(self) -> str:
        return "icalendarパッケージが必要です: pip install icalendar"

    def fetch(self, **kwargs) -> list[dict]:
        """ICSデータを取得してリストで返す。失敗時は空リスト。"""
        try:
            content = self._get_content()
        except Exception as e:
            print(f"[ical] 取得失敗 ({self.source_url_or_path}): {e}")
            return []

        try:
            import icalendar
            cal = icalendar.Calendar.from_ical(content)
            results = []
            for component in cal.walk():
                if component.name == "VEVENT":
                    raw = self._parse_vevent(component)
                    if raw:
                        results.append(raw)
            return results
        except Exception as e:
            print(f"[ical] パースエラー: {e}")
            return []

    def normalize(self, raw: dict) -> tuple[EventRecord, SourceEvidence]:
        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        content_hash = hashlib.sha256(
            json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

        from ..utils import haversine
        distance = None
        if raw.get("latitude") and raw.get("longitude") and self.store_lat and self.store_lon:
            distance = haversine(self.store_lat, self.store_lon, raw["latitude"], raw["longitude"])

        evidence = SourceEvidence(
            id=evidence_id,
            source_type="ical",
            source_name=self.source_name,
            source_url=self.source_url_or_path,
            external_id=raw.get("uid", ""),
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data={k: str(v) for k, v in raw.items()},
            confidence=0.85,
            terms_or_access_note="ICS/iCalendarフィード",
            created_at=_now_jst(),
        )

        record = EventRecord(
            id=event_id,
            source_evidence_id=evidence_id,
            external_id=raw.get("uid", ""),
            title=raw.get("summary", ""),
            description=raw.get("description", "")[:500],
            category=self._guess_category(raw.get("summary", ""), raw.get("description", "")),
            venue_name=raw.get("location", "").split(",")[0][:100],
            address=raw.get("location", ""),
            latitude=raw.get("latitude"),
            longitude=raw.get("longitude"),
            distance_from_store_km=distance,
            starts_at=raw.get("dtstart", ""),
            ends_at=raw.get("dtend", ""),
            all_day=raw.get("all_day", False),
            official_url=raw.get("url", ""),
            status="confirmed",
            confidence=0.85,
            content_hash=content_hash,
            first_seen_at=_now_jst(),
            last_seen_at=_now_jst(),
        )
        return record, evidence

    def _get_content(self) -> bytes:
        p = Path(self.source_url_or_path)
        if p.exists():
            return p.read_bytes()
        # URLの場合
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            self.source_url_or_path,
            headers={"User-Agent": "cafe-reform-market-intelligence/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            return r.read(1024 * 512)  # 512KB上限

    def _parse_vevent(self, component) -> Optional[dict]:
        try:
            def dt_to_iso(val) -> str:
                if val is None:
                    return ""
                if hasattr(val, "dt"):
                    val = val.dt
                if hasattr(val, "tzinfo") and val.tzinfo:
                    return val.astimezone(TZ_TOKYO).isoformat()
                if hasattr(val, "isoformat"):
                    return val.isoformat()
                return str(val)

            summary = _safe_str(component.get("SUMMARY", ""))
            if not summary:
                return None

            return {
                "uid": _safe_str(component.get("UID", "")),
                "summary": summary,
                "description": _safe_str(component.get("DESCRIPTION", ""))[:500],
                "location": _safe_str(component.get("LOCATION", ""))[:200],
                "url": _safe_str(component.get("URL", ""))[:200],
                "dtstart": dt_to_iso(component.get("DTSTART")),
                "dtend": dt_to_iso(component.get("DTEND")),
                "all_day": not hasattr(getattr(component.get("DTSTART"), "dt", None), "hour"),
            }
        except Exception:
            return None

    def _guess_category(self, title: str, desc: str) -> str:
        text = (title + " " + desc).lower()
        keywords = {
            "fireworks": ["花火", "firework"],
            "concert": ["ライブ", "コンサート", "live", "concert", "音楽"],
            "sports": ["スポーツ", "マラソン", "試合", "sport", "race"],
            "tourism": ["観光", "インバウンド", "tourism", "festival"],
            "market": ["マーケット", "マルシェ", "市場", "market"],
            "school": ["学校", "大学", "入学", "卒業", "school"],
            "holiday": ["祝日", "休日", "holiday"],
            "weather": ["天気", "気温", "雨", "weather"],
        }
        for cat, words in keywords.items():
            if any(w in text for w in words):
                return cat
        return "local_event"
