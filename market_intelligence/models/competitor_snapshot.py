from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CompetitorSnapshot:
    id: str
    competitor_id: str
    captured_at: str
    source_evidence_ids: list[str] = field(default_factory=list)
    menu_items: list[dict] = field(default_factory=list)
    prices: dict = field(default_factory=dict)
    sets: list[dict] = field(default_factory=list)
    discounts: list[dict] = field(default_factory=list)
    new_items: list[dict] = field(default_factory=list)
    removed_items: list[dict] = field(default_factory=list)
    opening_hours: dict = field(default_factory=dict)
    order_availability: Optional[bool] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    review_topics: dict = field(default_factory=dict)
    photo_metadata: list[dict] = field(default_factory=list)
    content_hash: str = ""
    status: str = "success"  # "success", "failed", "partial", "unavailable"
    confidence: float = 0.8

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CompetitorSnapshot":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class PriceChange:
    item_name: str
    previous_price: Optional[int]
    current_price: Optional[int]
    difference: Optional[int]
    change_rate_pct: Optional[float]

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


@dataclass
class SnapshotDiff:
    id: str
    competitor_id: str
    previous_snapshot_id: str
    current_snapshot_id: str
    compared_at: str
    price_changes: list[dict] = field(default_factory=list)
    new_items: list[dict] = field(default_factory=list)
    removed_items: list[dict] = field(default_factory=list)
    set_changes: list[dict] = field(default_factory=list)
    discount_changes: list[dict] = field(default_factory=list)
    opening_hours_changes: list[dict] = field(default_factory=list)
    order_availability_change: Optional[dict] = None
    rating_change: Optional[dict] = None
    review_count_change: Optional[dict] = None
    review_topic_changes: list[dict] = field(default_factory=list)
    photo_changes: list[dict] = field(default_factory=list)
    severity: str = "low"  # "low", "medium", "high"
    has_changes: bool = False

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SnapshotDiff":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
