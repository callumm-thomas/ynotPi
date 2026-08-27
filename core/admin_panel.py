"""
ynotPi — core/admin_panel.py
-----------------------------
In-app admin overlay for the photo frame.

Opened from the slideshow with a customisable hotkey (default F1). Lets you:
- see every content type in a grid and flip it on/off
- pick which photo sources are active (local folder / USB / network share)
- add a new custom API entry, saved straight into config/apis.json
- rebind the hotkey that opens this panel

Settings are persisted to config/settings.json. Nothing here talks to
photoframe.py directly (it's imported by that module, not the other way
around) — the caller passes in the screen, fonts and color theme to use.
"""

import json
from pathlib import Path

import pygame

from core import api_manager

BASE_DIR = Path(__file__).parent.parent
SETTINGS_PATH = BASE_DIR / "config" / "settings.json"

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
}

CONTENT_LABELS = {
    "photos": "Photos",
    "weather": "Weather",
    "crypto": "Crypto",
    "news": "News",
    "apod": "NASA APOD",
    "trivia": "Trivia",
}

SOURCE_LABELS = {
    "local": ("Local Folder", "assets/photos"),
    "usb": ("USB Drive", "/media/pi, /media/<user>"),
    "network": ("Network Folder", "/mnt/photos"),
}

TABS = ["Content", "Photo Sources", "Add API", "Hotkey"]


def _deep_merge(defaults, loaded):
    result = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            result[key] = _deep_merge(defaults[key], value)
        else:
            result[key] = value
    return result


def load_settings():
    if not SETTINGS_PATH.exists():
        return json.loads(json.dumps(DEFAULT_SETTINGS))

    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as file:
            loaded = json.load(file)
        if not isinstance(loaded, dict):
            return json.loads(json.dumps(DEFAULT_SETTINGS))
        return _deep_merge(DEFAULT_SETTINGS, loaded)
    except Exception as error:
        print(f"[Admin] Couldn't load settings.json — {error}")
        return json.loads(json.dumps(DEFAULT_SETTINGS))


def save_settings(settings):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2)
        file.write("\n")


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


# ─── SMALL UI HELPERS ──────────────────────────────────────────────────────────
def _draw_text(surface, text, font, color, pos):
    surface.blit(font.render(text, True, color), pos)


def _draw_button(surface, rect, label, font, colors, hover=False, active=False):
    bg = colors["BUTTON_HOVER"] if (hover or active) else colors["BUTTON_COLOR"]
    pygame.draw.rect(surface, bg, rect, border_radius=10)
    if active:
        pygame.draw.rect(surface, colors["HIGHLIGHT_COLOR"], rect, width=2, border_radius=10)
    text_surface = font.render(label, True, colors["TEXT_COLOR"])
    text_rect = text_surface.get_rect(center=rect.center)
    surface.blit(text_surface, text_rect)


def _draw_toggle_tile(surface, rect, label, enabled, font, small_font, colors, focused=False):
    pygame.draw.rect(surface, colors["CARD_COLOR"], rect, border_radius=14)
    border_color = colors["HIGHLIGHT_COLOR"] if focused else colors["CARD_BORDER"]
    pygame.draw.rect(surface, border_color, rect, width=2 if focused else 1, border_radius=14)

    _draw_text(surface, label, font, colors["TEXT_COLOR"], (rect.x + 16, rect.y + 14))

    status_text = "ON" if enabled else "OFF"
    status_color = (110, 210, 130) if enabled else (210, 100, 100)
    pill = pygame.Rect(rect.x + 16, rect.bottom - 42, 70, 28)
    pygame.draw.rect(surface, status_color, pill, border_radius=14)
    status_surface = small_font.render(status_text, True, (15, 15, 15))
    surface.blit(status_surface, status_surface.get_rect(center=pill.center))


