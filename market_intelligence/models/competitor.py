from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CompetitorProfile:
    id: str
    name: str
    business_unit: str  # "cafe", "delivery", "both"
    category: str  # e.g. "matcha_cafe", "ramen", "izakaya"
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_from_store_km: Optional[float] = None
    official_website_url: str = ""
    public_menu_url: str = ""
    delivery_platform_urls: list[str] = field(default_factory=list)
    social_urls: list[str] = field(default_factory=list)
    review_source_urls: list[str] = field(default_factory=list)
    monitoring_enabled: bool = True
    monitoring_frequency: str = "daily"  # "daily", "weekly", "manual"
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CompetitorProfile":
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
