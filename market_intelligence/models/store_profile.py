from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StoreProfile:
    id: str
    name: str
    business_unit: str  # "cafe", "delivery", "both"
    address: str
    latitude: float
    longitude: float
    timezone: str = "Asia/Tokyo"
    search_radius_km: float = 3.0
    languages: list[str] = field(default_factory=lambda: ["ja"])
    target_segments: list[str] = field(default_factory=list)
    brand_positioning: str = ""
    menu: list[dict] = field(default_factory=list)
    opening_hours: dict = field(default_factory=dict)
    delivery_areas: list[str] = field(default_factory=list)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StoreProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def validate(self) -> list[str]:
        errors = []
        if self.business_unit not in ("cafe", "delivery", "both"):
            errors.append(f"invalid business_unit: {self.business_unit}")
        if not self.id:
            errors.append("id is required")
        if not self.name:
            errors.append("name is required")
        return errors
