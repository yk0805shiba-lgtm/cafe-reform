"""store_profiles.jsonのスキーマ検証。"""
from __future__ import annotations

VALID_BUSINESS_UNITS = {"cafe", "delivery", "both"}
KNOWN_SOURCE_TYPES = {"csv", "ical", "doorkeeper", "kanko_shinjuku", "regasu_bunka_center", "demo", "manual"}


def validate_store_profiles(data) -> list[str]:
    """
    Returns list of error strings. Empty list = valid.
    Validates: list format, required fields, business_unit, event_sources format.
    """
    errors = []

    if not isinstance(data, list):
        errors.append(f"store_profiles must be a list, got {type(data).__name__}")
        return errors  # Cannot continue validation

    seen_ids: set[str] = set()
    for i, profile in enumerate(data):
        if not isinstance(profile, dict):
            errors.append(f"profile[{i}]: expected object, got {type(profile).__name__}")
            continue

        store_id = profile.get("id", "")
        label = f"store={store_id!r}" if store_id else f"profile[{i}]"

        if not store_id:
            errors.append(f"{label}: id is required")
        elif store_id in seen_ids:
            errors.append(f"{label}: duplicate store id")
        else:
            seen_ids.add(store_id)

        bu = profile.get("business_unit", "")
        if bu not in VALID_BUSINESS_UNITS:
            errors.append(f"{label}: invalid business_unit={bu!r} (must be one of {sorted(VALID_BUSINESS_UNITS)})")

        sources = profile.get("event_sources", [])
        if not isinstance(sources, list):
            errors.append(f"{label}: event_sources must be a list, got {type(sources).__name__}")
        else:
            seen_src_keys: set[str] = set()
            for j, src in enumerate(sources):
                if not isinstance(src, dict):
                    errors.append(
                        f"Invalid event source: store={store_id}, index={j}, expected object, got {type(src).__name__}"
                    )
                    continue
                src_type = src.get("type", "")
                if not src_type:
                    errors.append(f"store={store_id}, source[{j}]: type is required")
                elif src_type not in KNOWN_SOURCE_TYPES:
                    errors.append(f"store={store_id}, source[{j}]: unknown source type {src_type!r}")

                enabled = src.get("enabled", True)
                if not isinstance(enabled, bool):
                    errors.append(
                        f"store={store_id}, source[{j}]: enabled must be bool, got {type(enabled).__name__}"
                    )

                src_key = f"{store_id}:{src_type}:{src.get('name', '')}"
                if src_key in seen_src_keys:
                    errors.append(f"store={store_id}, source[{j}]: duplicate source (type={src_type!r}, name={src.get('name', '')!r})")
                else:
                    seen_src_keys.add(src_key)

    return errors
