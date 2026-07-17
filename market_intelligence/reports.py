"""
HTMLレポート生成モジュール。
既存の docs/timeblock.html と同じスタイルで管理画面を生成する。
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from .utils import format_jst, now_jst_iso, days_until

TZ_TOKYO = ZoneInfo("Asia/Tokyo")


def generate_dashboard_html(store, event_agent, competitor_agent, store_profile: dict) -> str:
    store_id = store_profile["id"]
    store_name = store_profile.get("name", store_id)
    bu = store_profile.get("business_unit", "both")
    now = datetime.now(TZ_TOKYO).strftime("%Y/%m/%d %H:%M")

    # データ収集
    cal_30 = event_agent.get_promotional_calendar(store_id, days=30)
    cal_7 = [e for e in cal_30 if e["days_until"] <= 7]
    all_recs = [r for r in store.list_all("recommendations") if r.get("store_id") == store_id]
    draft_recs = [r for r in all_recs if r.get("status") == "draft"]
    high_urgency = [r for r in all_recs if r.get("urgency") == "high" and r.get("status") == "draft"]
    competitors = store.list_all("competitor_profiles")
    recent_diffs = []
    for c in competitors:
        diff = competitor_agent.get_latest_diff(c["id"])
        if diff and diff.get("has_changes"):
            recent_diffs.append((c, diff))
    high_diffs = [d for d in recent_diffs if d[1].get("severity") == "high"]

    # Agent実行履歴
    runs = sorted(store.list_all("agent_runs"), key=lambda r: r.get("started_at",""), reverse=True)
    last_event_run = next((r for r in runs if r["agent_type"] == "local_event_promotion"), None)
    last_comp_run = next((r for r in runs if r["agent_type"] == "competitor_monitoring"), None)

    is_demo = any("[DEMO]" in store_name for _ in [1])
    demo_banner = '<div class="demo-banner">⚠ このレポートはDEMOデータです。実在する店舗・競合ではありません。</div>' if is_demo else ""

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Local Market Intelligence - {store_name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Hiragino Kaku Gothic ProN', 'Meiryo', sans-serif; background: #f5f5f5; color: #333; }}
  .header {{ background: #1a1a2e; color: #fff; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 18px; }}
  .header .meta {{ font-size: 12px; opacity: 0.7; }}
  .demo-banner {{ background: #ff6b35; color: #fff; text-align: center; padding: 8px; font-size: 13px; font-weight: bold; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
  .dashboard {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
  .card .num {{ font-size: 32px; font-weight: bold; color: #1a1a2e; }}
  .card .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
  .card.alert {{ border-left: 4px solid #e74c3c; }}
  .card.warn {{ border-left: 4px solid #f39c12; }}
  .card.ok {{ border-left: 4px solid #27ae60; }}
  .section {{ background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
  .section h2 {{ font-size: 16px; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #1a1a2e; }}
  .event-item {{ border-left: 4px solid #3498db; padding: 12px 16px; margin-bottom: 12px; background: #f8f9fa; border-radius: 0 6px 6px 0; }}
  .event-item.high {{ border-color: #e74c3c; }}
  .event-item.medium {{ border-color: #f39c12; }}
  .event-item .event-title {{ font-weight: bold; margin-bottom: 4px; }}
  .event-item .event-meta {{ font-size: 12px; color: #666; margin-bottom: 8px; }}
  .rec-item {{ padding: 10px 14px; margin-bottom: 8px; border-radius: 6px; border: 1px solid #e0e0e0; }}
  .rec-item.cafe {{ background: #e8f5e9; border-color: #4caf50; }}
  .rec-item.delivery {{ background: #fff3e0; border-color: #ff9800; }}
  .rec-item .rec-title {{ font-weight: bold; font-size: 14px; }}
  .rec-item .rec-summary {{ font-size: 12px; color: #555; margin-top: 4px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; margin-right: 4px; }}
  .badge.high {{ background: #e74c3c; color: #fff; }}
  .badge.medium {{ background: #f39c12; color: #fff; }}
  .badge.low {{ background: #95a5a6; color: #fff; }}
  .badge.cafe {{ background: #27ae60; color: #fff; }}
  .badge.delivery {{ background: #e67e22; color: #fff; }}
  .badge.draft {{ background: #3498db; color: #fff; }}
  .score-bar {{ display: inline-block; width: 80px; height: 8px; background: #e0e0e0; border-radius: 4px; vertical-align: middle; margin-left: 8px; }}
  .score-fill {{ height: 100%; border-radius: 4px; background: linear-gradient(90deg, #27ae60, #f39c12, #e74c3c); }}
  .diff-item {{ padding: 10px; margin-bottom: 8px; background: #fff9f0; border-radius: 6px; border: 1px solid #f39c12; }}
  .diff-item.high {{ background: #fff0f0; border-color: #e74c3c; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #e0e0e0; font-size: 13px; }}
  th {{ background: #f5f5f5; font-weight: bold; }}
  .status-ok {{ color: #27ae60; }}
  .status-err {{ color: #e74c3c; }}
  .tabs {{ display: flex; gap: 4px; margin-bottom: 20px; }}
  .tab-btn {{ padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; background: #e0e0e0; color: #333; }}
  .tab-btn.active {{ background: #1a1a2e; color: #fff; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
  .approve-btn {{ background: #27ae60; color: #fff; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; margin-right: 4px; }}
  .reject-btn {{ background: #e74c3c; color: #fff; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }}
</style>
</head>
<body>
<div class="header">
  <h1>📊 Local Market Intelligence</h1>
  <div class="meta">{store_name} | {bu} | {now} 生成</div>
</div>
{demo_banner}
<div class="container">

  <!-- ダッシュボード -->
  <div class="dashboard">
    <div class="card {'alert' if len(cal_7) > 0 else 'ok'}">
      <div class="num">{len(cal_7)}</div>
      <div class="label">直近7日の重要イベント</div>
    </div>
    <div class="card {'alert' if len(draft_recs) > 5 else 'warn'}">
      <div class="num">{len(draft_recs)}</div>
      <div class="label">未承認の提案</div>
    </div>
    <div class="card {'alert' if len(high_diffs) > 0 else 'ok'}">
      <div class="num">{len(high_diffs)}</div>
      <div class="label">競合の重要変化</div>
    </div>
    <div class="card ok">
      <div class="num">{len(competitors)}</div>
      <div class="label">監視中の競合</div>
    </div>
    <div class="card ok">
      <div class="num">{len(high_urgency)}</div>
      <div class="label">緊急対応が必要な提案</div>
    </div>
  </div>

  <!-- タブ -->
  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('calendar')">📅 販促カレンダー</button>
    <button class="tab-btn" onclick="showTab('competitor')">🔍 競合モニタリング</button>
    <button class="tab-btn" onclick="showTab('recommendations')">💡 提案管理</button>
    <button class="tab-btn" onclick="showTab('status')">⚙ Agent状態</button>
  </div>

  <!-- タブ: 販促カレンダー -->
  <div id="tab-calendar" class="tab-content active">
    <div class="section">
      <h2>📅 販促カレンダー（30日間）</h2>
      {_render_calendar(cal_30)}
    </div>
  </div>

  <!-- タブ: 競合モニタリング -->
  <div id="tab-competitor" class="tab-content">
    <div class="section">
      <h2>🔍 競合モニタリング</h2>
      {_render_competitors(competitors, competitor_agent)}
    </div>
  </div>

  <!-- タブ: 提案管理 -->
  <div id="tab-recommendations" class="tab-content">
    <div class="section">
      <h2>💡 提案一覧</h2>
      <p style="font-size:12px;color:#666;margin-bottom:12px;">
        承認後も外部投稿・価格変更は自動実行されません。手動で対応してください。<br>
        CLIで承認: <code>python3 cli.py recommend approve --id &lt;id&gt;</code>
      </p>
      {_render_recommendations(all_recs)}
    </div>
  </div>

  <!-- タブ: Agent状態 -->
  <div id="tab-status" class="tab-content">
    <div class="section">
      <h2>⚙ Agent実行状態</h2>
      {_render_status(last_event_run, last_comp_run, runs[:10])}
    </div>
  </div>

</div>

<script>
function showTab(name) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}
</script>
</body>
</html>"""
    return html


