"""
新宿文化センター（れがす新宿）イベントカレンダーをスクレイピングするアダプター。
robots.txt: /bunka-center/wp-admin/ のみ禁止。イベントカレンダーパスは許可。
転載禁止の明文なし。内部業務利用のみ・再配布禁止。
外部コンテンツは信頼できないデータとして扱う。

実際のHTML構造（2026-07-16調査）:
  <table id="event-calendar-07" class="event-calendar cal_large-hall">
    <tr><td colspan="5" class="td-month">7月</td></tr>
    <tr><th class="th1">公演日</th>...</tr>
    <tr>
      <td class="td1">4 (<span>土</span>)</td>
      <td class="td2">13：40</td>
      <td class="td3"><a id="45627" name="45627"></a>リゾナーレ吹奏楽団第三回定期演奏会 ...</td>
      <td class="td4">...</td>
      <td class="td5">...</td>
    </tr>
  </table>
"""
from __future__ import annotations
import hashlib
import html.parser
import json
import re
import ssl
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .base import BaseEventAdapter
from ..models import EventRecord, SourceEvidence

TZ_TOKYO = ZoneInfo("Asia/Tokyo")

USER_AGENT = "cafe-reform-market-intelligence/1.0 (yk0805shiba@gmail.com)"

# 会場クラス → 会場名マッピング
HALL_MAP = {
    "cal_large-hall": "新宿文化センター 大ホール",
    "cal_small-hall": "新宿文化センター 小ホール",
    "cal_display-room": "新宿文化センター 展示室",
}

# 時刻パターン（全角・半角コロン両対応）
_TIME_PAT = re.compile(r'(\d{1,2})[：:](\d{2})')

# 月ヘッダーパターン
_MONTH_PAT = re.compile(r'^(\d{1,2})月$')

# 日パターン: "4 (土)" や "4 ( 土 )" など（<span>タグ除去後）
_DAY_PAT = re.compile(r'^(\d{1,2})\s*[（(]\s*[月火水木金土日・祝]+\s*[）)]')


def _now_jst() -> str:
    return datetime.now(TZ_TOKYO).isoformat()


def _safe_str(val, max_len: int = 500) -> str:
    """外部コンテンツを安全な文字列に変換する。制御文字を除去。"""
    if val is None:
        return ""
    s = str(val)[:max_len].strip()
    s = s.replace("\x00", "").replace("\r", " ")
    return s


