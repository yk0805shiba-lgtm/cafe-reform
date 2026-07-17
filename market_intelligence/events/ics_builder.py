"""
RFC 5545準拠ICS生成。icalendarライブラリを使用。
手作業の文字列連結でICSを生成しない。
同じ入力から2回buildしてbyte列が同一になること（DTSTAMPに実行時刻を使わない）。
"""
from __future__ import annotations
import os
import tempfile
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event as ICalEvent

PRODID = "-//cafe-reform market-intelligence//Local Event Feed//JA"
TZ = ZoneInfo("Asia/Tokyo")


def build_ics_feed(
    events_with_assessments: list[dict],  # [{"event": dict, "assessment": dict}]
    calname: str,
    store_id: str | None,
    business_unit: str | None,
    output_path: Path,
) -> None:
    """
    ICSをtmpファイルへ書いてatomic replace。
    build失敗時に既存ICSを壊さない。
    同じ入力からは常に同じbyte列を生成する（DTSTAMPは実行時刻を使わず安定値）。
    """
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("x-wr-calname", calname)
    cal.add("x-wr-timezone", "Asia/Tokyo")

    # 決定的sort: impact_score降順 → start昇順 → uid昇順
    sorted_events = sorted(
        events_with_assessments,
        key=lambda e: (
            -e["assessment"].get("impact_score", 0),
            e["event"].get("starts_at", ""),
            e["event"].get("uid") or e["event"].get("id", ""),
        ),
    )

    for item in sorted_events:
        ev = item["event"]
        asm = item["assessment"]
        vevent = _build_vevent(ev, asm, business_unit)
        cal.add_component(vevent)

    content = cal.to_ical()
    _atomic_write(output_path, content)


def _build_vevent(ev: dict, asm: dict, business_unit: str | None) -> ICalEvent:
    vevent = ICalEvent()

    uid = ev.get("uid") or ev.get("id", "")
    vevent.add("uid", uid)

    # DTSTAMP: first_seen_at（安定値。実行時刻ではない）
    dtstamp = _parse_dt(ev.get("first_seen_at") or ev.get("created_at", ""))
    if dtstamp:
        vevent.add("dtstamp", dtstamp)

    # LAST-MODIFIED: updated_at or last_seen_at
    last_mod = _parse_dt(ev.get("updated_at") or ev.get("last_seen_at", ""))
    if last_mod:
        vevent.add("last-modified", last_mod)

    vevent.add("sequence", ev.get("sequence", 0))

    # SUMMARY: ★ + title
    score = asm.get("impact_score", 0)
    stars = "★" * score if score > 0 else "☆"
    vevent.add("summary", f"{stars} {ev.get('title', '')}")

    # DTSTART / DTEND
    all_day = ev.get("all_day", False)
    _add_dtstart_dtend(vevent, ev.get("starts_at", ""), ev.get("ends_at"), all_day)

    # LOCATION
    location_parts = [ev.get("venue_name", ""), ev.get("address", "")]
    location = " ".join(p for p in location_parts if p)
    if location:
        vevent.add("location", location)

    # URL
    if ev.get("official_url"):
        vevent.add("url", ev["official_url"])

    # DESCRIPTION
    vevent.add("description", _build_description(ev, asm))

    # CATEGORIES
    if ev.get("category"):
        vevent.add("categories", ev["category"])

    # GEO
    lat = ev.get("latitude")
    lon = ev.get("longitude")
    if lat is not None and lon is not None:
        vevent.add("geo", (lat, lon))

    # Custom X- properties
    vevent.add("x-impact-score", str(asm.get("impact_score", 0)))
    if asm.get("impact_reasons"):
        vevent.add("x-impact-reasons", ",".join(asm["impact_reasons"]))
    if asm.get("distance_m") is not None:
        vevent.add("x-distance-m", str(asm["distance_m"]))
    if ev.get("source_id"):
        vevent.add("x-source-id", ev["source_id"])
    if ev.get("merged_from_source_ids"):
        vevent.add("x-merged-from", ",".join(ev["merged_from_source_ids"]))
    if asm.get("store_id"):
        vevent.add("x-store-id", asm["store_id"])
    if business_unit:
        vevent.add("x-business-unit", business_unit)
    if asm.get("operational_signals"):
        vevent.add("x-operational-signals", ",".join(asm["operational_signals"]))
    evidence_ids = ev.get("source_evidence_ids") or []
    if ev.get("source_evidence_id") and ev["source_evidence_id"] not in evidence_ids:
        evidence_ids = [ev["source_evidence_id"]] + evidence_ids
    if evidence_ids:
        vevent.add("x-source-evidence-ids", ",".join(evidence_ids))

    return vevent


def _add_dtstart_dtend(vevent: ICalEvent, starts_at: str, ends_at: str | None, all_day: bool) -> None:
    from icalendar import vDate, vDatetime

    if all_day:
        start_date = _parse_date(starts_at)
        if start_date:
            vevent.add("dtstart", vDate(start_date))
        if ends_at:
            end_date = _parse_date(ends_at)
            if end_date:
                # RFC 5545: exclusive end → +1 day
                vevent.add("dtend", vDate(end_date + timedelta(days=1)))
        elif start_date:
            vevent.add("dtend", vDate(start_date + timedelta(days=1)))
    else:
        start_dt = _parse_dt(starts_at)
        if start_dt:
            # ZoneInfo("Asia/Tokyo")に変換してtzinfoが再parse後も保持されるようにする
            start_dt = start_dt.astimezone(TZ)
            vevent.add("dtstart", start_dt)
        if ends_at:
            end_dt = _parse_dt(ends_at)
            if end_dt:
                end_dt = end_dt.astimezone(TZ)
                vevent.add("dtend", end_dt)


def _build_description(ev: dict, asm: dict) -> str:
    parts: list[str] = []
    if ev.get("description"):
        parts.append(ev["description"])
    source_id = ev.get("source_id") or ev.get("source_evidence_id", "不明")
    parts.append(f"情報源: {source_id}")
    if ev.get("official_url"):
        parts.append(f"URL: {ev['official_url']}")
    if asm.get("impact_reasons"):
        parts.append(f"Impact: {', '.join(asm['impact_reasons'])}")
    if asm.get("operational_signals"):
        parts.append(f"Signals: {', '.join(asm['operational_signals'])}")
    parts.append("注意: 需要増加は予測であり保証ではありません。")
    return "\n".join(parts)


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


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