def _render_calendar(cal: list) -> str:
    if not cal:
        return "<p>該当するイベントがありません。<code>python3 cli.py event run --store &lt;id&gt;</code>でデータを取得してください。</p>"
    parts = []
    for entry in cal:
        ev = entry["event"]
        score = entry["score"]
        recs = entry["recommendations"]
        days = entry["days_until"]
        level = "high" if score["total"] >= 70 else "medium" if score["total"] >= 40 else ""
        score_pct = min(100, score["total"])

        rec_html = ""
        for r in recs[:3]:
            badge_class = "cafe" if r.get("business_unit") == "cafe" else "delivery"
            rec_html += f'<div class="rec-item {badge_class}" style="margin-top:8px"><span class="badge {badge_class}">{r.get("business_unit","")}</span><span class="badge {r.get("urgency","low")}">{r.get("urgency","?")}</span> <span class="rec-title">{r["title"]}</span><div class="rec-summary">{r.get("summary","")[:80]}</div></div>'

        scale = ev.get("estimated_scale","?")
        dist = f"{ev.get('distance_from_store_km', '?')}km" if ev.get("distance_from_store_km") else "距離不明"
        parts.append(f"""
<div class="event-item {level}">
  <div class="event-title">{ev['title']}</div>
  <div class="event-meta">
    {format_jst(ev.get('starts_at',''))} ～ {format_jst(ev.get('ends_at',''))} |
    {days}日後 | {ev.get('venue_name','会場不明')} | {dist} | 規模:{scale}
    <span class="score-bar"><span class="score-fill" style="width:{score_pct}%"></span></span>
    スコア {score['total']}/100
  </div>
  {f'<div style="font-size:11px;color:#888">{ev.get("status","?")}</div>' if ev.get("status","confirmed") != "confirmed" else ""}
  {rec_html if rec_html else '<p style="font-size:12px;color:#aaa;margin-top:8px">提案なし（スコアが低いため）</p>'}
</div>""")
    return "\n".join(parts)


