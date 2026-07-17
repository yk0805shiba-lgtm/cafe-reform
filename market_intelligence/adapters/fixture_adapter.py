"""
Demoモード用Fixtureアダプター。
APIキーや実店舗情報がなくても全機能を確認できる。
[DEMO DATA] と明示し、実イベント・実競合と誤認されないようにする。
"""
from __future__ import annotations
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .base import BaseEventAdapter, BaseCompetitorAdapter
from ..models import EventRecord, SourceEvidence, CompetitorSnapshot

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
TZ_TOKYO = ZoneInfo("Asia/Tokyo")


def _now_jst() -> str:
    return datetime.now(TZ_TOKYO).isoformat()


def _days_from_now(days: int) -> str:
    return (datetime.now(TZ_TOKYO) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _content_hash(data: dict) -> str:
    s = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


class FixtureEventAdapter(BaseEventAdapter):
    """デモ用イベントデータを提供する。実イベントではない。"""

    source_type = "fixture"
    source_name = "[DEMO] Fixture Events"

    def fetch(self, store_id: str = "demo", **kwargs) -> list[dict]:
        fp = FIXTURES_DIR / "events_demo.json"
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
        else:
            data = self._builtin_fixtures()
        now = datetime.now(TZ_TOKYO)
        result = []
        for raw in data:
            days_offset = raw.pop("_days_from_now_start", 7)
            days_end_offset = raw.pop("_days_from_now_end", days_offset + 2)
            raw["starts_at"] = (now + timedelta(days=days_offset)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
            raw["ends_at"] = (now + timedelta(days=days_end_offset)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
            result.append(raw)
        return result

    def normalize(self, raw: dict) -> tuple[EventRecord, SourceEvidence]:
        import uuid
        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        content_hash = _content_hash(raw)

        evidence = SourceEvidence(
            id=evidence_id,
            source_type="fixture",
            source_name="[DEMO] Fixture Events",
            source_url="",
            external_id=raw.get("external_id", ""),
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data=raw,
            confidence=0.9,
            terms_or_access_note="デモデータ。実在するイベントではありません。",
            created_at=_now_jst(),
        )

        record = EventRecord(
            id=event_id,
            source_evidence_id=evidence_id,
            external_id=raw.get("external_id", ""),
            title="[DEMO] " + raw.get("title", ""),
            description=raw.get("description", ""),
            category=raw.get("category", "unknown"),
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
            official_url="",
            status="confirmed",
            confidence=0.9,
            content_hash=content_hash,
            first_seen_at=_now_jst(),
            last_seen_at=_now_jst(),
        )
        return record, evidence

    def _builtin_fixtures(self) -> list[dict]:
        return [
            {
                "external_id": "demo_fireworks_001",
                "title": "夏の大花火大会",
                "description": "近隣河川敷で開催される恒例の花火大会。例年2万人以上が来場。",
                "category": "fireworks",
                "venue_name": "河川敷公園",
                "address": "東京都新宿区河川敷1-1",
                "latitude": 35.6900,
                "longitude": 139.7050,
                "distance_from_store_km": 1.8,
                "expected_audience": 20000,
                "audience_segments": ["families", "couples", "tourists", "young_adults"],
                "estimated_scale": "large",
                "languages": ["ja", "en"],
                "indoor_or_outdoor": "outdoor",
                "weather_sensitivity": "high",
                "_days_from_now_start": 14,
                "_days_from_now_end": 14,
            },
            {
                "external_id": "demo_hot_day_001",
                "title": "猛暑日（最高気温35度予報）",
                "description": "気象庁の天気予報により、最高気温35度の猛暑日が予測されています。",
                "category": "weather",
                "venue_name": "",
                "address": "",
                "latitude": None,
                "longitude": None,
                "distance_from_store_km": 0.0,
                "expected_audience": None,
                "audience_segments": ["all"],
                "estimated_scale": "unknown",
                "languages": ["ja"],
                "indoor_or_outdoor": "outdoor",
                "weather_sensitivity": "high",
                "_days_from_now_start": 3,
                "_days_from_now_end": 3,
            },
            {
                "external_id": "demo_rain_001",
                "title": "雨天予報（終日雨）",
                "description": "終日雨天が予報されています。来店客数減少の可能性があります。",
                "category": "weather",
                "venue_name": "",
                "address": "",
                "latitude": None,
                "longitude": None,
                "distance_from_store_km": 0.0,
                "expected_audience": None,
                "audience_segments": ["all"],
                "estimated_scale": "unknown",
                "languages": ["ja"],
                "indoor_or_outdoor": "outdoor",
                "weather_sensitivity": "high",
                "_days_from_now_start": 7,
                "_days_from_now_end": 7,
            },
            {
                "external_id": "demo_concert_001",
                "title": "大型音楽ライブイベント",
                "description": "近隣ライブハウスで大型コンサートが開催。外国人来場者も多い見込み。",
                "category": "concert",
                "venue_name": "近隣ライブホール",
                "address": "東京都新宿区○○町2-3",
                "latitude": 35.6880,
                "longitude": 139.7030,
                "distance_from_store_km": 0.9,
                "expected_audience": 3000,
                "audience_segments": ["young_adults", "tourists", "music_fans"],
                "estimated_scale": "medium",
                "languages": ["ja", "en"],
                "indoor_or_outdoor": "indoor",
                "weather_sensitivity": "low",
                "_days_from_now_start": 21,
                "_days_from_now_end": 21,
            },
            {
                "external_id": "demo_inbound_001",
                "title": "外国人観光客向け文化体験フェスタ",
                "description": "インバウンド観光客向けの日本文化体験イベント。英語・中国語対応あり。",
                "category": "tourism",
                "venue_name": "観光センター",
                "address": "東京都新宿区観光通り1-5",
                "latitude": 35.6920,
                "longitude": 139.7060,
                "distance_from_store_km": 2.1,
                "expected_audience": 5000,
                "audience_segments": ["tourists", "inbound"],
                "estimated_scale": "medium",
                "languages": ["ja", "en", "zh", "ko"],
                "indoor_or_outdoor": "mixed",
                "weather_sensitivity": "medium",
                "_days_from_now_start": 30,
                "_days_from_now_end": 32,
            },
        ]


class FixtureCompetitorAdapter(BaseCompetitorAdapter):
    """デモ用競合データを提供する。実在する競合店舗ではない。"""

    source_type = "fixture"
    source_name = "[DEMO] Fixture Competitors"

    def fetch(self, competitor_id: str, **kwargs) -> dict:
        fp = FIXTURES_DIR / "competitors_demo.json"
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            for item in data:
                if item.get("competitor_id") == competitor_id:
                    return item
        return self._builtin_fixture(competitor_id)

    def to_snapshot(self, raw: dict, competitor_id: str) -> tuple[CompetitorSnapshot, SourceEvidence]:
        import uuid
        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
        content_hash = _content_hash(raw)

        evidence = SourceEvidence(
            id=evidence_id,
            source_type="fixture",
            source_name="[DEMO] Fixture Competitors",
            source_url="",
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data=raw,
            confidence=0.9,
            terms_or_access_note="デモデータ。実在する競合ではありません。",
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
            confidence=0.9,
        )
        return snapshot, evidence

    def _builtin_fixture(self, competitor_id: str) -> dict:
        fixtures = {
            "demo_competitor_price_change": {
                "competitor_id": "demo_competitor_price_change",
                "menu_items": [
                    {"name": "混ぜそば（並）", "price": 1100, "previous_price": 1000},
                    {"name": "混ぜそば（大）", "price": 1300},
                    {"name": "温玉トッピング", "price": 100},
                ],
                "prices": {"混ぜそば（並）": 1100, "混ぜそば（大）": 1300},
                "sets": [],
                "discounts": [],
                "opening_hours": {"open": "11:00", "close": "23:00"},
                "order_availability": True,
                "rating": 4.1,
                "review_count": 230,
                "review_topics": {"味": 45, "量": 30, "価格": 25, "接客": 15},
            },
            "demo_competitor_new_set": {
                "competitor_id": "demo_competitor_new_set",
                "menu_items": [
                    {"name": "混ぜそば（並）", "price": 980},
                    {"name": "温玉追い飯セット", "price": 1280, "is_new": True},
                ],
                "prices": {"混ぜそば（並）": 980},
                "sets": [
                    {"name": "温玉追い飯セット", "price": 1280, "items": ["混ぜそば（並）", "温玉", "追い飯"], "is_new": True}
                ],
                "discounts": [],
                "opening_hours": {"open": "11:00", "close": "21:00"},
                "order_availability": True,
                "rating": 4.3,
                "review_count": 185,
                "review_topics": {"味": 50, "量": 40, "価格": 20, "接客": 10},
            },
            "demo_competitor_hours_change": {
                "competitor_id": "demo_competitor_hours_change",
                "menu_items": [
                    {"name": "混ぜそば（並）", "price": 950},
                ],
                "prices": {"混ぜそば（並）": 950},
                "sets": [],
                "discounts": [],
                "opening_hours": {"open": "11:00", "close": "23:00"},
                "order_availability": True,
                "rating": 3.9,
                "review_count": 95,
                "review_topics": {"味": 30, "量": 25, "提供時間": 20, "価格": 15},
            },
        }
        return fixtures.get(competitor_id, {"competitor_id": competitor_id, "menu_items": [], "prices": {}})
