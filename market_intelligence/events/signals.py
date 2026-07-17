"""
LLMを使わない決定的なoperational signals計算。
カフェ向けとデリバリー向けの2種類を提供する。
"""
from __future__ import annotations
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt
    except Exception:
        return None


def _parse_hhmm(hhmm: str) -> time | None:
    """'HH:MM' 形式をtimeに変換する"""
    if not hhmm:
        return None
    try:
        parts = hhmm.split(":")
        return time(int(parts[0]) % 24, int(parts[1]))
    except Exception:
        return None


def _time_on_date(base_dt: datetime, hhmm: str) -> datetime | None:
    """baseと同じ日にHH:MMのdatetimeを生成する"""
    t = _parse_hhmm(hhmm)
    if t is None:
        return None
    return base_dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def _overlap_minutes(s1: datetime, e1: datetime, s2: datetime, e2: datetime) -> int:
    """2つの期間の重なり分数を返す"""
    overlap_start = max(s1, s2)
    overlap_end = min(e1, e2)
    if overlap_end <= overlap_start:
        return 0
    return int((overlap_end - overlap_start).total_seconds() / 60)


def compute_cafe_signals(
    event_start: str,       # ISO8601
    event_end: str | None,
    store_open: str,        # "09:00"
    store_close: str,       # "21:00"
    distance_m: int | None,
    category: str,
    languages: list[str],
) -> list[str]:
    """
    カフェ向けoperational signals（決定的）。

    生成シグナル:
    - pre_event_walk_in: イベント開始前1〜3時間が営業時間内
    - during_event_walk_in: イベント時間と営業時間が60分以上重なる
    - takeout_opportunity: festival/market/culture/exhibitionで近距離(<1500m)
    - inbound_language_support_possible: languagesにen/zh/ko等
    - daytime_peak_possible: イベント日に昼帯(11:00-17:00)が含まれる
    """
    signals: list[str] = []

    ev_start_dt = _parse_dt(event_start)
    if ev_start_dt is None:
        return signals

    ev_end_dt = _parse_dt(event_end) if event_end else ev_start_dt + timedelta(hours=2)

    # 店舗営業時間を当日のdatetimeに変換
    store_open_dt = _time_on_date(ev_start_dt, store_open)
    store_close_dt = _time_on_date(ev_start_dt, store_close)
    if store_open_dt is None or store_close_dt is None:
        return signals

    # 閉店が開店より前（翌日にまたぐ）の場合は翌日扱い
    if store_close_dt <= store_open_dt:
        store_close_dt += timedelta(days=1)

    # pre_event_walk_in: イベント開始前1〜3時間が営業時間内
    pre_start = ev_start_dt - timedelta(hours=3)
    pre_end = ev_start_dt - timedelta(hours=1)
    pre_overlap = _overlap_minutes(pre_start, pre_end, store_open_dt, store_close_dt)
    if pre_overlap >= 30:
        signals.append("pre_event_walk_in")

    # during_event_walk_in: イベント時間と営業時間が60分以上重なる
    during_overlap = _overlap_minutes(ev_start_dt, ev_end_dt, store_open_dt, store_close_dt)
    if during_overlap >= 60:
        signals.append("during_event_walk_in")

    # takeout_opportunity: 特定カテゴリ + 近距離
    takeout_categories = {"festival", "market", "culture", "exhibition", "fireworks", "tourism"}
    if category in takeout_categories:
        if distance_m is not None and distance_m < 1500:
            signals.append("takeout_opportunity")

    # inbound_language_support_possible: en/zh/ko等が含まれる
    inbound_langs = {"en", "zh", "ko", "fr", "es", "de", "it", "pt", "ru", "ar", "th"}
    if any(lang in inbound_langs for lang in languages):
        signals.append("inbound_language_support_possible")

    # daytime_peak_possible: イベント日に昼帯(11:00-17:00)が含まれる
    daytime_start = _time_on_date(ev_start_dt, "11:00")
    daytime_end = _time_on_date(ev_start_dt, "17:00")
    if daytime_start and daytime_end:
        daytime_overlap = _overlap_minutes(ev_start_dt, ev_end_dt, daytime_start, daytime_end)
        if daytime_overlap >= 60:
            signals.append("daytime_peak_possible")

    return signals


def compute_delivery_signals(
    event_start: str,
    event_end: str | None,
    delivery_peak_windows: list[dict],   # [{"start":"20:00","end":"01:00"}]
    distance_m: int | None,
    delivery_radius_km: float,
    event_lat: float | None,
    event_lon: float | None,
    store_lat: float,
    store_lon: float,
    category: str,
) -> list[str]:
    """
    デリバリー向けoperational signals（決定的）。

    生成シグナル:
    - post_event_delivery_possible: イベント終了がpeak window内
    - evening_peak_possible: 18:00以降終了
    - late_event_end: 21:00以降終了
    - delivery_area_overlap: 会場が配達圏内
    - high_kitchen_load_possible: カテゴリがfestival/concert/sports + peak帯に重なる
    """
    signals: list[str] = []

    ev_start_dt = _parse_dt(event_start)
    if ev_start_dt is None:
        return signals

    ev_end_dt = _parse_dt(event_end) if event_end else ev_start_dt + timedelta(hours=2)

    # delivery_area_overlap: 会場が配達圏内
    if event_lat is not None and event_lon is not None:
        from market_intelligence.utils import haversine
        dist_km = haversine(store_lat, store_lon, event_lat, event_lon)
        if dist_km <= delivery_radius_km:
            signals.append("delivery_area_overlap")

    # evening_peak_possible: 18:00以降終了
    evening_threshold = _time_on_date(ev_end_dt, "18:00")
    if evening_threshold and ev_end_dt >= evening_threshold:
        signals.append("evening_peak_possible")

    # late_event_end: 21:00以降終了
    late_threshold = _time_on_date(ev_end_dt, "21:00")
    if late_threshold and ev_end_dt >= late_threshold:
        signals.append("late_event_end")

    # post_event_delivery_possible: イベント終了がpeak window内
    for pw in delivery_peak_windows:
        pw_start_str = pw.get("start", "")
        pw_end_str = pw.get("end", "")
        if not pw_start_str or not pw_end_str:
            continue
        pw_start = _time_on_date(ev_end_dt, pw_start_str)
        pw_end = _time_on_date(ev_end_dt, pw_end_str)
        if pw_start is None or pw_end is None:
            continue
        # ピークがまたぐ場合（例: 20:00〜01:00）
        if pw_end <= pw_start:
            pw_end += timedelta(days=1)
        # イベント終了がpeak windowの前後30分以内か、window内にある
        window_with_buffer_start = pw_start - timedelta(minutes=30)
        window_with_buffer_end = pw_end + timedelta(minutes=30)
        if window_with_buffer_start <= ev_end_dt <= window_with_buffer_end:
            signals.append("post_event_delivery_possible")
            break

    # high_kitchen_load_possible: 特定カテゴリ + ピーク帯に重なる
    high_load_categories = {"festival", "concert", "sports", "fireworks"}
    if category in high_load_categories and "post_event_delivery_possible" in signals:
        signals.append("high_kitchen_load_possible")

    return signals
