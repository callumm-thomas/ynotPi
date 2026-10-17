#!/usr/bin/env python3

"""
Photo Frame v2.0 — photos + API slides
--------------------------------------
Keeps the original source picker, fullscreen slideshow, crop-to-fill photos,
and now injects extra slides with live API data.

Flow each cycle:
- load photos from USB / network / both
- fetch live API data
- build a queue of photo slides plus one slide per API
- display them fullscreen

Keys:
- space / right arrow = skip
- esc = quit (dev mode only - on the Pi, quitting goes through Technician mode > Power)
- r = rebuild queue + refresh API data
- admin hotkey (default F1, customisable in the admin panel) = open admin panel (asks for a PIN)

Dev mode (for testing on a laptop/desktop instead of the Pi):
- python core/photoframe.py --dev          -> resizable window, mouse visible,
                                              dummy data for weather/news/APOD if their key isn't set
- python core/photoframe.py --dev --dummy  -> every feed uses dummy data (no internet needed)
Without --dev it runs fullscreen exactly like it always has.
"""

import argparse

import io
import os
import sys
import time
import random
import html
import urllib.request
from pathlib import Path

import pygame

# repo root (the folder above core/) - paths hang off this so it doesn't matter where we're launched from
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# start the log file before anything else prints, so startup messages get captured too
from core import logbook
logbook.start()

from core.api_manager import (
    get_weather, get_crypto_price, get_news, get_apod, get_custom_apis, get_trivia,
    has_key, load_custom_api_configs,
)
from core import admin_panel
from core import dummy_data
from core import technician


# ─── CONFIG ────────────────────────────────────────────────────────────────────
SLIDE_DURATION = 10
BACKGROUND_COLOR = (18, 22, 28)
TEXT_COLOR = (245, 245, 245)
SUBTEXT_COLOR = (170, 176, 186)
HIGHLIGHT_COLOR = (70, 130, 200)
BUTTON_COLOR = (55, 55, 55)
BUTTON_HOVER = (75, 75, 75)
CARD_COLOR = (30, 35, 43)
CARD_BORDER = (55, 63, 75)

NETWORK_SHARE_MOUNT = "/mnt/photos"
USB_BASE_PATHS = ["/media/pi", f"/media/{os.environ.get('USER', 'pi')}"]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".jfif", ".png", ".bmp", ".gif", ".webp"}
LOCAL_PHOTO_PATH = str(BASE_DIR / "assets" / "photos")  # anchored to the repo, not whatever folder we got launched from

WEATHER_CITY = os.environ.get("WEATHER_CITY", "Sydney")
CRYPTO_COINS = os.environ.get("CRYPTO_COINS", "bitcoin,ethereum,solana")
CRYPTO_CURRENCY = os.environ.get("CRYPTO_CURRENCY", "aud")
NEWS_COUNTRY = os.environ.get("NEWS_COUNTRY", "au")
NEWS_CATEGORY = os.environ.get("NEWS_CATEGORY", "technology")
NEWS_PAGE_SIZE = int(os.environ.get("NEWS_PAGE_SIZE", "5"))
ENABLE_APOD_IMAGE = os.environ.get("ENABLE_APOD_IMAGE", "1") == "1"


# ─── DEV MODE ──────────────────────────────────────────────────────────────────
# these get set from the command line in main() - see the docstring up top
DEV_MODE = False
DUMMY_MODE = False

DEV_WINDOW_SIZE = (1280, 720)  # starting window size in dev mode
DEV_MIN_SIZE = (1024, 720)     # slides + admin panel use fixed pixel positions, so don't let the window shrink below this
RESIZE_SETTLE_SECONDS = 0.25   # wait for the user to stop dragging before re-laying out slides

# built-in feeds that need a key: feed name -> key name in secrets.env
KEYED_FEEDS = {
    "weather": "OPENWEATHER_API_KEY",
    "news": "NEWS_API_KEY",
    "apod": "NASA_API_KEY",
}


