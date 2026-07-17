"""
Collect --demo 実行時に使うダミーイベントデータ。
実在するイベントではありません。
starts_at は実行時に「今日+7日」を計算してセットする。
"""
from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")

# ダミーイベント定義（starts_atは実行時に計算）
DEMO_EVENTS: list[dict] = [
    {
        "source_id": "demo",
        "title": "DEMO 新宿御苑周辺テストイベント",
        "description": "これはテスト用のデモイベントです。実在するイベントではありません。",
        "venue": "DEMO会場（新宿御苑前）",
        "address": "東京都新宿区新宿3丁目",
        "lat": 35.6852,
        "lon": 139.7100,
        "category": "festival",
        "all_day": False,
        # starts_at: 実行時に「今日+7日」を計算してセット
        "days_offset": 7,
        "duration_hours": 6,
        "languages": ["ja", "en"],
        "expected_audience": 3000,
    },
    {
        "source_id": "demo",
        "title": "DEMO 新宿文化祭（テスト）",
        "description": "これはテスト用のデモイベントです。実在するイベントではありません。",
        "venue": "DEMO文化会館（テスト）",
        "address": "東京都新宿区新宿2丁目",
        "lat": 35.6900,
        "lon": 139.7030,
        "category": "culture",
        "all_day": False,
        "days_offset": 14,
        "duration_hours": 8,
        "languages": ["ja"],
        "expected_audience": 1500,
    },
]


def make_demo_raw_events() -> list[dict]:
    """実行時にstarts_atを計算してデモイベントリストを返す"""
    now = datetime.now(TZ)
    result = []
    for tmpl in DEMO_EVENTS:
        ev = dict(tmpl)
        days = ev.pop("days_offset", 7)
        duration = ev.pop("duration_hours", 4)
        start = now + timedelta(days=days)
        start = start.replace(hour=11, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=duration)
        ev["starts_at"] = start.isoformat()
        ev["ends_at"] = end.isoformat()
        result.append(ev)
    return result
