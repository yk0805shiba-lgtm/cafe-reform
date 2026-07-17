"""テスト共通フィクスチャ"""
import os
import sys
import tempfile
import pytest
from pathlib import Path

# cafe-reform ディレクトリをパスに追加（market_intelligence パッケージを認識させる）
_CAFE_REFORM_DIR = Path(__file__).resolve().parents[2]
if str(_CAFE_REFORM_DIR) not in sys.path:
    sys.path.insert(0, str(_CAFE_REFORM_DIR))

# テスト用にDEMOモードを有効化
os.environ["LOCAL_INTELLIGENCE_DEMO_MODE"] = "true"
# テスト用に一時ディレクトリを使う
_tmp = tempfile.mkdtemp()
os.environ["LOCAL_INTELLIGENCE_DATA_DIR"] = _tmp


@pytest.fixture(autouse=True)
def fresh_store(tmp_path):
    """各テストごとにクリーンなストアを提供"""
    import importlib
    import market_intelligence.config as cfg
    old_dir = cfg.DATA_DIR
    cfg.DATA_DIR = tmp_path
    yield tmp_path
    cfg.DATA_DIR = old_dir


@pytest.fixture(autouse=True)
def isolate_operational_overrides(tmp_path, monkeypatch):
    """テストが実際の operational_overrides.json を汚染しないようにする"""
    import market_intelligence.overrides.operational_overrides as oo_mod
    tmp_overrides = tmp_path / "operational_overrides.json"
    monkeypatch.setattr(oo_mod, "DEFAULT_OVERRIDES_PATH", tmp_overrides)
    yield


@pytest.fixture
def store(fresh_store):
    from market_intelligence.storage import JsonStore
    s = JsonStore(fresh_store)
    s.initialize_schema()
    return s


@pytest.fixture
def demo_store_cafe():
    return {
        "id": "cafe_test",
        "name": "テストカフェ",
        "business_unit": "cafe",
        "address": "東京都新宿区西新宿1-1-1",
        "latitude": 35.6895,
        "longitude": 139.6917,
        "timezone": "Asia/Tokyo",
        "search_radius_km": 3.0,
        "languages": ["ja", "en"],
        "target_segments": ["young_adults", "tourists"],
        "brand_positioning": "抹茶カフェ",
        "menu": [{"name": "抹茶ラテ", "price": 650}],
        "opening_hours": {"open": "09:00", "close": "21:00"},
        "delivery_areas": [],
        "enabled": True,
        "created_at": "2026-07-14T00:00:00+09:00",
        "updated_at": "2026-07-14T00:00:00+09:00",
    }


@pytest.fixture
def demo_store_delivery():
    return {
        "id": "delivery_test",
        "name": "テストデリバリー",
        "business_unit": "delivery",
        "address": "東京都新宿区西新宿2-2-2",
        "latitude": 35.6880,
        "longitude": 139.6930,
        "timezone": "Asia/Tokyo",
        "search_radius_km": 5.0,
        "languages": ["ja"],
        "target_segments": ["office_workers", "night_workers"],
        "brand_positioning": "混ぜそばデリバリー",
        "menu": [{"name": "混ぜそば（並）", "price": 950}],
        "opening_hours": {"open": "11:00", "close": "03:00"},
        "delivery_areas": ["新宿区"],
        "enabled": True,
        "created_at": "2026-07-14T00:00:00+09:00",
        "updated_at": "2026-07-14T00:00:00+09:00",
    }
