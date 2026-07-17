"""
ユーティリティ関数。
距離計算・ハッシュ・日時処理などはLLMに任せず、決定論的に処理する。
"""
from __future__ import annotations
import hashlib
import math
import json
import urllib.request
import urllib.parse
import ssl
from datetime import datetime, date
from typing import Optional
from zoneinfo import ZoneInfo

TZ_TOKYO = ZoneInfo("Asia/Tokyo")

# ジオコーディング結果のメモリキャッシュ（同じ住所を繰り返し叩かない）
_geocode_cache: dict[str, Optional[tuple[float, float]]] = {}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の距離をキロメートルで返す（ハバースイン公式）"""
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """2点間の直線距離をメートルで返す（四捨五入）"""
    return round(haversine(lat1, lon1, lat2, lon2) * 1000)


def now_jst() -> datetime:
    return datetime.now(TZ_TOKYO)


def now_jst_iso() -> str:
    return datetime.now(TZ_TOKYO).isoformat()


def content_hash(data: dict | str) -> str:
    if isinstance(data, dict):
        s = json.dumps(data, sort_keys=True, ensure_ascii=False)
    else:
        s = str(data)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_TOKYO)
        return dt
    except ValueError:
        return None


def days_until(dt_str: str) -> Optional[int]:
    """指定日時まで何日かを返す。nullまたは過去の場合はNone"""
    dt = parse_iso(dt_str)
    if dt is None:
        return None
    delta = dt - now_jst()
    if delta.days < 0:
        return None
    return delta.days


def format_jst(dt_str: str, fmt: str = "%Y/%m/%d %H:%M") -> str:
    dt = parse_iso(dt_str)
    if dt is None:
        return ""
    return dt.astimezone(TZ_TOKYO).strftime(fmt)


def price_change_rate(prev: int, curr: int) -> float:
    """価格変更率（%）を計算する"""
    if prev == 0:
        return 0.0
    return round((curr - prev) / prev * 100, 1)


def geocode(address: str) -> Optional[tuple[float, float]]:
    """
    住所から緯度経度を取得する。
    GEOCODING_PROVIDER=google のとき Google Maps Geocoding API を使用する。
    APIキーがない・住所が空の場合は None を返す（アプリをクラッシュさせない）。
    結果はメモリキャッシュに保存して同じ住所への再呼び出しを防ぐ。
    """
    from . import config as cfg

    if not address:
        return None

    # キャッシュヒット
    if address in _geocode_cache:
        return _geocode_cache[address]

    result = None

    if cfg.GEOCODING_PROVIDER == "google" and cfg.GEOCODING_API_KEY:
        result = _geocode_google(address, cfg.GEOCODING_API_KEY)
    elif cfg.GEOCODING_PROVIDER == "nominatim":
        result = _geocode_nominatim(address)
    else:
        if cfg.GEOCODING_PROVIDER not in ("none", ""):
            print(f"[geocode] GEOCODING_API_KEY が未設定のためスキップ (provider={cfg.GEOCODING_PROVIDER})")

    _geocode_cache[address] = result
    return result


def _geocode_google(address: str, api_key: str) -> Optional[tuple[float, float]]:
    """Google Maps Geocoding API を呼び出して (lat, lon) を返す"""
    base = "https://maps.googleapis.com/maps/api/geocode/json"
    params = urllib.parse.urlencode({"address": address, "key": api_key, "language": "ja"})
    url = f"{base}?{params}"

    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "cafe-reform-market-intelligence/1.0"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read(1024 * 64).decode("utf-8"))

        if data.get("status") != "OK":
            print(f"[geocode] Google Maps エラー: {data.get('status')} address={address[:40]}")
            return None

        loc = data["results"][0]["geometry"]["location"]
        lat, lon = float(loc["lat"]), float(loc["lng"])
        print(f"[geocode] {address[:40]} → ({lat:.4f}, {lon:.4f})")
        return lat, lon

    except Exception as e:
        print(f"[geocode] 取得失敗: {e}")
        return None


def _geocode_nominatim(address: str) -> Optional[tuple[float, float]]:
    """OpenStreetMap Nominatim で (lat, lon) を返す（無料・APIキー不要）。
    日本の住所はビル名・番地を段階的に省略しながらリトライする。
    """
    import re
    import time

    candidates = [address]
    # ビル名を除去（番地の数字パターン以降を削る）
    stripped = re.sub(r"([０-９0-9]+[丁－\-][０-９0-9]+).*$", r"\1", address)
    if stripped != address:
        candidates.append(stripped)
    # 番地ごと除去（丁目までに短縮）
    chome = re.sub(r"[０-９0-9]+[丁－\-].*$", "", address).rstrip()
    if chome not in candidates:
        candidates.append(chome)

    ctx = ssl.create_default_context()
    for q in candidates:
        if not q:
            continue
        params = urllib.parse.urlencode({"q": q, "format": "json", "limit": 1, "accept-language": "ja"})
        url = f"https://nominatim.openstreetmap.org/search?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cafe-reform-market-intelligence/1.0 (yk0805shiba@gmail.com)"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read(1024 * 64).decode("utf-8"))
            if data:
                lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
                print(f"[geocode] {q[:40]} → ({lat:.4f}, {lon:.4f})")
                return lat, lon
            time.sleep(1)  # Nominatim利用規約: 1リクエスト/秒
        except Exception as e:
            print(f"[geocode] Nominatim 取得失敗: {e}")
            return None

    print(f"[geocode] Nominatim: 結果なし address={address[:40]}")
    return None


def geocode_if_missing(address: str, lat: Optional[float], lon: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    """緯度経度が未設定の場合のみジオコーディングを実行する"""
    if lat is not None and lon is not None:
        return lat, lon
    result = geocode(address)
    if result:
        return result
    return None, None
