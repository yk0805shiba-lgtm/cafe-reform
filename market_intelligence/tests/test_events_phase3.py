"""
Phase 3 テスト: RegasuBunkaCenterAdapter / 重複排除 / ICS X-MERGED-FROM
外部HTTPは一切行わず、urllib.request.urlopen をモックして使う。
"""
from __future__ import annotations
import io
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ────────────────────────────────────────────────────────────────
# テスト用HTMLヘルパー
# ────────────────────────────────────────────────────────────────

def _make_calendar_html(sections: list[dict]) -> bytes:
    """
    実際のHTML構造（tableタグ + クラス）に合わせたモックHTML生成。
    sections: [{"hall_class": "cal_large-hall", "month": 7, "rows": [{"day": 4, "dow": "土", "time": "13：40", "title": "テスト演奏会"}]}]

    実際のHTML:
      <table class="event-calendar cal_large-hall">
        <tr><td class="td-month">7月</td></tr>
        <tr><th class="th1">公演日</th>...</tr>
        <tr><td class="td1">4 (土)</td><td class="td2">13：40</td><td class="td3">催事名</td>...</tr>
      </table>
    """
    lines = ["<html><body>"]
    for sec in sections:
        hall_class = sec["hall_class"]
        month = sec["month"]
        lines.append(f'<table class="event-calendar {hall_class}">')
        # 月ヘッダー行
        lines.append(f'<tr><td class="td-month">{month}月</td></tr>')
        # 列ヘッダー行（th タグ）
        lines.append('<tr><th class="th1">公演日</th><th class="th2">開演時間</th><th class="th3">催事名</th><th class="th4">料金</th><th class="th5">問合せ先</th></tr>')
        for row in sec.get("rows", []):
            day = row["day"]
            dow = row.get("dow", "土")
            time_str = row.get("time", "14:00")
            title = row.get("title", "テストイベント")
            lines.append(
                f'<tr>'
                f'<td class="td1">{day} ({dow})</td>'
                f'<td class="td2">{time_str}</td>'
                f'<td class="td3">{title}</td>'
                f'<td class="td4">無料</td>'
                f'<td class="td5">主催者</td>'
                f'</tr>'
            )
        lines.append("</table>")
    lines.append("</body></html>")
    return "\n".join(lines).encode("utf-8")


class _FakeHTTPResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _patch_urlopen(html_bytes: bytes):
    """urllib.request.urlopen をモックしてhtmlを返すpatcherを返す。"""
    def _fake_urlopen(req, context=None, timeout=None):
        return _FakeHTTPResponse(html_bytes)
    return patch(
        "market_intelligence.adapters.regasu_bunka_center_adapter.urllib_request_fetch",
        side_effect=lambda req, ctx, timeout=15: html_bytes,
    )


def _get_adapter():
    from market_intelligence.adapters.regasu_bunka_center_adapter import RegasuBunkaCenterAdapter
    return RegasuBunkaCenterAdapter()


# ────────────────────────────────────────────────────────────────
# 1. 1月・1イベントのHTMLから日付・タイトル・会場が取れる
# ────────────────────────────────────────────────────────────────

def test_regasu_parse_single_month_single_event():
    html = _make_calendar_html([{
        "hall_class": "cal_large-hall",
        "month": 8,
        "rows": [{"day": 10, "dow": "月", "time": "14：00", "title": "サマーコンサート"}],
    }])
    adapter = _get_adapter()
    with _patch_urlopen(html):
        raws = adapter.fetch()

    assert len(raws) == 1
    r = raws[0]
    assert "サマーコンサート" == r["title"]
    assert "-08-10" in r["starts_at"]
    assert "14:00" in r["starts_at"]
    assert "新宿文化センター 大ホール" == r["venue_name"]


# ────────────────────────────────────────────────────────────────
# 2. 7月・8月が混在するHTMLから正しい月が割り当てられる
# ────────────────────────────────────────────────────────────────

