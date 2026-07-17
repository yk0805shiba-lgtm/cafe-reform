"""
競合モニタリングAgent（competitor_monitoring）。

公開情報から競合スナップショットを取得・保存し、
前回との差分を検知して戦略提案を生成する。
外部コンテンツは信頼できないデータとして扱う。
競合の単純コピー・値下げ追従は提案しない。
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from .. import config
from ..models import (
    CompetitorSnapshot, Recommendation, AgentRun, SnapshotDiff
)
from ..storage import JsonStore
from ..adapters import (
    BaseCompetitorAdapter, FixtureCompetitorAdapter, ManualCompetitorAdapter
)
from ..scoring import classify_severity
from ..utils import now_jst_iso, price_change_rate

TZ_TOKYO = ZoneInfo("Asia/Tokyo")
AGENT_TYPE = "competitor_monitoring"


class CompetitorAgent:
    """競合モニタリングAgent"""

    def __init__(self, store: JsonStore, llm=None):
        self.store = store
        self.llm = llm

    def run(self, store_id: str, trigger_type: str = "manual") -> AgentRun:
        """
        メイン実行エントリーポイント。
        全ての有効競合に対してスナップショットを取得し、差分検知・提案生成を行う。
        """
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run = AgentRun(
            id=run_id,
            agent_type=AGENT_TYPE,
            store_id=store_id,
            started_at=now_jst_iso(),
            trigger_type=trigger_type,
            created_at=now_jst_iso(),
        )
        self.store.upsert("agent_runs", run.to_dict())
        print(f"[{AGENT_TYPE}] 実行開始 store={store_id} trigger={trigger_type}")

        store_profile = self.store.get("store_profiles", store_id)
        if not store_profile:
            run.status = "failed"
            run.error_summary = f"店舗プロファイルが見つかりません: {store_id}"
            run.finished_at = now_jst_iso()
            self.store.upsert("agent_runs", run.to_dict())
            return run

        competitors = self.store.filter("competitor_profiles", monitoring_enabled=True)
        if not competitors:
            print(f"[{AGENT_TYPE}] 監視対象の競合がありません")

        all_fetched = 0
        created = 0
        updated = 0
        rec_count = 0
        errors = []
        provider_status = {}

        for competitor in competitors:
            c_id = competitor["id"]
            try:
                adapter = self._build_adapter(competitor)
                if not adapter.is_available():
                    provider_status[c_id] = "unavailable"
                    continue

                raw = adapter.fetch(competitor_id=c_id)
                all_fetched += 1

                snapshot, evidence = adapter.to_snapshot(raw, c_id)
                self.store.upsert("source_evidence", evidence.to_dict())

                # 前回スナップショットとの比較
                prev_snap = self._get_latest_snapshot(c_id, exclude_id=None)
                self.store.upsert("competitor_snapshots", snapshot.to_dict())
                created += 1

                if prev_snap:
                    diff = self._compute_diff(prev_snap, snapshot)
                    self.store.upsert("snapshot_diffs", diff.to_dict())

                    if diff.has_changes:
                        recs = self._generate_recommendations(diff, competitor, store_profile)
                        rec_count += recs
                        print(f"[{AGENT_TYPE}] 差分検知: {competitor.get('name')} 重要度={diff.severity}")

                provider_status[c_id] = "success"

            except Exception as e:
                errors.append(f"{c_id}: {str(e)[:100]}")
                provider_status[c_id] = f"error:{str(e)[:50]}"
                print(f"[{AGENT_TYPE}] 競合処理エラー {c_id}: {e}")
                continue

        run.finished_at = now_jst_iso()
        run.status = "success" if not errors else "partial"
        run.records_fetched = all_fetched
        run.records_created = created
        run.records_updated = updated
        run.recommendations_created = rec_count
        run.error_summary = "; ".join(errors[:3]) if errors else ""
        run.provider_status = provider_status
        run.model_info = {"provider": config.LLM_PROVIDER, "model": config.LLM_MODEL}
        self.store.upsert("agent_runs", run.to_dict())

        print(f"[{AGENT_TYPE}] 完了: 取得={all_fetched} 新規={created} 提案={rec_count}")
        return run

    def _build_adapter(self, competitor: dict) -> BaseCompetitorAdapter:
        if config.DEMO_MODE:
            return FixtureCompetitorAdapter()
        # 公式APIがなければ手動記録アダプター（取得不可ステータスで安全に処理）
        return ManualCompetitorAdapter()

    def _get_latest_snapshot(self, competitor_id: str, exclude_id: Optional[str] = None) -> Optional[dict]:
        snaps = [
            s for s in self.store.filter("competitor_snapshots", competitor_id=competitor_id)
            if s.get("id") != exclude_id
        ]
        if not snaps:
            return None
        return sorted(snaps, key=lambda s: s.get("captured_at", ""), reverse=True)[0]

    def _compute_diff(self, prev: dict, curr: CompetitorSnapshot) -> SnapshotDiff:
        """
        2つのスナップショットの差分を計算する。
        意味のない変更（空白差異など）を除外する。
        価格は変更前・後・差額・変更率を記録する。
        """
        diff_id = f"diff_{uuid.uuid4().hex[:8]}"
        price_changes = []
        new_items = []
        removed_items = []
        set_changes = []
        discount_changes = []
        hours_changes = []

        # 価格変更の検知
        prev_prices = prev.get("prices", {})
        curr_prices = curr.prices
        for item_name, curr_price in curr_prices.items():
            if item_name in prev_prices:
                prev_price = prev_prices[item_name]
                if isinstance(prev_price, (int, float)) and isinstance(curr_price, (int, float)):
                    diff = curr_price - prev_price
                    if diff != 0:
                        rate = price_change_rate(int(prev_price), int(curr_price))
                        price_changes.append({
                            "item_name": item_name,
                            "previous_price": prev_price,
                            "current_price": curr_price,
                            "difference": diff,
                            "change_rate_pct": rate,
                        })

        # 新商品・終売検知
        prev_items = {i.get("name", ""): i for i in prev.get("menu_items", [])}
        curr_items = {i.get("name", ""): i for i in curr.menu_items}
        for name, item in curr_items.items():
            if name and name not in prev_items:
                new_items.append(item)
        for name, item in prev_items.items():
            if name and name not in curr_items:
                removed_items.append(item)

        # セット変更の検知
        prev_sets = {s.get("name", ""): s for s in prev.get("sets", [])}
        curr_sets_dict = {s.get("name", ""): s for s in curr.sets}
        for name, s in curr_sets_dict.items():
            if name not in prev_sets:
                set_changes.append({"type": "new_set", "set": s})
            elif s.get("price") != prev_sets[name].get("price"):
                set_changes.append({"type": "price_change", "set": s, "prev": prev_sets[name]})

        # 営業時間変更の検知
        prev_hours = prev.get("opening_hours", {})
        curr_hours = curr.opening_hours
        if prev_hours and curr_hours and prev_hours != curr_hours:
            hours_changes.append({"previous": prev_hours, "current": curr_hours})

        # 注文受付状態変更
        order_change = None
        if prev.get("order_availability") is not None and curr.order_availability is not None:
            if prev.get("order_availability") != curr.order_availability:
                order_change = {
                    "previous": prev.get("order_availability"),
                    "current": curr.order_availability,
                }

        # 評価変化
        rating_change = None
        if prev.get("rating") and curr.rating:
            diff_rating = round(curr.rating - prev.get("rating", 0), 2)
            if abs(diff_rating) >= 0.1:
                rating_change = {"previous": prev.get("rating"), "current": curr.rating, "diff": diff_rating}

        has_changes = bool(
            price_changes or new_items or removed_items or set_changes
            or discount_changes or hours_changes or order_change
        )

        severity = classify_severity(
            {
                "price_changes": price_changes,
                "new_items": new_items,
                "set_changes": set_changes,
                "opening_hours_changes": hours_changes,
                "order_availability_change": order_change,
            },
            config.COMPETITOR_PRICE_CHANGE_HIGH_THRESHOLD,
            config.COMPETITOR_PRICE_CHANGE_MEDIUM_THRESHOLD,
        )

        return SnapshotDiff(
            id=diff_id,
            competitor_id=curr.competitor_id,
            previous_snapshot_id=prev.get("id", ""),
            current_snapshot_id=curr.id,
            compared_at=now_jst_iso(),
            price_changes=price_changes,
            new_items=new_items,
            removed_items=removed_items,
            set_changes=set_changes,
            discount_changes=discount_changes,
            opening_hours_changes=hours_changes,
            order_availability_change=order_change,
            rating_change=rating_change,
            severity=severity,
            has_changes=has_changes,
        )

    def _generate_recommendations(
        self, diff: SnapshotDiff, competitor: dict, store: dict
    ) -> int:
        """差分から戦略提案を生成する。単純コピー・値下げ追従は行わない。"""
        store_id = store["id"]
        business_units = []
        bu = store.get("business_unit", "both")
        if bu == "both":
            business_units = ["cafe", "delivery"]
        else:
            business_units = [bu]

        created = 0
        for unit in business_units:
            if self.llm and config.is_llm_available():
                suggestions = self.llm.generate_competitor_strategy(
                    diff.to_dict(), competitor, store, unit
                )
            else:
                suggestions = self._rule_based_competitor_suggestions(diff, competitor, store, unit)

            for s in suggestions:
                rec_id = f"rec_{uuid.uuid4().hex[:8]}"
                rec = Recommendation(
                    id=rec_id,
                    agent_type=AGENT_TYPE,
                    store_id=store_id,
                    business_unit=unit,
                    category=s.get("category", "promotion"),
                    title=s.get("title", ""),
                    summary=s.get("summary", ""),
                    reason=s.get("reason", ""),
                    evidence_ids=diff.source_evidence_ids if hasattr(diff, "source_evidence_ids") else [],
                    confidence=0.75,
                    estimated_impact=s.get("estimated_impact", "medium"),
                    effort=s.get("effort", "medium"),
                    urgency=s.get("urgency", "medium") if diff.severity == "high" else "medium",
                    status="draft",
                    approval_required=True,
                    source_ref=competitor.get("id", ""),
                    created_at=now_jst_iso(),
                    updated_at=now_jst_iso(),
                )
                self.store.upsert("recommendations", rec.to_dict())
                created += 1

        return created

    def _rule_based_competitor_suggestions(
        self, diff: SnapshotDiff, competitor: dict, store: dict, business_unit: str
    ) -> list[dict]:
        """LLMなしのルールベース競合対策提案"""
        suggestions = []
        comp_name = competitor.get("name", "競合店")

        # 価格変更
        for pc in diff.price_changes:
            rate = pc.get("change_rate_pct", 0)
            prev = pc.get("previous_price")
            curr = pc.get("current_price")
            if rate > 0:  # 値上げ
                if business_unit == "cafe":
                    suggestions.append({
                        "category": "pricing",
                        "title": "競合値上げを差別化に活用",
                        "summary": f"「{comp_name}」が{pc['item_name']}を{prev}円→{curr}円（{rate}%増）に値上げ。自店は抹茶の品質・体験価値を訴求し、価格以外での差別化を強化する。",
                        "reason": f"競合値上げで価格差が縮まり、品質訴求の機会",
                        "urgency": "medium", "effort": "low", "estimated_impact": "medium",
                    })
                elif business_unit == "delivery":
                    suggestions.append({
                        "category": "pricing",
                        "title": "競合値上げでのボリューム訴求",
                        "summary": f"「{comp_name}」が値上げ。自店は単純値下げせず、ボリューム・追い飯・トッピング自由度を強調して満足感で差別化する。",
                        "reason": "価格追従でなく、コストパフォーマンスの見せ方を強化する",
                        "urgency": "medium", "effort": "low", "estimated_impact": "medium",
                    })
            else:  # 値下げ
                suggestions.append({
                    "category": "pricing",
                    "title": "競合値下げへの差別化対応",
                    "summary": f"「{comp_name}」が{pc['item_name']}を値下げ（{abs(rate):.1f}%減）。追従値下げでなく、品質・体験・ボリュームで差別化する方針を確認する。",
                    "reason": "単純値下げ競争は利益率を悪化させる。強みで勝負する",
                    "urgency": "low" if diff.severity == "low" else "medium",
                    "effort": "low", "estimated_impact": "medium",
                })

        # 新商品・新セット
        if diff.new_items:
            if business_unit == "delivery":
                suggestions.append({
                    "category": "product",
                    "title": "競合新商品に対するメニュー見直し",
                    "summary": f"「{comp_name}」に新商品が追加された。自店は麺を混ぜる瞬間・具材量・満足感を見せる写真・説明文で差別化する。コピーは行わない。",
                    "reason": "競合新商品への対応は自店の強みを際立たせる機会",
                    "urgency": "low", "effort": "medium", "estimated_impact": "medium",
                })
            elif business_unit == "cafe":
                suggestions.append({
                    "category": "product",
                    "title": "自店の独自メニューの訴求強化",
                    "summary": f"「{comp_name}」に新商品追加。自店は抹茶を点てる工程・和の体験・スイーツセットの独自性を前面に出す。",
                    "reason": "競合との差別化ポイントを明確化する機会",
                    "urgency": "low", "effort": "low", "estimated_impact": "medium",
                })

        # 営業時間変更
        for hc in diff.opening_hours_changes:
            prev_close = hc.get("previous", {}).get("close", "")
            curr_close = hc.get("current", {}).get("close", "")
            if curr_close and prev_close and curr_close > prev_close:
                suggestions.append({
                    "category": "hours",
                    "title": "競合の営業時間延長への対応確認",
                    "summary": f"「{comp_name}」が閉店時間を{prev_close}→{curr_close}に延長。夜間の自店への影響を確認し、必要に応じて深夜デリバリーの訴求を強化する。",
                    "reason": "夜間の競合時間が増加するため、自店の強みを再確認する",
                    "urgency": "high", "effort": "medium", "estimated_impact": "high",
                })

        return suggestions[:3]

    def get_latest_diff(self, competitor_id: str) -> Optional[dict]:
        """最新の差分を返す"""
        diffs = self.store.filter("snapshot_diffs", competitor_id=competitor_id)
        if not diffs:
            return None
        return sorted(diffs, key=lambda d: d.get("compared_at", ""), reverse=True)[0]

    def register_competitor(self, competitor_data: dict) -> str:
        """競合を登録する"""
        from ..models import CompetitorProfile
        from ..utils import geocode_if_missing
        import uuid as _uuid
        if not competitor_data.get("id"):
            competitor_data["id"] = f"comp_{_uuid.uuid4().hex[:8]}"
        # 住所があってlat/lonが未設定ならジオコーディングを試みる
        lat, lon = geocode_if_missing(
            competitor_data.get("address", ""),
            competitor_data.get("latitude"),
            competitor_data.get("longitude"),
        )
        if lat is not None:
            competitor_data["latitude"] = lat
        if lon is not None:
            competitor_data["longitude"] = lon
        competitor_data["created_at"] = now_jst_iso()
        competitor_data["updated_at"] = now_jst_iso()
        cp = CompetitorProfile.from_dict(competitor_data)
        errors = cp.validate()
        if errors:
            raise ValueError(f"競合データが無効: {errors}")
        self.store.upsert("competitor_profiles", cp.to_dict())
        return cp.id

    def record_manual_snapshot(self, competitor_id: str, data: dict) -> CompetitorSnapshot:
        """手動記録したスナップショットを保存する"""
        adapter = ManualCompetitorAdapter()
        raw = adapter.fetch(competitor_id=competitor_id, data=data)
        snapshot, evidence = adapter.to_snapshot(raw, competitor_id)
        self.store.upsert("source_evidence", evidence.to_dict())

        prev = self._get_latest_snapshot(competitor_id, exclude_id=snapshot.id)
        self.store.upsert("competitor_snapshots", snapshot.to_dict())

        if prev:
            diff = self._compute_diff(prev, snapshot)
            self.store.upsert("snapshot_diffs", diff.to_dict())

        return snapshot
