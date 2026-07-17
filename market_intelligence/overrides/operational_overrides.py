"""
運用状態の永続化ファイル管理。
market_intelligence/overrides/operational_overrides.json に保存し、git追跡対象とする。

適用順序:
  1. store_profiles (Secret or demo) を読み込む
  2. source_overrides を store_profiles に適用（enabled=False等）
  3. event_records を読み込む
  4. event_visibility_overrides を event_records に適用（visibility=hidden等）

公開安全性:
  このファイルはgit追跡対象（publicリポジトリで閲覧可能）。
  pause_reason_code / suppression_reason_code は定義済みコードのみ使用。
  自由記述の内部メモは含めない。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from ..utils import now_jst_iso

SCHEMA_VERSION = 2

DEFAULT_OVERRIDES_PATH = Path(__file__).resolve().parent / "operational_overrides.json"

VALID_MODES = frozenset({"shadow", "active", "manual-only"})

# 公開可能な理由コード（自由記述は使用しない）
VALID_PAUSE_REASON_CODES = frozenset({
    "maintenance",      # 定期メンテナンス
    "terms_review",     # 利用規約の確認中
    "parser_failure",   # サイト構造変更でパーサー失敗
    "manual_pause",     # 手動停止（理由なし）
    "",                 # 省略可
})

VALID_SUPPRESSION_REASON_CODES = frozenset({
    "duplicate",         # 重複イベント
    "not_relevant",      # 関連性なし
    "incorrect_source",  # 誤ったソース
    "manual_review",     # 手動確認中
    "",                  # 省略可
})

_EMPTY_OVERRIDES: dict = {
    "schema_version": SCHEMA_VERSION,
    "collection_mode": "shadow",
    "source_overrides": [],
    "event_visibility_overrides": [],
}


def load_overrides(path: Optional[Path] = None) -> dict:
    """overridesファイルを読み込む。存在しない場合はデフォルト（shadow）を返す。"""
    p = path or DEFAULT_OVERRIDES_PATH
    if not p.exists():
        return _empty_overrides()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_overrides()
    if not isinstance(data, dict):
        return _empty_overrides()
    # normalize: ensure expected keys exist
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("collection_mode", "shadow")
    data.setdefault("source_overrides", [])
    data.setdefault("event_visibility_overrides", [])
    # backward compat: rename resume_at → planned_resume_at
    for ov in data["source_overrides"]:
        if "resume_at" in ov and "planned_resume_at" not in ov:
            ov["planned_resume_at"] = ov.pop("resume_at")
        # backward compat: rename pause_reason → pause_reason_code
        if "pause_reason" in ov and "pause_reason_code" not in ov:
            old = ov.pop("pause_reason", "")
            ov["pause_reason_code"] = old if old in VALID_PAUSE_REASON_CODES else "manual_pause"
    for ov in data["event_visibility_overrides"]:
        # backward compat: rename suppression_reason → suppression_reason_code
        if "suppression_reason" in ov and "suppression_reason_code" not in ov:
            old = ov.pop("suppression_reason", "")
            ov["suppression_reason_code"] = old if old in VALID_SUPPRESSION_REASON_CODES else "manual_review"
    return data


def save_overrides(data: dict, path: Optional[Path] = None) -> None:
    """overridesファイルに保存する（deterministic sort_keys）。"""
    p = path or DEFAULT_OVERRIDES_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _empty_overrides() -> dict:
    import copy
    return copy.deepcopy(_EMPTY_OVERRIDES)


# ─── Collection Mode ──────────────────────────────────────────────────────────

def get_collection_mode(overrides: dict) -> str:
    """
    operational_overrides.json の collection_mode を返す。
    未設定・不正値の場合はデフォルト "shadow"。

    優先順位（呼び出し側で制御）:
      1. CLIの --mode 引数
      2. このファイルの collection_mode
      3. "shadow"（安全側デフォルト）
    """
    mode = overrides.get("collection_mode", "shadow")
    return mode if mode in VALID_MODES else "shadow"


def set_collection_mode(overrides: dict, mode: str) -> None:
    """collection_mode を設定する。保存は呼び出し側で save_overrides() を呼ぶこと。"""
    if mode not in VALID_MODES:
        raise ValueError(f"不正なモード: {mode!r}  有効値: {sorted(VALID_MODES)}")
    overrides["collection_mode"] = mode


# ─── Source Override ──────────────────────────────────────────────────────────

def apply_source_overrides(profiles: list[dict], overrides: dict) -> list[dict]:
    """
    source_overrides を store_profiles の event_sources に適用する。
    store_profiles の enabled フラグを上書きする（設定は削除しない）。
    """
    import copy
    source_ovs = overrides.get("source_overrides", [])
    if not source_ovs:
        return profiles

    result = []
    for profile in profiles:
        p = copy.deepcopy(profile)
        store_id = p.get("id", "")
        for src in p.get("event_sources", []):
            if not isinstance(src, dict):
                continue
            src_key = src.get("name", "") or src.get("type", "")
            for ov in source_ovs:
                ov_store = ov.get("store_id", "")
                ov_source = ov.get("source_key", "")
                store_match = (ov_store == store_id or ov_store == "all" or ov_store == "")
                src_match = (ov_source == src_key or ov_source == src.get("type", ""))
                if store_match and src_match:
                    src["enabled"] = ov.get("enabled", True)
                    if not ov.get("enabled", True):
                        src["paused_at"] = ov.get("paused_at")
                        src["paused_by"] = ov.get("paused_by")
                        src["pause_reason_code"] = ov.get("pause_reason_code", "")
                        src["planned_resume_at"] = ov.get("planned_resume_at")
        result.append(p)
    return result


def add_source_pause(
    overrides: dict,
    store_id: str,
    source_key: str,
    reason_code: str = "",
    paused_by: str = "cli",
    planned_resume_at: Optional[str] = None,
) -> None:
    """
    source_overrides にpause entryを追加・更新する。
    reason_code は VALID_PAUSE_REASON_CODES のいずれか（公開安全性のため自由記述不可）。
    """
    if reason_code not in VALID_PAUSE_REASON_CODES:
        reason_code = "manual_pause"
    source_ovs = overrides.setdefault("source_overrides", [])
    for ov in source_ovs:
        if ov.get("store_id") == store_id and ov.get("source_key") == source_key:
            ov["enabled"] = False
            ov["paused_at"] = now_jst_iso()
            ov["paused_by"] = paused_by
            ov["pause_reason_code"] = reason_code
            ov["planned_resume_at"] = planned_resume_at
            return
    source_ovs.append({
        "enabled": False,
        "pause_reason_code": reason_code,
        "paused_at": now_jst_iso(),
        "paused_by": paused_by,
        "planned_resume_at": planned_resume_at,
        "source_key": source_key,
        "store_id": store_id,
    })


def remove_source_pause(
    overrides: dict,
    store_id: str,
    source_key: str,
    resumed_by: str = "cli",
) -> bool:
    """source_overrides からpause entryを削除（resume）する。戻り値: 削除があった場合True。"""
    source_ovs = overrides.get("source_overrides", [])
    new_ovs = [
        ov for ov in source_ovs
        if not (ov.get("store_id") == store_id and ov.get("source_key") == source_key)
    ]
    changed = len(new_ovs) < len(source_ovs)
    overrides["source_overrides"] = new_ovs
    return changed


# ─── Event Visibility Override ────────────────────────────────────────────────

def apply_event_visibility_overrides(events: list[dict], overrides: dict) -> list[dict]:
    """
    event_visibility_overrides を event_records に適用する。
    visibility=hidden を設定する（status は変更しない）。
    次回collect後も hidden が解除されない。
    """
    import copy
    vis_ovs = overrides.get("event_visibility_overrides", [])
    if not vis_ovs:
        return events

    uid_to_ov = {ov["event_uid"]: ov for ov in vis_ovs if ov.get("event_uid")}
    result = []
    for ev in events:
        uid = ev.get("uid") or ev.get("id", "")
        if uid in uid_to_ov:
            ev = copy.deepcopy(ev)
            ov = uid_to_ov[uid]
            ev["visibility"] = ov.get("visibility", "hidden")
            ev["suppressed_at"] = ov.get("suppressed_at")
            ev["suppressed_by"] = ov.get("suppressed_by")
            ev["suppression_reason_code"] = ov.get("suppression_reason_code", "")
        result.append(ev)
    return result


def add_event_hidden(
    overrides: dict,
    event_uid: str,
    reason_code: str = "",
    suppressed_by: str = "cli",
) -> None:
    """
    event_visibility_overrides に hidden entry を追加・更新する。
    reason_code は VALID_SUPPRESSION_REASON_CODES のいずれか。
    """
    if reason_code not in VALID_SUPPRESSION_REASON_CODES:
        reason_code = "manual_review"
    vis_ovs = overrides.setdefault("event_visibility_overrides", [])
    for ov in vis_ovs:
        if ov.get("event_uid") == event_uid:
            ov["visibility"] = "hidden"
            ov["suppressed_at"] = now_jst_iso()
            ov["suppressed_by"] = suppressed_by
            ov["suppression_reason_code"] = reason_code
            return
    vis_ovs.append({
        "event_uid": event_uid,
        "suppressed_at": now_jst_iso(),
        "suppressed_by": suppressed_by,
        "suppression_reason_code": reason_code,
        "visibility": "hidden",
    })


def remove_event_hidden(overrides: dict, event_uid: str) -> bool:
    """event_visibility_overrides から hidden entry を削除（show）する。"""
    vis_ovs = overrides.get("event_visibility_overrides", [])
    new_ovs = [ov for ov in vis_ovs if ov.get("event_uid") != event_uid]
    changed = len(new_ovs) < len(vis_ovs)
    overrides["event_visibility_overrides"] = new_ovs
    return changed
