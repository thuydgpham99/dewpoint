"""Weather lookup via Open-Meteo.

Open-Meteo is free and requires no API key, which keeps the project inside the
assignment's rule that only PORTKEY_API_KEY and OPENAI_API_KEY may appear.

Every lookup falls back to a bundled fixture so the app still runs with no
network. Set DEWPOINT_OFFLINE=1 to force fixture mode.
"""
import json
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
FIXTURES = json.loads((DATA_DIR / "sample_days.json").read_text())

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 6


def _ssl_context():
    """Build an SSL context that actually has root certificates.

    The python.org macOS installer ships its own OpenSSL with an empty trust
    store unless "Install Certificates.command" has been run, so urllib fails
    HTTPS verification on a machine where curl works fine. certifi is already
    present as an openai dependency, so we point at its bundle and fall back to
    the system default elsewhere.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CONTEXT = _ssl_context()


def _get(url: str, params: dict) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full, headers={"User-Agent": "DewPoint/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode())


def fixture_for(city: str) -> dict:
    """Nearest bundled sample, or the first one."""
    key = city.strip().lower()
    for name, payload in FIXTURES.items():
        if key and (key in name.lower() or name.lower().startswith(key[:4])):
            return dict(payload, source="bundled sample (offline)")
    first = next(iter(FIXTURES.values()))
    return dict(first, source="bundled sample (offline)")


def fetch(city: str) -> dict:
    """Return the normalised fields the climate engine needs."""
    if os.getenv("DEWPOINT_OFFLINE") == "1":
        return fixture_for(city)

    try:
        geo = _get(GEOCODE_URL, {"name": city, "count": 1, "language": "en", "format": "json"})
        results = geo.get("results") or []
        if not results:
            return fixture_for(city)
        place = results[0]

        fc = _get(FORECAST_URL, {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m,dew_point_2m,"
                       "precipitation,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,uv_index_max,precipitation_sum",
            "timezone": "auto",
            "forecast_days": 1,
        })
        cur = fc["current"]
        daily = fc["daily"]

        label = place["name"]
        if place.get("admin1"):
            label += f", {place['admin1']}"
        if place.get("country_code"):
            label += f" ({place['country_code']})"

        return {
            "location": label,
            "temp_c": cur["temperature_2m"],
            "temp_min_c": daily["temperature_2m_min"][0],
            "temp_max_c": daily["temperature_2m_max"][0],
            "dew_point_c": cur["dew_point_2m"],
            "outdoor_rh": cur["relative_humidity_2m"],
            "uv_index": daily["uv_index_max"][0] or 0.0,
            "precip_mm": daily["precipitation_sum"][0] or 0.0,
            "wind_kph": cur["wind_speed_10m"],
            "source": "Open-Meteo (live)",
        }
    except Exception as exc:  # network down, bad city, API change
        fb = fixture_for(city)
        fb["source"] = f"bundled sample (live lookup failed: {type(exc).__name__})"
        return fb
