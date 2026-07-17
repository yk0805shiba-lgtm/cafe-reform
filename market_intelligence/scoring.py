"""
関連度スコアリングエンジン。
距離・日時・規模・ターゲット層などをルールベースで計算し、
スコア内訳を保存する。LLMに任せず、決定論的に処理する。
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .utils import parse_iso, days_until

TZ_TOKYO = ZoneInfo("Asia/Tokyo")


def score_event(event: dict, store: dict, business_unit: str) -> dict:
    """
    イベントと店舗の関連度スコアを計算する。
    戻り値: {"total": 0-100, "breakdown": {...}, "explanation": "..."}
    """
    breakdown = {}
    total = 0

    # 1. 距離スコア（最大25点）
    dist = event.get("distance_from_store_km")
    if dist is not None:
        if dist <= 0.5:
            d_score = 25
        elif dist <= 1.0:
            d_score = 20
        elif dist <= 2.0:
            d_score = 15
        elif dist <= 3.0:
            d_score = 10
        elif dist <= 5.0:
            d_score = 5
        else:
            d_score = 0
    else:
        d_score = 10  # 距離不明の場合は中程度
    breakdown["distance"] = {"score": d_score, "max": 25, "raw": dist}
    total += d_score

    # 2. 日程スコア（最大20点）- 近い将来ほど高い
    days = days_until(event.get("starts_at", ""))
    if days is not None:
        if days <= 3:
            t_score = 20
        elif days <= 7:
            t_score = 18
        elif days <= 14:
            t_score = 15
        elif days <= 30:
            t_score = 10
        elif days <= 60:
            t_score = 5
        else:
            t_score = 2
    else:
        t_score = 0
    breakdown["timing"] = {"score": t_score, "max": 20, "raw_days": days}
    total += t_score

    # 3. 規模スコア（最大15点）
    scale = event.get("estimated_scale", "unknown")
    audience = event.get("expected_audience")
    if audience:
        if audience >= 10000:
            s_score = 15
        elif audience >= 5000:
            s_score = 12
        elif audience >= 1000:
            s_score = 8
        elif audience >= 100:
            s_score = 4
        else:
            s_score = 1
    elif scale == "large":
        s_score = 12
    elif scale == "medium":
        s_score = 7
    elif scale == "small":
        s_score = 3
    else:
        s_score = 3
    breakdown["scale"] = {"score": s_score, "max": 15, "raw": scale, "audience": audience}
    total += s_score

    # 4. ターゲット層一致スコア（最大15点）
    store_segments = set(store.get("target_segments", []))
    event_segments = set(event.get("audience_segments", []))
    if store_segments and event_segments:
        overlap = store_segments & event_segments
        if overlap:
            seg_score = min(15, len(overlap) * 5)
        else:
            seg_score = 2
    else:
        seg_score = 5  # 不明の場合は中程度
    breakdown["target_segments"] = {"score": seg_score, "max": 15, "overlap": list(store_segments & event_segments)}
    total += seg_score

    # 5. 業態適性スコア（最大10点）
    category = event.get("category", "unknown")
    bu_score = _business_unit_fit(category, business_unit)
    breakdown["business_unit_fit"] = {"score": bu_score, "max": 10, "category": category}
    total += bu_score

    # 6. 外国語需要スコア（最大5点）
    event_langs = event.get("languages", ["ja"])
    store_langs = store.get("languages", ["ja"])
    if len(event_langs) > 1 and len(store_langs) > 1:
        lang_score = 5
    elif len(event_langs) > 1:
        lang_score = 3  # 対応の余地あり
    else:
        lang_score = 0
    breakdown["language_demand"] = {"score": lang_score, "max": 5}
    total += lang_score

    # 7. 天気感応度スコア（最大5点）- 屋外+天気感応度高は影響大
    weather_sens = event.get("weather_sensitivity", "unknown")
    outdoor = event.get("indoor_or_outdoor", "unknown")
    if outdoor == "outdoor" and weather_sens == "high":
        w_score = 5
    elif outdoor == "outdoor" and weather_sens == "medium":
        w_score = 3
    else:
        w_score = 1
    breakdown["weather_sensitivity"] = {"score": w_score, "max": 5}
    total += w_score

    # 8. 情報の信頼度スコア（最大5点）
    confidence = event.get("confidence", 1.0)
    conf_score = round(confidence * 5)
    breakdown["confidence"] = {"score": conf_score, "max": 5, "raw": confidence}
    total += conf_score

    explanation = _build_explanation(breakdown, business_unit, event)

    return {
        "total": min(100, total),
        "breakdown": breakdown,
        "business_unit": business_unit,
        "explanation": explanation,
    }


def _business_unit_fit(category: str, business_unit: str) -> int:
    """カテゴリと業態の適性スコア（0-10）"""
    cafe_high = {"fireworks", "concert", "festival", "tourism", "market", "cultural", "holiday"}
    delivery_high = {"concert", "sports", "festival", "holiday", "weather"}
    both_high = {"fireworks", "festival", "tourism"}

    if business_unit == "cafe":
        return 10 if category in cafe_high else 5
    elif business_unit == "delivery":
        return 10 if category in delivery_high else 5
    else:  # both
        return 10 if category in (cafe_high | delivery_high) else 5


def _build_explanation(breakdown: dict, business_unit: str, event: dict) -> str:
    parts = []
    d = breakdown.get("distance", {})
    if d.get("raw") is not None:
        parts.append(f"距離{d['raw']:.1f}km（{d['score']}点）")
    t = breakdown.get("timing", {})
    if t.get("raw_days") is not None:
        parts.append(f"開催まで{t['raw_days']}日（{t['score']}点）")
    s = breakdown.get("scale", {})
    parts.append(f"規模:{s.get('raw','不明')}（{s['score']}点）")
    seg = breakdown.get("target_segments", {})
    if seg.get("overlap"):
        parts.append(f"ターゲット一致:{seg['overlap']}（{seg['score']}点）")
    if breakdown.get("language_demand", {}).get("score", 0) > 0:
        parts.append("外国語需要あり")
    return "、".join(parts)


def classify_severity(diff: dict, high_threshold: float = 10.0, medium_threshold: float = 5.0) -> str:
    """競合差分の重要度を分類する"""
    price_changes = diff.get("price_changes", [])
    for pc in price_changes:
        rate = abs(pc.get("change_rate_pct", 0) or 0)
        if rate >= high_threshold:
            return "high"

    if diff.get("new_items") and len(diff.get("new_items", [])) >= 3:
        return "high"
    if diff.get("opening_hours_changes"):
        return "high"
    if diff.get("order_availability_change"):
        return "high"

    if price_changes:
        for pc in price_changes:
            rate = abs(pc.get("change_rate_pct", 0) or 0)
            if rate >= medium_threshold:
                return "medium"
    if diff.get("new_items"):
        return "medium"
    if diff.get("set_changes"):
        return "medium"
    if diff.get("discount_changes"):
        return "medium"

    return "low"
