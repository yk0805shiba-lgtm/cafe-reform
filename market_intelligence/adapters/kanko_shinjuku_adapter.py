"""
新宿観光振興協会サイトからイベントデータをスクレイピングするアダプター。
robots.txt は 404（制限なし）、転載禁止の明文なし。内部業務利用のみ。
外部コンテンツは信頼できないデータとして扱う。
"""
from __future__ import annotations
import hashlib
import html.parser
import json
import re
import ssl
import time
import urllib.request
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .base import BaseEventAdapter
from ..models import EventRecord, SourceEvidence

TZ_TOKYO = ZoneInfo("Asia/Tokyo")

BASE_URL = "https://www.kanko-shinjuku.jp"
EVENT_INDEX_PATH = "/event/-/index.html"
USER_AGENT = "cafe-reform-market-intelligence/1.0 (yk0805shiba@gmail.com)"

# カテゴリマッピング
CATEGORY_MAP = {
    "エンタメ": "festival",
    "まつり・伝統": "festival",
    "文化": "culture",
    "芸術": "culture",
    "スポーツ": "sports",
    "グルメ": "food",
    "観光": "tourism",
}


def _now_jst() -> str:
    return datetime.now(TZ_TOKYO).isoformat()


def _safe_str(val, max_len: int = 500) -> str:
    """外部コンテンツを安全な文字列に変換する。制御文字を除去。"""
    if val is None:
        return ""
    s = str(val)[:max_len].strip()
    s = s.replace("\x00", "").replace("\r", " ")
    return s


def _map_category(categories: list[str]) -> str:
    """観光サイトのカテゴリ名を内部カテゴリにマッピングする。"""
    for cat in categories:
        mapped = CATEGORY_MAP.get(cat)
        if mapped:
            return mapped
    return "local_event"


def _parse_date_range(raw_date: str) -> tuple[str, str]:
    """
    日付文字列をパースして (starts_at, ends_at) のISO文字列を返す。

    対応形式:
    - 単日: '2026年7月25日(土)' → ('2026-07-25T11:00:00+09:00', '2026-07-25T20:00:00+09:00')
    - 期間: '2026年8月29日(土)～30日(日)' → (Aug 29, Aug 30)
    - 期間（月をまたぐ）: '2026年7月31日(土)～8月1日(日)' → (Jul 31, Aug 1)
    """
    raw_date = _safe_str(raw_date, max_len=100)

    # 波ダッシュ（〜・～・〜）で分割
    tilde_pattern = r'[～〜~]'
    parts = re.split(tilde_pattern, raw_date, maxsplit=1)

    def extract_ymd(text: str) -> tuple[int, int, int] | None:
        """'YYYY年M月D日(曜日)' または 'D日(曜日)' から年月日を抽出する。"""
        # 年月日の完全形
        m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        # 月日のみ（年は前のパートから引き継ぐ）
        m = re.search(r'(\d{1,2})月(\d{1,2})日', text)
        if m:
            return None, int(m.group(1)), int(m.group(2))
        # 日のみ
        m = re.search(r'(\d{1,2})日', text)
        if m:
            return None, None, int(m.group(1))
        return None

    start_ymd = extract_ymd(parts[0])
    if start_ymd is None:
        # パース失敗時はとりあえず空文字列
        return "", ""

    start_year, start_month, start_day = start_ymd

    # 年月が取れなかった場合は今年・今月を使う（フォールバック）
    now = datetime.now(TZ_TOKYO)
    if start_year is None:
        start_year = now.year
    if start_month is None:
        start_month = now.month

    starts_at = f"{start_year:04d}-{start_month:02d}-{start_day:02d}T11:00:00+09:00"

    if len(parts) == 1:
        # 単日
        ends_at = f"{start_year:04d}-{start_month:02d}-{start_day:02d}T20:00:00+09:00"
        return starts_at, ends_at

    # 期間: 終了日をパース
    end_raw = parts[1]
    end_ymd = extract_ymd(end_raw)
    if end_ymd is None:
        ends_at = f"{start_year:04d}-{start_month:02d}-{start_day:02d}T20:00:00+09:00"
        return starts_at, ends_at

    end_year, end_month, end_day = end_ymd
    if end_year is None:
        end_year = start_year
    if end_month is None:
        end_month = start_month

    ends_at = f"{end_year:04d}-{end_month:02d}-{end_day:02d}T20:00:00+09:00"
    return starts_at, ends_at