class TextField:
    def __init__(self, name, label, rect):
        self.name = name
        self.label = label
        self.rect = rect
        self.text = ""
        self.active = False

    def handle_key(self, event):
        if not self.active:
            return
        if event.key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]

    def handle_text_input(self, event):
        if self.active:
            self.text += event.text

    def draw(self, surface, font, small_font, colors):
        _draw_text(surface, self.label, small_font, colors["SUBTEXT_COLOR"], (self.rect.x, self.rect.y - 22))
        bg = colors["CARD_COLOR"]
        border = colors["HIGHLIGHT_COLOR"] if self.active else colors["CARD_BORDER"]
        pygame.draw.rect(surface, bg, self.rect, border_radius=8)
        pygame.draw.rect(surface, border, self.rect, width=2, border_radius=8)

        display_text = self.text
        if self.active and int(pygame.time.get_ticks() / 500) % 2 == 0:
            display_text += "|"

        text_surface = font.render(display_text, True, colors["TEXT_COLOR"])
        surface.blit(text_surface, (self.rect.x + 10, self.rect.y + (self.rect.height - text_surface.get_height()) // 2))


# ─── MAIN PANEL ────────────────────────────────────────────────────────────────
def run_admin_panel(screen, fonts, colors):
    """
    Blocking loop for the admin overlay. Runs its own event loop until the
    user closes it (Esc, or clicking Close). Reads/writes settings.json and
    apis.json directly. Returns nothing — the caller should reload settings
    and rebuild its slide queue afterwards.
    """
    settings = load_settings()
    screen_w, screen_h = screen.get_size()

    active_tab = 0
    content_focus = 0
    source_focus = 0
    waiting_for_key = False
    status_message = ""

    key_location = "query"

    fields = [
        TextField("name", "API Name", pygame.Rect(100, 220, 500, 44)),
        TextField("url", "URL", pygame.Rect(100, 300, 700, 44)),
        TextField("key_name", "Key Name (optional, from secrets.env)", pygame.Rect(100, 380, 500, 44)),
        TextField("key_param_name", "Key Param Name (default: apiKey)", pygame.Rect(650, 380, 300, 44)),
        TextField("params", "Extra Params (k=v,k2=v2 — optional)", pygame.Rect(100, 460, 700, 44)),
    ]

    def custom_api_names():
        return [cfg.get("name", "custom") for cfg in api_manager.load_custom_api_configs()]

    def content_grid_items():
        items = [(key, CONTENT_LABELS[key], None) for key in CONTENT_LABELS]
        for name in custom_api_names():
            items.append((name, name, name))
        return items

    def submit_new_api():
        nonlocal status_message
        name = fields[0].text.strip()
        url = fields[1].text.strip()

        if not name or not url:
            status_message = "Name and URL are required."
            return

        config = {"name": name, "url": url}

        key_name = fields[2].text.strip()
        if key_name:
            config["key_name"] = key_name
            config["key_location"] = key_location
            key_param_name = fields[3].text.strip()
            config["key_param_name"] = key_param_name if key_param_name else "apiKey"

        params_text = fields[4].text.strip()
        if params_text:
            params = {}
            for pair in params_text.split(","):
                if "=" in pair:
                    k, _, v = pair.partition("=")
                    params[k.strip()] = v.strip()
            if params:
                config["params"] = params

        api_manager.add_custom_api_config(config)
        status_message = f"Added '{name}' to apis.json."

        for field in fields:
            field.text = ""
            field.active = False

    running = True
    clock = pygame.time.Clock()

    while running:
        tab_rects = []
        tab_x = 40
        for i, tab_name in enumerate(TABS):
            width = fonts["body"].size(tab_name)[0] + 40
            tab_rects.append((pygame.Rect(tab_x, 30, width, 48), i))
            tab_x += width + 12

        close_rect = pygame.Rect(screen_w - 150, 30, 110, 48)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if waiting_for_key:
                    if event.key != pygame.K_ESCAPE:
                        settings["admin_hotkey"] = pygame.key.name(event.key)
                        save_settings(settings)
                        status_message = f"Hotkey set to '{pygame.key.name(event.key)}'."
                    waiting_for_key = False
                    continue

                if any(f.active for f in fields):
                    active_field = next(f for f in fields if f.active)
                    if event.key == pygame.K_ESCAPE:
                        active_field.active = False
                    elif event.key == pygame.K_TAB:
                        idx = fields.index(active_field)
                        active_field.active = False
                        fields[(idx + 1) % len(fields)].active = True
                    elif event.key == pygame.K_RETURN:
                        active_field.active = False
                    else:
                        active_field.handle_key(event)
                    continue

                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key in (pygame.K_LEFT,) and active_tab > 0:
                    active_tab -= 1
                elif event.key in (pygame.K_RIGHT,) and active_tab < len(TABS) - 1:
                    active_tab += 1
                elif TABS[active_tab] == "Content":
                    items = content_grid_items()
                    if event.key == pygame.K_UP and content_focus - 3 >= 0:
                        content_focus -= 3
                    elif event.key == pygame.K_DOWN and content_focus + 3 < len(items):
                        content_focus += 3
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and items:
                        key, _, custom_name = items[content_focus]
                        if custom_name:
                            settings["content"]["custom"][custom_name] = not is_content_enabled(settings, key, custom_name)
                        else:
                            settings["content"][key] = not is_content_enabled(settings, key)
                        save_settings(settings)
                elif TABS[active_tab] == "Photo Sources":
                    keys = list(SOURCE_LABELS)
                    if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        key = keys[source_focus]
                        settings["sources"][key] = not is_source_enabled(settings, key)
                        save_settings(settings)
                elif TABS[active_tab] == "Hotkey":
                    if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        waiting_for_key = True
                        status_message = "Press any key to set the new hotkey..."

            elif event.type == pygame.TEXTINPUT:
                for field in fields:
                    field.handle_text_input(event)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_pos = event.pos
                if close_rect.collidepoint(mouse_pos):
                    running = False
                    continue

                for rect, i in tab_rects:
                    if rect.collidepoint(mouse_pos):
                        active_tab = i
                        break

                if TABS[active_tab] == "Content":
                    items = content_grid_items()
                    columns = max(1, (screen_w - 120) // 300)
                    for idx, (key, _, custom_name) in enumerate(items):
                        col = idx % columns
                        row = idx // columns
                        rect = pygame.Rect(60 + col * 300, 150 + row * 150, 270, 120)
                        if rect.collidepoint(mouse_pos):
                            content_focus = idx
                            if custom_name:
                                settings["content"]["custom"][custom_name] = not is_content_enabled(settings, key, custom_name)
                            else:
                                settings["content"][key] = not is_content_enabled(settings, key)
                            save_settings(settings)

                elif TABS[active_tab] == "Photo Sources":
                    for idx, key in enumerate(SOURCE_LABELS):
                        rect = pygame.Rect(60 + idx * 300, 150, 270, 150)
                        if rect.collidepoint(mouse_pos):
                            settings["sources"][key] = not is_source_enabled(settings, key)
                            save_settings(settings)

                elif TABS[active_tab] == "Add API":
                    for field in fields:
                        field.active = field.rect.collidepoint(mouse_pos)

                    location_rect = pygame.Rect(650, 300, 200, 44)
                    if location_rect.collidepoint(mouse_pos):
                        key_location = "header" if key_location == "query" else "query"

                    submit_rect = pygame.Rect(100, 540, 200, 50)
                    if submit_rect.collidepoint(mouse_pos):
                        submit_new_api()

                elif TABS[active_tab] == "Hotkey":
                    change_rect = pygame.Rect(100, 220, 260, 50)
                    if change_rect.collidepoint(mouse_pos):
                        waiting_for_key = True
                        status_message = "Press any key to set the new hotkey..."

        # ── draw ──
        screen.fill(colors["BACKGROUND_COLOR"])

        _draw_text(screen, "Admin Panel", fonts["title"], colors["TEXT_COLOR"], (40, screen_h - 60))
        _draw_button(screen, close_rect, "Close (Esc)", fonts["small"], colors)

        for rect, i in tab_rects:
            _draw_button(screen, rect, TABS[i], fonts["body"], colors, active=(i == active_tab))

        if TABS[active_tab] == "Content":
            items = content_grid_items()
            columns = max(1, (screen_w - 120) // 300)
            for idx, (key, label, custom_name) in enumerate(items):
                col = idx % columns
                row = idx // columns
                rect = pygame.Rect(60 + col * 300, 150 + row * 150, 270, 120)
                enabled = is_content_enabled(settings, key, custom_name)
                _draw_toggle_tile(screen, rect, label, enabled, fonts["body"], fonts["small"], colors, focused=(idx == content_focus))

        elif TABS[active_tab] == "Photo Sources":
            for idx, key in enumerate(SOURCE_LABELS):
                label, path_hint = SOURCE_LABELS[key]
                rect = pygame.Rect(60 + idx * 300, 150, 270, 150)
                enabled = is_source_enabled(settings, key)
                _draw_toggle_tile(screen, rect, label, enabled, fonts["body"], fonts["small"], colors, focused=(idx == source_focus))
                _draw_text(screen, path_hint, fonts["small"], colors["SUBTEXT_COLOR"], (rect.x, rect.bottom + 10))

        elif TABS[active_tab] == "Add API":
            _draw_text(screen, "New Custom API", fonts["body"], colors["TEXT_COLOR"], (100, 170))
            for field in fields:
                field.draw(screen, fonts["body"], fonts["small"], colors)

            _draw_text(screen, "Key Location", fonts["small"], colors["SUBTEXT_COLOR"], (650, 278))
            location_rect = pygame.Rect(650, 300, 200, 44)
            _draw_button(screen, location_rect, key_location, fonts["body"], colors)

            submit_rect = pygame.Rect(100, 540, 200, 50)
            _draw_button(screen, submit_rect, "Save API", fonts["body"], colors)

            if status_message:
                _draw_text(screen, status_message, fonts["small"], colors["HIGHLIGHT_COLOR"], (100, 610))

        elif TABS[active_tab] == "Hotkey":
            current = settings.get("admin_hotkey", "f1")
            _draw_text(screen, f"Current hotkey: {current.upper()}", fonts["body"], colors["TEXT_COLOR"], (100, 170))
            change_rect = pygame.Rect(100, 220, 260, 50)
            label = "Press a key..." if waiting_for_key else "Change Hotkey"
            _draw_button(screen, change_rect, label, fonts["body"], colors)

            if status_message:
                _draw_text(screen, status_message, fonts["small"], colors["HIGHLIGHT_COLOR"], (100, 300))

        pygame.display.flip()
        clock.tick(30)
