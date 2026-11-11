"""
ynotPi — core/sources_tab.py
----------------------------
The Photo Sources tab in the admin panel.

Top    : the three places photos come from (local folder / USB / network share).
         Focus one to see its photos; Enter (or clicking its ON/OFF) switches
         the whole source on or off.
Bottom : every photo found in the selected source, with a tick box each.
         Unticked = hidden, i.e. found but never shown on the frame. Moving
         through the list previews each photo on the right.

Hidden photos are saved in settings.json as "hidden_photos" (full paths) -
the files themselves are never touched.
"""

import os

import pygame

from core import photos
from core import settings as settings_store
from core import ui

SOURCE_ORDER = ["local", "usb", "network"]

NOTHING_FOUND = {
    "local": ["No photos in the local folder yet.", "Copy some into assets/photos, then press Refresh."],
    "usb": ["No USB drive with photos found.", "Plug one in, wait a few seconds, then press Refresh."],
    "network": ["The network folder isn't connected, or it's empty.", "Ask your technician to check the share."],
}


class SourcesTab(ui.Tab):
    name = "Photo Sources"
    hint = "Arrows: move    Enter: on / off, show / hide    Esc: back"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.selected = "local"
        self.files = None  # source -> list of full paths. None until the tab is first opened
        self.list = ui.ListView("photo")
        self.preview = ui.Preview()

    # ── data ──
    def opened(self, ui_):
        if self.files is None:
            self._scan()

    def _scan(self):
        # looking through a big network share can take a moment, so it's done when
        # the tab opens (and on Refresh), not every frame
        self.files = {source: photos.find_photos(source) for source in SOURCE_ORDER}

    def _hidden(self):
        return set(self.ctx.settings.get("hidden_photos") or [])

    def _save_hidden(self, hidden):
        self.ctx.settings["hidden_photos"] = sorted(hidden)
        if not self.ctx.save():
            self.say("Couldn't save that change — see the log in Technician mode.", False)
            return False
        return True

    def _counts(self, source, hidden):
        paths = self.files.get(source, []) if self.files else []
        return len(paths), sum(1 for path in paths if path in hidden)

    # ── drawing ──
    def draw(self, ui_, area):
        if self.files is None:
            self._scan()

        hidden = self._hidden()
        gap = ui_.pad
        body_h = ui_.fonts["body"].get_height()

        # focusing a source card selects it
        focus = str(ui_.focus)
        if focus.startswith("source:"):
            chosen = focus.split(":")[1]
            if chosen != self.selected:
                self.selected = chosen
                self.list.scroll = 0
                self.list.current = 0

        # ── the three source cards ──
        card_w = (area.width - 2 * gap) // 3
        card_h = body_h + 2 * (ui_.u + 4) + 2 * ui_.pad
        self._power_rects = {}

        for index, source in enumerate(SOURCE_ORDER):
            label, where, _ = photos.SOURCES[source]
            rect = pygame.Rect(area.x + index * (card_w + gap), area.y, card_w, card_h)
            state = ui_.register(f"source:{source}", rect)
            is_on = settings_store.is_source_enabled(self.ctx.settings, source)
            is_selected = source == self.selected
            colors = ui_.colors

            pygame.draw.rect(ui_.screen, colors["BUTTON_COLOR"] if state.hovered else colors["CARD_COLOR"], rect, border_radius=14)
            pygame.draw.rect(
                ui_.screen,
                colors["HIGHLIGHT_COLOR"] if is_selected else colors["CARD_BORDER"],
                rect, width=2 if is_selected else 1, border_radius=14,
            )

            # ON/OFF pill, top right - clicking it (rather than the rest of the card) flips the source
            pill_w = ui_.fonts["small"].size("OFF")[0] + 2 * ui_.pad
            pill = pygame.Rect(rect.right - ui_.pad - pill_w, rect.y + ui_.pad, pill_w, ui_.u + 6)
            self._power_rects[source] = pill.inflate(ui_.pad, ui_.pad)
            pygame.draw.rect(ui_.screen, ui.OK_COLOR if is_on else ui.OFF_COLOR, pill, border_radius=pill.height // 2)
            rendered = ui_.fonts["small"].render("ON" if is_on else "OFF", True, (15, 15, 15))
            ui_.screen.blit(rendered, rendered.get_rect(center=pill.center))

            text_w = rect.width - 2 * ui_.pad
            ui_.text(label, (rect.x + ui_.pad, rect.y + ui_.pad), "body", "TEXT_COLOR", max_w=text_w - pill_w - ui_.pad)
            y = rect.y + ui_.pad + body_h + 4
            ui_.text(where, (rect.x + ui_.pad, y), max_w=text_w, keep_end=True)

            total, hidden_count = self._counts(source, hidden)
            if total:
                summary = f"{total} photo{'s' if total != 1 else ''}"
                if hidden_count:
                    summary += f", {hidden_count} hidden"
            else:
                summary = "Nothing found" if source == "local" or photos.is_available(source) else "Not connected"
            ui_.text(summary, (rect.x + ui_.pad, y + ui_.u + 4), max_w=text_w)

        # ── heading + buttons for the selected source ──
        paths = self.files.get(self.selected, [])
        label = photos.SOURCES[self.selected][0]
        row_y = area.y + card_h + gap
        buttons = [("photos:refresh", "Refresh"), ("photos:hideall", "Hide all"), ("photos:showall", "Show all")]

        x = area.right
        for item_id, text in buttons:
            width = ui_.button_w(text, "small")
            x -= width
            enabled = item_id == "photos:refresh" or bool(paths)
            ui_.button(item_id, pygame.Rect(x, row_y, width, ui_.h_small), text, font="small", enabled=enabled)
            x -= max(6, gap // 2)

        heading = f"Photos in {label}"
        if not settings_store.is_source_enabled(self.ctx.settings, self.selected):
            heading += "  (this source is switched off)"
        ui_.text(heading, (area.x, row_y + (ui_.h_small - ui_.u) // 2), "small", "TEXT_COLOR", max_w=x - area.x - gap)

        # ── photo list (left) + preview (right) ──
        list_top = row_y + ui_.h_small + max(6, gap // 2)
        list_h = area.bottom - list_top
        if list_h < ui_.u * 3:
            return  # window too short to show a list at all

        list_w = int(area.width * 0.58)
        list_rect = pygame.Rect(area.x, list_top, list_w, list_h)
        preview_rect = pygame.Rect(list_rect.right + gap, list_top, area.right - list_rect.right - gap, list_h)
        row_h = ui_.u + ui_.pad
        box = ui_.u  # tick box size
        self._tick_right = list_rect.x + 5 + ui_.pad + box + ui_.pad // 2  # clicks left of this hit the tick box

        def draw_row(index, row_rect, state, selected):
            path = paths[index]
            shown = path not in hidden
            tick = pygame.Rect(row_rect.x + ui_.pad // 2 + 2, row_rect.y + (row_rect.height - box) // 2, box, box)
            ui_.checkbox(tick, shown)
            tag_w = ui_.fonts["small"].size("hidden")[0] + ui_.pad if not shown else 0
            name_x = tick.right + ui_.pad
            ui_.text(
                photos.short_name(self.selected, path),
                (name_x, row_rect.y + (row_rect.height - ui_.u) // 2),
                "small",
                "TEXT_COLOR" if shown else "SUBTEXT_COLOR",
                max_w=row_rect.right - name_x - tag_w - 6,
                keep_end=True,
            )
            if not shown:
                ui_.text("hidden", (row_rect.right - tag_w, row_rect.y + (row_rect.height - ui_.u) // 2), color=ui.WARN_COLOR)

        self.list.draw(ui_, list_rect, len(paths), row_h, draw_row, empty_lines=NOTHING_FOUND[self.selected])
        self._draw_preview(ui_, preview_rect, paths, hidden)

    def _draw_preview(self, ui_, rect, paths, hidden):
        colors = ui_.colors
        pygame.draw.rect(ui_.screen, colors["CARD_COLOR"], rect, border_radius=10)
        pygame.draw.rect(ui_.screen, colors["CARD_BORDER"], rect, width=1, border_radius=10)

        if not paths:
            return

        path = paths[self.list.current]
        caption_h = ui_.u + ui_.pad
        max_w = rect.width - 2 * ui_.pad
        max_h = rect.height - 2 * ui_.pad - caption_h
        if max_w < 20 or max_h < 20:
            return

        status, surface = self.preview.get(path, max_w, max_h)
        image_area = pygame.Rect(rect.x + ui_.pad, rect.y + ui_.pad, max_w, max_h)
        if status == "ok":
            ui_.screen.blit(surface, surface.get_rect(center=image_area.center))
        elif status == "loading":
            ui_.text("Loading preview...", (image_area.x, image_area.y))
        else:
            ui_.text("Can't open this file", (image_area.x, image_area.y), color=ui.ERROR_COLOR)

        caption = os.path.basename(path)
        colour = "SUBTEXT_COLOR"
        if path in hidden:
            caption = "Hidden — " + caption
            colour = ui.WARN_COLOR
        ui_.text(caption, (rect.x + ui_.pad, rect.bottom - caption_h), color=colour, max_w=max_w, keep_end=True)

    # ── actions ──
    def handle_action(self, action, ui_):
        if action[0] != "activate" or self.files is None:
            return None
        item_id, how = str(action[1]), action[2]
        hidden = self._hidden()
        paths = self.files.get(self.selected, [])

        if item_id.startswith("source:"):
            source = item_id.split(":")[1]
            self.selected = source
            # a click only flips the source if it landed on the ON/OFF pill - anywhere
            # else on the card just selects it. Enter/Space always flips.
            pill = getattr(self, "_power_rects", {}).get(source)
            if how == "click" and not (pill is not None and pill.collidepoint(ui_.click_pos)):
                return None
            turned_on = not settings_store.is_source_enabled(self.ctx.settings, source)
            self.ctx.settings["sources"][source] = turned_on
            if self.ctx.save():
                self.say(f"{photos.SOURCES[source][0]} turned {'on' if turned_on else 'off'}.")
            else:
                self.say("Couldn't save that change — see the log in Technician mode.", False)

        elif item_id == "photos:refresh":
            self._scan()
            total = sum(len(found) for found in self.files.values())
            self.say(f"Looked again — {total} photo{'s' if total != 1 else ''} found.")

        elif item_id == "photos:showall" and paths:
            if self._save_hidden(hidden - set(paths)):
                self.say(f"Every photo in {photos.SOURCES[self.selected][0]} will be shown.")

        elif item_id == "photos:hideall" and paths:
            if self._save_hidden(hidden | set(paths)):
                self.say(f"Every photo in {photos.SOURCES[self.selected][0]} is now hidden.")

        else:
            index = self.list.index_of(item_id)
            if index is None or index >= len(paths):
                return None
            # clicking a photo's name just selects it (for the preview) - the tick box flips it
            if how == "click" and ui_.click_pos[0] > getattr(self, "_tick_right", 0):
                return None
            path = paths[index]
            if path in hidden:
                hidden.discard(path)
                message = f"Showing {os.path.basename(path)}."
            else:
                hidden.add(path)
                message = f"Hidden {os.path.basename(path)} — it won't appear on the frame."
            if self._save_hidden(hidden):
                self.say(message)
        return None
