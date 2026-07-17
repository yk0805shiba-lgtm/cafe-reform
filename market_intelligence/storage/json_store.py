"""
ファイルベースのJSONストレージ。
既存プロジェクトにDBがないため、JSON形式でデータを永続化する。
各コレクションは1ファイル（リスト形式）で管理する。
"""
from __future__ import annotations
import json
import os
import fcntl
import tempfile
from pathlib import Path
from typing import Any, Optional


class JsonStore:
    """スレッドセーフなJSONファイルベースストレージ"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, collection: str) -> Path:
        return self.data_dir / f"{collection}.json"

    def _read_all(self, collection: str) -> list[dict]:
        p = self._path(collection)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _write_all(self, collection: str, records: list[dict]) -> None:
        p = self._path(collection)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.data_dir, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, p)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def upsert(self, collection: str, record: dict, key: str = "id") -> bool:
        """存在すれば更新、なければ挿入。戻り値: Trueで新規作成、Falseで更新"""
        records = self._read_all(collection)
        key_val = record.get(key)
        for i, r in enumerate(records):
            if r.get(key) == key_val:
                records[i] = record
                self._write_all(collection, records)
                return False
        records.append(record)
        self._write_all(collection, records)
        return True

    def get(self, collection: str, id: str, key: str = "id") -> Optional[dict]:
        for r in self._read_all(collection):
            if r.get(key) == id:
                return r
        return None

    def list_all(self, collection: str) -> list[dict]:
        return self._read_all(collection)

    def filter(self, collection: str, **kwargs) -> list[dict]:
        results = []
        for r in self._read_all(collection):
            if all(r.get(k) == v for k, v in kwargs.items()):
                results.append(r)
        return results

    def delete(self, collection: str, id: str, key: str = "id") -> bool:
        records = self._read_all(collection)
        new_records = [r for r in records if r.get(key) != id]
        if len(new_records) == len(records):
            return False
        self._write_all(collection, new_records)
        return True

    def exists(self, collection: str, id: str, key: str = "id") -> bool:
        return self.get(collection, id, key) is not None

    def count(self, collection: str) -> int:
        return len(self._read_all(collection))

    def update_field(self, collection: str, id: str, field: str, value: Any, key: str = "id") -> bool:
        records = self._read_all(collection)
        for i, r in enumerate(records):
            if r.get(key) == id:
                records[i][field] = value
                self._write_all(collection, records)
                return True
        return False

    def initialize_schema(self) -> None:
        """全コレクションの初期ファイルを作成（マイグレーション相当）"""
        collections = [
            "store_profiles",
            "source_evidence",
            "event_records",
            "recommendations",
            "approval_history",
            "creative_briefs",
            "agent_runs",
            "competitor_profiles",
            "competitor_snapshots",
            "snapshot_diffs",
            "temporary_playbooks",
            "raw_events",
            "store_event_assessments",
            # Phase 6: shadow mode
            "shadow_event_records",
            "shadow_store_event_assessments",
            "shadow_source_evidence",
            "shadow_reports",
            "event_collection_settings",
        ]
        for c in collections:
            p = self._path(c)
            if not p.exists():
                self._write_all(c, [])
        print(f"[storage] スキーマ初期化完了: {self.data_dir}")
