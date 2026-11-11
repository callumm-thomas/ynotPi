"""
ynotPi — core/api_manager.py
----------------------------
Built-in API helpers + custom API registry support.

Custom APIs are defined in apis.json (the frame's own copy lives in
config/local/, see storage.py) and API keys in config/secrets.env. Both can be
edited from the admin panel's APIs tab - nobody should need to open the files.
A custom API can use:
- just a URL
- a URL + API key from secrets.env
- optional query params
- optional headers
"""

import re
import json
import urllib.request
import urllib.parse

from core import storage


# ─── PATHS ─────────────────────────────────────────────────────────────────────
SECRETS_PATH = storage.SECRETS_PATH
CUSTOM_APIS_PATH = storage.APIS_PATH  # this frame's own list - see storage.py

# built-in feeds: feed name -> (key name in secrets.env, is the key required?)
BUILTIN_KEYS = {
    "weather": ("OPENWEATHER_API_KEY", True),
    "crypto": ("COINGECKO_API_KEY", False),  # free tier works without one
    "news": ("NEWS_API_KEY", True),
    "apod": ("NASA_API_KEY", True),
}


# ─── SECRETS (API KEYS) ────────────────────────────────────────────────────────
def _load_secrets():
    if not SECRETS_PATH.exists():
        print("[API] secrets.env not found — add keys in the admin panel (APIs tab) or run scripts/setup_keys.sh")
        return {}

    secrets = {}
    try:
        with open(SECRETS_PATH, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                if "=" in line:
                    key, _, value = line.partition("=")
                    secrets[key.strip()] = value.strip()
    except OSError as error:
        print(f"[API] Couldn't read secrets.env — {error}")

    return secrets


_SECRETS = _load_secrets()


def _get_key(name):
    value = _SECRETS.get(name, "")
    if not value:
        print(f"[API] '{name}' is not set in secrets.env — skipping this call.")
        return None
    return value

def has_key(name):
    """True if this key is set in secrets.env. Silent, unlike _get_key()."""
    return bool(_SECRETS.get(name, "").strip())


def get_key_value(name):
    """The saved key itself ('' if not set). Only for the admin panel - never print or log it."""
    return _SECRETS.get(name, "").strip()


def mask_key(value, show_last=4):
    """'abcd1234efgh5678' -> '••••••••5678'. Short keys are hidden completely."""
    if not value:
        return ""
    if len(value) <= show_last * 2:
        return "•" * 8
    return "•" * 8 + value[-show_last:]


def set_key(name, value):
    """
    Save one key into secrets.env (value '' clears it). Every other line in the
    file - comments, other keys - is left exactly as it was.
    Returns (ok, message).
    """
    name = name.strip()
    value = "".join(str(value).split())  # keys never contain spaces/newlines - strips a stray one from typing

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return False, "That key name isn't valid."

    try:
        if SECRETS_PATH.exists():
            with open(SECRETS_PATH, "r", encoding="utf-8") as file:
                lines = file.read().splitlines()
        else:
            lines = ["# ynotPi — secrets.env  (NEVER commit this file to GitHub!)", ""]

        new_lines = []
        written = False
        for line in lines:
            stripped = line.strip()
            is_this_key = (
                "=" in stripped
                and not stripped.startswith("#")
                and stripped.partition("=")[0].strip() == name
            )
            if not is_this_key:
                new_lines.append(line)
            elif not written:
                new_lines.append(f"{name}={value}")
                written = True
            # (a second copy of the same key further down gets dropped)

        if not written:
            new_lines.append(f"{name}={value}")

        storage.write_text_safely(SECRETS_PATH, "\n".join(new_lines) + "\n", private=True)
    except OSError as error:
        print(f"[API] Couldn't save secrets.env — {error}")
        return False, f"Couldn't save the key — {error}"

    _SECRETS[name] = value
    print(f"[API] Key '{name}' {'updated' if value else 'cleared'}")  # the name only, never the key
    return True, "Key saved." if value else "Key removed."


def make_key_name(api_name, taken=()):
    """'Football Data' -> 'FOOTBALL_DATA_KEY' - the name a custom API's key is stored under."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", api_name).strip("_").upper() or "CUSTOM"
    if base[0].isdigit():
        base = "API_" + base
    name = f"{base}_KEY"
    counter = 2
    while name in taken:
        name = f"{base}_{counter}_KEY"
        counter += 1
    return name


# ─── LOAD CUSTOM API CONFIG ────────────────────────────────────────────────────
def load_custom_api_configs():
    data = storage.read_json(storage.APIS_PATH, storage.FACTORY_APIS_PATH, "custom API")
    if data is None:
        return []

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


def save_custom_api_configs(configs):
    """Write the full list of custom API configs to this frame's apis.json. Returns True if it saved."""
    try:
        storage.write_json_safely(storage.APIS_PATH, {"apis": configs})
        return True
    except OSError as error:
        print(f"[API] Couldn't save apis.json — {error}")
        return False


def add_custom_api_config(config):
    """Append one new custom API config to apis.json and save it."""
    configs = load_custom_api_configs()
    configs.append(config)
    save_custom_api_configs(configs)
    return configs


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
        # log the address without the ?query part - that's where API keys travel
        print(f"[API] Request failed for {url.split('?')[0]} — {error}")
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
def get_weather(city="Sydney", units="metric", lat=None, lon=None):
    """
    Current weather. If lat/lon are given (a town picked from the look-up list
    in the admin panel) they're used, and `city` is just the name shown on the
    slide. Otherwise OpenWeather is asked for `city` by name.
    """
    key = _get_key("OPENWEATHER_API_KEY")
    if not key:
        return None

    params = {"appid": key, "units": units}
    if lat is not None and lon is not None:
        params["lat"] = lat
        params["lon"] = lon
    else:
        params["q"] = city

    data = _fetch("https://api.openweathermap.org/data/2.5/weather", params)

    # "cod" comes back as the number 200 on success, but as a string on some errors
    if not data or str(data.get("cod")) != "200":
        print(f"[API] OpenWeather returned an error: {data}")
        return None

    try:
        return {
            # with lat/lon OpenWeather names the nearest weather station (often a suburb),
            # so show the town that was actually picked instead
            "city": city if (lat is not None and lon is not None and city) else data["name"],
            "temp": data["main"]["temp"],
            "feels_like": data["main"]["feels_like"],
            "description": data["weather"][0]["description"],
            "humidity": data["main"]["humidity"],
            "icon": data["weather"][0]["icon"],
        }
    except (KeyError, IndexError, TypeError) as error:
        print(f"[API] OpenWeather reply was missing something: {error}")
        return None


def find_towns(query, limit=5):
    """
    Look a town name up with OpenWeather's geocoding service.
    Returns (matches, error message). Each match is
    {"name", "state", "country", "lat", "lon", "label"} - label is e.g. "Newcastle, New South Wales, AU".
    """
    query = query.strip()
    if not query:
        return [], "Type a town name first."

    key = get_key_value("OPENWEATHER_API_KEY")
    if not key:
        return [], "Add the weather key first — the look-up needs it."

    data = _fetch(
        "https://api.openweathermap.org/geo/1.0/direct",
        {"q": query, "limit": limit, "appid": key},
    )

    if data is None:
        return [], "Couldn't reach the weather service — check the internet connection and the key."
    if not isinstance(data, list):
        return [], "The weather service didn't accept that — check the key."

    matches = []
    seen = set()
    for item in data:
        if not isinstance(item, dict) or "lat" not in item or "lon" not in item:
            continue
        parts = [item.get("name", ""), item.get("state", ""), item.get("country", "")]
        label = ", ".join(part for part in parts if part)
        if not label or label in seen:
            continue
        seen.add(label)
        matches.append({
            "name": item.get("name", query),
            "state": item.get("state", ""),
            "country": item.get("country", ""),
            "lat": item["lat"],
            "lon": item["lon"],
            "label": label,
        })

    if not matches:
        return [], f"No town found called '{query}'. Check the spelling."
    return matches, ""


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
            "amount": 100,
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