def _extract_first_time(text: str) -> tuple[int, int] | None:
    """
    テキストから最初の時刻（HH, MM）を返す。
    全角コロン（：）・半角コロン（:）両対応。
    複数開演時刻がある場合は最初のものを採用。
    見つからない場合はNone。
    """
    m = _TIME_PAT.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _make_starts_at(year: int, month: int, day: int, hour: int, minute: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00+09:00"


def _make_ends_at(starts_at: str) -> str:
    """starts_at + 3時間。"""
    try:
        dt = datetime.fromisoformat(starts_at)
        dt_end = dt + timedelta(hours=3)
        return dt_end.isoformat()
    except Exception:
        return ""


def _strip_tags(text: str) -> str:
    """簡易HTMLタグ除去。"""
    return re.sub(r'<[^>]+>', '', text)


class _CalendarParser(html.parser.HTMLParser):
    """
    新宿文化センターのイベントカレンダーHTMLをパースする。

    実際のHTML構造:
      table.event-calendar.cal_large-hall (tableタグ)
        tr > td.td-month: "7月"
        tr > th.th1/th2/th3...: ヘッダー行（スキップ）
        tr > td.td1 / td.td2 / td.td3: イベント行

    td.td1: 日付 例 "4 (<span>土</span>)"
    td.td2: 開演時間 例 "13：40" (全角コロン)
    td.td3: 催事名（aタグ + テキスト混在）
    """

    def __init__(self):
        super().__init__()
        self.events: list[dict] = []

        # 現在のテーブルセクション
        self._current_hall: str | None = None
        self._current_month: int | None = None

        # テーブルスタック（tableタグの深さ管理）
        self._table_stack: list[str] = []  # クラス名のスタック
        self._in_event_table: bool = False

        # 行状態
        self._in_tr: bool = False
        self._current_day: int | None = None
        self._current_time_text: str = ""
        self._current_title: str = ""

        # セル状態
        self._in_td: bool = False
        self._current_td_class: str = ""
        self._td_text_parts: list[str] = []

        # ヘッダー行スキップ（th タグを含む行）
        self._tr_has_th: bool = False

    def handle_starttag(self, tag: str, attrs_list):
        attrs = dict(attrs_list)
        css_class = attrs.get("class", "")

        if tag == "table":
            self._table_stack.append(css_class)
            # event-calendar テーブルを検出
            if "event-calendar" in css_class:
                for hall_class, hall_name in HALL_MAP.items():
                    if hall_class in css_class:
                        self._current_hall = hall_name
                        self._in_event_table = True
                        self._current_month = None
                        break

        elif tag == "tr" and self._in_event_table:
            self._in_tr = True
            self._current_day = None
            self._current_time_text = ""
            self._current_title = ""
            self._tr_has_th = False

        elif tag == "th" and self._in_event_table:
            self._tr_has_th = True

        elif tag == "td" and self._in_event_table and self._in_tr and not self._tr_has_th:
            self._in_td = True
            self._current_td_class = css_class
            self._td_text_parts = []

    def handle_endtag(self, tag: str):
        if tag == "table":
            if self._table_stack:
                closed_class = self._table_stack.pop()
                # event-calendar テーブルが閉じた
                if self._in_event_table and "event-calendar" in closed_class:
                    self._in_event_table = False
                    self._current_hall = None

        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            # イベント行を確定（th行でなく、タイトルと日付がある場合）
            if not self._tr_has_th and self._current_day and self._current_title.strip():
                self.events.append({
                    "_hall": self._current_hall,
                    "_month": self._current_month,
                    "_day": self._current_day,
                    "_time_text": self._current_time_text,
                    "title": _safe_str(self._current_title, max_len=200),
                })
            self._current_day = None
            self._current_time_text = ""
            self._current_title = ""

        elif tag == "td" and self._in_td:
            self._in_td = False
            text = "".join(self._td_text_parts).strip()
            # タグを除去した後のテキスト
            self._process_td(self._current_td_class, text)
            self._current_td_class = ""
            self._td_text_parts = []

    def handle_data(self, data: str):
        if self._in_td:
            self._td_text_parts.append(data)
        elif self._in_event_table and self._in_tr:
            # td外のデータ（テーブル直下のテキスト）は無視
            pass

    def _process_td(self, td_class: str, text: str):
        """tdのクラスと内容テキストに応じて処理する。"""
        text = text.strip()
        if not text:
            return

        if "td-month" in td_class:
            # 月ヘッダー: "7月" など
            m = _MONTH_PAT.match(text)
            if m:
                self._current_month = int(m.group(1))

        elif "td1" in td_class:
            # 日付: "4 (土)" など
            # まず月を含む複合日付をチェック "7月20日（月・祝）..."
            m_full = re.search(r'(\d{1,2})月(\d{1,2})日', text)
            if m_full:
                self._current_month = int(m_full.group(1))
                self._current_day = int(m_full.group(2))
                return
            # 通常の日付パターン "4 (土)"
            m_day = _DAY_PAT.match(text)
            if m_day:
                self._current_day = int(m_day.group(1))

        elif "td2" in td_class:
            # 開演時間
            self._current_time_text = text

        elif "td3" in td_class:
            # 催事名（テキスト取得。空白・改行を正規化）
            # aタグ（id/name属性のみ）のテキストを除去してメインテキストを取る
            # handle_dataで取得したテキストパーツをjoineして使う
            # td_text_parts はすでに設定済みだが、ここでは渡されたtextを使う
            clean = re.sub(r'\s+', ' ', text).strip()
            self._current_title = clean


class RegasuBunkaCenterAdapter(BaseEventAdapter):
    """新宿文化センターのイベントカレンダーをスクレイピングするアダプター"""

    source_type = "html_scrape"
    source_name = "新宿文化センター"
    CALENDAR_URL = "https://www.regasu-shinjuku.or.jp/bunka-center/event-calendar/"
    STORE_ADDRESS = "東京都新宿区新宿6-14-1"
    STORE_LAT = 35.6918
    STORE_LON = 139.7044
    SOURCE_PRIORITY = 5

    def fetch(self, **kwargs) -> list[dict]:
        """
        新宿文化センターのイベントカレンダーHTMLを取得・パースする。
        SSL証明書エラーを無視して接続する。
        最大2回リトライ（計3試行）。エラー時は [] を返す。
        """
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        last_error = None
        for attempt in range(3):  # 最初 + 2回リトライ = 最大3試行
            try:
                req = urllib_request_make(self.CALENDAR_URL)
                html_bytes = urllib_request_fetch(req, ctx, timeout=15)
                try:
                    body = html_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    body = html_bytes.decode("shift_jis", errors="replace")

                content_hash = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:16]
                parser = _CalendarParser()
                parser.feed(body)
                raw_events = parser.events

                if not raw_events:
                    print("[regasu] WARNING: 0件取得。HTML構造が変わった可能性あり")
                    return []

                # 現在年・月を取得してstarts_atを確定させる
                now = datetime.now(TZ_TOKYO)
                result = []
                for ev in raw_events:
                    month = ev.get("_month")
                    day = ev.get("_day")
                    if not month or not day:
                        continue

                    # 月が現在月より過去の場合は翌年と判断
                    year = now.year
                    if month < now.month:
                        year = now.year + 1

                    time_text = ev.get("_time_text", "")
                    time_result = _extract_first_time(time_text)
                    if time_result:
                        hour, minute = time_result
                    else:
                        hour, minute = 12, 0  # 不明な場合は正午をデフォルト

                    starts_at = _make_starts_at(year, month, day, hour, minute)
                    ends_at = _make_ends_at(starts_at)

                    result.append({
                        "title": ev["title"],
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "venue_name": ev.get("_hall") or self.source_name,
                        "address": self.STORE_ADDRESS,
                        "lat": self.STORE_LAT,
                        "lon": self.STORE_LON,
                        "category": "culture",
                        "confidence": 0.90,
                        "_content_hash": content_hash,
                    })

                return result

            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(1)

        print(f"[regasu] fetch エラー: {last_error}")
        return []

    def normalize(self, raw: dict) -> tuple[EventRecord, SourceEvidence]:
        """
        fetch()が返した辞書1件を EventRecord + SourceEvidence に変換する。
        """
        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        event_id = f"evt_{uuid.uuid4().hex[:8]}"

        raw_for_hash = {k: v for k, v in raw.items() if not k.startswith("_")}
        content_hash = hashlib.sha256(
            json.dumps(raw_for_hash, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

        title = _safe_str(raw.get("title", ""), max_len=200)
        starts_at = _safe_str(raw.get("starts_at", ""), max_len=50)
        ends_at = _safe_str(raw.get("ends_at", ""), max_len=50)
        venue_name = _safe_str(raw.get("venue_name", ""), max_len=200)
        address = _safe_str(raw.get("address", self.STORE_ADDRESS), max_len=300)

        lat_raw = raw.get("lat")
        lon_raw = raw.get("lon")
        try:
            latitude = float(lat_raw) if lat_raw is not None else None
        except (TypeError, ValueError):
            latitude = None
        try:
            longitude = float(lon_raw) if lon_raw is not None else None
        except (TypeError, ValueError):
            longitude = None

        confidence = float(raw.get("confidence", 0.90))

        evidence = SourceEvidence(
            id=evidence_id,
            source_type=self.source_type,
            source_name=self.source_name,
            source_url=self.CALENDAR_URL,
            fetched_at=_now_jst(),
            content_hash=content_hash,
            raw_data=raw_for_hash,
            confidence=confidence,
            terms_or_access_note="新宿文化センター公式サイト（robots.txt制限なし）内部業務利用のみ・再配布禁止",
            created_at=_now_jst(),
        )

        record = EventRecord(
            id=event_id,
            source_evidence_id=evidence_id,
            external_id="",
            title=title,
            description="",
            category=_safe_str(raw.get("category", "culture"), max_len=50),
            venue_name=venue_name,
            address=address,
            latitude=latitude,
            longitude=longitude,
            distance_from_store_km=None,
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=False,
            expected_audience=None,
            estimated_scale="unknown",
            indoor_or_outdoor="indoor",
            weather_sensitivity="low",
            official_url=self.CALENDAR_URL,
            status="confirmed",
            confidence=confidence,
            content_hash=content_hash,
            first_seen_at=_now_jst(),
            last_seen_at=_now_jst(),
        )
        return record, evidence


# urllib ヘルパー（テストでモックしやすくするために分離）
import urllib.request as _urllib_request


def urllib_request_make(url: str):
    return _urllib_request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )


def urllib_request_fetch(req, ctx, timeout: int = 15) -> bytes:
    with _urllib_request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return resp.read()
