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

import pygame

from core import branding
from core import ui

HEX_CHARS = set("0123456789abcdefABCDEF#")


# ─── LOGO CHOOSER ──────────────────────────────────────────────────────────────
class LogoChooser:
    """Takes over the tab: a list of image files found on the Pi / USB / network share, with a preview."""

    def __init__(self):
        self.items = branding.find_logo_candidates()
        self.list = ui.ListView("logo")
        self.preview = ui.Preview(keep_alpha=True)

    def selected_path(self):
        if not self.items:
            return None
        return self.items[min(self.list.current, len(self.items) - 1)][1]

    def draw(self, ui_, area):
        gap = ui_.pad
        ui_.text("Choose a logo", (area.x, area.y), "body", "TEXT_COLOR")
        top = area.y + ui_.fonts["body"].get_height() + gap

        buttons_y = area.bottom - ui_.h_body
        list_w = int(area.width * 0.55)
        list_rect = pygame.Rect(area.x, top, list_w, buttons_y - gap - top)
        row_h = ui_.u + ui_.pad

        def draw_row(index, row_rect, state, selected):
            label, path = self.items[index]
            label_w = ui_.fonts["small"].size(label)[0]
            y = row_rect.y + (row_rect.height - ui_.u) // 2
            ui_.text(path.name, (row_rect.x + ui_.pad, y), "small", "TEXT_COLOR",
                     max_w=row_rect.width - label_w - 3 * ui_.pad, keep_end=True)
            ui_.text(label, (row_rect.right - label_w - ui_.pad, y))

        self.list.draw(ui_, list_rect, len(self.items), row_h, draw_row, empty_lines=[
            "No images found.",
            "Put the logo (a PNG with a transparent background works best) in assets/branding, "
            "on a USB stick, or on the network share, then open this again.",
        ])

        # preview of the highlighted file
        preview_rect = pygame.Rect(list_rect.right + gap, top, area.right - list_rect.right - gap, list_rect.height)
        pygame.draw.rect(ui_.screen, ui_.colors["CARD_COLOR"], preview_rect, border_radius=10)
        path = self.selected_path()
        if path is not None:
            inner = preview_rect.inflate(-2 * ui_.pad, -2 * ui_.pad - ui_.u)
            status, surface = self.preview.get(path, inner.width, inner.height)
            if status == "ok":
                ui_.screen.blit(surface, surface.get_rect(center=inner.center))
            elif status == "loading":
                ui_.text("Loading preview...", inner.topleft)
            else:
                ui_.text("Can't open this file", inner.topleft, color=ui.ERROR_COLOR)
            ui_.text(str(path), (preview_rect.x + ui_.pad, preview_rect.bottom - ui_.u - ui_.pad // 2),
                     max_w=preview_rect.width - 2 * ui_.pad, keep_end=True)

        use_w = ui_.button_w("Use this logo")
        ui_.button("logo:use", pygame.Rect(area.x, buttons_y, use_w, ui_.h_body), "Use this logo", enabled=path is not None)
        ui_.button("logo:cancel", pygame.Rect(area.x + use_w + gap, buttons_y, ui_.button_w("Cancel"), ui_.h_body), "Cancel")


# ─── THE TAB ───────────────────────────────────────────────────────────────────
class BrandingTab(ui.Tab):
    name = "Branding"
    hint = "Arrows: move    Enter: select    Esc: back"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.editing = "primary"   # which colour the swatches / hex box are setting
        self.form = {"hex": ""}
        self.chooser = None

    @property
    def brand(self):
        return branding.get_branding(self.ctx.settings)

    def opened(self, ui_):
        self.chooser = None

    def _update(self, **changes):
        self.ctx.settings.setdefault("branding", {}).update(changes)
        saved = self.ctx.save()
        self.ctx.colors.update(branding.palette_for(self.brand))  # re-theme the panel straight away
        if not saved:
            self.say("Couldn't save that change — see the log in Technician mode.", False)
        return saved

    def _set_colour(self, hex_value):
        if self._update(**{self.editing: hex_value}):
            self.say(f"{self.editing.title()} colour set to {hex_value}.")

    # ── drawing ──
    def draw(self, ui_, area):
        if self.chooser:
            self.chooser.draw(ui_, area)
            return

        brand = self.brand
        gap = ui_.pad
        left_w = min(int(area.width * 0.48), 30 * ui_.u)
        left = pygame.Rect(area.x, area.y, left_w, area.height)
        right = pygame.Rect(left.right + 3 * gap, area.y, area.right - left.right - 3 * gap, area.height)
        self._draw_colours(ui_, left, brand)
        self._draw_logo_side(ui_, right, brand)

    def _draw_colours(self, ui_, rect, brand):
        gap = ui_.pad
        body_h = ui_.fonts["body"].get_height()
        ui_.text("Colours", (rect.x, rect.y), "body", "TEXT_COLOR")
        y = rect.y + body_h + gap

        # which colour is being set - two chips, the lit one is being edited
        chip_w = (rect.width - gap) // 2
        for index, key in enumerate(("primary", "accent")):
            chip = pygame.Rect(rect.x + index * (chip_w + gap), y, chip_w, ui_.h_body)
            value = brand.get(key)
            ui_.button(f"edit:{key}", chip, "", active=(key == self.editing))
            swatch = pygame.Rect(chip.x + ui_.pad, chip.y + (chip.height - ui_.u) // 2, ui_.u, ui_.u)
            if value:
                pygame.draw.rect(ui_.screen, branding.parse_hex(value), swatch, border_radius=4)
            else:
                pygame.draw.rect(ui_.screen, ui_.colors["SUBTEXT_COLOR"], swatch, width=2, border_radius=4)
            ui_.text(f"{key.title()}  {value or 'default'}", (swatch.right + ui_.pad // 2, chip.y + (chip.height - ui_.u) // 2),
                     "small", "TEXT_COLOR", max_w=chip.right - swatch.right - ui_.pad)
        y += ui_.h_body + gap

        # swatches - 8 across, sized to the column
        step = rect.width // 8
        size = step - max(6, step // 6)
        current = (brand.get(self.editing) or "").upper()
        for index, hex_value in enumerate(branding.SWATCHES):
            col, row = index % 8, index // 8
            swatch = pygame.Rect(rect.x + col * step, y + row * step, size, size)
            state = ui_.register(f"swatch:{index}", swatch)
            pygame.draw.rect(ui_.screen, branding.parse_hex(hex_value), swatch, border_radius=8)
            if current == hex_value.upper() or state.hovered:
                pygame.draw.rect(ui_.screen, ui_.colors["TEXT_COLOR"], swatch.inflate(-6, -6), width=2, border_radius=6)
        y += 2 * step + gap // 2

        ui_.text("Or type a hex code", (rect.x, y))
        y += ui_.u + 3
        apply_w = ui_.button_w("Apply")
        hex_w = min(rect.width - apply_w - gap, ui_.fonts["body"].size("#000000")[0] + 3 * ui_.pad)
        ui_.text_input("field:hex", pygame.Rect(rect.x, y, hex_w, ui_.h_body), self.form, "hex",
                       placeholder="#1E5AA8", allowed=HEX_CHARS, max_len=7, upper=True)
        ui_.button("hex:apply", pygame.Rect(rect.x + hex_w + gap, y, apply_w, ui_.h_body), "Apply")
        y += ui_.h_body + gap

        ui_.button("colours:reset", pygame.Rect(rect.x, y, ui_.button_w("Reset to default look", "small"), ui_.h_small),
                   "Reset to default look", font="small")
        y += ui_.h_small + gap
        ui_.paragraph("Primary tints the backgrounds. Accent is used for highlights. "
                      "Very dark accents are lightened automatically so they show up.",
                      (rect.x, y), rect.width, max_lines=max(1, (rect.bottom - y) // (ui_.u + 4)))

    def _draw_logo_side(self, ui_, rect, brand):
        gap = ui_.pad
        body_h = ui_.fonts["body"].get_height()
        ui_.text("Logo + preview", (rect.x, rect.y), "body", "TEXT_COLOR")
        y = rect.y + body_h + gap

        # rows under the preview: buttons, corner, size, on photos
        rows_h = ui_.h_body + 3 * (ui_.h_small + gap) + gap
        preview_h = max(4 * ui_.u, min(int(rect.width * 9 / 16), rect.bottom - y - rows_h))
        preview = pygame.Rect(rect.x, y, min(rect.width, int(preview_h * 16 / 9)), preview_h)
        self._draw_preview(ui_, preview, brand)
        y = preview.bottom + gap

        choose_w = ui_.button_w("Choose logo...")
        ui_.button("logo:choose", pygame.Rect(rect.x, y, choose_w, ui_.h_body), "Choose logo...")
        ui_.button("logo:remove", pygame.Rect(rect.x + choose_w + gap, y, ui_.button_w("Remove"), ui_.h_body), "Remove",
                   enabled=bool(brand.get("logo")))
        y += ui_.h_body + gap

        label_w = max(ui_.fonts["small"].size(text)[0] for text in ("Corner", "Size", "On photos")) + gap

        def option_row(y, title, options, current):
            ui_.text(title, (rect.x, y + (ui_.h_small - ui_.u) // 2))
            x = rect.x + label_w
            for value, text in options:
                width = ui_.button_w(text, "small")
                ui_.button(f"{title.lower().replace(' ', '')}:{value}", pygame.Rect(x, y, width, ui_.h_small), text,
                           font="small", active=(value == current))
                x += width + 6
            return y + ui_.h_small + gap

        y = option_row(y, "Corner", [("bottom-left", "Bottom left"), ("bottom-right", "Bottom right")], brand.get("logo_corner"))
        y = option_row(y, "Size", [(size, size.title()) for size in branding.LOGO_SIZES], brand.get("logo_size"))
        option_row(y, "On photos", [(True, "Show"), (False, "Hide")], bool(brand.get("logo_on_photos", True)))

    def _draw_preview(self, ui_, rect, brand):
        """A mini slide in the chosen colours, with the logo at the same relative size and corner."""
        palette = branding.palette_for(brand)
        preview = pygame.Surface(rect.size)
        preview.fill(palette["BACKGROUND_COLOR"])

        small = ui_.fonts["small"]
        card = pygame.Rect(10, small.get_height() + 8, rect.width - 20,
                           rect.height - small.get_height() - 14 - int(rect.height * 0.14))
        pygame.draw.rect(preview, palette["CARD_COLOR"], card, border_radius=8)
        pygame.draw.rect(preview, palette["CARD_BORDER"], card, width=1, border_radius=8)
        pygame.draw.rect(preview, palette["HIGHLIGHT_COLOR"], pygame.Rect(card.x + 10, card.y + 6, 28, 3), border_radius=2)

        preview.blit(small.render("Weather", True, palette["TEXT_COLOR"]), (10, 4))
        preview.blit(small.render("22°C  Partly cloudy", True, palette["TEXT_COLOR"]), (card.x + 12, card.y + 16))

        branding.draw_logo(preview, brand)
        if not brand.get("logo"):
            text = small.render("No logo", True, palette["SUBTEXT_COLOR"])
            preview.blit(text, (rect.width - text.get_width() - 10, rect.height - text.get_height() - 4))

        ui_.screen.blit(preview, rect.topleft)
        pygame.draw.rect(ui_.screen, palette["CARD_BORDER"], rect, width=1)

    # ── actions ──
    def escape(self, ui_):
        if self.chooser:
            self.chooser = None
            ui_.set_focus("logo:choose")
            return True
        return False

    def handle_action(self, action, ui_):
        kind, item_id = action[0], str(action[1])

        if kind == "commit" and item_id == "field:hex":
            self._apply_hex()
            return None
        if kind != "activate":
            return None

        if self.chooser:
            if item_id == "logo:cancel":
                self.escape(ui_)
            elif item_id == "logo:use" or (self.chooser.list.index_of(item_id) is not None and action[2] != "click"):
                # Enter on a file uses it straight away; a click just selects it (then "Use this logo")
                path = self.chooser.selected_path()
                self.chooser = None
                ui_.set_focus("logo:choose")
                if path is not None:
                    rel_path, message = branding.install_logo(path)
                    if rel_path and self._update(logo=rel_path):
                        self.say(message)
                    elif not rel_path:
                        self.say(message, False)
            return None

        group, _, value = item_id.partition(":")
        brand = self.brand

        if group == "edit":
            self.editing = value
            self.say(f"Pick a {value} colour.")
        elif group == "swatch":
            self._set_colour(branding.SWATCHES[int(value)])
        elif item_id == "hex:apply":
            # pressing Apply while still typing is handled by the commit above; this covers a box already filled in
            self._apply_hex()
        elif item_id == "colours:reset":
            if self._update(primary=None, accent=None):
                self.say("Colours reset to the default ynotPi look.")
        elif item_id == "logo:choose":
            self.chooser = LogoChooser()
            self.say("")
        elif item_id == "logo:remove" and brand.get("logo"):
            if self._update(logo=None):
                self.say("Logo removed.")
        elif group == "corner":
            if self._update(logo_corner=value):
                self.say("Logo moved to the " + value.replace("-", " ") + " corner.")
        elif group == "size":
            if self._update(logo_size=value):
                self.say(f"Logo size set to {value}.")
        elif group == "onphotos":
            show = value == "True"
            if self._update(logo_on_photos=show):
                self.say("Logo shown on photos." if show else "Logo hidden on photos (still shown on the info slides).")
        return None

    def _apply_hex(self):
        text = self.form.get("hex", "").strip()
        if not text:
            self.say("Type a colour first, like #1E5AA8.", False)
            return
        rgb = branding.parse_hex(text)
        if rgb is None:
            self.say("Not a valid colour — use 6 hex digits, like #1E5AA8.", False)
            return
        self.form["hex"] = ""
        self._set_colour(branding.to_hex(rgb))
