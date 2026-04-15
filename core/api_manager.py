"""
ynotPi — core/api_manager.py
-----------------------------
Loads API keys from config/secrets.env and exposes simple
fetch functions for each service. Import this anywhere in
the app to grab live data without worrying about keys or URLs.

Usage:
    from core.api_manager import get_weather, get_crypto_price, get_news, get_apod

All functions return a dict on success, or None if something goes wrong
(missing key, network error, bad response, etc.) — callers should
always check for None before using the result.
"""

import os
import json
import urllib.request
import urllib.parse
from pathlib import Path


# ─── LOAD SECRETS ──────────────────────────────────────────────────────────────

def _load_secrets():
    # find secrets.env relative to this file — works wherever the repo is cloned
    secrets_path = Path(__file__).parent.parent / "config" / "secrets.env"

    if not secrets_path.exists():
        print("[API] secrets.env not found — run scripts/setup_keys.sh first!")
        return {}

    secrets = {}
    with open(secrets_path) as f:
        for line in f:
            line = line.strip()
            # skip blank lines and comments
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                secrets[key.strip()] = value.strip()

    return secrets


# load once when the module is imported — no need to re-read the file every call
_SECRETS = _load_secrets()


def _get_key(name):
    # grab a key from the loaded secrets — warn clearly if it's missing or blank
    value = _SECRETS.get(name, "")
    if not value:
        print(f"[API] '{name}' is not set in secrets.env — skipping this call.")
        return None
    return value


# ─── SHARED HTTP HELPER ────────────────────────────────────────────────────────

def _fetch(url, params=None):
    # build the full URL with query params if provided
    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except Exception as e:
        print(f"[API] Request failed for {url} — {e}")
        return None


# ─── OPENWEATHER ───────────────────────────────────────────────────────────────

def get_weather(city="Sydney", units="metric"):
    """
    Fetch current weather for a city.
    units: 'metric' (°C), 'imperial' (°F), 'standard' (K)

    Returns a dict like:
    {
        "city": "Sydney",
        "temp": 22.4,
        "feels_like": 21.0,
        "description": "light rain",
        "humidity": 78,
        "icon": "10d"
    }
    """
    key = _get_key("OPENWEATHER_API_KEY")
    if not key:
        return None

    data = _fetch("https://api.openweathermap.org/data/2.5/weather", {
        "q": city,
        "appid": key,
        "units": units,
    })

    if not data or data.get("cod") != 200:
        print(f"[API] OpenWeather returned an error: {data}")
        return None

    # pull out just the bits we actually care about
    return {
        "city":        data["name"],
        "temp":        data["main"]["temp"],
        "feels_like":  data["main"]["feels_like"],
        "description": data["weather"][0]["description"],
        "humidity":    data["main"]["humidity"],
        "icon":        data["weather"][0]["icon"],  # e.g. "10d" — use with icon URL below
        # icon URL: f"https://openweathermap.org/img/wn/{icon}@2x.png"
    }


# ─── COINGECKO ─────────────────────────────────────────────────────────────────

def get_crypto_price(coin_ids="bitcoin,ethereum", currency="aud"):
    """
    Fetch current prices for one or more coins.
    coin_ids: comma-separated CoinGecko IDs (e.g. 'bitcoin,ethereum,solana')
    currency: target currency code (e.g. 'aud', 'usd', 'eur')

    Returns a dict like:
    {
        "bitcoin": {"aud": 98432.11, "aud_24h_change": 2.34},
        "ethereum": {"aud": 5120.45, "aud_24h_change": -1.12},
    }

    Note: CoinGecko's free tier doesn't need an API key — the key just
    unlocks higher rate limits on the pro plan.
    """
    key = _get_key("COINGECKO_API_KEY")  # None is fine here — free tier works without it

    params = {
        "ids": coin_ids,
        "vs_currencies": currency,
        "include_24hr_change": "true",
    }

    # pro endpoint needs the key in the header — but for free tier we just add it as a param if present
    url = "https://api.coingecko.com/api/v3/simple/price"
    if key:
        params["x_cg_pro_api_key"] = key

    data = _fetch(url, params)

    if not data:
        return None

    return data  # already in a clean format: {coin_id: {currency: price, currency_24h_change: pct}}


# ─── NEWS API ──────────────────────────────────────────────────────────────────

def get_news(country="au", category="general", page_size=5):
    """
    Fetch top headlines.
    country: two-letter country code (e.g. 'au', 'us', 'gb')
    category: one of business, entertainment, general, health, science, sports, technology
    page_size: how many articles to return (max 100)

    Returns a list of dicts like:
    [
        {"title": "...", "source": "ABC News", "url": "https://...", "published": "2026-04-15T..."},
        ...
    ]
    """
    key = _get_key("NEWS_API_KEY")
    if not key:
        return None

    data = _fetch("https://newsapi.org/v2/top-headlines", {
        "country":  country,
        "category": category,
        "pageSize": page_size,
        "apiKey":   key,
    })

    if not data or data.get("status") != "ok":
        print(f"[API] News API error: {data}")
        return None

    # flatten to just what's useful
    articles = []
    for a in data.get("articles", []):
        articles.append({
            "title":     a.get("title", ""),
            "source":    a.get("source", {}).get("name", ""),
            "url":       a.get("url", ""),
            "published": a.get("publishedAt", ""),
        })

    return articles


# ─── NASA APOD ─────────────────────────────────────────────────────────────────

def get_apod():
    """
    Fetch NASA's Astronomy Picture of the Day.

    Returns a dict like:
    {
        "title": "The Milky Way over...",
        "explanation": "...",
        "url": "https://apod.nasa.gov/apod/image/...",
        "media_type": "image",  # or "video"
        "date": "2026-04-15"
    }
    """
    key = _get_key("NASA_API_KEY")
    if not key:
        return None

    data = _fetch("https://api.nasa.gov/planetary/apod", {
        "api_key": key,
    })

    if not data:
        return None

    return {
        "title":       data.get("title", ""),
        "explanation": data.get("explanation", ""),
        "url":         data.get("url", ""),
        "media_type":  data.get("media_type", "image"),
        "date":        data.get("date", ""),
    }


# ─── SPOTIFY ───────────────────────────────────────────────────────────────────

def get_spotify_token():
    """
    Get a Spotify client credentials token (app-level, not user-level).
    This is enough for searching tracks, artists, playlists etc.
    For currently-playing track you'll need user OAuth — that's a future step.

    Returns the access token string, or None on failure.
    """
    import base64

    client_id     = _get_key("SPOTIFY_CLIENT_ID")
    client_secret = _get_key("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    # encode credentials as base64 for the Authorization header
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    try:
        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            return data.get("access_token")
    except Exception as e:
        print(f"[API] Spotify token fetch failed — {e}")
        return None


# ─── QUICK TEST ────────────────────────────────────────────────────────────────
# run this file directly to sanity-check all your keys: python3 core/api_manager.py

if __name__ == "__main__":
    print("\n── Testing API connections ──\n")

    print("OpenWeather:")
    print(get_weather("Sydney"))

    print("\nCoinGecko:")
    print(get_crypto_price("bitcoin,ethereum"))

    print("\nNews API:")
    news = get_news()
    if news:
        for article in news[:2]:  # just show the first two so it's not overwhelming
            print(f"  - {article['title']} ({article['source']})")

    print("\nNASA APOD:")
    apod = get_apod()
    if apod:
        print(f"  {apod['title']} — {apod['date']}")

    print("\nSpotify token:")
    token = get_spotify_token()
    print(f"  {'Got a token!' if token else 'No token — check your keys.'}")

    print("\n── Done ──\n")
