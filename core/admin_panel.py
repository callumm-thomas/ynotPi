"""
ynotPi — core/admin_panel.py
-----------------------------
In-app admin overlay for the photo frame.

Opened from the slideshow with a customisable hotkey (default F1), behind a PIN
(see access.py). The client PIN opens Admin mode; the technician PIN opens the
same plus a Technician tab (see technician.py).

Tabs:
- Content        every content type in a grid, flip each on/off        (this file)
- Photo Sources  where photos come from + hide individual photos        (sources_tab.py)
- Branding       brand colours + logo                                   (branding_tab.py)
- APIs           every feed's settings and keys, add/edit/delete        (apis_tab.py)
- Hotkey         rebind the key that opens this panel                   (this file)
- Technician     system info, PINs, log, power (technician PIN only)    (technician.py)

Every tab is drawn with the toolkit in ui.py, which is what makes the keyboard
and mouse work the same way on all of them:
    Left/Right on the tab bar picks a tab, Down goes into it, arrows move
    around, Enter/Space selects, Esc steps back out (and closes from the bar).

Nothing here talks to photoframe.py directly (it's imported by that module, not
the other way around) — the caller passes in the screen, fonts and color theme.
"""

import pygame

from core import access
from core import api_manager
from core import apis_tab
from core import branding_tab
from core import settings as settings_store
from core import sources_tab
from core import technician
from core import ui

# these used to live in this file - kept under the old names so anything that
# does admin_panel.load_settings() etc. carries on working
DEFAULT_SETTINGS = settings_store.DEFAULT_SETTINGS
load_settings = settings_store.load_settings
save_settings = settings_store.save_settings
resolve_key = settings_store.resolve_key
is_content_enabled = settings_store.is_content_enabled
is_source_enabled = settings_store.is_source_enabled

CONTENT_LABELS = {
    "photos": "Photos",
    "weather": "Weather",
    "crypto": "Crypto",
    "news": "News",
    "apod": "NASA APOD",
    "trivia": "Trivia",
}

# keys that can't be the admin hotkey: they already do something in the
# slideshow or the panel, or (Shift, Ctrl...) aren't reliable on their own
BLOCKED_HOTKEYS = {
    pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_TAB, pygame.K_BACKSPACE,
    pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, pygame.K_r,
    pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_LCTRL, pygame.K_RCTRL, pygame.K_LALT, pygame.K_RALT,
    pygame.K_LGUI, pygame.K_RGUI, pygame.K_CAPSLOCK,
}


class Context:
    """The bits every tab shares."""

    def __init__(self, settings, colors, is_technician, dev_mode):
        self.settings = settings            # one dict, edited in place by the tabs
        self.colors = colors                # the panel's colours - Branding updates these live
        self.is_technician = is_technician
        self.dev_mode = dev_mode

    def save(self):
        """Write settings.json. Returns True if it saved."""
        return save_settings(self.settings)