def test_regasu_parse_multi_month():
    html = _make_calendar_html([
        {
            "hall_class": "cal_large-hall",
            "month": 7,
            "rows": [{"day": 5, "dow": "日", "time": "14：00", "title": "7月イベント"}],
        },
        {
            "hall_class": "cal_large-hall",
            "month": 8,
            "rows": [{"day": 3, "dow": "月", "time": "15：00", "title": "8月イベント"}],
        },
    ])
    adapter = _get_adapter()
    with _patch_urlopen(html):
        raws = adapter.fetch()

    titles = {r["title"]: r["starts_at"] for r in raws}
    assert "7月イベント" in titles
    assert "8月イベント" in titles

    july_starts = titles["7月イベント"]
    aug_starts = titles["8月イベント"]
    assert "-07-05" in july_starts or "-07-" in july_starts
    assert "-08-03" in aug_starts or "-08-" in aug_starts


# ────────────────────────────────────────────────────────────────
# 3. 現在月より前の月は翌年と判断する
# ────────────────────────────────────────────────────────────────

def test_regasu_past_month_advances_year():
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    # 明らかに過去の月（1月、現在が7月以降なら1月は過去）
    past_month = 1
    if now.month == 1:
        past_month = 12  # 1月なら12月を過去として使う

    html = _make_calendar_html([{
        "hall_class": "cal_small-hall",
        "month": past_month,
        "rows": [{"day": 15, "dow": "木", "time": "14：00", "title": "来年イベント"}],
    }])
    adapter = _get_adapter()
    with _patch_urlopen(html):
        raws = adapter.fetch()

    assert len(raws) == 1
    starts_at = raws[0]["starts_at"]
    year_in_starts = int(starts_at[:4])
    assert year_in_starts == now.year + 1, f"翌年になるべき: {starts_at}"


# ────────────────────────────────────────────────────────────────
# 4. 全角コロン時刻が正しく変換される
# ────────────────────────────────────────────────────────────────

def test_regasu_fullwidth_colon_time():
    html = _make_calendar_html([{
        "hall_class": "cal_large-hall",
        "month": 8,
        "rows": [{"day": 4, "dow": "土", "time": "13：40", "title": "全角コロンテスト"}],
    }])
    adapter = _get_adapter()
    with _patch_urlopen(html):
        raws = adapter.fetch()

    assert len(raws) == 1
    assert "13:40" in raws[0]["starts_at"]


# ────────────────────────────────────────────────────────────────
# 5. 複数開演時刻の場合は最初のもの（1回目）を採用
# ────────────────────────────────────────────────────────────────

def test_regasu_multi_showtime():
    html = _make_calendar_html([{
        "hall_class": "cal_large-hall",
        "month": 8,
        "rows": [{"day": 20, "dow": "月", "time": "【1回目】13:00開演　【2回目】16:00開演", "title": "複数回公演"}],
    }])
    adapter = _get_adapter()
    with _patch_urlopen(html):
        raws = adapter.fetch()

    assert len(raws) == 1
    starts_at = raws[0]["starts_at"]
    assert "13:00" in starts_at
    assert "16:00" not in starts_at


# ────────────────────────────────────────────────────────────────
# 6. 会場クラスのマッピング
# ────────────────────────────────────────────────────────────────

def test_regasu_hall_mapping():
    for hall_class, expected_name in [
        ("cal_large-hall", "新宿文化センター 大ホール"),
        ("cal_small-hall", "新宿文化センター 小ホール"),
        ("cal_display-room", "新宿文化センター 展示室"),
    ]:
        html = _make_calendar_html([{
            "hall_class": hall_class,
            "month": 8,
            "rows": [{"day": 5, "dow": "水", "time": "14：00", "title": f"{expected_name}テスト"}],
        }])
        adapter = _get_adapter()
        with _patch_urlopen(html):
            raws = adapter.fetch()

        assert len(raws) >= 1, f"{hall_class} でイベントが取れなかった"
        assert raws[0]["venue_name"] == expected_name, f"{hall_class} → {raws[0]['venue_name']} (期待: {expected_name})"


