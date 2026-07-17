from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EventRecord:
    id: str
    source_evidence_id: str
    external_id: str = ""
    # 安定UID（sha256ベース）。idはDB主キー、uidはICS/外部連携用の安定識別子
    uid: str = ""
    source_id: str = ""
    merged_from_source_ids: list[str] = field(default_factory=list)
    sequence: int = 0
    title: str = ""
    description: str = ""
    category: str = "unknown"
    venue_name: str = ""
    address: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_from_store_km: Optional[float] = None
    starts_at: str = ""
    ends_at: str = ""
    all_day: bool = False
    expected_audience: Optional[int] = None
    audience_segments: list[str] = field(default_factory=list)
    estimated_scale: str = "unknown"  # "small", "medium", "large", "unknown"
    languages: list[str] = field(default_factory=lambda: ["ja"])
    indoor_or_outdoor: str = "unknown"  # "indoor", "outdoor", "mixed", "unknown"
    weather_sensitivity: str = "unknown"  # "high", "medium", "low", "unknown"
    official_url: str = ""
    status: str = "confirmed"  # "confirmed", "tentative", "cancelled", "postponed"
    confidence: float = 1.0
    content_hash: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    source_evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EventRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
