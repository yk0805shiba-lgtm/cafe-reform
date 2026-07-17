from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AgentRun:
    id: str
    agent_type: str  # "local_event_promotion", "competitor_monitoring"
    store_id: str
    started_at: str
    finished_at: str = ""
    status: str = "running"  # "running", "success", "failed", "partial"
    trigger_type: str = "manual"  # "manual", "scheduled", "demo"
    records_fetched: int = 0
    records_created: int = 0
    records_updated: int = 0
    recommendations_created: int = 0
    error_summary: str = ""
    provider_status: dict = field(default_factory=dict)
    prompt_version: str = "1.0"
    model_info: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentRun":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
