"""
Source の一時停止・再開・状態確認、イベント visibility（表示/非表示）制御。

【設計原則】
- source 停止: store_profile.event_sources の enabled フラグで制御。設定は削除しない。
- cancelled: 主催者/公式情報源がイベント中止を発表した場合のみ使用。
- visibility hidden: 店舗側の都合による非表示。公式 status とは独立して管理する。
- operational_overrides.json: pause/hide 状態を git 管理ファイルに永続化し、
  GitHub Actions の runs 間でも状態を引き継ぐ。
"""
from __future__ import annotations

from ..storage import JsonStore
from ..utils import now_jst_iso


# ─── Source 一時停止 ──────────────────────────────────────────────────────────

def pause_source(
    store: JsonStore,
    source_name: str,
    store_id: str | None = None,
    reason: str = "",
    paused_by: str = "cli",
    resume_at: str | None = None,
    planned_resume_at: str | None = None,
    reason_code: str = "",
) -> list[str]:
    """
    指定名の source を一時停止する（enabled=False）。
    URL・設定・SourceEvidence はそのまま維持する。

    store_id=None → 全店舗に適用（全体停止）
    store_id 指定 → 当該店舗のみ停止（店舗単位停止）

    resume_at: 後方互換のため残す（planned_resume_at が優先される）
    planned_resume_at: 再開予定日（メモ。自動再開はしない）

    戻り値: 更新した store_id のリスト
    """
    # planned_resume_at が未指定の場合は resume_at (旧名) を使う（後方互換）
    effective_resume_at = planned_resume_at if planned_resume_at is not None else resume_at

    profiles = _get_target_profiles(store, store_id)
    updated: list[str] = []
    for profile in profiles:
        changed = False
        for src in profile.get("event_sources", []):
            if src.get("name") == source_name:
                src["enabled"] = False
                src["paused_at"] = now_jst_iso()
                src["paused_by"] = paused_by
                src["pause_reason"] = reason
                # store_profiles 内は後方互換のため resume_at も設定する
                src["resume_at"] = effective_resume_at
                src["planned_resume_at"] = effective_resume_at
                changed = True
        if changed:
            store.upsert("store_profiles", profile)
            updated.append(profile["id"])

    # operational_overrides.json にも永続化
    if updated:
        _persist_source_pause_to_overrides(
            source_name=source_name,
            store_ids=updated,
            store_id_arg=store_id,
            reason=reason,
            paused_by=paused_by,
            planned_resume_at=effective_resume_at,
            reason_code=reason_code,
        )

    return updated


def _persist_source_pause_to_overrides(
    source_name: str,
    store_ids: list[str],
    store_id_arg: str | None,
    reason: str,
    paused_by: str,
    planned_resume_at: str | None,
    reason_code: str = "",
) -> None:
    """operational_overrides.json に pause エントリを保存する（公開安全なコードのみ）。"""
    try:
        from ..overrides.operational_overrides import (
            load_overrides, save_overrides, add_source_pause, VALID_PAUSE_REASON_CODES
        )
        # reason_code が指定されていない場合は "" (省略) を使う
        effective_code = reason_code if reason_code in VALID_PAUSE_REASON_CODES else ""
        overrides = load_overrides()
        if store_id_arg:
            for sid in store_ids:
                add_source_pause(
                    overrides,
                    store_id=sid,
                    source_key=source_name,
                    reason_code=effective_code,
                    paused_by=paused_by,
                    planned_resume_at=planned_resume_at,
                )
        else:
            add_source_pause(
                overrides,
                store_id="all",
                source_key=source_name,
                reason_code=effective_code,
                paused_by=paused_by,
                planned_resume_at=planned_resume_at,
            )
        save_overrides(overrides)
    except Exception as e:
        print(f"[source_control] operational_overrides.json への保存失敗（非致命的）: {e}")


def resume_source(
    store: JsonStore,
    source_name: str,
    store_id: str | None = None,
    resumed_by: str = "cli",
) -> list[str]:
    """
    指定名の source を再開する（enabled=True）。
    一時停止時の metadata をクリアし、元の URL・設定をそのまま再利用する。

    store_id=None → 全店舗に適用
    戻り値: 更新した store_id のリスト
    """
    profiles = _get_target_profiles(store, store_id)
    updated: list[str] = []
    for profile in profiles:
        changed = False
        for src in profile.get("event_sources", []):
            if src.get("name") == source_name:
                src["enabled"] = True
                src["paused_at"] = None
                src["paused_by"] = None
                src["pause_reason"] = None
                src["resume_at"] = None
                src["planned_resume_at"] = None
                changed = True
        if changed:
            store.upsert("store_profiles", profile)
            updated.append(profile["id"])

    # operational_overrides.json からも削除
    if updated:
        _persist_source_resume_to_overrides(
            source_name=source_name,
            store_ids=updated,
            store_id_arg=store_id,
            resumed_by=resumed_by,
        )

    return updated


