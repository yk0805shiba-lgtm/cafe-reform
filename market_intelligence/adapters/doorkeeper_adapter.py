"""
Doorkeeper APIからイベントデータを取得するアダプター。
認証不要のパブリックAPI。外部コンテンツは信頼できないデータとして扱う。
"""
from __future__ import annotations
import hashlib
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from .base import BaseEventAdapter
from ..models import EventRecord, SourceEvidence

TZ_TOKYO = ZoneInfo("Asia/Tokyo")
TZ_UTC = timezone.utc
JST_OFFSET = timedelta(hours=9)

USER_AGENT = "cafe-reform-market-intelligence/1.0 (yk0805shiba@gmail.com)"
BASE_URL = "https://api.doorkeeper.jp/events"


def _now_jst() -> str:
    return datetime.now(TZ_TOKYO).isoformat()


def _safe_str(val, max_len: int = 500) -> str:
    """外部コンテンツを安全な文字列に変換する。制御文字を除去。"""
    if val is None:
        return ""
    s = str(val)[:max_len].strip()
    s = s.replace("\x00", "").replace("\r", " ")
    return s


def _utc_str_to_jst(utc_str: str) -> str:
    """
    'YYYY-MM-DDTHH:MM:SS.sssZ' 形式のUTC文字列をJSTのISO文字列に変換する。
    例: '2026-07-26T00:30:00.000Z' → '2026-07-26T09:30:00+09:00'
    """
    if not utc_str:
        return ""
    try:
        # .000Z 形式の末尾を正規化
        s = utc_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt_utc = datetime.fromisoformat(s)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=TZ_UTC)
        dt_jst = dt_utc.astimezone(TZ_TOKYO)
        # +09:00 形式で返す
        return dt_jst.isoformat()
    except Exception:
        return utc_str


def _strip_html(text: str) -> str:
    """HTMLタグを除去して安全なプレーンテキストを返す。"""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)


def _estimate_scale(ticket_limit) -> str:
    """ticket_limit から estimated_scale を返す。"""
    try:
        limit = int(ticket_limit or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return "unknown"
    if limit < 50:
        return "small"
    if limit < 300:
        return "medium"
    return "large"


class DoorkeeperAdapter(BaseEventAdapter):
    """Doorkeeper APIからイベントを取得するアダプター"""

    source_type = "doorkeeper_api"

    def __init__(self, source_name: str = "Doorkeeper新宿", keyword: str = "新宿"):
        self.source_name = source_name
        self.keyword = _safe_str(keyword, max_len=100)

    def fetch(self, **kwargs) -> list[dict]:
        """
        Doorkeeper APIからページネーションしてイベントを取得する。
        最大5ページ（500件）。ページ間は1秒待機。
        """
        results = []
        ssl_ctx = ssl.create_default_context()

        for page in range(5):
            offset = page * 100
            try:
                encoded_keyword = urllib.parse.quote(self.keyword)
                url = (
                    f"{BASE_URL}"
                    f"?q={encoded_keyword}"
                    f"&per_page=100"
                    f"&locale=ja"
                    f"&start={offset}"
                )
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
                    body = resp.read().decode("utf-8")

                data = json.loads(body)

                if not data:
                    # 空リストが返ったら終了
                    break

                results.extend(data)

            except Exception as e:
                print(f"[doorkeeper] ページ取得エラー (offset={offset}): {e}")
                break

            if page < 4:
                time.sleep(1)

        return results

    def normalize(self, raw: dict) -> tuple[EventRecord, SourceEvidence]:
        """
        DoorKeeperのレスポンス1件を EventRecord + SourceEvidence に変換する。
        raw は {"event": {...}} 形式。
        """
        event = raw.get("event", raw)

        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        content_hash = hashlib.sha256(
            json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

        # 日時: UTC → JST
        starts_at = _utc_str_to_jst(_safe_str(event.get("starts_at", ""), max_len=50))
        ends_at = _utc_str_to_jst(_safe_str(event.get("ends_at", ""), max_len=50))

        # 説明: HTMLタグ除去 + 500文字上限
        raw_desc = _safe_str(event.get("description", ""), max_len=2000)
        description = _strip_html(raw_desc)[:500]

        # 位置情報
        lat_raw = event.get("lat")
        lon_raw = event.get("long")
        try:
            latitude = float(lat_raw) if lat_raw is not None else None
        except (TypeError, ValueError):
            latitude = None
        try:
            longitude = float(lon_raw) if lon_raw is not None else None
        except (TypeError, ValueError):
            longitude = None

        # 参加者数
        participants = event.get("participants")
        try:
            expected_audience = int(participants) if participants is not None else None
        except (TypeError, ValueError):
            expected_audience = None

        # スケール
        estimated_scale = _estimate_scale(event.get("ticket_limit"))

        # 公式URL
        official_url = _safe_str(event.get("public_url", ""), max_len=200)

        # 外部ID
        external_id = str(event.get("id", ""))

        evidence = SourceEvidence(
            id=evidence_id,
            source_type=self.source_type,
            source_name=self.source_name,
            source_url=official_url,
            external_id=external_id,
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data=raw,
            confidence=0.95,
            terms_or_access_note="Doorkeeper公開API（APIキー不要）内部業務利用のみ・再配布禁止",
            created_at=_now_jst(),
        )

        record = EventRecord(
            id=event_id,
            source_evidence_id=evidence_id,
            external_id=external_id,
            title=_safe_str(event.get("title", ""), max_len=200),
            description=description,
            category="community",
            venue_name=_safe_str(event.get("venue_name", ""), max_len=200),
            address=_safe_str(event.get("address", ""), max_len=300),
            latitude=latitude,
            longitude=longitude,
            distance_from_store_km=None,
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=False,
            expected_audience=expected_audience,
            estimated_scale=estimated_scale,
            indoor_or_outdoor="unknown",
            weather_sensitivity="unknown",
            official_url=official_url,
            status="confirmed",
            confidence=0.95,
            content_hash=content_hash,
            first_seen_at=_now_jst(),
            last_seen_at=_now_jst(),
        )
        return record, evidence