# ─── PHOTO DISCOVERY ───────────────────────────────────────────────────────────
def find_usb_photos():
    photos = []
    for base in USB_BASE_PATHS:
        if os.path.isdir(base):
            for root, _, files in os.walk(base):
                for file_name in files:
                    if Path(file_name).suffix.lower() in IMAGE_EXTENSIONS:
                        photos.append(os.path.join(root, file_name))
    return photos


def find_network_photos():
    photos = []
    if os.path.isdir(NETWORK_SHARE_MOUNT) and os.listdir(NETWORK_SHARE_MOUNT):
        for root, _, files in os.walk(NETWORK_SHARE_MOUNT):
            for file_name in files:
                if Path(file_name).suffix.lower() in IMAGE_EXTENSIONS:
                    photos.append(os.path.join(root, file_name))
    return photos

def find_local_photos():
    photos = []
    if os.path.isdir(LOCAL_PHOTO_PATH):
        for root, _, files in os.walk(LOCAL_PHOTO_PATH):
            for file_name in files:
                if Path(file_name).suffix.lower() in IMAGE_EXTENSIONS:
                    photos.append(os.path.join(root, file_name))
    return photos

def get_photos():
    settings = admin_panel.load_settings()

    if not admin_panel.is_content_enabled(settings, "photos"):
        print("[PhotoFrame] Photos are disabled in the admin panel — skipping.")
        return []

    usb_photos = find_usb_photos() if admin_panel.is_source_enabled(settings, "usb") else []
    network_photos = find_network_photos() if admin_panel.is_source_enabled(settings, "network") else []
    local_photos = find_local_photos() if admin_panel.is_source_enabled(settings, "local") else []

    photos = list(set(usb_photos + network_photos + local_photos))
    random.shuffle(photos)

    print(
        f"[PhotoFrame] Loaded {len(photos)} photo(s) "
        f"(USB: {len(usb_photos)}, Network: {len(network_photos)}, Local: {len(local_photos)})"
    )

    return photos


# ─── IMAGE HELPERS ─────────────────────────────────────────────────────────────
def crop_to_fill(image, target_w, target_h):
    img_w, img_h = image.get_size()
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    scaled = pygame.transform.smoothscale(image, (new_w, new_h))

    x = (new_w - target_w) // 2
    y = (new_h - target_h) // 2
    cropped = scaled.subsurface(pygame.Rect(x, y, target_w, target_h))
    return cropped.copy()


def fit_inside(image, target_w, target_h):
    img_w, img_h = image.get_size()
    scale = min(target_w / img_w, target_h / img_h)
    new_w = max(1, int(img_w * scale))
    new_h = max(1, int(img_h * scale))
    return pygame.transform.smoothscale(image, (new_w, new_h))


def load_image(path, target_w, target_h):
    try:
        image = pygame.image.load(path).convert()
        return crop_to_fill(image, target_w, target_h)
    except Exception as error:
        print(f"[PhotoFrame] Skipping {path} — couldn't load it: {error}")
        return None


# url -> surface (or None if it failed). cached so re-laying out slides after a resize
# doesn't re-download the APOD image (or sit through an 8s timeout again if it failed)
_remote_image_cache = {}


def clear_remote_image_cache():
    _remote_image_cache.clear()


def load_remote_image(url):
    if url in _remote_image_cache:
        return _remote_image_cache[url]

    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            raw = response.read()
        image = pygame.image.load(io.BytesIO(raw)).convert()
    except Exception as error:
        print(f"[PhotoFrame] Couldn't load remote image {url}: {error}")
        image = None

    _remote_image_cache[url] = image
    return image