class _EventBlockParser(html.parser.HTMLParser):
    """
    `div.event_pickup_box` ブロックを抽出してイベント情報を収集する。
    シンプルな状態マシンで実装。
    """

    def __init__(self):
        super().__init__()
        self._events: list[dict] = []
        self._in_box = False
        self._box_depth = 0
        self._in_category = False
        self._in_h3 = False
        self._in_schedule = False
        self._in_desc_p = False
        self._in_button = False
        self._in_a_href = False

        self._current: dict = {}
        self._div_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs_list):
        attrs = dict(attrs_list)
        css_class = attrs.get("class", "")

        if tag == "div":
            if "event_pickup_box" in css_class:
                self._in_box = True
                self._box_depth = 1
                self._current = {
                    "title": "",
                    "raw_date": "",
                    "categories": [],
                    "description": "",
                    "url": "",
                }
                self._div_stack = ["event_pickup_box"]
            elif self._in_box:
                self._box_depth += 1
                self._div_stack.append(css_class)
                if "schedule_block" in css_class:
                    self._in_schedule = True
                elif "parts_button3" in css_class:
                    self._in_button = True

        elif tag == "ul" and self._in_box:
            if "category_block" in css_class:
                self._in_category = True

        elif tag == "li" and self._in_category:
            pass  # category テキストは handle_data で取得

        elif tag == "h3" and self._in_box:
            self._in_h3 = True

        elif tag == "p" and self._in_box and not self._in_category and not self._in_schedule and not self._in_button:
            self._in_desc_p = True

        elif tag == "a" and self._in_button:
            href = attrs.get("href", "")
            if href:
                self._current["url"] = _safe_str(href, max_len=300)
            self._in_a_href = True

    def handle_endtag(self, tag: str):
        if not self._in_box:
            return

        if tag == "div":
            self._box_depth -= 1
            if self._div_stack:
                closed = self._div_stack.pop()
                if "schedule_block" in closed:
                    self._in_schedule = False
                elif "parts_button3" in closed:
                    self._in_button = False

            if self._box_depth <= 0:
                # event_pickup_box が閉じた
                self._in_box = False
                self._box_depth = 0
                if self._current.get("title"):
                    self._events.append(dict(self._current))
                self._current = {}

        elif tag == "ul":
            self._in_category = False

        elif tag == "h3":
            self._in_h3 = False

        elif tag == "p":
            self._in_desc_p = False

        elif tag == "a":
            self._in_a_href = False

    def handle_data(self, data: str):
        if not self._in_box:
            return
        text = _safe_str(data.strip(), max_len=500)
        if not text:
            return

        if self._in_h3:
            self._current["title"] = self._current.get("title", "") + text
        elif self._in_schedule:
            self._current["raw_date"] = self._current.get("raw_date", "") + text
        elif self._in_category:
            if text not in self._current["categories"]:
                self._current["categories"].append(text)
        elif self._in_desc_p:
            existing = self._current.get("description", "")
            self._current["description"] = (existing + " " + text).strip()[:500]

    @property
    def events(self) -> list[dict]:
        return self._events


class KankoShinjukuAdapter(BaseEventAdapter):
    """新宿観光振興協会サイトからイベントをスクレイピングするアダプター"""

    source_type = "html_scrape"

    def __init__(self, source_name: str = "新宿観光振興協会", max_pages: int = 3):
        self.source_name = source_name
        self.max_pages = max_pages

    def fetch(self, **kwargs) -> list[dict]:
        """
        新宿観光振興協会のイベント一覧ページをスクレイピングする。
        最大 max_pages ページ。ページ間は2秒待機。
        """
        results: list[dict] = []
        ssl_ctx = ssl.create_default_context()

        for page in range(self.max_pages):
            if page == 0:
                path = EVENT_INDEX_PATH
            else:
                offset = page * 20
                path = f"/event/-vi-{offset}/index.html"

            url = BASE_URL + path

            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
                    raw_bytes = resp.read()

                # エンコーディングを検出して読む
                try:
                    body = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    body = raw_bytes.decode("shift_jis", errors="replace")

                parser = _EventBlockParser()
                parser.feed(body)
                page_events = parser.events

                if not page_events:
                    break

                # ソース情報を付与
                for ev in page_events:
                    ev["_source_url"] = url
                results.extend(page_events)

            except Exception as e:
                print(f"[kanko_shinjuku] ページ取得エラー ({url}): {e}")
                break

            if page < self.max_pages - 1:
                time.sleep(2)

        return results

    def normalize(self, raw: dict) -> tuple[EventRecord, SourceEvidence]:
        """
        スクレイピング結果1件を EventRecord + SourceEvidence に変換する。
        """
        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        content_hash = hashlib.sha256(
            json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

        title = _safe_str(raw.get("title", ""), max_len=200)
        raw_date = _safe_str(raw.get("raw_date", ""), max_len=100)
        categories = raw.get("categories", [])
        description = _safe_str(raw.get("description", ""), max_len=500)
        official_url = _safe_str(raw.get("url", ""), max_len=300)
        source_url = _safe_str(raw.get("_source_url", BASE_URL + EVENT_INDEX_PATH), max_len=300)

        # 日付パース
        starts_at, ends_at = _parse_date_range(raw_date)

        # カテゴリマッピング
        category = _map_category(categories)

        evidence = SourceEvidence(
            id=evidence_id,
            source_type=self.source_type,
            source_name=self.source_name,
            source_url=source_url,
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data=raw,
            confidence=0.85,
            terms_or_access_note="新宿観光振興協会サイト（robots.txt未設定、転載禁止明文なし）内部業務利用のみ・再配布禁止",
            created_at=_now_jst(),
        )

        record = EventRecord(
            id=event_id,
            source_evidence_id=evidence_id,
            external_id="",
            title=title,
            description=description,
            category=category,
            venue_name="",
            address="東京都新宿区",
            latitude=None,
            longitude=None,
            distance_from_store_km=None,
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=False,
            expected_audience=None,
            estimated_scale="unknown",
            indoor_or_outdoor="unknown",
            weather_sensitivity="unknown",
            official_url=official_url,
            status="confirmed",
            confidence=0.85,
            content_hash=content_hash,
            first_seen_at=_now_jst(),
            last_seen_at=_now_jst(),
        )
        return record, evidence
