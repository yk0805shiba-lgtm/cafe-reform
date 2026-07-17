"""
Configuration loader. Reads from environment variables (set in .env or shell).
Never hard-codes secrets. Missing optional keys degrade gracefully.
"""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ── 基本設定 ──────────────────────────────────────────────────────────────────
DEMO_MODE: bool = os.getenv("LOCAL_INTELLIGENCE_DEMO_MODE", "false").lower() in ("1", "true", "yes")
ENABLED: bool = os.getenv("LOCAL_INTELLIGENCE_ENABLED", "true").lower() in ("1", "true", "yes")
TIMEZONE: str = os.getenv("LOCAL_INTELLIGENCE_TIMEZONE", "Asia/Tokyo")

# ── イベントAgent設定 ──────────────────────────────────────────────────────────
EVENT_AGENT_ENABLED: bool = os.getenv("LOCAL_EVENT_AGENT_ENABLED", "true").lower() in ("1", "true", "yes")
EVENT_LOOKAHEAD_DAYS: int = int(os.getenv("LOCAL_EVENT_LOOKAHEAD_DAYS", "90"))
EVENT_DEFAULT_RADIUS_KM: float = float(os.getenv("LOCAL_EVENT_DEFAULT_RADIUS_KM", "3.0"))
EVENT_SCHEDULE: str = os.getenv("LOCAL_EVENT_SCHEDULE", "0 6 * * *")

# ── 競合Agent設定 ──────────────────────────────────────────────────────────────
COMPETITOR_AGENT_ENABLED: bool = os.getenv("COMPETITOR_AGENT_ENABLED", "true").lower() in ("1", "true", "yes")
COMPETITOR_MONITOR_SCHEDULE: str = os.getenv("COMPETITOR_MONITOR_SCHEDULE", "0 8 * * *")
COMPETITOR_PRICE_CHANGE_HIGH_THRESHOLD: float = float(
    os.getenv("COMPETITOR_PRICE_CHANGE_HIGH_THRESHOLD", "10.0")
)
COMPETITOR_PRICE_CHANGE_MEDIUM_THRESHOLD: float = float(
    os.getenv("COMPETITOR_PRICE_CHANGE_MEDIUM_THRESHOLD", "5.0")
)

# ── 天気プロバイダー ───────────────────────────────────────────────────────────
WEATHER_PROVIDER: str = os.getenv("WEATHER_PROVIDER", "none")
WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")

# ── ジオコーディング ──────────────────────────────────────────────────────────
GEOCODING_PROVIDER: str = os.getenv("GEOCODING_PROVIDER", "none")
GEOCODING_API_KEY: str = os.getenv("GEOCODING_API_KEY", "")

# ── LLM設定 ───────────────────────────────────────────────────────────────────
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "anthropic")
LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# ── ストレージパス ─────────────────────────────────────────────────────────────
DATA_DIR: Path = Path(os.getenv("LOCAL_INTELLIGENCE_DATA_DIR", str(ROOT / "data")))
REPORTS_DIR: Path = Path(os.getenv("LOCAL_INTELLIGENCE_REPORTS_DIR", str(ROOT / "reports_output")))
FIXTURES_DIR: Path = ROOT / "fixtures"

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def validate_api_keys() -> list[str]:
    """必須APIキーが欠けている場合の警告リストを返す（アプリはクラッシュさせない）"""
    warnings = []
    if LLM_PROVIDER == "anthropic" and not LLM_API_KEY:
        warnings.append("ANTHROPIC_API_KEY が未設定です。LLM機能はスキップされます。")
    if WEATHER_PROVIDER not in ("none", "") and not WEATHER_API_KEY:
        warnings.append(f"WEATHER_API_KEY が未設定です（provider={WEATHER_PROVIDER}）。天気データはスキップされます。")
    if GEOCODING_PROVIDER not in ("none", "") and not GEOCODING_API_KEY:
        warnings.append(f"GEOCODING_API_KEY が未設定です（provider={GEOCODING_PROVIDER}）。")
    return warnings


def is_llm_available() -> bool:
    return bool(LLM_API_KEY) and LLM_PROVIDER == "anthropic"
