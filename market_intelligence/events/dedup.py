"""
ソース間重複排除・マージモジュール。
Levenshtein距離による類似度計算は純Python実装（外部ライブラリ禁止）。
"""
from __future__ import annotations
import re
import unicodedata


# ────────────────────────────────────────────────────────────────
# ソース優先度
# ────────────────────────────────────────────────────────────────

SOURCE_PRIORITY: dict[str, int] = {
    "kanko_shinjuku":      10,  # 新宿観光振興協会（中-高）
    "regasu_bunka_center":  5,  # 新宿文化センター（中）
    "doorkeeper_api":       3,  # Doorkeeper（低-中）
    "html_scrape":          3,  # 汎用HTMLスクレイパー（低-中）
    "doorkeeper":           3,
    "csv":                  2,  # 手動CSV（低）
    "manual":               2,
    "demo":                 1,
}


# ────────────────────────────────────────────────────────────────
# Levenshtein距離（純Python DP実装）
# ────────────────────────────────────────────────────────────────

def levenshtein_similarity(s1: str, s2: str) -> float:
    """
    0.0〜1.0 のLevenshtein類似度を返す。
    実装: 標準的なDP。別アルゴリズムへの置き換え禁止。
    """
    if s1 == s2:
        return 1.0
    len1 = len(s1)
    len2 = len(s2)
    if len1 == 0 and len2 == 0:
        return 1.0
    if len1 == 0 or len2 == 0:
        return 0.0

    # DP テーブル初期化
    prev = list(range(len2 + 1))
    curr = [0] * (len2 + 1)

    for i in range(1, len1 + 1):
        curr[0] = i
        for j in range(1, len2 + 1):
            if s1[i - 1] == s2[j - 1]:
                curr[j] = prev[j - 1]
            else:
                curr[j] = 1 + min(prev[j], curr[j - 1], prev[j - 1])
        prev, curr = curr, prev

    distance = prev[len2]
    max_len = max(len1, len2)
    return 1.0 - distance / max_len


