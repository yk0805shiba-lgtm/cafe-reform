from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SourceEvidence:
    id: str
    source_type: str  # "official_site", "ical", "csv", "manual", "fixture", "api", "rss"
    source_name: str
    source_url: str = ""
    external_id: str = ""
    fetched_at: str = ""
    published_at: str = ""
    content_hash: str = ""
    raw_data: dict = field(default_factory=dict)
    confidence: float = 1.0
    terms_or_access_note: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SourceEvidence":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
