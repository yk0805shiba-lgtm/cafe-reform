"""
近隣イベント連動Agent（local_event_promotion）。

店舗周辺のイベント情報を収集・正規化・重複排除し、
cafe/delivery/bothそれぞれの販促提案とCreativeBriefを生成する。
外部投稿・価格変更などはdraftとして保存し、承認前には実行しない。
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .. import config
from ..models import (
    EventRecord, SourceEvidence, Recommendation, AgentRun, CreativeBrief
)
from ..storage import JsonStore
from ..adapters import (
    BaseEventAdapter, FixtureEventAdapter, ICalEventAdapter,
    CsvEventAdapter, ManualEventAdapter,
)
from ..scoring import score_event
from ..utils import now_jst_iso, parse_iso, content_hash as make_hash

TZ_TOKYO = ZoneInfo("Asia/Tokyo")
AGENT_TYPE = "local_event_promotion"


class LocalEventAgent:
    """近隣イベント連動Agent"""

    def __init__(self, store: JsonStore, llm=None):
        self.store = store
        self.llm = llm

    def run(self, store_id: str, trigger_type: str = "manual", lookahead_days: int = None) -> AgentRun:
        """
        メイン実行エントリーポイント。
        returns: AgentRun（実行結果サマリー）
        """
        lookahead_days = lookahead_days or config.EVENT_LOOKAHEAD_DAYS
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

        try:
            store_profile = self.store.get("store_profiles", store_id)
            if not store_profile:
                raise ValueError(f"店舗プロファイルが見つかりません: {store_id}")

            adapters = self._build_adapters(store_profile)
            all_records = 0
            created = 0
            updated = 0
            errors = []
            provider_status = {}

            for adapter in adapters:
                if not adapter.is_available():
                    provider_status[adapter.source_name] = "unavailable"
                    print(f"[{AGENT_TYPE}] スキップ: {adapter.source_name} - {adapter.availability_message()}")
                    continue

                try:
                    raws = adapter.fetch(store_id=store_id)
                    all_records += len(raws)
                    provider_status[adapter.source_name] = f"success:{len(raws)}"

                    for raw in raws:
                        try:
                            record, evidence = adapter.normalize(raw)
                            errs = adapter.validate(record)
                            if errs:
                                continue

                            # 重複判定: タイトル + 開始日時 + 会場のハッシュ
                            dedup_key = make_hash({
                                "title": record.title.replace("[DEMO] ", ""),
                                "starts_at": record.starts_at[:10],
                                "venue": record.venue_name,
                            })

                            # 距離計算（未計算の場合）
                            if record.distance_from_store_km is None and record.latitude and record.longitude:
                                from ..utils import haversine
                                record.distance_from_store_km = haversine(
                                    store_profile["latitude"], store_profile["longitude"],
                                    record.latitude, record.longitude
                                )

                            # 既存チェック（content_hashまたはdedup_key）
                            existing = self._find_existing_event(dedup_key, record)
                            if existing:
                                # 更新チェック（キャンセル・時間変更など）
                                self._check_event_change(existing, record, evidence)
                                self.store.update_field("event_records", existing["id"], "last_seen_at", now_jst_iso())
                                updated += 1
                            else:
                                self.store.upsert("source_evidence", evidence.to_dict())
                                self.store.upsert("event_records", record.to_dict())
                                created += 1

                        except Exception as e:
                            errors.append(str(e)[:100])
                            continue

                except Exception as e:
                    provider_status[adapter.source_name] = f"error:{str(e)[:50]}"
                    errors.append(f"{adapter.source_name}: {str(e)[:100]}")
                    continue

            # 期限内イベントのスコアリング + 提案生成
            rec_count = self._generate_recommendations(store_profile, lookahead_days)

            # AgentRun更新
            run.finished_at = now_jst_iso()
            run.status = "success" if not errors else "partial"
            run.records_fetched = all_records
            run.records_created = created
            run.records_updated = updated
            run.recommendations_created = rec_count
            run.error_summary = "; ".join(errors[:3]) if errors else ""
            run.provider_status = provider_status
            run.model_info = {"provider": config.LLM_PROVIDER, "model": config.LLM_MODEL}
            self.store.upsert("agent_runs", run.to_dict())

            print(f"[{AGENT_TYPE}] 完了: 取得={all_records} 新規={created} 更新={updated} 提案={rec_count}")
            return run

        except Exception as e:
            run.finished_at = now_jst_iso()
            run.status = "failed"
            run.error_summary = str(e)[:200]
            self.store.upsert("agent_runs", run.to_dict())
            print(f"[{AGENT_TYPE}] 失敗: {e}")
            return run

    def _build_adapters(self, store_profile: dict) -> list[BaseEventAdapter]:
        """店舗設定に基づいてアダプターリストを構築する"""
        adapters: list[BaseEventAdapter] = []

        if config.DEMO_MODE:
            adapters.append(FixtureEventAdapter())
            return adapters

        # ユーザー登録のICSソース
        for src in store_profile.get("event_sources", []):
            if src.get("type") == "ical" and src.get("url"):
                adapters.append(ICalEventAdapter(
                    source_name=src.get("name", src["url"]),
                    source_url_or_path=src["url"],
                    store_lat=store_profile.get("latitude", 0),
                    store_lon=store_profile.get("longitude", 0),
                ))
            elif src.get("type") == "csv" and src.get("path"):
                adapters.append(CsvEventAdapter(
                    source_name=src.get("name", src["path"]),
                    csv_path=src["path"],
                    store_lat=store_profile.get("latitude", 0),
                    store_lon=store_profile.get("longitude", 0),
                ))

        if not adapters:
            print(f"[{AGENT_TYPE}] イベントソースが設定されていません。フィクスチャを使用します。")
            adapters.append(FixtureEventAdapter())

        return adapters

    def _find_existing_event(self, dedup_key: str, record: EventRecord) -> Optional[dict]:
        """重複イベントを検索する"""
        for ev in self.store.list_all("event_records"):
            existing_key = make_hash({
                "title": ev.get("title", "").replace("[DEMO] ", ""),
                "starts_at": ev.get("starts_at", "")[:10],
                "venue": ev.get("venue_name", ""),
            })
            if existing_key == dedup_key:
                return ev
        return None

    def _check_event_change(self, existing: dict, new: EventRecord, evidence: SourceEvidence) -> None:
        """イベントの変更（キャンセル・日時変更）を検知する"""
        changes = []
        if existing.get("status") != new.status and new.status in ("cancelled", "postponed"):
            changes.append(f"ステータス変更: {existing.get('status')} → {new.status}")
        if existing.get("starts_at", "")[:16] != new.starts_at[:16]:
            changes.append(f"開始時刻変更: {existing.get('starts_at')} → {new.starts_at}")

        if changes:
            self.store.upsert("source_evidence", evidence.to_dict())
            for field, val in [("status", new.status), ("starts_at", new.starts_at), ("ends_at", new.ends_at)]:
                self.store.update_field("event_records", existing["id"], field, val)
            print(f"[{AGENT_TYPE}] イベント変更検知: {existing.get('title')} - {changes}")

    def _generate_recommendations(self, store_profile: dict, lookahead_days: int) -> int:
        """全イベントに対して、cafe/delivery両方の提案を生成する"""
        now = datetime.now(TZ_TOKYO)
        cutoff = now + timedelta(days=lookahead_days)
        count = 0
        business_units = []
        bu = store_profile.get("business_unit", "both")
        if bu == "both":
            business_units = ["cafe", "delivery"]
        else:
            business_units = [bu]

        for event in self.store.list_all("event_records"):
            if event.get("status") in ("cancelled",):
                continue
            starts_at = parse_iso(event.get("starts_at", ""))
            if starts_at is None or starts_at > cutoff:
                continue
            if starts_at < now - timedelta(days=1):
                continue

            for unit in business_units:
                score = score_event(event, store_profile, unit)
                if score["total"] < 20:
                    continue

                count += self._create_recommendations_for_event(event, store_profile, unit, score)

        return count

    def _create_recommendations_for_event(
        self, event: dict, store: dict, business_unit: str, score: dict
    ) -> int:
        """1イベント分の提案を生成・保存する"""
        created = 0

        if self.llm and config.is_llm_available():
            suggestions = self.llm.generate_event_recommendations(event, store, business_unit, score)
        else:
            suggestions = self._rule_based_suggestions(event, store, business_unit, score)

        for s in suggestions:
            rec_id = f"rec_{uuid.uuid4().hex[:8]}"
            rec = Recommendation(
                id=rec_id,
                agent_type=AGENT_TYPE,
                store_id=store["id"],
                business_unit=business_unit,
                category=s.get("category", "promotion"),
                title=s.get("title", ""),
                summary=s.get("summary", ""),
                reason=s.get("reason", ""),
                evidence_ids=[event.get("source_evidence_id", "")],
                confidence=score["total"] / 100,
                estimated_impact=s.get("estimated_impact", "medium"),
                effort=s.get("effort", "medium"),
                urgency=s.get("urgency", "medium"),
                recommended_start_at=_days_before(event.get("starts_at", ""), 3),
                recommended_end_at=event.get("ends_at", "") or event.get("starts_at", ""),
                status="draft",
                approval_required=True,
                source_ref=event.get("id", ""),
                created_at=now_jst_iso(),
                updated_at=now_jst_iso(),
            )
            self.store.upsert("recommendations", rec.to_dict())
            created += 1

        # CreativeBriefを生成（SNS動画広告との連携点）
        if score["total"] >= 50 and self.llm and config.is_llm_available():
            brief_data = self.llm.generate_creative_brief(event, store, business_unit)
            if brief_data:
                brief_id = f"brief_{uuid.uuid4().hex[:8]}"
                brief = CreativeBrief(
                    id=brief_id,
                    store_id=store["id"],
                    business_unit=business_unit,
                    event_id=event.get("id", ""),
                    campaign_goal=brief_data.get("campaign_goal", ""),
                    target_audience=brief_data.get("target_audience", ""),
                    recommended_product=brief_data.get("recommended_product", ""),
                    offer=brief_data.get("offer", ""),
                    key_message=brief_data.get("key_message", ""),
                    opening_hook=brief_data.get("opening_hook", ""),
                    call_to_action=brief_data.get("call_to_action", ""),
                    tone=brief_data.get("tone", ""),
                    asset_requirements=brief_data.get("asset_requirements", {}),
                    source_evidence_ids=[event.get("source_evidence_id", "")],
                    confidence=score["total"] / 100,
                    status="draft",
                    created_at=now_jst_iso(),
                )
                self.store.upsert("creative_briefs", brief.to_dict())

        # 一時運用手順書（マニュアル機能との連携点）
        if score["total"] >= 60 and self.llm and config.is_llm_available():
            playbook = self.llm.generate_temporary_playbook(event, store, business_unit)
            if playbook:
                pb = {
                    "id": f"pb_{uuid.uuid4().hex[:8]}",
                    "event_id": event.get("id", ""),
                    "store_id": store["id"],
                    "business_unit": business_unit,
                    "status": "draft",
                    "content": playbook,
                    "created_at": now_jst_iso(),
                }
                self.store.upsert("temporary_playbooks", pb)

        return created

    def _rule_based_suggestions(self, event: dict, store: dict, business_unit: str, score: dict) -> list[dict]:
        """LLMが使えない場合のルールベース提案（必ず最低限の提案を生成）"""
        category = event.get("category", "")
        title = event.get("title", "").replace("[DEMO] ", "")
        starts_at = event.get("starts_at", "")[:16]
        scale = event.get("estimated_scale", "unknown")
        langs = event.get("languages", ["ja"])
        has_inbound = len(langs) > 1
        outdoor = event.get("indoor_or_outdoor", "unknown")
        weather_sens = event.get("weather_sensitivity", "unknown")

        suggestions = []

        if business_unit == "cafe":
            if category == "fireworks" or scale == "large":
                suggestions.append({
                    "category": "product",
                    "title": "テイクアウト商品の強化",
                    "summary": f"「{title}」開始前の時間帯に、テイクアウト抹茶ドリンクの種類と仕込み量を増やす。冷たい商品を前面に出す。",
                    "reason": f"大規模屋外イベントで来店・持ち歩き需要が増加する見込み",
                    "urgency": "high", "effort": "medium", "estimated_impact": "high",
                })
                suggestions.append({
                    "category": "sns",
                    "title": "イベント前SNS投稿計画",
                    "summary": f"イベント開始3時間前〜1時間前にSNS投稿。テイクアウト可・待ち時間短縮を訴求。",
                    "reason": "来場者のルート上に位置する場合、事前投稿でテイクアウト需要を取り込める",
                    "urgency": "medium", "effort": "low", "estimated_impact": "medium",
                })
                if has_inbound:
                    suggestions.append({
                        "category": "promotion",
                        "title": "英語メニューの準備",
                        "summary": "英語表記のメニューボードまたはメニュー表を準備する。",
                        "reason": "外国語来場者が想定されるため、英語対応で購入機会を逃さない",
                        "urgency": "medium", "effort": "low", "estimated_impact": "medium",
                    })
            elif category == "weather":
                if "猛暑" in title or "高温" in title or "35" in title or "32" in title:
                    suggestions.append({
                        "category": "product",
                        "title": "冷たい抹茶商品を前面に",
                        "summary": "抹茶フローズン・冷抹茶ラテなど冷たい商品をメニューの1番手に配置。仕込み量を1.5倍に増やす。",
                        "reason": "猛暑日は冷たい飲料の需要が顕著に増加する傾向あり",
                        "urgency": "high", "effort": "low", "estimated_impact": "high",
                    })
                elif "雨" in title:
                    suggestions.append({
                        "category": "promotion",
                        "title": "雨の日限定特典を検討",
                        "summary": "雨の日に来店した方への特典（ドリンクSサイズ無料等）を用意し、SNSで告知して来店を促進する。",
                        "reason": "雨天は来店客数減少が予想されるため、集客施策で補う",
                        "urgency": "medium", "effort": "low", "estimated_impact": "medium",
                    })
            elif category in ("concert", "sports", "festival"):
                suggestions.append({
                    "category": "staffing",
                    "title": "イベント日のスタッフ配置見直し",
                    "summary": f"「{title}」開催日のピーク時間帯（イベント前後）に合わせてスタッフを増員する。",
                    "reason": "近隣イベントによる来客増加に備えた人員配置",
                    "urgency": "medium", "effort": "medium", "estimated_impact": "medium",
                })
            else:
                suggestions.append({
                    "category": "promotion",
                    "title": "イベント連動販促の検討",
                    "summary": f"「{title}」に合わせた期間限定メニューまたはSNS投稿を検討する。",
                    "reason": "近隣イベントに連動した販促で認知度向上と来店促進を図る",
                    "urgency": "low", "effort": "low", "estimated_impact": "medium",
                })

        elif business_unit == "delivery":
            if category == "fireworks" or scale == "large":
                suggestions.append({
                    "category": "product",
                    "title": "イベント終了後のセット提案",
                    "summary": f"「{title}」終了後（20:30〜21:00以降）の注文増加に備えて、帰宅後需要向けセット（混ぜそば＋追い飯または温玉）を用意する。",
                    "reason": "大型屋外イベント後は帰宅者のデリバリー注文が増加する傾向がある（仮説）",
                    "urgency": "medium", "effort": "low", "estimated_impact": "high",
                })
                suggestions.append({
                    "category": "staffing",
                    "title": "ピーク時間の調理体制確認",
                    "summary": "終了後のピーク時間帯に調理負荷が集中するため、仕込み量を確認し、対応可能な商品数を事前に絞る基準を設ける。",
                    "reason": "調理キャパシティを超えると品質低下・注文キャンセルにつながる",
                    "urgency": "medium", "effort": "medium", "estimated_impact": "medium",
                })
            elif category == "weather":
                if "雨" in title:
                    suggestions.append({
                        "category": "promotion",
                        "title": "雨天デリバリー需要の活用",
                        "summary": "雨天は外出を避ける人が増えデリバリー注文が増加する可能性がある。仕込みを通常の1.2倍にし、SNSで告知する。",
                        "reason": "雨天時のデリバリー需要増加は可能性であり断定しないが、備えておく価値がある",
                        "urgency": "medium", "effort": "low", "estimated_impact": "medium",
                    })
            elif category in ("concert", "sports", "festival"):
                suggestions.append({
                    "category": "product",
                    "title": "ボリュームセットでの差別化",
                    "summary": f"「{title}」の観客向けに、ボリューム訴求セット（大盛り・追い飯・トッピング自由）をデリバリーアプリで目立たせる。",
                    "reason": "スポーツ・ライブ後は満足感・ボリュームを求める傾向がある",
                    "urgency": "low", "effort": "low", "estimated_impact": "medium",
                })
            else:
                suggestions.append({
                    "category": "promotion",
                    "title": "デリバリー需要の事前確認",
                    "summary": f"「{title}」が配達エリア内の顧客に影響する場合、デリバリーアプリでの露出強化を検討する。",
                    "reason": "近隣イベントに連動したデリバリー需要の取り込み",
                    "urgency": "low", "effort": "low", "estimated_impact": "low",
                })

        return suggestions[:5]

    def get_promotional_calendar(
        self, store_id: str, days: int = 30, business_unit: str = None
    ) -> list[dict]:
        """販促カレンダーデータを返す"""
        now = datetime.now(TZ_TOKYO)
        cutoff = now + timedelta(days=days)
        events = []

        store_profile = self.store.get("store_profiles", store_id)
        if not store_profile:
            return []

        for event in self.store.list_all("event_records"):
            if event.get("status") == "cancelled":
                continue
            starts_at = parse_iso(event.get("starts_at", ""))
            if starts_at is None:
                continue
            if starts_at > cutoff or starts_at < now - timedelta(hours=24):
                continue

            # 店舗にひも付いた提案を集める
            recs = [
                r for r in self.store.filter("recommendations", store_id=store_id, source_ref=event.get("id", ""))
                if (business_unit is None or r.get("business_unit") == business_unit)
            ]

            score = score_event(event, store_profile, business_unit or store_profile.get("business_unit", "cafe"))

            events.append({
                "event": event,
                "score": score,
                "recommendations": recs,
                "days_until": (starts_at - now).days,
            })

        events.sort(key=lambda x: (x["days_until"], -x["score"]["total"]))
        return events


def _days_before(dt_str: str, days: int) -> str:
    dt = parse_iso(dt_str)
    if dt is None:
        return ""
    return (dt - timedelta(days=days)).isoformat()
