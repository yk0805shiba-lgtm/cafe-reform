from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawEvent:
    source_id: str
    source_priority: int
    external_id: Optional[str]
    title: str
    description: Optional[str]
    start_raw: str
    end_raw: Optional[str]
    all_day_hint: Optional[bool]
    venue: Optional[str]
    address: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    url: Optional[str]
    category_hint: Optional[str]
    fetched_at: str  # ISO8601
    source_hash: str
    raw_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RawEvent":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
