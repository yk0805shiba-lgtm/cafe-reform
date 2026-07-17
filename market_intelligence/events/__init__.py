"""近隣イベント機能パッケージ。Phase 1: スキーマ・ICS・デモデータ。"""
from .uid import generate_event_uid
from .impact import compute_impact_score
from .signals import compute_cafe_signals, compute_delivery_signals
from .ics_builder import build_ics_feed
from .collect import collect_events
from .service import build_feeds
from .query import query_events

__all__ = [
    "generate_event_uid",
    "compute_impact_score",
    "compute_cafe_signals",
    "compute_delivery_signals",
    "build_ics_feed",
    "collect_events",
    "build_feeds",
    "query_events",
]
