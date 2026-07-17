"""
共通Adapterインターフェース。
全てのデータソースAdapterはこれを継承し、
fetch → normalize → validate → deduplicate → persist の流れを実装する。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from ..models import EventRecord, SourceEvidence, CompetitorSnapshot


class BaseEventAdapter(ABC):
    """イベントデータソースの共通インターフェース"""

    source_type: str = "unknown"
    source_name: str = "unknown"

    @abstractmethod
    def fetch(self, **kwargs) -> list[dict]:
        """外部ソースから生データを取得する"""
        ...

    @abstractmethod
    def normalize(self, raw: dict) -> tuple[EventRecord, SourceEvidence]:
        """生データをEventRecord + SourceEvidenceに正規化する"""
        ...

    def validate(self, record: EventRecord) -> list[str]:
        """バリデーションエラーリストを返す。空リストなら合格"""
        errors = []
        if not record.title:
            errors.append("title is empty")
        if not record.starts_at:
            errors.append("starts_at is empty")
        return errors

    def is_available(self) -> bool:
        """このAdapterが利用可能かどうかを返す"""
        return True

    def availability_message(self) -> str:
        return ""


class BaseCompetitorAdapter(ABC):
    """競合データソースの共通インターフェース"""

    source_type: str = "unknown"
    source_name: str = "unknown"

    @abstractmethod
    def fetch(self, competitor_id: str, **kwargs) -> dict:
        """競合の公開情報を取得する"""
        ...

    @abstractmethod
    def to_snapshot(self, raw: dict, competitor_id: str) -> tuple[CompetitorSnapshot, SourceEvidence]:
        """生データをCompetitorSnapshot + SourceEvidenceに変換する"""
        ...

    def is_available(self) -> bool:
        return True

    def availability_message(self) -> str:
        return ""