def _persist_source_resume_to_overrides(
    source_name: str,
    store_ids: list[str],
    store_id_arg: str | None,
    resumed_by: str,
) -> None:
    """operational_overrides.json から pause エントリを削除する。"""
    try:
        from ..overrides.operational_overrides import load_overrides, save_overrides, remove_source_pause
        overrides = load_overrides()
        if store_id_arg:
            for sid in store_ids:
                remove_source_pause(overrides, store_id=sid, source_key=source_name, resumed_by=resumed_by)
        else:
            # 全店舗停止の場合: "all" エントリを削除し、各店舗エントリも削除
            remove_source_pause(overrides, store_id="all", source_key=source_name, resumed_by=resumed_by)
            for sid in store_ids:
                remove_source_pause(overrides, store_id=sid, source_key=source_name, resumed_by=resumed_by)
        save_overrides(overrides)
    except Exception as e:
        print(f"[source_control] operational_overrides.json からの削除失敗（非致命的）: {e}")


def list_source_status(
    store: JsonStore,
    store_id: str | None = None,
) -> list[dict]:
    """
    全ソースの状態（enabled/paused など）を返す。
    store_id 指定で当該店舗のみ返す。
    """
    profiles = _get_target_profiles(store, store_id)
    result: list[dict] = []
    for profile in profiles:
        for src in profile.get("event_sources", []):
            result.append({
                "store_id": profile["id"],
                "store_name": profile.get("name", ""),
                "source_name": src.get("name", ""),
                "source_type": src.get("type", ""),
                "enabled": src.get("enabled", True),
                "paused_at": src.get("paused_at"),
                "paused_by": src.get("paused_by"),
                "pause_reason": src.get("pause_reason"),
                "resume_at": src.get("resume_at"),
                "planned_resume_at": src.get("planned_resume_at"),
            })
    return result


def _get_target_profiles(store: JsonStore, store_id: str | None) -> list[dict]:
    if store_id and store_id != "all":
        profile = store.get("store_profiles", store_id)
        return [profile] if profile else []
    return store.list_all("store_profiles")


# ─── Event Visibility（表示/非表示） ──────────────────────────────────────────

def hide_event(
    store: JsonStore,
    event_id: str,
    reason: str = "",
    suppressed_by: str = "cli",
    reason_code: str = "",
) -> bool:
    """
    イベントを非表示にする（visibility=hidden）。
    公式 status（confirmed/cancelled/tentative など）は変更しない。
    通常の query/ICS/Recommendation からは除外されるが、
    --include-hidden で管理画面から確認できる。

    戻り値: True=成功、False=対象イベントなし
    """
    ev = store.get("event_records", event_id)
    if ev is None:
        return False
    ev["visibility"] = "hidden"
    ev["suppressed_at"] = now_jst_iso()
    ev["suppressed_by"] = suppressed_by
    ev["suppression_reason"] = reason
    store.upsert("event_records", ev)

    # operational_overrides.json にも永続化（uid を使って保存）
    event_uid = ev.get("uid") or event_id
    _persist_event_hide_to_overrides(
        event_uid=event_uid,
        reason=reason,
        suppressed_by=suppressed_by,
        reason_code=reason_code,
    )

    return True


def _persist_event_hide_to_overrides(
    event_uid: str,
    reason: str,
    suppressed_by: str,
    reason_code: str = "",
) -> None:
    """operational_overrides.json に event_visibility override を保存する（公開安全なコードのみ）。"""
    try:
        from ..overrides.operational_overrides import (
            load_overrides, save_overrides, add_event_hidden, VALID_SUPPRESSION_REASON_CODES
        )
        effective_code = reason_code if reason_code in VALID_SUPPRESSION_REASON_CODES else ""
        overrides = load_overrides()
        add_event_hidden(overrides, event_uid=event_uid, reason_code=effective_code, suppressed_by=suppressed_by)
        save_overrides(overrides)
    except Exception as e:
        print(f"[source_control] operational_overrides.json への event hide 保存失敗（非致命的）: {e}")


def show_event(
    store: JsonStore,
    event_id: str,
) -> bool:
    """
    非表示イベントを再表示する（visibility=visible）。
    戻り値: True=成功、False=対象イベントなし
    """
    ev = store.get("event_records", event_id)
    if ev is None:
        return False

    # operational_overrides.json から削除（uid を使う）
    event_uid = ev.get("uid") or event_id
    _persist_event_show_to_overrides(event_uid=event_uid)

    ev["visibility"] = "visible"
    ev["suppressed_at"] = None
    ev["suppressed_by"] = None
    ev["suppression_reason"] = None
    store.upsert("event_records", ev)
    return True


def _persist_event_show_to_overrides(event_uid: str) -> None:
    """operational_overrides.json から event_visibility override を削除する。"""
    try:
        from ..overrides.operational_overrides import load_overrides, save_overrides, remove_event_hidden
        overrides = load_overrides()
        remove_event_hidden(overrides, event_uid=event_uid)
        save_overrides(overrides)
    except Exception as e:
        print(f"[source_control] operational_overrides.json からの event show 削除失敗（非致命的）: {e}")


def list_events_admin(
    store: JsonStore,
    include_hidden: bool = True,
) -> list[dict]:
    """
    管理用イベント一覧。デフォルトで hidden を含む。
    通常 query との違い: 日付フィルタなし、キャンセルも含む。
    """
    events = store.list_all("event_records")
    if not include_hidden:
        events = [e for e in events if e.get("visibility", "visible") != "hidden"]
    return sorted(events, key=lambda e: e.get("starts_at", ""))
