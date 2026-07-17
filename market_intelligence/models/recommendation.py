from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Recommendation:
    id: str
    agent_type: str  # "local_event_promotion", "competitor_monitoring"
    store_id: str
    business_unit: str  # "cafe", "delivery", "both"
    category: str
    title: str
    summary: str
    reason: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.8
    estimated_impact: str = "medium"  # "high", "medium", "low"
    effort: str = "medium"           # "high", "medium", "low"
    urgency: str = "medium"          # "high", "medium", "low"
    recommended_start_at: str = ""
    recommended_end_at: str = ""
    status: str = "draft"  # "draft", "approved", "rejected", "completed"
    approval_required: bool = True
    source_ref: str = ""  # event_id or competitor_id that triggered this
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Recommendation":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ApprovalHistory:
    recommendation_id: str
    action: str  # "approved", "rejected", "completed"
    actor: str
    comment: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ApprovalHistory":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CreativeBrief:
    id: str
    store_id: str
    business_unit: str
    event_id: str
    campaign_goal: str
    target_audience: str
    recommended_product: str
    offer: str
    key_message: str
    opening_hook: str
    call_to_action: str
    language: str = "ja"
    tone: str = ""
    recommended_publish_at: str = ""
    campaign_start_at: str = ""
    campaign_end_at: str = ""
    asset_requirements: dict = field(default_factory=dict)
    weather_context: str = ""
    source_evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.8
    status: str = "draft"  # "draft", "approved"
    created_at: str = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CreativeBrief":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
