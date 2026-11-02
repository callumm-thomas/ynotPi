"""
ynotPi — core/branding_tab.py
-----------------------------
The Branding tab in the admin panel (client PIN and up).

Left side  : pick the primary + accent colours from swatches, or type a hex code
Right side : live preview, choose/remove logo, corner, size, show on photos

Everything saves straight away (same as the other tabs), and the admin panel
re-themes itself immediately so you can see the colours in use.
The colour / logo logic itself lives in branding.py - this file is just the UI.
"""

from pathlib import Path

import pygame

from core import branding

ERROR_COLOR = (230, 120, 110)
HEX_CHARS = set("0123456789abcdefABCDEF#")


# ─── SMALL DRAW HELPERS ────────────────────────────────────────────────────────
def _text(surface, text, font, color, pos):
    surface.blit(font.render(text, True, color), pos)


def _button(surface, rect, label, font, colors, active=False):
    pygame.draw.rect(surface, colors["BUTTON_HOVER"] if active else colors["BUTTON_COLOR"], rect, border_radius=10)
    if active:
        pygame.draw.rect(surface, colors["HIGHLIGHT_COLOR"], rect, width=2, border_radius=10)
    rendered = font.render(label, True, colors["TEXT_COLOR"])
    surface.blit(rendered, rendered.get_rect(center=rect.center))


def _fit(image, max_w, max_h):
    img_w, img_h = image.get_size()
    scale = min(max_w / img_w, max_h / img_h, 1.0)  # never blow small images up
    return pygame.transform.smoothscale(image, (max(1, int(img_w * scale)), max(1, int(img_h * scale))))


def _shorten(text, font, max_w):
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size("..." + text)[0] > max_w:
        text = text[1:]  # cut from the front so the file name (the useful bit) stays visible
    return "..." + text