# ─── TEXT / UI HELPERS ─────────────────────────────────────────────────────────
def make_fonts(screen_h):
    title_size = max(36, screen_h // 18)
    body_size = max(24, screen_h // 32)
    small_size = max(18, screen_h // 45)

    return {
        "title": pygame.font.SysFont("arial", title_size, bold=True),
        "body": pygame.font.SysFont("arial", body_size),
        "small": pygame.font.SysFont("arial", small_size),
    }


def draw_wrapped_text(surface, text, font, color, rect, line_gap=8, max_lines=None):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = word if not current else current + " " + word
        if font.size(test)[0] <= rect.width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            while font.size(lines[-1] + "...")[0] > rect.width and lines[-1]:
                lines[-1] = lines[-1][:-1]
            lines[-1] += "..."

    y = rect.top
    line_height = font.get_height() + line_gap

    for line in lines:
        if y + font.get_height() > rect.bottom:
            break
        rendered = font.render(line, True, color)
        surface.blit(rendered, (rect.left, y))
        y += line_height

    return y


def draw_card(surface, rect):
    pygame.draw.rect(surface, CARD_COLOR, rect, border_radius=18)
    pygame.draw.rect(surface, CARD_BORDER, rect, width=2, border_radius=18)


# ─── API DATA ──────────────────────────────────────────────────────────────────
def use_dummy(feed_name):
    """Should this feed use dummy data instead of calling the real API?"""
    if DUMMY_MODE:
        return True

    # dev mode only: fill in feeds whose key isn't set rather than just dropping the slide
    key_name = KEYED_FEEDS.get(feed_name)
    if DEV_MODE and key_name and not has_key(key_name):
        print(f"[PhotoFrame] Dev mode: {key_name} not set - using dummy {feed_name} data")
        return True

    return False


def fetch_api_data():
    settings = admin_panel.load_settings()
    api_data = {}

    if admin_panel.is_content_enabled(settings, "weather"):
        weather = dummy_data.weather(WEATHER_CITY) if use_dummy("weather") else get_weather(WEATHER_CITY)
        if weather:
            api_data["weather"] = weather

    if admin_panel.is_content_enabled(settings, "crypto"):
        if use_dummy("crypto"):
            crypto = dummy_data.crypto(CRYPTO_COINS, CRYPTO_CURRENCY)
        else:
            crypto = get_crypto_price(CRYPTO_COINS, CRYPTO_CURRENCY)
        if crypto:
            api_data["crypto"] = crypto

    if admin_panel.is_content_enabled(settings, "news"):
        if use_dummy("news"):
            news = dummy_data.news(NEWS_PAGE_SIZE)
        else:
            news = get_news(NEWS_COUNTRY, NEWS_CATEGORY, NEWS_PAGE_SIZE)
        if news:
            api_data["news"] = news

    if admin_panel.is_content_enabled(settings, "apod"):
        apod = dummy_data.apod() if use_dummy("apod") else get_apod()
        if apod:
            api_data["apod"] = apod

    all_custom = dummy_data.custom_apis(load_custom_api_configs()) if use_dummy("custom") else get_custom_apis()
    custom_apis = [
        item for item in all_custom
        if admin_panel.is_content_enabled(settings, "custom", custom_name=item.get("name"))
    ]
    if custom_apis:
        api_data["custom"] = custom_apis

    if admin_panel.is_content_enabled(settings, "trivia"):
        trivia = dummy_data.trivia() if use_dummy("trivia") else get_trivia()
        if trivia:
            api_data["trivia"] = trivia

    print(
        f"[PhotoFrame] API slides available: {', '.join(api_data.keys()) if api_data else 'none'}"
    )
    return api_data


# ─── API SLIDE BUILDERS ────────────────────────────────────────────────────────
def build_weather_slide(screen_size, fonts, weather):
    screen_w, screen_h = screen_size
    surface = pygame.Surface((screen_w, screen_h))
    surface.fill(BACKGROUND_COLOR)

    title = fonts["title"].render("Weather", True, TEXT_COLOR)
    surface.blit(title, (60, 40))

    card = pygame.Rect(60, 130, screen_w - 120, screen_h - 220)
    draw_card(surface, card)

    city = fonts["title"].render(weather.get("city", WEATHER_CITY), True, TEXT_COLOR)
    temp = fonts["title"].render(f"{round(weather.get('temp', 0))}°C", True, TEXT_COLOR)
    feels = fonts["body"].render(f"Feels like {round(weather.get('feels_like', 0))}°C", True, SUBTEXT_COLOR)
    desc = fonts["body"].render(weather.get("description", "").title(), True, TEXT_COLOR)
    humidity = fonts["body"].render(f"Humidity: {weather.get('humidity', '?')}%", True, TEXT_COLOR)

    surface.blit(city, (100, 180))
    surface.blit(temp, (100, 270))
    surface.blit(feels, (100, 360))
    surface.blit(desc, (100, 430))
    surface.blit(humidity, (100, 490))

    footer = fonts["small"].render(f"Source: OpenWeather • {WEATHER_CITY}", True, SUBTEXT_COLOR)
    surface.blit(footer, (100, screen_h - 120))

    return surface


def build_crypto_slide(screen_size, fonts, crypto):
    screen_w, screen_h = screen_size
    surface = pygame.Surface((screen_w, screen_h))
    surface.fill(BACKGROUND_COLOR)

    title = fonts["title"].render("Crypto", True, TEXT_COLOR)
    surface.blit(title, (60, 40))

    card = pygame.Rect(60, 130, screen_w - 120, screen_h - 220)
    draw_card(surface, card)

    y = 180
    currency = CRYPTO_CURRENCY.upper()

    for coin_name, values in crypto.items():
        price = values.get(CRYPTO_CURRENCY)
        change = values.get(f"{CRYPTO_CURRENCY}_24h_change")

        coin_text = fonts["body"].render(coin_name.replace("-", " ").title(), True, TEXT_COLOR)
        price_text = fonts["body"].render(f"{currency} {price:,.2f}" if isinstance(price, (int, float)) else "N/A", True, TEXT_COLOR)

        if isinstance(change, (int, float)):
            direction = "+" if change >= 0 else ""
            change_text = fonts["small"].render(f"24h: {direction}{change:.2f}%", True, SUBTEXT_COLOR)
        else:
            change_text = fonts["small"].render("24h: N/A", True, SUBTEXT_COLOR)

        surface.blit(coin_text, (100, y))
        surface.blit(price_text, (screen_w // 2, y))
        surface.blit(change_text, (screen_w // 2, y + 42))
        y += 110

        if y > screen_h - 180:
            break

    footer = fonts["small"].render("Source: CoinGecko", True, SUBTEXT_COLOR)
    surface.blit(footer, (100, screen_h - 120))

    return surface


def build_news_slide(screen_size, fonts, news_items):
    screen_w, screen_h = screen_size
    surface = pygame.Surface((screen_w, screen_h))
    surface.fill(BACKGROUND_COLOR)

    title = fonts["title"].render("News", True, TEXT_COLOR)
    surface.blit(title, (60, 40))

    card = pygame.Rect(60, 130, screen_w - 120, screen_h - 220)
    draw_card(surface, card)

    y = 175
    for index, item in enumerate(news_items[:5], start=1):
        bullet = fonts["body"].render(f"{index}.", True, TEXT_COLOR)
        surface.blit(bullet, (95, y))

        text_rect = pygame.Rect(140, y, card.width - 180, 110)
        end_y = draw_wrapped_text(
            surface,
            item.get("title", "Untitled"),
            fonts["body"],
            TEXT_COLOR,
            text_rect,
            line_gap=6,
            max_lines=2,
        )

        source_text = item.get("source", "")
        published_text = item.get("published", "")[:10] if item.get("published") else ""
        meta = " • ".join(part for part in [source_text, published_text] if part)
        meta_render = fonts["small"].render(meta, True, SUBTEXT_COLOR)
        surface.blit(meta_render, (140, end_y + 4))

        y += 105
        if y > screen_h - 180:
            break

    footer = fonts["small"].render(f"Source: News API • {NEWS_COUNTRY.upper()} / {NEWS_CATEGORY}", True, SUBTEXT_COLOR)
    surface.blit(footer, (100, screen_h - 120))

    return surface


def build_apod_slide(screen_size, fonts, apod):
    screen_w, screen_h = screen_size
    surface = pygame.Surface((screen_w, screen_h))
    surface.fill(BACKGROUND_COLOR)

    title = fonts["title"].render("NASA APOD", True, TEXT_COLOR)
    surface.blit(title, (60, 40))

    card = pygame.Rect(60, 130, screen_w - 120, screen_h - 220)
    draw_card(surface, card)

    text_x = 100
    text_w = card.width - 80

    media_type = apod.get("media_type", "")
    remote_url = apod.get("url", "")

    if ENABLE_APOD_IMAGE and media_type == "image" and remote_url:
        image = load_remote_image(remote_url)
        if image:
            fitted = fit_inside(image, int(card.width * 0.48), int(card.height * 0.7))
            image_x = card.right - fitted.get_width() - 40
            image_y = card.top + 40
            surface.blit(fitted, (image_x, image_y))
            text_w = image_x - text_x - 30

    title_rect = pygame.Rect(text_x, 180, text_w, 120)
    next_y = draw_wrapped_text(surface, apod.get("title", "Astronomy Picture of the Day"), fonts["body"], TEXT_COLOR, title_rect, max_lines=3)

    date_text = fonts["small"].render(apod.get("date", ""), True, SUBTEXT_COLOR)
    surface.blit(date_text, (text_x, next_y + 8))

    explanation_rect = pygame.Rect(text_x, next_y + 50, text_w, card.height - 180)
    draw_wrapped_text(surface, apod.get("explanation", ""), fonts["small"], TEXT_COLOR, explanation_rect, line_gap=5, max_lines=10)

    footer = fonts["small"].render("Source: NASA APOD", True, SUBTEXT_COLOR)
    surface.blit(footer, (100, screen_h - 120))

    return surface

def flatten_custom_data(data, prefix=""):
    rows = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(flatten_custom_data(value, new_prefix))

    elif isinstance(data, list):
        for index, value in enumerate(data[:8]):
            new_prefix = f"{prefix}[{index}]"
            rows.extend(flatten_custom_data(value, new_prefix))

    else:
        rows.append((prefix, str(data)))

    return rows


def build_custom_api_slide(screen_size, fonts, custom_api):
    screen_w, screen_h = screen_size
    surface = pygame.Surface((screen_w, screen_h))
    surface.fill(BACKGROUND_COLOR)

    title = fonts["title"].render(custom_api.get("name", "Custom API"), True, TEXT_COLOR)
    surface.blit(title, (60, 40))

    card = pygame.Rect(60, 130, screen_w - 120, screen_h - 220)
    draw_card(surface, card)

    rows = flatten_custom_data(custom_api.get("data", {}))[:10]

    y = 180
    for key, value in rows:
        key_text = fonts["small"].render(str(key), True, SUBTEXT_COLOR)
        surface.blit(key_text, (100, y))

        value_rect = pygame.Rect(100, y + 28, card.width - 80, 55)
        draw_wrapped_text(
            surface,
            value,
            fonts["body"],
            TEXT_COLOR,
            value_rect,
            line_gap=4,
            max_lines=2,
        )

        y += 85
        if y > screen_h - 170:
            break

    footer = fonts["small"].render("Source: custom API", True, SUBTEXT_COLOR)
    surface.blit(footer, (100, screen_h - 120))

    return surface


def draw_trivia_content(surface, fonts, trivia_item, highlight_correct=False):
    screen_w, screen_h = surface.get_size()

    title = fonts["title"].render("Trivia", True, TEXT_COLOR)
    surface.blit(title, (60, 40))

    card = pygame.Rect(60, 130, screen_w - 120, screen_h - 220)
    draw_card(surface, card)

    question = html.unescape(trivia_item.get("question", ""))
    correct = html.unescape(trivia_item.get("correct_answer", ""))
    incorrect = [html.unescape(a) for a in trivia_item.get("incorrect_answers", [])]

    answers = incorrect + [correct]
    random.seed(hash(question))
    random.shuffle(answers)
    random.seed()  # reset so nothing else is affected

    q_rect = pygame.Rect(100, 180, card.width - 80, 90)
    draw_wrapped_text(
        surface,
        question,
        fonts["small"],
        TEXT_COLOR,
        q_rect,
        line_gap=4,
        max_lines=2,
    )

    start_y = 300
    answer_box_height = 58
    gap = 16

    for i, answer in enumerate(answers[:4]):
        box_y = start_y + i * (answer_box_height + gap)

        is_correct = answer == correct

        box_color = (45, 50, 60)
        border_color = None

        if highlight_correct and is_correct:
            box_color = (40, 100, 55)
            border_color = (90, 200, 120)

        answer_box = pygame.Rect(95, box_y, card.width - 70, answer_box_height)
        pygame.draw.rect(surface, box_color, answer_box, border_radius=10)

        if border_color:
            pygame.draw.rect(surface, border_color, answer_box, width=3, border_radius=10)

        label = chr(65 + i) + ". "
        text = label + answer

        text_rect = pygame.Rect(115, box_y + 10, card.width - 110, 36)
        draw_wrapped_text(
            surface,
            text,
            fonts["small"],
            TEXT_COLOR,
            text_rect,
            line_gap=2,
            max_lines=1,
        )

    footer_text = "Source: OpenTDB"
    if highlight_correct:
        footer_text += " • Correct answer shown"

    footer = fonts["small"].render(footer_text, True, SUBTEXT_COLOR)
    surface.blit(footer, (100, screen_h - 120))


def build_trivia_question_slide(screen_size, fonts, trivia_item):
    screen_w, screen_h = screen_size
    surface = pygame.Surface((screen_w, screen_h))
    surface.fill(BACKGROUND_COLOR)
    draw_trivia_content(surface, fonts, trivia_item, highlight_correct=False)
    return surface


def build_trivia_answer_slide(screen_size, fonts, trivia_item):
    screen_w, screen_h = screen_size
    surface = pygame.Surface((screen_w, screen_h))
    surface.fill(BACKGROUND_COLOR)
    draw_trivia_content(surface, fonts, trivia_item, highlight_correct=True)
    return surface

def build_api_slides(screen_size, fonts, api_data, trivia_item=None):
    slides = []

    if api_data.get("weather"):
        slides.append({
            "kind": "api",
            "name": "weather",
            "surface": build_weather_slide(screen_size, fonts, api_data["weather"]),
        })

    if api_data.get("crypto"):
        slides.append({
            "kind": "api",
            "name": "crypto",
            "surface": build_crypto_slide(screen_size, fonts, api_data["crypto"]),
        })

    if api_data.get("news"):
        slides.append({
            "kind": "api",
            "name": "news",
            "surface": build_news_slide(screen_size, fonts, api_data["news"]),
        })

    if api_data.get("apod"):
        slides.append({
            "kind": "api",
            "name": "apod",
            "surface": build_apod_slide(screen_size, fonts, api_data["apod"]),
        })

    if api_data.get("custom"):
        for custom_api in api_data["custom"]:
            slides.append(
                {
                    "kind": "api",
                    "name": custom_api.get("name", "custom"),
                    "surface": build_custom_api_slide(screen_size, fonts, custom_api),
                }
            )

    if api_data.get("trivia"):
        # normally picked once in gather_content() so a re-layout keeps the same question
        if trivia_item is None:
            trivia_item = random.choice(api_data["trivia"])

        slides.append(
            {
                "kind": "api",
                "name": "trivia_question",
                "surface": build_trivia_question_slide(screen_size, fonts, trivia_item),
                "duration": 12,
            }
        )

        slides.append(
            {
                "kind": "api",
                "name": "trivia_answer",
                "surface": build_trivia_answer_slide(screen_size, fonts, trivia_item),
                "duration": 8,
            }
        )      

    return slides

# ─── SLIDESHOW QUEUE ───────────────────────────────────────────────────────────
def gather_content():
    """
    The slow part: find photos + hit the APIs. Kept separate from building the
    slides so a dev-window resize can re-lay everything out without re-fetching.
    """
    clear_remote_image_cache()  # fresh data = allow a fresh image download too

    photos = get_photos()
    api_data = fetch_api_data()
    trivia_item = random.choice(api_data["trivia"]) if api_data.get("trivia") else None

    return {"photos": photos, "api_data": api_data, "trivia_item": trivia_item}


def build_slide_queue(screen_w, screen_h, fonts, content):
    photos = content["photos"]
    api_slides = build_api_slides((screen_w, screen_h), fonts, content["api_data"], content["trivia_item"])

    queue = []

    for path in photos:
        queue.append({"kind": "photo", "path": path, "surface": None})

    queue.extend(api_slides)

    if not queue:
        fallback = pygame.Surface((screen_w, screen_h))
        fallback.fill(BACKGROUND_COLOR)
        title = fonts["title"].render("No slides available", True, TEXT_COLOR)
        hint = fonts["body"].render("Add photos or configure API keys.", True, SUBTEXT_COLOR)
        fallback.blit(title, (screen_w // 2 - title.get_width() // 2, screen_h // 2 - 40))
        fallback.blit(hint, (screen_w // 2 - hint.get_width() // 2, screen_h // 2 + 20))
        queue.append({"kind": "api", "name": "fallback", "surface": fallback})

    print(f"[PhotoFrame] Queue ready: {len(photos)} photo slide(s), {len(api_slides)} API slide(s)")
    return queue


# ─── MAIN DISPLAY LOOP ─────────────────────────────────────────────────────────
def ensure_min_window_size():
    """Dev mode: if the window's been dragged smaller than DEV_MIN_SIZE, snap it back up."""
    screen = pygame.display.get_surface()
    w, h = screen.get_size()
    min_w, min_h = DEV_MIN_SIZE

    if w < min_w or h < min_h:
        screen = pygame.display.set_mode((max(w, min_w), max(h, min_h)), pygame.RESIZABLE)

    return screen


def run_slideshow(screen):
    """Runs until quit. Returns "restart" / "exit" if Technician mode asked for that, otherwise None."""
    screen_w, screen_h = screen.get_size()
    fonts = make_fonts(screen_h)

    theme_colors = {
        "BACKGROUND_COLOR": BACKGROUND_COLOR,
        "TEXT_COLOR": TEXT_COLOR,
        "SUBTEXT_COLOR": SUBTEXT_COLOR,
        "HIGHLIGHT_COLOR": HIGHLIGHT_COLOR,
        "BUTTON_COLOR": BUTTON_COLOR,
        "BUTTON_HOVER": BUTTON_HOVER,
        "CARD_COLOR": CARD_COLOR,
        "CARD_BORDER": CARD_BORDER,
    }

    content = gather_content()
    slides = build_slide_queue(screen_w, screen_h, fonts, content)
    index = 0
    current_surface = None
    current_photo_path = None
    last_switch = time.time()
    resize_pending_since = None  # dev mode: time of the most recent resize event

    admin_key = admin_panel.resolve_key(admin_panel.load_settings().get("admin_hotkey", "f1"))

    clock = pygame.time.Clock()

    while True:
        now = time.time()

        slide = slides[index]
        slide_duration = slide.get("duration", SLIDE_DURATION)

        if now - last_switch >= slide_duration:
            index = (index + 1) % len(slides)
            last_switch = now

            if index == 0:
                content = gather_content()
                slides = build_slide_queue(screen_w, screen_h, fonts, content)

            current_surface = None
            current_photo_path = None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                # closing the window only counts in dev mode - on the Pi (e.g. Alt+F4)
                # it's ignored, so the frame can't be closed without the technician PIN
                if DEV_MODE:
                    return None
                continue

            if event.type == pygame.VIDEORESIZE:
                # dragging the window edge fires loads of these - just note it,
                # the actual re-layout happens once things settle (below)
                resize_pending_since = now
                continue

            if event.type == pygame.KEYDOWN:
                if event.key == admin_key:
                    action = admin_panel.run_admin_panel(screen, fonts, theme_colors, dev_mode=DEV_MODE)
                    if action:
                        return action  # restart / exit - main() carries it out once pygame is closed

                    admin_key = admin_panel.resolve_key(admin_panel.load_settings().get("admin_hotkey", "f1"))

                    if DEV_MODE:
                        # window might've been resized while the panel was open
                        screen = ensure_min_window_size()
                        screen_w, screen_h = screen.get_size()
                        fonts = make_fonts(screen_h)

                    content = gather_content()
                    slides = build_slide_queue(screen_w, screen_h, fonts, content)
                    index = 0
                    last_switch = time.time()
                    current_surface = None
                    current_photo_path = None
                    continue
                if event.key == pygame.K_ESCAPE and DEV_MODE:
                    return None
                if event.key in (pygame.K_SPACE, pygame.K_RIGHT):
                    index = (index + 1) % len(slides)
                    last_switch = now
                    current_surface = None
                    current_photo_path = None
                if event.key == pygame.K_r:
                    content = gather_content()
                    slides = build_slide_queue(screen_w, screen_h, fonts, content)
                    index = 0
                    last_switch = now
                    current_surface = None
                    current_photo_path = None

        # dev mode: once the user stops dragging, re-lay out every slide at the new size
        # using the content we already have - no new API calls
        if resize_pending_since is not None and now - resize_pending_since >= RESIZE_SETTLE_SECONDS:
            resize_pending_since = None
            screen = ensure_min_window_size()
            screen_w, screen_h = screen.get_size()
            fonts = make_fonts(screen_h)
            slides = build_slide_queue(screen_w, screen_h, fonts, content)
            index = min(index, len(slides) - 1)
            current_surface = None  # forces the current photo to re-crop at the new size
            current_photo_path = None
            print(f"[PhotoFrame] Window resized to {screen_w}x{screen_h} - slides re-laid out")

        slide = slides[index]

        if slide["kind"] == "photo":
            if current_surface is None or current_photo_path != slide["path"]:
                current_surface = load_image(slide["path"], screen_w, screen_h)
                current_photo_path = slide["path"]

            if current_surface is None:
                index = (index + 1) % len(slides)
                last_switch = now
                continue

        else:
            if current_surface is None:
                current_surface = slide["surface"]
                current_photo_path = None

        # mid-drag the window and the slide can be different sizes - clear the leftover edges
        if current_surface.get_size() != screen.get_size():
            screen.fill(BACKGROUND_COLOR)

        screen.blit(current_surface, (0, 0))
        pygame.display.flip()
        clock.tick(30)


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="ynotPi photo frame")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="resizable window + visible mouse, dummy data for weather/news/APOD if their key isn't set",
    )
    parser.add_argument(
        "--dummy",
        action="store_true",
        help="use dummy data for every API feed (no internet needed)",
    )
    return parser.parse_args()


def main():
    global DEV_MODE, DUMMY_MODE

    args = parse_args()
    DEV_MODE = args.dev
    DUMMY_MODE = args.dummy

    pygame.init()

    if DEV_MODE:
        screen = pygame.display.set_mode(DEV_WINDOW_SIZE, pygame.RESIZABLE)
        pygame.display.set_caption("ynotPi Photo Frame (dev)")
        pygame.mouse.set_visible(True)
    else:
        # the normal Pi setup - unchanged
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption("ynotPi Photo Frame")
        pygame.mouse.set_visible(False)

    screen_w, screen_h = screen.get_size()
    print(f"[PhotoFrame] Running at {screen_w}x{screen_h}{' (dev mode)' if DEV_MODE else ''}")
    if DUMMY_MODE:
        print("[PhotoFrame] Dummy mode - every API feed is using dummy data")

    action = run_slideshow(screen)

    pygame.quit()

    if action == "restart":
        technician.restart_app()
    elif action == "exit":
        technician.exit_to_desktop()

    sys.exit()


if __name__ == "__main__":
    main()