# ─── CONTENT TAB ───────────────────────────────────────────────────────────────
class ContentTab(ui.Tab):
    name = "Content"
    hint = "Arrows: move    Enter: turn on / off    Esc: back"

    def _items(self):
        """(id, label, key, custom name or None, note) for every tile."""
        items = []
        for key, label in CONTENT_LABELS.items():
            key_name, required = api_manager.BUILTIN_KEYS.get(key, (None, False))
            note = "No key set" if (required and not api_manager.has_key(key_name)) else ""
            items.append((f"content:{key}", label, key, None, note))

        for index, config in enumerate(api_manager.load_custom_api_configs()):
            name = config.get("name", "custom")
            key_name = config.get("key_name")
            note = "No key set" if (key_name and not api_manager.has_key(key_name)) else ""
            items.append((f"content:custom:{index}", name, name, name, note))
        return items

    def draw(self, ui_, area):
        self._current = self._items()  # remembered so a click/Enter acts on exactly what was drawn
        count = len(self._current)
        gap = ui_.pad
        tile_h = ui_.fonts["body"].get_height() + ui_.u + 6 + 3 * ui_.pad

        # as many columns as fit comfortably - but squeeze in more (narrower tiles)
        # if that's what it takes to get every tile on screen
        columns = max(1, (area.width + gap) // (11 * ui_.u + gap))
        rows_that_fit = max(1, (area.height + gap) // (tile_h + gap))
        max_columns = max(columns, (area.width + gap) // (7 * ui_.u + gap))
        while columns < max_columns and columns * rows_that_fit < count:
            columns += 1
        tile_w = (area.width - gap * (columns - 1)) // columns

        for index, (item_id, label, key, custom_name, note) in enumerate(self._current):
            col, row = index % columns, index // columns
            if row >= rows_that_fit:
                break
            rect = pygame.Rect(area.x + col * (tile_w + gap), area.y + row * (tile_h + gap), tile_w, tile_h)
            enabled = is_content_enabled(self.ctx.settings, key, custom_name)
            ui_.tile(item_id, rect, label, enabled, note=note if enabled else "")

    def handle_action(self, action, ui_):
        if action[0] != "activate":
            return None
        for item_id, label, key, custom_name, _ in getattr(self, "_current", []):
            if item_id != action[1]:
                continue
            content = self.ctx.settings["content"]
            turned_on = not is_content_enabled(self.ctx.settings, key, custom_name)
            if custom_name is not None:
                content.setdefault("custom", {})[custom_name] = turned_on
            else:
                content[key] = turned_on
            if self.ctx.save():
                self.say(f"{label} turned {'on' if turned_on else 'off'}.")
            else:
                self.say("Couldn't save that change — see the log in Technician mode.", False)
        return None


# ─── HOTKEY TAB ────────────────────────────────────────────────────────────────
class HotkeyTab(ui.Tab):
    name = "Hotkey"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.waiting = False  # True = the next key press becomes the hotkey

    def opened(self, ui_):
        self.waiting = False

    def draw(self, ui_, area):
        current = str(self.ctx.settings.get("admin_hotkey", "f1")).upper()
        ui_.text(f"Current hotkey: {current}", (area.x, area.y), "body", "TEXT_COLOR")

        label = "Press a key..." if self.waiting else "Change hotkey"
        width = max(ui_.button_w("Press a key..."), ui_.button_w("Change hotkey"))
        rect = pygame.Rect(area.x, area.y + ui_.fonts["body"].get_height() + ui_.u, width, ui_.h_body)
        ui_.button("hotkey:change", rect, label, active=self.waiting)

        ui_.paragraph(
            "This is the key that opens this panel from the slideshow. "
            "Pick one that won't get pressed by accident — an F key works well.",
            (area.x, rect.bottom + ui_.u),
            min(area.width, 34 * ui_.u),
        )

    def handle_action(self, action, ui_):
        if action[0] == "activate" and action[1] == "hotkey:change":
            self.waiting = True
            self.say("Press the key you want to use  (Esc to cancel).")
        return None

    def escape(self, ui_):
        if self.waiting:
            self.waiting = False
            self.say("Hotkey not changed.")
            return True
        return False

    def handle_raw(self, event, ui_):
        if not self.waiting:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN:
            self.waiting = False  # clicked somewhere instead - call it off, and let the click through
            self.say("Hotkey not changed.")
            return False

        if event.type != pygame.KEYDOWN:
            return False

        self.waiting = False
        if event.key == pygame.K_ESCAPE:
            self.say("Hotkey not changed.")
            return True

        name = pygame.key.name(event.key)
        if event.key in BLOCKED_HOTKEYS or not name:
            self.say("That key is already used for something else — pick another (an F key works well).", False)
            return True

        # make sure the saved name turns back into the same key when the app next starts
        try:
            round_trips = pygame.key.key_code(name) == event.key
        except Exception:
            round_trips = False
        if not round_trips:
            self.say("That key can't be used as the hotkey — pick another.", False)
            return True

        self.ctx.settings["admin_hotkey"] = name
        if self.ctx.save():
            self.say(f"Hotkey set to {name.upper()}.")
        else:
            self.say("Couldn't save that change — see the log in Technician mode.", False)
        return True


# ─── MAIN PANEL ────────────────────────────────────────────────────────────────
def _layout_tab_bar(ui_, tabs, screen_w, margin):
    """Work out where the tab buttons + Close go. Returns (font name, [rects], close rect)."""
    close_w = ui_.button_w("Close", "small")
    gap = max(6, ui_.pad // 2)
    room = screen_w - 2 * margin - close_w - gap * 2

    # with every tab showing, the bar can get wider than a small window - drop to the small font if so
    font = "body"
    if sum(ui_.button_w(tab.name, "body") + gap for tab in tabs) > room:
        font = "small"

    height = ui_.h_body
    rects = []
    x = margin
    for tab in tabs:
        width = ui_.button_w(tab.name, font)
        rects.append(pygame.Rect(x, ui_.u, width, height))
        x += width + gap

    close_rect = pygame.Rect(screen_w - margin - close_w, ui_.u, close_w, height)
    return font, rects, close_rect


def run_admin_panel(screen, fonts, colors, dev_mode=False):
    """
    Blocking loop for the admin overlay. Asks for a PIN first, then runs its
    own event loop until the user closes it (Esc from the tab bar, or Close).

    Returns "restart" or "exit" if a Technician action needs the app to do
    that, otherwise None. Either way the caller should reload settings and
    rebuild its slide queue afterwards.
    """
    level = access.prompt_for_pin(screen, fonts, colors)
    if level is None:
        return None  # cancelled or wrong PIN - straight back to the slideshow

    is_technician = level == access.TECHNICIAN
    ctx = Context(load_settings(), colors, is_technician, dev_mode)

    tabs = [
        ContentTab(ctx),
        sources_tab.SourcesTab(ctx),
        branding_tab.BrandingTab(ctx),
        apis_tab.ApisTab(ctx),
        HotkeyTab(ctx),
    ]
    if is_technician:
        tabs.append(technician.TechnicianTab(ctx))
    panel_title = "Technician Mode" if is_technician else "Admin Panel"

    # in dev mode the normal system mouse pointer is showing, so we don't draw our own
    ui_ = ui.UI(colors, draw_pointer=not dev_mode)

    # holding a key down repeats it while the panel is open (arrows through a
    # list, backspace in a text box) - put back how it was on the way out
    try:
        old_repeat = pygame.key.get_repeat()
        pygame.key.set_repeat(400, 40)
    except Exception:
        old_repeat = None

    try:
        return _panel_loop(ui_, tabs, panel_title, fonts, colors)
    finally:
        try:
            if old_repeat and old_repeat[0]:
                pygame.key.set_repeat(*old_repeat)
            else:
                pygame.key.set_repeat()  # no arguments = repeat off
        except Exception:
            pass
        pygame.event.clear()  # don't let a leftover key press leak into the slideshow


def _panel_loop(ui_, tabs, panel_title, fonts, colors):
    active = 0
    result = None
    running = True
    clock = pygame.time.Clock()

    def switch_to(index):
        nonlocal active
        active = index
        ui_.stop_editing()
        ui_.scope = tabs[index].name
        ui_.tab_anchor = f"tab:{index}"
        tabs[index].opened(ui_)

    switch_to(0)
    ui_.set_focus("tab:0")

    # key presses / clicks still waiting their turn (see below)
    waiting = []
    INPUT_EVENTS = (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL, pygame.TEXTINPUT)

    while running:
        tab = tabs[active]

        # ── events ──
        # Only ONE key press / click is handled per frame - the rest wait for the
        # next one. Each press can change what's on screen (a new tab opens, the
        # form beside a list changes), and the next press has to act on that new
        # screen, not the old one. At 30 frames a second nobody can type faster.
        incoming = waiting + pygame.event.get()
        waiting = []
        events = []
        for position, event in enumerate(incoming):
            events.append(event)
            if event.type in INPUT_EVENTS:
                waiting = incoming[position + 1:]
                break

        for event in events:
            if event.type == pygame.QUIT:
                running = False
                continue

            # key releases always go to the toolkit (it tracks which keys are held)
            if event.type != pygame.KEYUP and tab.handle_raw(event, ui_):
                continue

            for action in ui_.handle_event(event):
                kind = action[0]
                target = action[1] if len(action) > 1 else None

                if kind == "escape":
                    focused = ui_.item(ui_.focus)
                    if tab.escape(ui_):
                        pass  # the tab closed something of its own
                    elif focused is not None and focused.group == "content":
                        ui_.set_focus(ui_.tab_anchor)  # step back up to the tab bar
                    else:
                        running = False
                elif kind == "activate" and target == "close":
                    running = False
                elif kind == "activate" and str(target).startswith("tab:"):
                    index = int(str(target).split(":")[1])
                    if index != active:
                        switch_to(index)
                        tab = tabs[active]
                else:
                    outcome = tab.handle_action(action, ui_)
                    if outcome:  # only the Technician tab ever returns one (restart / exit)
                        result = outcome
                        running = False

        # moving along the tab bar with Left/Right opens each tab as you land on it
        if running and str(ui_.focus).startswith("tab:"):
            index = int(str(ui_.focus).split(":")[1])
            if index != active and index < len(tabs):
                switch_to(index)
        tab = tabs[active]

        # ── draw ──
        screen = pygame.display.get_surface()  # re-read every frame so it follows a dev-mode window resize
        screen_w, screen_h = screen.get_size()
        screen.fill(colors["BACKGROUND_COLOR"])
        ui_.begin(screen, fonts)

        margin = max(40, screen_w // 25)
        tab_font, tab_rects, close_rect = _layout_tab_bar(ui_, tabs, screen_w, margin)
        for index, rect in enumerate(tab_rects):
            ui_.button(f"tab:{index}", rect, tabs[index].name, font=tab_font, active=(index == active), group="tabs")
        ui_.button("close", close_rect, "Close", font="small", group="tabs")

        # footer: panel title bottom-left, key hints bottom-right, status line just above
        title_font = fonts["title"]
        title_y = screen_h - title_font.get_height() - ui_.pad
        ui_.text(panel_title, (margin, title_y), "title", "TEXT_COLOR")

        hint_room = screen_w - 2 * margin - title_font.size(panel_title)[0] - 2 * ui_.u
        hint = ui.fit_text(tab.hint, fonts["small"], hint_room)
        hint_w = fonts["small"].size(hint)[0]
        ui_.text(hint, (screen_w - margin - hint_w, screen_h - ui_.u - ui_.pad - 4))

        status_y = title_y - ui_.u - ui_.pad
        if tab.status:
            ui_.text(
                tab.status, (margin, status_y), "small",
                "HIGHLIGHT_COLOR" if tab.status_ok else ui.ERROR_COLOR,
                max_w=screen_w - 2 * margin,
            )

        top = tab_rects[0].bottom + ui_.u
        area = pygame.Rect(margin, top, screen_w - 2 * margin, status_y - ui_.pad - top)
        tab.draw(ui_, area)

        ui_.end()
        pygame.display.flip()

        # slow jobs (town look-up, update, reboot) run here, after their "please wait" message is showing
        outcome = tab.tick()
        if outcome:
            result = outcome
            running = False

        clock.tick(30)

    return result