# ─── LOGO CHOOSER ──────────────────────────────────────────────────────────────
class LogoChooser:
    """Full-panel list of image files found on the Pi / USB / network share."""

    def __init__(self):
        self.items = branding.find_logo_candidates()
        self.selected = 0 if self.items else None
        self.scroll = 0
        self._preview = {"path": None, "surface": None}

    # layout
    @staticmethod
    def _list_rect(screen_h):
        return pygame.Rect(60, 150, 560, screen_h - 150 - 190)

    def _row_h(self, fonts):
        return fonts["small"].get_height() + 16

    def _visible_rows(self, screen_h, fonts):
        return max(1, (self._list_rect(screen_h).height - 10) // self._row_h(fonts))

    @staticmethod
    def _use_rect(screen_h):
        return pygame.Rect(60, screen_h - 170, 220, 48)

    @staticmethod
    def _cancel_rect(screen_h):
        return pygame.Rect(300, screen_h - 170, 160, 48)

    def _select(self, index, screen_h, fonts):
        if not self.items:
            return
        self.selected = max(0, min(len(self.items) - 1, index))
        visible = self._visible_rows(screen_h, fonts)
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + visible:
            self.scroll = self.selected - visible + 1

    def handle_event(self, event, screen, fonts):
        """Returns ("use", Path), ("cancel", None) or None."""
        _, screen_h = screen.get_size()

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return ("cancel", None)
            if self.selected is None:
                return None
            if event.key == pygame.K_UP:
                self._select(self.selected - 1, screen_h, fonts)
            elif event.key == pygame.K_DOWN:
                self._select(self.selected + 1, screen_h, fonts)
            elif event.key == pygame.K_RETURN:
                return ("use", self.items[self.selected][1])
            return None

        if event.type == pygame.MOUSEWHEEL and self.items:
            visible = self._visible_rows(screen_h, fonts)
            self.scroll = max(0, min(max(0, len(self.items) - visible), self.scroll - event.y * 3))
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._cancel_rect(screen_h).collidepoint(event.pos):
                return ("cancel", None)
            if self._use_rect(screen_h).collidepoint(event.pos) and self.selected is not None:
                return ("use", self.items[self.selected][1])

            list_rect = self._list_rect(screen_h)
            if list_rect.collidepoint(event.pos) and self.items:
                row = (event.pos[1] - list_rect.y - 5) // self._row_h(fonts)
                index = self.scroll + row
                if 0 <= row < self._visible_rows(screen_h, fonts) and index < len(self.items):
                    self.selected = index

        return None

    def _preview_surface(self, path, max_w, max_h):
        if self._preview["path"] != path:
            try:
                image = pygame.image.load(str(path)).convert_alpha()
                self._preview["surface"] = _fit(image, max_w, max_h)
            except Exception:
                self._preview["surface"] = None
            self._preview["path"] = path
        return self._preview["surface"]

    def draw(self, screen, fonts, colors):
        screen_w, screen_h = screen.get_size()
        _text(screen, "Choose a logo", fonts["body"], colors["TEXT_COLOR"], (60, 105))

        list_rect = self._list_rect(screen_h)
        pygame.draw.rect(screen, colors["CARD_COLOR"], list_rect, border_radius=10)
        pygame.draw.rect(screen, colors["CARD_BORDER"], list_rect, width=1, border_radius=10)

        if not self.items:
            lines = [
                "No images found.",
                "Put the logo (a PNG with a transparent",
                "background works best) in assets/branding,",
                "on a USB stick, or on the network share,",
                "then open this again.",
            ]
            y = list_rect.y + 20
            for line in lines:
                _text(screen, line, fonts["small"], colors["SUBTEXT_COLOR"], (list_rect.x + 20, y))
                y += fonts["small"].get_height() + 8
        else:
            row_h = self._row_h(fonts)
            visible = self._visible_rows(screen_h, fonts)
            for row, (label, path) in enumerate(self.items[self.scroll:self.scroll + visible]):
                index = self.scroll + row
                row_rect = pygame.Rect(list_rect.x + 5, list_rect.y + 5 + row * row_h, list_rect.width - 10, row_h - 4)
                if index == self.selected:
                    pygame.draw.rect(screen, colors["BUTTON_HOVER"], row_rect, border_radius=6)
                _text(screen, _shorten(path.name, fonts["small"], 330), fonts["small"], colors["TEXT_COLOR"], (row_rect.x + 12, row_rect.y + 6))
                _text(screen, label, fonts["small"], colors["SUBTEXT_COLOR"], (row_rect.x + 370, row_rect.y + 6))

            _text(
                screen,
                f"{len(self.items)} image(s) found  •  Up/Down or click to pick  •  Enter to use",
                fonts["small"],
                colors["SUBTEXT_COLOR"],
                (list_rect.x, list_rect.bottom + 8),
            )

        # preview of the highlighted file
        preview_rect = pygame.Rect(660, 150, min(320, screen_w - 700), 200)
        pygame.draw.rect(screen, colors["CARD_COLOR"], preview_rect, border_radius=10)
        if self.selected is not None:
            path = self.items[self.selected][1]
            image = self._preview_surface(path, preview_rect.width - 20, preview_rect.height - 20)
            if image:
                screen.blit(image, image.get_rect(center=preview_rect.center))
            else:
                _text(screen, "Can't open this file", fonts["small"], ERROR_COLOR, (preview_rect.x + 15, preview_rect.y + 15))
            _text(
                screen,
                _shorten(str(path), fonts["small"], preview_rect.width),
                fonts["small"],
                colors["SUBTEXT_COLOR"],
                (preview_rect.x, preview_rect.bottom + 10),
            )

        _button(screen, self._use_rect(screen_h), "Use this logo", fonts["body"], colors, active=self.selected is not None)
        _button(screen, self._cancel_rect(screen_h), "Cancel", fonts["body"], colors)


# ─── THE TAB ───────────────────────────────────────────────────────────────────
class BrandingTab:
    # layout - fixed positions sized for the 1024x720 minimum (same approach as the other tabs)
    CHIP_RECTS = {"primary": pygame.Rect(60, 190, 200, 50), "accent": pygame.Rect(280, 190, 200, 50)}
    SWATCH_SIZE = 44
    SWATCH_GAP = 10
    SWATCH_TOP = 260
    HEX_RECT = pygame.Rect(60, 400, 180, 44)
    APPLY_RECT = pygame.Rect(250, 400, 110, 44)
    RESET_RECT = pygame.Rect(60, 470, 260, 44)

    PREVIEW_RECT = pygame.Rect(540, 190, 400, 225)
    CHOOSE_RECT = pygame.Rect(540, 430, 190, 44)
    REMOVE_RECT = pygame.Rect(745, 430, 120, 44)
    CORNER_RECTS = {"bottom-left": pygame.Rect(640, 485, 140, 40), "bottom-right": pygame.Rect(790, 485, 150, 40)}
    SIZE_RECTS = {
        "small": pygame.Rect(640, 535, 95, 40),
        "medium": pygame.Rect(745, 535, 95, 40),
        "large": pygame.Rect(850, 535, 90, 40),
    }
    PHOTOS_RECT = pygame.Rect(640, 585, 100, 40)

    def __init__(self, settings, save_settings, colors):
        """
        settings      : the admin panel's settings dict (edited in place)
        save_settings : function that writes settings.json
        colors        : the admin panel's colour dict - updated in place so the panel re-themes live
        """
        self.settings = settings
        self.save_settings = save_settings
        self.colors = colors
        self.editing = "primary"
        self.hex_text = ""
        self.hex_active = False
        self.chooser = None
        self.status = ""
        self.status_ok = True

    @property
    def brand(self):
        return branding.get_branding(self.settings)

    def has_active_field(self):
        # while typing a hex code or picking a logo, this tab gets every key press
        return self.hex_active or self.chooser is not None

    def _set_status(self, text, ok=True):
        self.status = text
        self.status_ok = ok

    def _update(self, **changes):
        self.settings.setdefault("branding", {}).update(changes)
        self.save_settings(self.settings)
        self.colors.update(branding.palette_for(self.brand))  # re-theme the panel straight away

    def _swatch_rect(self, index):
        col, row = index % 8, index // 8
        step = self.SWATCH_SIZE + self.SWATCH_GAP
        return pygame.Rect(60 + col * step, self.SWATCH_TOP + row * step, self.SWATCH_SIZE, self.SWATCH_SIZE)

    def _set_colour(self, hex_value):
        self._update(**{self.editing: hex_value})
        self._set_status(f"{self.editing.title()} colour set to {hex_value}.")

    def _apply_hex(self):
        rgb = branding.parse_hex(self.hex_text)
        if rgb is None:
            self._set_status("Not a valid colour — use 6 hex digits, like #1E5AA8.", False)
            return
        self._set_colour(branding.to_hex(rgb))
        self.hex_text = ""
        self.hex_active = False

    # ── events ──
    def handle_event(self, event, screen, fonts):
        if self.chooser:
            result = self.chooser.handle_event(event, screen, fonts)
            if result:
                choice, path = result
                self.chooser = None
                if choice == "use":
                    rel_path, message = branding.install_logo(path)
                    if rel_path:
                        self._update(logo=rel_path)
                    self._set_status(message, rel_path is not None)
            return None

        if event.type == pygame.KEYDOWN and self.hex_active:
            if event.key == pygame.K_ESCAPE:
                self.hex_active = False
            elif event.key == pygame.K_RETURN:
                self._apply_hex()
            elif event.key == pygame.K_BACKSPACE:
                self.hex_text = self.hex_text[:-1]
            elif event.unicode and event.unicode in HEX_CHARS and len(self.hex_text) < 7:
                self.hex_text += event.unicode.upper()
            return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        pos = event.pos
        self.hex_active = self.HEX_RECT.collidepoint(pos)

        for key, rect in self.CHIP_RECTS.items():
            if rect.collidepoint(pos):
                self.editing = key
                return None

        for index, hex_value in enumerate(branding.SWATCHES):
            if self._swatch_rect(index).collidepoint(pos):
                self._set_colour(hex_value)
                return None

        if self.APPLY_RECT.collidepoint(pos):
            self._apply_hex()
        elif self.RESET_RECT.collidepoint(pos):
            self._update(primary=None, accent=None)
            self._set_status("Colours reset to the default ynotPi look.")
        elif self.CHOOSE_RECT.collidepoint(pos):
            self._set_status("")
            self.chooser = LogoChooser()
        elif self.REMOVE_RECT.collidepoint(pos) and self.brand.get("logo"):
            self._update(logo=None)
            self._set_status("Logo removed.")
        elif self.PHOTOS_RECT.collidepoint(pos):
            self._update(logo_on_photos=not self.brand.get("logo_on_photos", True))
        else:
            for corner, rect in self.CORNER_RECTS.items():
                if rect.collidepoint(pos):
                    self._update(logo_corner=corner)
            for size, rect in self.SIZE_RECTS.items():
                if rect.collidepoint(pos):
                    self._update(logo_size=size)

        return None

    # ── drawing ──
    def draw(self, screen, fonts, colors):
        if self.chooser:
            self.chooser.draw(screen, fonts, colors)
            return

        brand = self.brand
        self._draw_colours(screen, fonts, colors, brand)
        self._draw_logo_side(screen, fonts, colors, brand)

        if self.status:
            _text(screen, self.status, fonts["small"], colors["HIGHLIGHT_COLOR"] if self.status_ok else ERROR_COLOR, (60, 590))

    def _draw_colours(self, screen, fonts, colors, brand):
        _text(screen, "Colours", fonts["body"], colors["TEXT_COLOR"], (60, 150))

        for key, rect in self.CHIP_RECTS.items():
            active = key == self.editing
            _button(screen, rect, "", fonts["small"], colors, active=active)
            value = brand.get(key)
            chip = pygame.Rect(rect.x + 10, rect.y + 10, 30, 30)
            if value:
                pygame.draw.rect(screen, branding.parse_hex(value), chip, border_radius=6)
            else:
                pygame.draw.rect(screen, colors["SUBTEXT_COLOR"], chip, width=2, border_radius=6)
            label = f"{key.title()}  {value if value else 'default'}"
            _text(screen, label, fonts["small"], colors["TEXT_COLOR"], (rect.x + 50, rect.y + 14))

        current = brand.get(self.editing)
        for index, hex_value in enumerate(branding.SWATCHES):
            rect = self._swatch_rect(index)
            pygame.draw.rect(screen, branding.parse_hex(hex_value), rect, border_radius=8)
            if current and current.upper() == hex_value.upper():
                pygame.draw.rect(screen, colors["TEXT_COLOR"], rect.inflate(6, 6), width=3, border_radius=10)

        _text(screen, "Or type a hex code", fonts["small"], colors["SUBTEXT_COLOR"], (60, 376))
        pygame.draw.rect(screen, colors["CARD_COLOR"], self.HEX_RECT, border_radius=8)
        pygame.draw.rect(
            screen,
            colors["HIGHLIGHT_COLOR"] if self.hex_active else colors["CARD_BORDER"],
            self.HEX_RECT,
            width=2,
            border_radius=8,
        )
        if self.hex_text or self.hex_active:
            cursor = "|" if self.hex_active and int(pygame.time.get_ticks() / 500) % 2 == 0 else ""
            _text(screen, self.hex_text + cursor, fonts["body"], colors["TEXT_COLOR"], (self.HEX_RECT.x + 10, self.HEX_RECT.y + 8))
        else:
            _text(screen, "#1E5AA8", fonts["body"], colors["SUBTEXT_COLOR"], (self.HEX_RECT.x + 10, self.HEX_RECT.y + 8))
        _button(screen, self.APPLY_RECT, "Apply", fonts["body"], colors)

        _button(screen, self.RESET_RECT, "Reset to default look", fonts["small"], colors)
        _text(screen, "Primary tints the backgrounds. Accent is used for highlights.", fonts["small"], colors["SUBTEXT_COLOR"], (60, 530))
        _text(screen, "Very dark accents are lightened automatically so they show up.", fonts["small"], colors["SUBTEXT_COLOR"], (60, 555))

    def _draw_logo_side(self, screen, fonts, colors, brand):
        _text(screen, "Logo + preview", fonts["body"], colors["TEXT_COLOR"], (540, 150))
        self._draw_preview(screen, fonts, brand)

        _button(screen, self.CHOOSE_RECT, "Choose logo...", fonts["body"], colors)
        _button(screen, self.REMOVE_RECT, "Remove", fonts["body"], colors)

        _text(screen, "Corner", fonts["small"], colors["SUBTEXT_COLOR"], (540, 495))
        for corner, rect in self.CORNER_RECTS.items():
            label = "Bottom left" if corner == "bottom-left" else "Bottom right"
            _button(screen, rect, label, fonts["small"], colors, active=brand.get("logo_corner") == corner)

        _text(screen, "Size", fonts["small"], colors["SUBTEXT_COLOR"], (540, 545))
        for size, rect in self.SIZE_RECTS.items():
            _button(screen, rect, size.title(), fonts["small"], colors, active=brand.get("logo_size") == size)

        _text(screen, "On photos", fonts["small"], colors["SUBTEXT_COLOR"], (540, 595))
        on_photos = brand.get("logo_on_photos", True)
        _button(screen, self.PHOTOS_RECT, "ON" if on_photos else "OFF", fonts["small"], colors, active=on_photos)

    def _draw_preview(self, screen, fonts, brand):
        """A mini slide in the chosen colours, with the logo at the same relative size and corner."""
        rect = self.PREVIEW_RECT
        palette = branding.palette_for(brand)
        preview = pygame.Surface(rect.size)
        preview.fill(palette["BACKGROUND_COLOR"])

        card = pygame.Rect(14, 30, rect.width - 28, rect.height - 30 - int(rect.height * 0.125) - 6)
        pygame.draw.rect(preview, palette["CARD_COLOR"], card, border_radius=8)
        pygame.draw.rect(preview, palette["CARD_BORDER"], card, width=1, border_radius=8)
        pygame.draw.rect(preview, palette["HIGHLIGHT_COLOR"], pygame.Rect(card.x + 10, card.y + 6, 28, 3), border_radius=2)

        _text(preview, "Weather", fonts["small"], palette["TEXT_COLOR"], (14, 5))
        _text(preview, "Sydney  22°C", fonts["small"], palette["TEXT_COLOR"], (card.x + 12, card.y + 22))
        _text(preview, "Scattered clouds", fonts["small"], palette["SUBTEXT_COLOR"], (card.x + 12, card.y + 50))

        branding.draw_logo(preview, brand)
        if not brand.get("logo"):
            _text(preview, "No logo", fonts["small"], palette["SUBTEXT_COLOR"], (rect.width - 90, rect.height - 28))

        screen.blit(preview, rect.topleft)
        pygame.draw.rect(screen, palette["CARD_BORDER"], rect, width=1)