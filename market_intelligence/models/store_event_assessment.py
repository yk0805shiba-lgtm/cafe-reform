from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StoreEventAssessment:
    id: str                       # "sea_{event_uid[:8]}_{store_id}"
    event_uid: str                # EventRecordのUID
    store_id: str
    business_unit: str            # "cafe" | "delivery" | "both"
    distance_m: Optional[int]
    impact_score: int             # 0-5
    impact_reasons: list[str] = field(default_factory=list)
    operational_signals: list[str] = field(default_factory=list)
    calculated_at: str = ""       # ISO8601

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StoreEventAssessment":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
