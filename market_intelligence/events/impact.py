"""
LLMを使わない決定的なimpact score計算。
距離・カテゴリ・曜日/祝日の組み合わせで0-5を算出する。
"""
from __future__ import annotations
from datetime import date
from zoneinfo import ZoneInfo


def compute_impact_score(
    distance_m: int | None,
    category: str,
    event_date: date,
    timezone: str = "Asia/Tokyo",
) -> tuple[int, list[str]]:
    """
    LLMを使わない決定的なimpact score計算。
    戻り値: (score 0-5, reasons list)

    各reasonは "factor:+N" 形式。
    """
    score = 0
    reasons: list[str] = []

    # 距離スコア
    if distance_m is None:
        reasons.append("distance_unknown:+0")
    elif distance_m < 500:
        score += 3
        reasons.append("distance_lt_500m:+3")
    elif distance_m < 1000:
        score += 2
        reasons.append("distance_lt_1000m:+2")
    elif distance_m < 2000:
        score += 1
        reasons.append("distance_lt_2000m:+1")
    else:
        reasons.append("distance_gte_2000m:+0")

    # カテゴリスコア
    if category in ("festival", "market"):
        score += 2
        reasons.append(f"category_{category}:+2")
    elif category in ("exhibition", "culture", "sports"):
        score += 1
        reasons.append(f"category_{category}:+1")
    else:
        reasons.append(f"category_{category}:+0")

    # 曜日・祝日スコア
    wd = event_date.weekday()
    if wd >= 5:  # 土日
        score += 1
        reasons.append("weekend:+1")
    else:
        try:
            import jpholiday
            if jpholiday.is_holiday(event_date):
                score += 1
                reasons.append("holiday:+1")
            else:
                reasons.append("weekday:+0")
        except ImportError:
            reasons.append("weekday:+0")

    # 0-5 clip
    if score > 5:
        reasons.append(f"clipped_to_5 (raw={score})")
        score = 5

    return score, reasons
