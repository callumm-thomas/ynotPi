"""
ynotPi — core/settings.py
-------------------------
Loading + saving the frame's settings (everything the admin panel changes
except API keys, PINs and the custom API list).

Read from config/local/settings.json, falling back to the factory defaults -
see storage.py for why there are two files.
"""

import json
import os

import pygame

from core import branding
from core import storage

DEFAULT_SETTINGS = {
    "admin_hotkey": "f1",
    "sources": {"local": True, "usb": True, "network": True},
    "content": {
        "photos": True,
        "weather": True,
        "crypto": True,
        "news": True,
        "apod": True,
        "trivia": True,
        "custom": {},
    },
    "branding": dict(branding.DEFAULT_BRANDING),
    # full paths of photos that are found but shouldn't be shown (Photo Sources tab)
    "hidden_photos": [],
    # options for the built-in feeds (APIs tab). The environment variables are
    # how these used to be set - still honoured as the starting value.
    "feeds": {
        "weather": {
            "town": os.environ.get("WEATHER_CITY", "Sydney"),
            # filled in when a town is picked from the look-up list, so the frame
            # asks for that exact place rather than the first town with that name
            "lat": None,
            "lon": None,
        },
        "crypto": {
            "coins": os.environ.get("CRYPTO_COINS", "bitcoin,ethereum,solana"),
            "currency": os.environ.get("CRYPTO_CURRENCY", "aud"),
        },
        "news": {
            "country": os.environ.get("NEWS_COUNTRY", "au"),
            "category": os.environ.get("NEWS_CATEGORY", "technology"),
        },
    },
}


def _fresh_defaults():
    return json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy, so nobody edits the defaults by accident


def _deep_merge(defaults, loaded):
    result = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            result[key] = _deep_merge(defaults[key], value)
        else:
            result[key] = value
    return result


def load_settings():
    loaded = storage.read_json(storage.SETTINGS_PATH, storage.FACTORY_SETTINGS_PATH, "settings")
    if not isinstance(loaded, dict):
        return _fresh_defaults()

    settings = _deep_merge(_fresh_defaults(), loaded)

    # belt and braces: a hand-edited file could have the wrong type in here
    if not isinstance(settings.get("hidden_photos"), list):
        settings["hidden_photos"] = []
    if not isinstance(settings["content"].get("custom"), dict):
        settings["content"]["custom"] = {}
    return settings


def save_settings(settings):
    try:
        storage.write_json_safely(storage.SETTINGS_PATH, settings)
        return True
    except OSError as error:
        print(f"[Settings] Couldn't save settings — {error}")
        return False


def resolve_key(key_name):
    """Turn a saved key name (e.g. 'f1') into a pygame key constant."""
    try:
        return pygame.key.key_code(key_name)
    except Exception:
        return pygame.K_F1


def is_content_enabled(settings, key, custom_name=None):
    if custom_name is not None:
        return settings.get("content", {}).get("custom", {}).get(custom_name, True)
    return settings.get("content", {}).get(key, True)


def is_source_enabled(settings, key):
    return settings.get("sources", {}).get(key, True)


def feed_options(settings, feed):
    """Options for a built-in feed ('weather', 'crypto', 'news'), defaults filled in."""
    merged = dict(DEFAULT_SETTINGS["feeds"].get(feed, {}))
    merged.update((settings.get("feeds") or {}).get(feed) or {})
    return merged
