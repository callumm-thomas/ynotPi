#!/usr/bin/env python3

"""
Photo Frame v2.0 — photos + API slides
--------------------------------------
Keeps the original source picker, fullscreen slideshow, crop-to-fill photos,
and now injects extra ([raw.githubusercontent.com](https://raw.githubusercontent.com/callumm-thomas/ynotPi/main/core/api_manager.py))a.

Flow each cycle:
- load photos from USB / network / both
- fetch live API data
- build a queue of photo slides plus one slide per API
- display them fullscreen

Keys:
- space / right arrow = skip
- esc = quit
- r = rebuild queue + refresh API data
"""

import io
import os
import sys
import time
import random
import html
import urllib.request
from pathlib import Path

import pygame

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.api_manager import (get_weather, get_crypto_price, get_news, get_apod, get_custom_apis, get_trivia,)


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
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
LOCAL_PHOTO_PATH = "assets/photos"

WEATHER_CITY = os.environ.get("WEATHER_CITY", "Sydney")
CRYPTO_COINS = os.environ.get("CRYPTO_COINS", "bitcoin,ethereum,solana")
CRYPTO_CURRENCY = os.environ.get("CRYPTO_CURRENCY", "aud")
NEWS_COUNTRY = os.environ.get("NEWS_COUNTRY", "au")
NEWS_CATEGORY = os.environ.get("NEWS_CATEGORY", "technology")
NEWS_PAGE_SIZE = int(os.environ.get("NEWS_PAGE_SIZE", "5"))
ENABLE_APOD_IMAGE = os.environ.get("ENABLE_APOD_IMAGE", "1") == "1"


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
    usb_photos = find_usb_photos()
    network_photos = find_network_photos()
    local_photos = find_local_photos()

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


def load_remote_image(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            raw = response.read()
        return pygame.image.load(io.BytesIO(raw)).convert()
    except Exception as error:
        print(f"[PhotoFrame] Couldn't load remote image {url}: {error}")
        return None


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
def fetch_api_data():
    api_data = {}

    weather = get_weather(WEATHER_CITY)
    if weather:
        api_data["weather"] = weather

    crypto = get_crypto_price(CRYPTO_COINS, CRYPTO_CURRENCY)
    if crypto:
        api_data["crypto"] = crypto

    news = get_news(NEWS_COUNTRY, NEWS_CATEGORY, NEWS_PAGE_SIZE)
    if news:
        api_data["news"] = news

    apod = get_apod()
    if apod:
        api_data["apod"] = apod

def fetch_api_data():
    api_data = {}

    weather = get_weather(WEATHER_CITY)
    if weather:
        api_data["weather"] = weather

    crypto = get_crypto_price(CRYPTO_COINS, CRYPTO_CURRENCY)
    if crypto:
        api_data["crypto"] = crypto

    news = get_news(NEWS_COUNTRY, NEWS_CATEGORY, NEWS_PAGE_SIZE)
    if news:
        api_data["news"] = news

    apod = get_apod()
    if apod:
        api_data["apod"] = apod

    custom_apis = get_custom_apis()
    if custom_apis:
        api_data["custom"] = custom_apis

    trivia = get_trivia()
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
    random.shuffle(answers)

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

def build_api_slides(screen_size, fonts, api_data):
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
def build_slide_queue(screen_w, screen_h, fonts):
    photos = get_photos()
    api_data = fetch_api_data()
    api_slides = build_api_slides((screen_w, screen_h), fonts, api_data)

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
def run_slideshow(screen):
    screen_w, screen_h = screen.get_size()
    fonts = make_fonts(screen_h)

    slides = build_slide_queue(screen_w, screen_h, fonts)
    index = 0
    current_surface = None
    current_photo_path = None
    last_switch = 0

    clock = pygame.time.Clock()

    while True:
        now = time.time()

        slide = slides[index]
        slide_duration = slide.get("duration", SLIDE_DURATION)

        if now - last_switch >= slide_duration:
            index = (index + 1) % len(slides)
            last_switch = now

            if index == 0:
                slides = build_slide_queue(screen_w, screen_h, fonts)

            current_surface = None
            current_photo_path = None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return
                if event.key in (pygame.K_SPACE, pygame.K_RIGHT):
                    index = (index + 1) % len(slides)
                    last_switch = now
                    current_surface = None
                    current_photo_path = None
                if event.key == pygame.K_r:
                    slides = build_slide_queue(screen_w, screen_h, fonts)
                    index = 0
                    last_switch = now
                    current_surface = None
                    current_photo_path = None

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

        screen.blit(current_surface, (0, 0))
        pygame.display.flip()
        clock.tick(30)


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────
def main():
    pygame.init()
    pygame.mouse.set_visible(True)

    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("ynotPi Photo Frame")

    screen_w, screen_h = screen.get_size()
    print(f"[PhotoFrame] Running at {screen_w}x{screen_h}")

    pygame.mouse.set_visible(False)
    run_slideshow(screen)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