# ────────────────────────────────────────────────────────────────
# 7. normalize() が (EventRecord, SourceEvidence) を返す
# ────────────────────────────────────────────────────────────────

def test_regasu_normalize_basic():
    from market_intelligence.models.event_record import EventRecord
    from market_intelligence.models.source_evidence import SourceEvidence

    adapter = _get_adapter()
    raw = {
        "title": "テストコンサート",
        "starts_at": "2026-08-10T14:00:00+09:00",
        "ends_at": "2026-08-10T17:00:00+09:00",
        "venue_name": "新宿文化センター 大ホール",
        "address": "東京都新宿区新宿6-14-1",
        "lat": 35.6918,
        "lon": 139.7044,
        "category": "culture",
        "confidence": 0.90,
    }
    result = adapter.normalize(raw)

    assert isinstance(result, tuple)
    assert len(result) == 2
    record, evidence = result
    assert isinstance(record, EventRecord)
    assert isinstance(evidence, SourceEvidence)
    assert record.title == "テストコンサート"
    assert evidence.source_type == "html_scrape"
    assert evidence.source_name == "新宿文化センター"


# ────────────────────────────────────────────────────────────────
# 8. confidence = 0.90
# ────────────────────────────────────────────────────────────────

def test_regasu_confidence_090():
    adapter = _get_adapter()
    raw = {
        "title": "信頼度テスト",
        "starts_at": "2026-08-10T14:00:00+09:00",
        "ends_at": "2026-08-10T17:00:00+09:00",
        "venue_name": "新宿文化センター 大ホール",
        "address": "東京都新宿区新宿6-14-1",
        "lat": 35.6918,
        "lon": 139.7044,
        "category": "culture",
        "confidence": 0.90,
    }
    record, evidence = adapter.normalize(raw)
    assert record.confidence == 0.90
    assert evidence.confidence == 0.90


# ────────────────────────────────────────────────────────────────
# 9. 0件のとき標準出力にWARNINGが出力される
# ────────────────────────────────────────────────────────────────

def test_regasu_zero_events_warning(capsys):
    # イベントが0件になるHTML（会場セクションなし）
    empty_html = "<html><body><p>no events</p></body></html>".encode("utf-8")
    adapter = _get_adapter()
    with _patch_urlopen(empty_html):
        raws = adapter.fetch()

    assert raws == []
    captured = capsys.readouterr()
    assert "WARNING" in captured.out


# ────────────────────────────────────────────────────────────────
# 10. HTTP 503 のとき [] を返す（クラッシュしない）
# ────────────────────────────────────────────────────────────────

