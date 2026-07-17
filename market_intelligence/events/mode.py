"""
イベント収集モード管理: shadow / active / manual-only

shadow     : 自動収集→shadow_event_records。canonical(event_records)は変更しない。
active     : 自動収集→event_records(canonical)。手動入力は補正・緊急追加用。
manual-only: event_records の手動イベントのみ使用。外部source障害時の緊急退避。

今回はshadowのみ有効化。activeへの切り替えはオーナーの明示的な承認が必要。
"""
from __future__ import annotations
from ..storage import JsonStore
from ..utils import now_jst_iso

VALID_MODES = ("shadow", "active", "manual-only")
COLLECTION = "event_collection_settings"
SETTINGS_ID = "current"

# 自動収集対象のsource_type（shadow syncで収集されるもの）
AUTO_SOURCE_TYPES: frozenset[str] = frozenset({
    "kanko_shinjuku",
    "doorkeeper",
    "regasu_bunka_center",
    "ical",
})

# 手動入力と見なすsource_type
MANUAL_SOURCE_TYPES: frozenset[str] = frozenset({
    "csv",
    "manual",
    "demo",
})


def get_settings(store: JsonStore) -> dict:
    """現在のモード設定を返す。存在しない場合はデフォルト（shadow）を返す。"""
    s = store.get(COLLECTION, SETTINGS_ID)
    if not s:
        return _default_settings()
    return s


def get_current_mode(store: JsonStore) -> str:
    """現在のモードを返す: 'shadow' | 'active' | 'manual-only'"""
    return get_settings(store).get("mode", "shadow")


def set_mode(store: JsonStore, mode: str) -> None:
    """モードを設定する。activeへの切り替えは呼び出し側で確認済みであること。"""
    if mode not in VALID_MODES:
        raise ValueError(f"不正なモード: {mode}  有効値: {VALID_MODES}")
    settings = get_settings(store)
    settings["mode"] = mode
    settings["updated_at"] = now_jst_iso()
    store.upsert(COLLECTION, settings)


def is_auto_source(src: dict) -> bool:
    """store_profileのevent_source定義が自動収集対象かどうか"""
    return src.get("type", "") in AUTO_SOURCE_TYPES


def is_manual_source(src: dict) -> bool:
    """store_profileのevent_source定義が手動入力扱いかどうか"""
    src_type = src.get("type", "")
    if src_type in MANUAL_SOURCE_TYPES:
        return True
    # CSV でも名前に「手動」「manual」が含まれる場合は手動扱い
    name = src.get("name", "").lower()
    if src_type == "csv" and ("手動" in name or "manual" in name):
        return True
    return False


def _default_settings() -> dict:
    return {
        "id": SETTINGS_ID,
        "mode": "shadow",
        "active_requires_confirmation": True,
        "shadow_store_results_separately": True,
        "created_at": now_jst_iso(),
        "updated_at": now_jst_iso(),
    }