def _render_competitors(competitors: list, competitor_agent) -> str:
    if not competitors:
        return "<p>競合が登録されていません。<code>python3 cli.py competitor add</code>で登録してください。</p>"
    rows = []
    for c in competitors:
        diff = competitor_agent.get_latest_diff(c["id"])
        severity_badge = ""
        diff_detail = "前回との差分なし"
        if diff and diff.get("has_changes"):
            sev = diff.get("severity", "low")
            severity_badge = f'<span class="badge {sev}">{sev}</span>'
            parts = []
            for pc in diff.get("price_changes", [])[:2]:
                parts.append(f"価格: {pc['item_name']} {pc['previous_price']}→{pc['current_price']}円 ({pc.get('change_rate_pct',0):+.1f}%)")
            for ni in diff.get("new_items", [])[:2]:
                parts.append(f"新商品: {ni.get('name','?')}")
            for hc in diff.get("opening_hours_changes", [])[:1]:
                parts.append(f"営業時間変更: {hc.get('previous',{})}.get('close','?') → {hc.get('current',{}).get('close','?')}")
            diff_detail = " / ".join(parts) if parts else "変化あり"

        rows.append(f"""
<div class="diff-item {diff.get('severity','low') if diff and diff.get('has_changes') else ''}">
  <strong>[{c['business_unit']}] {c['name']}</strong> {severity_badge}
  <span style="font-size:12px;color:#666"> | 監視: {'有効' if c.get('monitoring_enabled') else '無効'} | 距離: {c.get('distance_from_store_km','?')}km</span>
  <div style="font-size:12px;margin-top:4px;color:#555">{diff_detail}</div>
</div>""")
    return "\n".join(rows)


def _render_recommendations(recs: list) -> str:
    if not recs:
        return "<p>提案がありません。</p>"
    parts = []
    for r in sorted(recs, key=lambda x: (x.get("urgency","low") == "high", x.get("created_at",""))[::-1])[:20]:
        badge_class = "cafe" if r.get("business_unit") == "cafe" else "delivery"
        status_badge = f'<span class="badge draft">{r.get("status","?")}</span>'
        parts.append(f"""
<div class="rec-item {badge_class}">
  <div>
    <span class="badge {badge_class}">{r.get("business_unit","")}</span>
    <span class="badge {r.get('urgency','low')}">{r.get('urgency','low')}</span>
    {status_badge}
    <span class="rec-title">{r['title']}</span>
  </div>
  <div class="rec-summary">{r.get('summary','')[:120]}</div>
  <div style="font-size:11px;color:#999;margin-top:4px">ID: {r['id']} | {r.get('created_at','')[:10]}</div>
  <div style="margin-top:6px">
    <code style="font-size:11px">python3 cli.py recommend approve --id {r['id']}</code>
  </div>
</div>""")
    return "\n".join(parts)


def _render_status(last_event_run, last_comp_run, recent_runs: list) -> str:
    def run_row(run):
        if not run:
            return "<tr><td colspan=5>実行履歴なし</td></tr>"
        status_cls = "status-ok" if run.get("status") == "success" else "status-err"
        return f"<tr><td>{run.get('agent_type','')}</td><td>{run.get('store_id','')}</td><td class='{status_cls}'>{run.get('status','')}</td><td>{run.get('started_at','')[:16]}</td><td>{run.get('error_summary','') or '-'}</td></tr>"

    rows = "".join(run_row(r) for r in recent_runs)
    return f"""
<table>
<tr><th>Agent</th><th>店舗</th><th>状態</th><th>実行日時</th><th>エラー</th></tr>
{rows}
</table>
<p style="font-size:12px;color:#666;margin-top:12px">
  手動実行: <code>python3 cli.py event run --store &lt;id&gt;</code><br>
  定期実行設定: <code>market-intelligence/scheduler/cron_setup.sh</code>
</p>"""
