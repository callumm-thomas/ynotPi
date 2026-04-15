"""
ynotPi — core/api_manager.py
----------------------------
Built-in API helpers + custom API registry support.

Custom APIs are defined in config/apis.json.
A custom API can use:
- just a URL
- a URL + API key from secrets.env
- optional query params
- optional headers
"""

import os
import json
import urllib.request
import urllib.parse
from pathlib import Path


# ─── PATHS ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
SECRETS_PATH = BASE_DIR / "config" / "secrets.env"
CUSTOM_APIS_PATH = BASE_DIR / "config" / "apis.json"


# ─── LOAD SECRETS ──────────────────────────────────────────────────────────────
def _load_secrets():
    if not SECRETS_PATH.exists():
        print("[API] secrets.env not found — run scripts/setup_keys.sh first!")
        return {}

    secrets = {}
    with open(SECRETS_PATH, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key, _, value = line.partition("=")
                secrets[key.strip()] = value.strip()

    return secrets


_SECRETS = _load_secrets()


def _get_key(name):
    value = _SECRETS.get(name, "")
    if not value:
        print(f"[API] '{name}' is not set in secrets.env — skipping this call.")
        return None
    return value


# ─── LOAD CUSTOM API CONFIG ────────────────────────────────────────────────────
def load_custom_api_configs():
    if not CUSTOM_APIS_PATH.exists():
        return []

    try:
        with open(CUSTOM_APIS_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            data = data.get("apis", [])

        if not isinstance(data, list):
            print("[API] apis.json is not a list or {'apis': [...]} format.")
            return []

        valid_configs = []
        for item in data:
            if isinstance(item, dict) and item.get("name") and item.get("url"):
                valid_configs.append(item)
            else:
                print(f"[API] Skipping invalid custom API config: {item}")

        return valid_configs

    except Exception as error:
        print(f"[API] Couldn't load apis.json — {error}")
        return []


# ─── SHARED HTTP HELPER ────────────────────────────────────────────────────────
def _fetch(url, params=None, headers=None):
    if params:
        query_string = urllib.parse.urlencode(params, doseq=True)
        join_char = "&" if "?" in url else "?"
        url = f"{url}{join_char}{query_string}"

    try:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except Exception as error:
        print(f"[API] Request failed for {url} — {error}")
        return None


# ─── CUSTOM API SUPPORT ────────────────────────────────────────────────────────
def fetch_custom_api(config):
    """
    config example:
    {
      "name": "Exchange Rates",
      "url": "https://api.exchangerate.host/latest",
      "params": {"base": "AUD", "symbols": "USD,EUR"}
    }

    or

    {
      "name": "Football Data",
      "url": "https://api.football-data.org/v4/matches",
      "key_name": "FOOTBALL_DATA_KEY",
      "key_location": "header",
      "key_param_name": "X-Auth-Token"
    }

    Supported fields:
    - name
    - url
    - params
    - headers
    - key_name
    - key_location: "header" or "query"
    - key_param_name
    - result_path
    """

    name = config.get("name", "Custom API")
    url = config.get("url")
    params = dict(config.get("params", {}))
    headers = dict(config.get("headers", {}))

    if not url:
        return None

    key_name = config.get("key_name")
    key_location = config.get("key_location", "query")
    key_param_name = config.get("key_param_name", "apiKey")

    if key_name:
        key_value = _get_key(key_name)
        if not key_value:
            return None

        if key_location == "header":
            headers[key_param_name] = key_value
        else:
            params[key_param_name] = key_value

    data = _fetch(url, params=params, headers=headers)

    if data is None:
        return None

    # optional: drill into nested result
    result_path = config.get("result_path", [])
    if isinstance(result_path, str):
        result_path = [part for part in result_path.split(".") if part]

    for part in result_path:
        try:
            if isinstance(data, list):
                data = data[int(part)]
            else:
                data = data[part]
        except Exception:
            print(f"[API] Couldn't follow result_path for {name}")
            return None

    return {
        "name": name,
        "data": data,
        "source_url": url,
    }


def get_custom_apis():
    configs = load_custom_api_configs()
    results = []

    for config in configs:
        result = fetch_custom_api(config)
        if result is not None:
            results.append(result)

    return results


# ─── OPENWEATHER ───────────────────────────────────────────────────────────────
def get_weather(city="Sydney", units="metric"):
    key = _get_key("OPENWEATHER_API_KEY")
    if not key:
        return None

    data = _fetch(
        "https://api.openweathermap.org/data/2.5/weather",
        {
            "q": city,
            "appid": key,
            "units": units,
        },
    )

    if not data or data.get("cod") != 200:
        print(f"[API] OpenWeather returned an error: {data}")
        return None

    return {
        "city": data["name"],
        "temp": data["main"]["temp"],
        "feels_like": data["main"]["feels_like"],
        "description": data["weather"][0]["description"],
        "humidity": data["main"]["humidity"],
        "icon": data["weather"][0]["icon"],
    }


# ─── COINGECKO ─────────────────────────────────────────────────────────────────
def get_crypto_price(coin_ids="bitcoin,ethereum", currency="aud"):
    # optional key only - don't use _get_key here
    key = _SECRETS.get("COINGECKO_API_KEY", "").strip()

    params = {
        "ids": coin_ids,
        "vs_currencies": currency,
        "include_24hr_change": "true",
    }

    url = "https://api.coingecko.com/api/v3/simple/price"

    # only include pro key if one is actually provided
    if key:
        params["x_cg_pro_api_key"] = key

    data = _fetch(url, params)

    if not data:
        return None

    return data


# ─── NEWS API ──────────────────────────────────────────────────────────────────
def get_news(country="au", category="general", page_size=5):
    key = _get_key("NEWS_API_KEY")
    if not key:
        return None

    data = _fetch(
        "https://newsapi.org/v2/top-headlines",
        {
            "country": country,
            "category": category,
            "pageSize": page_size,
            "apiKey": key,
        },
    )

    if not data or data.get("status") != "ok":
        print(f"[API] News API error: {data}")
        return None

    articles = []
    for article in data.get("articles", []):
        articles.append(
            {
                "title": article.get("title", ""),
                "source": article.get("source", {}).get("name", ""),
                "url": article.get("url", ""),
                "published": article.get("publishedAt", ""),
            }
        )

    return articles


# ─── NASA APOD ─────────────────────────────────────────────────────────────────
def get_apod():
    key = _get_key("NASA_API_KEY")
    if not key:
        return None

    data = _fetch(
        "https://api.nasa.gov/planetary/apod",
        {
            "api_key": key,
        },
    )

    if not data:
        return None

    return {
        "title": data.get("title", ""),
        "explanation": data.get("explanation", ""),
        "url": data.get("url", ""),
        "media_type": data.get("media_type", "image"),
        "date": data.get("date", ""),
    }


# ─── SPOTIFY ───────────────────────────────────────────────────────────────────
def get_spotify_token():
    import base64

    client_id = _get_key("SPOTIFY_CLIENT_ID")
    client_secret = _get_key("SPOTIFY_CLIENT_SECRET")

    if not client_id or not client_secret:
        return None

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    try:
        request = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode())
            return data.get("access_token")

    except Exception as error:
        print(f"[API] Spotify token fetch failed — {error}")
        return None


def get_trivia():
    data = _fetch(
        "https://opentdb.com/api.php",
        {
            "amount": 10,
            "type": "multiple",
        },
    )

    if not data or data.get("response_code") != 0:
        print("[API] Trivia API failed")
        return None

    return data.get("results", [])

# ─── QUICK TEST ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n── Testing built-in APIs ──\n")

    print("OpenWeather:")
    print(get_weather("Sydney"))

    print("\nCoinGecko:")
    print(get_crypto_price("bitcoin,ethereum"))

    print("\nNews API:")
    print(get_news())

    print("\nNASA APOD:")
    print(get_apod())

    print("\nSpotify token:")
    token = get_spotify_token()
    print("Got a token!" if token else "No token — check your keys.")

    print("\nCustom APIs:")
    for item in get_custom_apis():
        print(f" - {item['name']}")

    print("\n── Done ──\n")