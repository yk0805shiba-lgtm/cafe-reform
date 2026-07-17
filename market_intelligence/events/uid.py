"""
安定イベントUID生成。
同じ入力からは常に同じUIDを生成する（決定論的）。
フィールド補完後にUIDを再計算しない。
"""
from __future__ import annotations
import hashlib
import re
import unicodedata


def generate_event_uid(
    source_id: str,
    title: str,
    start_date_jst: str,
    venue: str = "",
) -> str:
    """
    同じ入力から常に同じUIDを生成する。
    start_date_jst はISO8601日付部分（YYYY-MM-DD）を使用する。
    フィールド補完でUIDを再計算しない。

    Returns: "<16hex>@market-intelligence"
    """
    date_part = start_date_jst[:10] if start_date_jst else ""
    normalized_title = _normalize_title(title)
    normalized_venue = _normalize_title(venue)
    seed = "\x1f".join([source_id, normalized_title, date_part, normalized_venue])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{digest}@market-intelligence"


def _normalize_title(s: str) -> str:
    """タイトル正規化：NFKC正規化 → casefold → 記号・空白・改行除去"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.casefold()
    s = re.sub(r"[\s\W]", "", s)
    return s