def test_regasu_http_failure_returns_empty():
    adapter = _get_adapter()

    def _raise_error(req, ctx, timeout=15):
        import urllib.error
        raise urllib.error.HTTPError(
            url="https://example.com",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

    with patch(
        "market_intelligence.adapters.regasu_bunka_center_adapter.urllib_request_fetch",
        side_effect=_raise_error,
    ):
        raws = adapter.fetch()

    assert raws == []


# ────────────────────────────────────────────────────────────────
# 11. Levenshtein: 同一文字列 → 1.0
# ────────────────────────────────────────────────────────────────

def test_levenshtein_identical():
    from market_intelligence.events.dedup import levenshtein_similarity
    assert levenshtein_similarity("abc", "abc") == 1.0
    assert levenshtein_similarity("新宿フェスティバル", "新宿フェスティバル") == 1.0


# ────────────────────────────────────────────────────────────────
# 12. Levenshtein: 全く異なる文字列 → 低い値
# ────────────────────────────────────────────────────────────────

def test_levenshtein_completely_different():
    from market_intelligence.events.dedup import levenshtein_similarity
    sim = levenshtein_similarity("abc", "xyz")
    assert sim < 1.0
    # 完全に異なる → 低い類似度
    sim2 = levenshtein_similarity("新宿フェスティバル2026", "渋谷ハロウィン")
    assert sim2 < 0.5


# ────────────────────────────────────────────────────────────────
# 13. Levenshtein: 閾値境界テスト
# ────────────────────────────────────────────────────────────────

def test_levenshtein_similarity_085_boundary():
    from market_intelligence.events.dedup import levenshtein_similarity, is_duplicate_candidate

    # threshold=0.85 に対してちょうど閾値以下はFalse、超えたらTrue
    # 同じ日付で試す
    ev_a = {"starts_at": "2026-08-10T14:00:00+09:00", "title": "新宿交響楽団第71回定期演奏会"}
    ev_b_similar = {"starts_at": "2026-08-10T14:00:00+09:00", "title": "新宿交響楽団第71回定期演奏会"}
    ev_b_diff = {"starts_at": "2026-08-10T14:00:00+09:00", "title": "渋谷フィルハーモニー管弦楽団"}

    assert is_duplicate_candidate(ev_a, ev_b_similar, title_threshold=0.85) is True
    assert is_duplicate_candidate(ev_a, ev_b_diff, title_threshold=0.85) is False


# ────────────────────────────────────────────────────────────────
# 14. normalize_title: 全角英数が半角に変換される
# ────────────────────────────────────────────────────────────────

def test_normalize_title_nfkc():
    from market_intelligence.events.dedup import normalize_title
    # ＡＢＣD → abcd
    result = normalize_title("ＡＢＣD")
    assert result == "abcd"
    # 全角数字
    result2 = normalize_title("２０２６年")
    assert "2026" in result2


# ────────────────────────────────────────────────────────────────
# 15. normalize_title: 記号・空白が除去される
# ────────────────────────────────────────────────────────────────

def test_normalize_title_removes_symbols():
    from market_intelligence.events.dedup import normalize_title
    result = normalize_title("新宿フェス　2026！ #event")
    assert " " not in result
    assert "　" not in result
    assert "！" not in result
    assert "#" not in result
    # 日本語は保持
    assert "新宿" in result
    assert "フェス" in result


# ────────────────────────────────────────────────────────────────
# 16. normalize_title: 英字が小文字化される
# ────────────────────────────────────────────────────────────────

def test_normalize_title_lowercase():
    from market_intelligence.events.dedup import normalize_title
    result = normalize_title("Shinjuku Festival 2026")
    assert result == result.lower()
    assert "shinjuku" in result
    assert "festival" in result


# ────────────────────────────────────────────────────────────────
# 17. 同日・類似タイトル（類似度>0.85）→ True
# ────────────────────────────────────────────────────────────────

def test_is_duplicate_same_day_similar_title():
    from market_intelligence.events.dedup import is_duplicate_candidate
    ev_a = {
        "starts_at": "2026-08-10T14:00:00+09:00",
        "title": "新宿交響楽団第71回定期演奏会",
    }
    ev_b = {
        "starts_at": "2026-08-10T15:00:00+09:00",  # 時刻が違っても日付が同じ
        "title": "新宿交響楽団 第71回 定期演奏会",
    }
    assert is_duplicate_candidate(ev_a, ev_b) is True


# ────────────────────────────────────────────────────────────────
# 18. 同日・異なるタイトル → False
# ────────────────────────────────────────────────────────────────

def test_is_duplicate_same_day_different_title():
    from market_intelligence.events.dedup import is_duplicate_candidate
    ev_a = {
        "starts_at": "2026-08-10T14:00:00+09:00",
        "title": "新宿交響楽団第71回定期演奏会",
    }
    ev_b = {
        "starts_at": "2026-08-10T14:00:00+09:00",
        "title": "渋谷ジャズフェスティバル",
    }
    assert is_duplicate_candidate(ev_a, ev_b) is False


# ────────────────────────────────────────────────────────────────
# 19. 異なる日・同タイトル → False（繰り返しイベントは別扱い）
# ────────────────────────────────────────────────────────────────

def test_is_duplicate_different_day_similar_title():
    from market_intelligence.events.dedup import is_duplicate_candidate
    ev_a = {
        "starts_at": "2026-08-10T14:00:00+09:00",
        "title": "新宿交響楽団定期演奏会",
    }
    ev_b = {
        "starts_at": "2026-09-10T14:00:00+09:00",
        "title": "新宿交響楽団定期演奏会",
    }
    assert is_duplicate_candidate(ev_a, ev_b) is False


# ────────────────────────────────────────────────────────────────
# 20. マージ: primaryにdescriptionがある場合secondaryで上書きされない
# ────────────────────────────────────────────────────────────────

def test_merge_primary_wins_existing_field():
    from market_intelligence.events.dedup import merge_events
    primary = {
        "id": "evt_primary",
        "uid": "uid_primary@market-intelligence",
        "source_id": "kanko_shinjuku",
        "source_evidence_id": "ev_primary_ev",
        "source_evidence_ids": ["ev_primary_ev"],
        "merged_from_source_ids": [],
        "title": "テストイベント",
        "description": "主要ソースの説明",
        "starts_at": "2026-08-10T14:00:00+09:00",
    }
    secondary = {
        "id": "evt_secondary",
        "uid": "uid_secondary@market-intelligence",
        "source_id": "regasu_bunka_center",
        "source_evidence_id": "ev_secondary_ev",
        "source_evidence_ids": ["ev_secondary_ev"],
        "merged_from_source_ids": [],
        "title": "テストイベント",
        "description": "副ソースの説明（上書きされないはず）",
        "starts_at": "2026-08-10T14:00:00+09:00",
    }
    result = merge_events(primary, secondary)
    assert result["description"] == "主要ソースの説明"


# ────────────────────────────────────────────────────────────────
# 21. マージ: primaryのaddressがNoneの場合secondaryで補完される
# ────────────────────────────────────────────────────────────────

def test_merge_secondary_fills_missing_field():
    from market_intelligence.events.dedup import merge_events
    primary = {
        "id": "evt_primary",
        "uid": "uid_primary@market-intelligence",
        "source_id": "doorkeeper_api",
        "source_evidence_id": "ev_primary_ev",
        "source_evidence_ids": ["ev_primary_ev"],
        "merged_from_source_ids": [],
        "title": "テストイベント",
        "address": None,
        "latitude": None,
        "longitude": None,
        "starts_at": "2026-08-10T14:00:00+09:00",
    }
    secondary = {
        "id": "evt_secondary",
        "uid": "uid_secondary@market-intelligence",
        "source_id": "regasu_bunka_center",
        "source_evidence_id": "ev_secondary_ev",
        "source_evidence_ids": ["ev_secondary_ev"],
        "merged_from_source_ids": [],
        "title": "テストイベント",
        "address": "東京都新宿区新宿6-14-1",
        "latitude": 35.6918,
        "longitude": 139.7044,
        "starts_at": "2026-08-10T14:00:00+09:00",
    }
    result = merge_events(primary, secondary)
    assert result["address"] == "東京都新宿区新宿6-14-1"
    assert result["latitude"] == 35.6918
    assert result["longitude"] == 139.7044


# ────────────────────────────────────────────────────────────────
# 22. マージ後もprimary UIDが維持される
# ────────────────────────────────────────────────────────────────

def test_merge_uid_preserved():
    from market_intelligence.events.dedup import merge_events
    primary = {
        "id": "evt_primary",
        "uid": "primaryuid001@market-intelligence",
        "source_id": "kanko_shinjuku",
        "source_evidence_id": "ev_primary_ev",
        "source_evidence_ids": ["ev_primary_ev"],
        "merged_from_source_ids": [],
        "title": "テストイベント",
        "starts_at": "2026-08-10T14:00:00+09:00",
    }
    secondary = {
        "id": "evt_secondary",
        "uid": "secondaryuid002@market-intelligence",
        "source_id": "regasu_bunka_center",
        "source_evidence_id": "ev_secondary_ev",
        "source_evidence_ids": ["ev_secondary_ev"],
        "merged_from_source_ids": [],
        "title": "テストイベント",
        "starts_at": "2026-08-10T14:00:00+09:00",
    }
    result = merge_events(primary, secondary)
    assert result["uid"] == "primaryuid001@market-intelligence"


# ────────────────────────────────────────────────────────────────
# 23. merged_from_source_ids にsecondaryのsource_idが記録される
# ────────────────────────────────────────────────────────────────

def test_merge_from_source_ids_recorded():
    from market_intelligence.events.dedup import merge_events
    primary = {
        "id": "evt_primary",
        "uid": "primaryuid001@market-intelligence",
        "source_id": "kanko_shinjuku",
        "source_evidence_id": "ev_primary_ev",
        "source_evidence_ids": ["ev_primary_ev"],
        "merged_from_source_ids": [],
        "title": "テストイベント",
        "starts_at": "2026-08-10T14:00:00+09:00",
    }
    secondary = {
        "id": "evt_secondary",
        "uid": "secondaryuid002@market-intelligence",
        "source_id": "新宿文化センター",
        "source_evidence_id": "ev_secondary_ev",
        "source_evidence_ids": ["ev_secondary_ev"],
        "merged_from_source_ids": [],
        "title": "テストイベント",
        "starts_at": "2026-08-10T14:00:00+09:00",
    }
    result = merge_events(primary, secondary)
    assert "新宿文化センター" in result["merged_from_source_ids"]
    assert "ev_secondary_ev" in result["source_evidence_ids"]


# ────────────────────────────────────────────────────────────────
# 24. merged_from_source_ids が非空の場合 X-MERGED-FROM が出力される
# ────────────────────────────────────────────────────────────────

def test_ics_has_x_merged_from():
    from market_intelligence.events.ics_builder import build_ics_feed
    import tempfile
    from pathlib import Path

    events_with_assessments = [{
        "event": {
            "id": "evt_test",
            "uid": "testuid001@market-intelligence",
            "title": "マージ済みイベント",
            "starts_at": "2026-08-10T14:00:00+09:00",
            "ends_at": "2026-08-10T17:00:00+09:00",
            "all_day": False,
            "merged_from_source_ids": ["kanko_shinjuku", "regasu_bunka_center"],
            "source_evidence_ids": [],
            "first_seen_at": "2026-07-16T10:00:00+09:00",
            "last_seen_at": "2026-07-16T10:00:00+09:00",
            "sequence": 0,
        },
        "assessment": {
            "impact_score": 2,
            "impact_reasons": ["nearby"],
            "store_id": "cafe_01",
        },
    }]

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test.ics"
        build_ics_feed(
            events_with_assessments,
            calname="テスト",
            store_id="cafe_01",
            business_unit="cafe",
            output_path=out_path,
        )
        content = out_path.read_text(encoding="utf-8")

    assert "X-MERGED-FROM" in content
    assert "kanko_shinjuku" in content
    assert "regasu_bunka_center" in content


# ────────────────────────────────────────────────────────────────
# 25. merged_from_source_ids が空の場合 X-MERGED-FROM が出力されない
# ────────────────────────────────────────────────────────────────

def test_ics_no_x_merged_from_when_empty():
    from market_intelligence.events.ics_builder import build_ics_feed
    import tempfile
    from pathlib import Path

    events_with_assessments = [{
        "event": {
            "id": "evt_test2",
            "uid": "testuid002@market-intelligence",
            "title": "単体イベント",
            "starts_at": "2026-08-10T14:00:00+09:00",
            "ends_at": "2026-08-10T17:00:00+09:00",
            "all_day": False,
            "merged_from_source_ids": [],
            "source_evidence_ids": [],
            "first_seen_at": "2026-07-16T10:00:00+09:00",
            "last_seen_at": "2026-07-16T10:00:00+09:00",
            "sequence": 0,
        },
        "assessment": {
            "impact_score": 1,
            "impact_reasons": [],
            "store_id": "cafe_01",
        },
    }]

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test_no_merge.ics"
        build_ics_feed(
            events_with_assessments,
            calname="テスト",
            store_id="cafe_01",
            business_unit="cafe",
            output_path=out_path,
        )
        content = out_path.read_text(encoding="utf-8")

    assert "X-MERGED-FROM" not in content


# ────────────────────────────────────────────────────────────────
# 26. Source障害分離: regasuがfails/doorkeeper成功
# ────────────────────────────────────────────────────────────────

def test_source_failure_isolation():
    """regasuがエラーでも、doorkeeperのデータは正常保存される"""
    import tempfile
    from pathlib import Path
    from market_intelligence.storage.json_store import JsonStore

    with tempfile.TemporaryDirectory() as tmpdir:
        store = JsonStore(Path(tmpdir))
        store.initialize_schema()

        # store_profiles に両ソースを持つプロファイルを作成
        profile = {
            "id": "test_store",
            "name": "テスト店舗",
            "business_unit": "cafe",
            "latitude": 35.69,
            "longitude": 139.711,
            "opening_hours": {"open": "09:00", "close": "21:00"},
            "event_sources": [
                {"type": "regasu_bunka_center", "name": "新宿文化センター"},
                {"type": "doorkeeper", "name": "Doorkeeper新宿", "keyword": "新宿"},
            ],
            "enabled": True,
        }
        store.upsert("store_profiles", profile)

        def _fake_regasu_fetch(**kwargs):
            raise RuntimeError("Regasu接続失敗テスト")

        # Doorkeeper は1件返す
        doorkeeper_raw = {
            "event": {
                "id": 99999,
                "title": "テストDoorkeeperイベント",
                "starts_at": "2026-08-20T05:00:00.000Z",
                "ends_at": "2026-08-20T09:00:00.000Z",
                "venue_name": "テスト会場",
                "address": "東京都新宿区",
                "lat": 35.69,
                "long": 139.711,
                "description": "テスト",
                "public_url": "https://example.doorkeeper.jp/events/99999",
                "participants": 10,
                "waitlisted": 0,
                "ticket_limit": 30,
            }
        }

        def _fake_doorkeeper_fetch(**kwargs):
            return [doorkeeper_raw]

        with patch("market_intelligence.adapters.RegasuBunkaCenterAdapter.fetch", side_effect=_fake_regasu_fetch):
            with patch("market_intelligence.adapters.DoorkeeperAdapter.fetch", side_effect=_fake_doorkeeper_fetch):
                from market_intelligence.events.collect import collect_events
                result = collect_events(store, store_id="test_store", days=90, demo=False, no_llm=True)

        events = store.list_all("event_records")
        # doorkeeperの分は保存されているはず
        assert any("テストDoorkeeperイベント" in e.get("title", "") for e in events), \
            f"doorkeeperイベントが保存されていない: {[e.get('title') for e in events]}"


# ────────────────────────────────────────────────────────────────
# 27. 全ソース0件の場合に警告が出力される（demoフォールバック）
# ────────────────────────────────────────────────────────────────

def test_all_sources_zero_warning(capsys):
    """全ソースが0件のとき、[collect]がデモデータにフォールバックすることを確認"""
    import tempfile
    from pathlib import Path
    from market_intelligence.storage.json_store import JsonStore

    with tempfile.TemporaryDirectory() as tmpdir:
        store = JsonStore(Path(tmpdir))
        store.initialize_schema()

        profile = {
            "id": "test_store2",
            "name": "テスト店舗2",
            "business_unit": "cafe",
            "latitude": 35.69,
            "longitude": 139.711,
            "opening_hours": {"open": "09:00", "close": "21:00"},
            "event_sources": [
                {"type": "regasu_bunka_center", "name": "新宿文化センター"},
            ],
            "enabled": True,
        }
        store.upsert("store_profiles", profile)

        def _fake_regasu_fetch(**kwargs):
            return []  # 0件

        with patch("market_intelligence.adapters.RegasuBunkaCenterAdapter.fetch", side_effect=_fake_regasu_fetch):
            from market_intelligence.events.collect import collect_events
            collect_events(store, store_id="test_store2", days=90, demo=False, no_llm=True)

    captured = capsys.readouterr()
    # フォールバックメッセージが出るはず
    assert "デモデータ" in captured.out or "demo" in captured.out.lower()
