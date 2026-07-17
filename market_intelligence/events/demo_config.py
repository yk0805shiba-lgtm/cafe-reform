"""
正式なデモ設定生成。
STORE_PROFILES_JSON Secret が未設定の場合に使用する。
秘密情報を含まない。
"""
from __future__ import annotations
import json
from pathlib import Path

_DEMO_PROFILES: list[dict] = [
    {
        "id": "cafe_01",
        "name": "Cafe Demo Store [DEMO]",
        "business_unit": "cafe",
        "address": "東京都新宿区新宿1丁目",
        "latitude": 35.6918,
        "longitude": 139.7044,
        "search_radius_km": 1.0,
        "timezone": "Asia/Tokyo",
        "languages": ["ja"],
        "target_segments": [],
        "brand_positioning": "DEMO",
        "event_sources": [
            {"type": "kanko_shinjuku", "name": "新宿観光振興協会", "enabled": True, "max_pages": 3},
            {"type": "doorkeeper", "name": "Doorkeeper新宿", "enabled": True, "keyword": "新宿"},
            {"type": "regasu_bunka_center", "name": "新宿文化センター", "enabled": True},
            {"type": "demo", "name": "デモイベント", "enabled": True},
        ],
        "opening_hours": {"open": "09:00", "close": "21:00"},
        "enabled": True,
    },
    {
        "id": "delivery_01",
        "name": "Delivery Demo Store [DEMO]",
        "business_unit": "delivery",
        "address": "東京都新宿区新宿1丁目",
        "latitude": 35.6918,
        "longitude": 139.7044,
        "search_radius_km": 5.0,
        "timezone": "Asia/Tokyo",
        "languages": ["ja"],
        "target_segments": [],
        "brand_positioning": "DEMO",
        "event_sources": [
            {"type": "doorkeeper", "name": "Doorkeeper新宿", "enabled": True, "keyword": "新宿"},
            {"type": "demo", "name": "デモイベント", "enabled": True},
        ],
        "opening_hours": {"open": "09:00", "close": "21:00"},
        "enabled": True,
    },
]


def generate_demo_profiles() -> list[dict]:
    """デモ用store_profileリストを返す（list-of-dicts形式）。"""
    import copy
    return copy.deepcopy(_DEMO_PROFILES)


def write_demo_profiles(output_path: Path) -> None:
    """デモ設定をJSONファイルに書き込む。"""
    from .config_validator import validate_store_profiles
    profiles = generate_demo_profiles()
    errors = validate_store_profiles(profiles)
    if errors:
        raise ValueError("デモ設定のバリデーション失敗:\n" + "\n".join(errors))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