# ────────────────────────────────────────────────────────────────
# タイトル正規化
# ────────────────────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """
    NFKC正規化 → 英字小文字化 → 全角英数を半角に → 記号除去 → 空白除去。
    ひらがな・カタカナ・漢字・英数字は保持。
    """
    s = unicodedata.normalize("NFKC", title)
    s = s.lower()
    # 記号・スペース除去（ひらがな・カタカナ・漢字・英数字保持）
    s = re.sub(r'[^\w぀-ヿ一-鿿]', '', s)
    return s


# ────────────────────────────────────────────────────────────────
# 重複候補判定
# ────────────────────────────────────────────────────────────────

def is_duplicate_candidate(
    event_a: dict,
    event_b: dict,
    title_threshold: float = 0.85,
) -> bool:
    """
    同一日 かつ タイトル正規化後Levenshtein類似度 > threshold の場合True。
    異なる日のイベントは繰り返しイベントとして別イベント扱い。
    """
    starts_a = event_a.get("starts_at", "")[:10]  # YYYY-MM-DD
    starts_b = event_b.get("starts_at", "")[:10]

    if not starts_a or not starts_b:
        return False

    # 日付が異なる場合は繰り返しイベントとして別扱い
    if starts_a != starts_b:
        return False

    title_a = normalize_title(event_a.get("title", ""))
    title_b = normalize_title(event_b.get("title", ""))

    if not title_a or not title_b:
        return False

    similarity = levenshtein_similarity(title_a, title_b)
    return similarity > title_threshold


# ────────────────────────────────────────────────────────────────
# マージ処理
# ────────────────────────────────────────────────────────────────

_COMPLEMENT_FIELDS = [
    "description",
    "ends_at",
    "venue_name",
    "address",
    "latitude",
    "longitude",
    "official_url",
    "category",
]


def merge_events(primary: dict, secondary: dict) -> dict:
    """
    primaryを主レコードとして採用。
    secondaryから以下のフィールドのみ補完（primaryに値がある場合は上書きしない）:
      description, ends_at, venue_name, address, latitude, longitude, official_url, category
    merged_from_source_ids に secondary の source_id を追加。
    source_evidence_ids に secondary の source_evidence_id を追加。
    UIDは primary のものを維持（再生成しない）。
    """
    merged = dict(primary)

    # 補完フィールド: primaryが空・None の場合のみsecondaryから補完
    for field in _COMPLEMENT_FIELDS:
        primary_val = merged.get(field)
        secondary_val = secondary.get(field)
        if (primary_val is None or primary_val == "") and secondary_val:
            merged[field] = secondary_val

    # merged_from_source_ids に secondary の source_id を追加
    merged_ids: list[str] = list(merged.get("merged_from_source_ids") or [])
    secondary_source_id = secondary.get("source_id", "")
    if secondary_source_id and secondary_source_id not in merged_ids:
        merged_ids.append(secondary_source_id)
    merged["merged_from_source_ids"] = merged_ids

    # source_evidence_ids に secondary の source_evidence_id を追加
    evidence_ids: list[str] = list(merged.get("source_evidence_ids") or [])
    secondary_evidence_id = secondary.get("source_evidence_id", "")
    if secondary_evidence_id and secondary_evidence_id not in evidence_ids:
        evidence_ids.append(secondary_evidence_id)
    merged["source_evidence_ids"] = evidence_ids

    # UIDは primary のものを維持（変更しない）

    return merged


# ────────────────────────────────────────────────────────────────
# 優先度取得ヘルパー
# ────────────────────────────────────────────────────────────────

def _get_priority(event: dict) -> int:
    """イベントのソース優先度を返す。未知のソースは0。"""
    source_id = event.get("source_id", "")
    source_type = event.get("source_type", "")

    # source_id でまず検索
    if source_id in SOURCE_PRIORITY:
        return SOURCE_PRIORITY[source_id]

    # source_type で検索
    if source_type in SOURCE_PRIORITY:
        return SOURCE_PRIORITY[source_type]

    # source_id に部分一致するキーを検索
    for key, priority in SOURCE_PRIORITY.items():
        if key in source_id or key in source_type:
            return priority

    return 0


# ────────────────────────────────────────────────────────────────
# 重複排除パイプライン
# ────────────────────────────────────────────────────────────────

def deduplicate_and_merge(store) -> dict:
    """
    保存済み全EventRecordを走査し、重複候補をマージして保存。
    戻り値: {"merged": int, "candidates": int, "errors": list}
    """
    merged_count = 0
    candidates_count = 0
    errors: list[str] = []

    try:
        events = store.list_all("event_records")
    except Exception as e:
        errors.append(f"event_records読み込み失敗: {str(e)[:80]}")
        return {"merged": merged_count, "candidates": candidates_count, "errors": errors}

    if len(events) < 2:
        return {"merged": merged_count, "candidates": candidates_count, "errors": errors}

    # マージ済みIDのセット（処理済みのsecondaryをスキップするため）
    merged_secondary_ids: set[str] = set()

    for i in range(len(events)):
        ev_a = events[i]
        a_id = ev_a.get("id", "")

        if a_id in merged_secondary_ids:
            continue

        for j in range(i + 1, len(events)):
            ev_b = events[j]
            b_id = ev_b.get("id", "")

            if b_id in merged_secondary_ids:
                continue

            try:
                if not is_duplicate_candidate(ev_a, ev_b):
                    continue

                candidates_count += 1

                # 優先度の高いほうをprimaryに
                prio_a = _get_priority(ev_a)
                prio_b = _get_priority(ev_b)

                if prio_a >= prio_b:
                    primary, secondary = ev_a, ev_b
                    primary_id, secondary_id = a_id, b_id
                else:
                    primary, secondary = ev_b, ev_a
                    primary_id, secondary_id = b_id, a_id

                # マージ
                merged_record = merge_events(primary, secondary)

                # primaryを更新して保存
                store.upsert("event_records", merged_record)

                # secondaryを削除
                store.delete("event_records", secondary_id)

                # eventsリスト内のprimaryを更新
                events[i if prio_a >= prio_b else j] = merged_record

                merged_secondary_ids.add(secondary_id)
                merged_count += 1

            except Exception as e:
                errors.append(f"マージ失敗 {a_id[:8]}/{b_id[:8]}: {str(e)[:80]}")

    return {"merged": merged_count, "candidates": candidates_count, "errors": errors}
