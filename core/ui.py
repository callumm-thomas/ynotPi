"""
ynotPi — core/ui.py
-------------------
The small UI toolkit every admin panel tab is built from, so keyboard and
mouse behave the same way everywhere.

How it works (one frame):
1. begin()   - start a new frame
2. the tab draws itself by calling button() / tile() / text_input() / ...
   Each call draws the control AND registers it as something that can be
   focused, clicked or typed into.
3. end()     - draws the focus ring + mouse pointer
4. handle_event() is then fed the keyboard/mouse events. It works out what
   they mean using the controls registered in step 2 - i.e. exactly what's on
   screen - and hands back a list of actions like ("activate", "save").

Keyboard:
- arrows move the focus to the nearest control in that direction
- Enter / Space use the focused control (or start typing in a text box)
- Esc goes back a step (stops typing -> back to the tab bar -> closes the panel)
Mouse:
- click anything, scroll wheel scrolls lists
- the pointer is drawn by us (see draw_pointer) because the slideshow hides
  the system one

Sizes are worked out from the fonts rather than fixed pixels, so the layout
holds together from the 1024x720 dev window up to a 1080p screen.
"""

import pygame

ERROR_COLOR = (230, 120, 110)
OK_COLOR = (110, 210, 130)
WARN_COLOR = (230, 180, 90)
OFF_COLOR = (210, 100, 100)

ENTER_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER)
ARROWS = {
    pygame.K_LEFT: (-1, 0),
    pygame.K_RIGHT: (1, 0),
    pygame.K_UP: (0, -1),
    pygame.K_DOWN: (0, 1),
}
# keys that are allowed to auto-repeat when held down. Everything else (Enter,
# Space, Esc...) only counts once per press, so holding Enter can't flip a
# setting on and off over and over.
REPEATING_KEYS = set(ARROWS) | {pygame.K_BACKSPACE, pygame.K_DELETE, pygame.K_PAGEUP, pygame.K_PAGEDOWN}


# ─── TEXT HELPERS ──────────────────────────────────────────────────────────────
def fit_text(text, font, max_w, keep_end=False):
    """Shorten text with '...' so it fits max_w. keep_end=True cuts from the front (good for file paths)."""
    text = str(text)
    if max_w <= 0:
        return ""
    if font.size(text)[0] <= max_w:
        return text
    dots = "..."
    if keep_end:
        while text and font.size(dots + text)[0] > max_w:
            text = text[1:]
        return dots + text
    while text and font.size(text + dots)[0] > max_w:
        text = text[:-1]
    return text + dots


def wrap_lines(text, font, max_w):
    """Split text into lines that each fit max_w."""
    lines = []
    current = ""
    for word in str(text).split():
        test = word if not current else current + " " + word
        if font.size(test)[0] <= max_w or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def printable(event):
    """The character a key press types, or '' for keys like Enter / arrows / F1."""
    char = getattr(event, "unicode", "") or ""
    if len(char) == 1 and char.isprintable():
        return char
    return ""


class Item:
    """One control on screen that can take focus / be clicked."""

    def __init__(self, item_id, rect, group, kind, opts):
        self.id = item_id
        self.rect = rect
        self.group = group  # "tabs" (the bar along the top) or "content"
        self.kind = kind    # "button", "text" or "row"
        self.opts = opts


class State:
    """What a control needs to know to draw itself this frame."""

    def __init__(self, focused, hovered):
        self.focused = focused
        self.hovered = hovered


# ─── SCROLLING LIST ────────────────────────────────────────────────────────────
class ListView:
    """
    A scrolling list of rows (photos, APIs, logo files). Each visible row is a
    focusable item with the id "<prefix>:<row number>". Up/Down walk the rows
    and scroll when they reach the edge; the mouse wheel scrolls too.

    `current` is the row that was last focused - the tab uses it as "the
    selected one" (e.g. which photo to preview).
    """

    def __init__(self, prefix):
        self.prefix = prefix
        self.scroll = 0
        self.count = 0
        self.visible = 1
        self.current = 0
        self.rect = None

    def row_id(self, index):
        return f"{self.prefix}:{index}"

    def index_of(self, item_id):
        """Row number for one of this list's ids, or None if the id belongs to something else."""
        if not item_id:
            return None
        prefix, _, number = str(item_id).rpartition(":")
        if prefix == self.prefix and number.isdigit():
            return int(number)
        return None

    def _clamp(self):
        self.scroll = max(0, min(max(0, self.count - self.visible), self.scroll))
        self.current = max(0, min(max(0, self.count - 1), self.current))

    def ensure_visible(self, index):
        if index < self.scroll:
            self.scroll = index
        elif index >= self.scroll + self.visible:
            self.scroll = index - self.visible + 1
        self._clamp()

    def scroll_by(self, rows):
        self.scroll += rows
        self._clamp()

    def draw(self, ui, rect, count, row_h, draw_row, empty_lines=()):
        """
        draw_row(index, row_rect, state, selected) draws one row's contents.
        empty_lines is shown instead when there are no rows.
        """
        colors = ui.colors
        self.rect = rect
        self.count = count
        self.visible = max(1, (rect.height - 10) // row_h)
        self._clamp()
        ui.lists[self.prefix] = self

        pygame.draw.rect(ui.screen, colors["CARD_COLOR"], rect, border_radius=10)
        pygame.draw.rect(ui.screen, colors["CARD_BORDER"], rect, width=1, border_radius=10)

        if count == 0:
            y = rect.y + ui.pad
            for line in empty_lines:
                for wrapped in wrap_lines(line, ui.fonts["small"], rect.width - 2 * ui.pad):
                    ui.text(wrapped, (rect.x + ui.pad, y))
                    y += ui.u + 4
            return

        needs_bar = count > self.visible
        bar_w = 8 if needs_bar else 0
        focus_index = self.index_of(ui.focus)

        for row in range(min(self.visible, count - self.scroll)):
            index = self.scroll + row
            row_rect = pygame.Rect(rect.x + 5, rect.y + 5 + row * row_h, rect.width - 10 - bar_w, row_h - 2)
            state = ui.register(self.row_id(index), row_rect, kind="row")
            selected = index == (focus_index if focus_index is not None else self.current)
            if selected:
                pygame.draw.rect(ui.screen, colors["BUTTON_HOVER"], row_rect, border_radius=6)
            elif state.hovered:
                pygame.draw.rect(ui.screen, colors["BUTTON_COLOR"], row_rect, border_radius=6)
            draw_row(index, row_rect, state, selected)

        if needs_bar:
            track = pygame.Rect(rect.right - 5 - bar_w, rect.y + 6, bar_w, rect.height - 12)
            thumb_h = max(20, track.height * self.visible // count)
            thumb_y = track.y + (track.height - thumb_h) * self.scroll // max(1, count - self.visible)
            pygame.draw.rect(ui.screen, colors["CARD_BORDER"], pygame.Rect(track.x, thumb_y, bar_w, thumb_h), border_radius=4)


# ─── THE TOOLKIT ───────────────────────────────────────────────────────────────
class UI:
    def __init__(self, colors, draw_pointer=True):
        self.colors = colors            # shared with the panel - Branding updates it in place
        self.draw_pointer = draw_pointer

        self.screen = None
        self.fonts = None
        self.u = 20                     # layout unit = height of the small font
        self.pad = 12

        self.items = []                 # controls from the last finished frame (what's on screen)
        self.lists = {}
        self._new_items = []
        self._new_lists = {}

        self._focus = None              # id of the focused control (see the focus property)
        self._focus_rect = None         # where it was, for picking a neighbour if it disappears
        self.tab_anchor = None          # id of the active tab's button - where Up / Esc lead back to
        self.scope = ""                 # name of the open tab (focus inside each tab is remembered)
        self._remembered = {}

        self.edit = None                # the text box being typed in (dict), or None
        self.mouse = (0, 0)
        self._pointer_seen = False      # the mouse has moved at least once -> draw the pointer
        self._pointer_active = False    # the mouse moved more recently than a key press -> show hover
        self._held = set()              # keys currently down, to tell a fresh press from auto-repeat
        self.click_pos = (0, 0)         # where the last click landed (rows use it for their checkbox)

    # ── focus (a property so lists know their selected row straight away) ──
    @property
    def focus(self):
        return self._focus

    @focus.setter
    def focus(self, item_id):
        self._focus = item_id
        # a list row got focus: make it the list's selected row now, not at the end of
        # the frame - otherwise whatever depends on the selection (the form beside the
        # API list, the photo preview) would be a frame behind the key presses
        for view in self.lists.values():
            index = view.index_of(item_id)
            if index is not None:
                view.current = index

    # ── frame ──
    def begin(self, screen, fonts):
        self.screen = screen
        self.fonts = fonts
        self.u = fonts["small"].get_height()
        self.pad = max(8, round(self.u * 0.6))
        self._new_items = []
        self._new_lists = {}
        self.lists = self._new_lists  # ListView.draw registers into this
        self.mouse = pygame.mouse.get_pos()

    def end(self):
        self.items = self._new_items
        self._fix_focus()

        focused = self.item(self.focus)
        if focused:
            self._focus_rect = focused.rect.copy()
            if focused.group == "content":
                self._remembered[self.scope] = focused.id
            for view in self.lists.values():
                index = view.index_of(focused.id)
                if index is not None:
                    view.current = index
            self._draw_focus_ring(focused)

        if self.draw_pointer and self._pointer_seen:
            self._draw_pointer()

    # ── sizes ──
    @property
    def h_body(self):
        """Height of a normal button / text box."""
        return self.fonts["body"].get_height() + round(self.u * 0.8)

    @property
    def h_small(self):
        """Height of a small button."""
        return self.u + round(self.pad * 1.4)

    def button_w(self, label, font="body"):
        return self.fonts[font].size(label)[0] + 2 * self.pad + 8

    # ── plain drawing ──
    def text(self, text, pos, font="small", color="SUBTEXT_COLOR", max_w=None, keep_end=False):
        """Draw one line of text. color is a palette name or an (r, g, b)."""
        font_obj = self.fonts[font]
        if max_w is not None:
            text = fit_text(text, font_obj, max_w, keep_end)
        rgb = self.colors[color] if isinstance(color, str) else color
        self.screen.blit(font_obj.render(str(text), True, rgb), (int(pos[0]), int(pos[1])))

    def paragraph(self, text, pos, max_w, font="small", color="SUBTEXT_COLOR", max_lines=None):
        """Draw wrapped text. Returns the y just below it."""
        font_obj = self.fonts[font]
        lines = wrap_lines(text, font_obj, max_w)
        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = fit_text(lines[-1] + " ...", font_obj, max_w)
        y = int(pos[1])
        for line in lines:
            self.text(line, (pos[0], y), font, color)
            y += font_obj.get_height() + 4
        return y

    def checkbox(self, rect, checked):
        pygame.draw.rect(self.screen, self.colors["BACKGROUND_COLOR"], rect, border_radius=5)
        pygame.draw.rect(self.screen, self.colors["SUBTEXT_COLOR"], rect, width=2, border_radius=5)
        if checked:
            x, y, s = rect.x, rect.y, rect.width
            points = [
                (int(x + s * 0.22), int(y + s * 0.52)),
                (int(x + s * 0.43), int(y + s * 0.72)),
                (int(x + s * 0.78), int(y + s * 0.28)),
            ]
            pygame.draw.line(self.screen, OK_COLOR, points[0], points[1], 3)
            pygame.draw.line(self.screen, OK_COLOR, points[1], points[2], 3)

    # ── controls ──
    def register(self, item_id, rect, kind="button", group="content", **opts):
        """Make a rectangle focusable/clickable. Returns its State for drawing."""
        self._new_items.append(Item(item_id, rect, group, kind, opts))
        hovered = self._pointer_active and rect.collidepoint(self.mouse)
        return State(self.focus == item_id, hovered)

    def button(self, item_id, rect, label, font="body", active=False, group="content", enabled=True, warn=False):
        """
        A push button. active=True draws it as "the chosen one" (current tab, selected size...).
        A disabled button is drawn greyed out and can't be focused.
        """
        colors = self.colors
        state = self.register(item_id, rect, "button", group) if enabled else State(False, False)

        bg = colors["BUTTON_HOVER"] if (active or state.hovered) else colors["BUTTON_COLOR"]
        pygame.draw.rect(self.screen, bg, rect, border_radius=10)
        if active or warn:
            pygame.draw.rect(self.screen, WARN_COLOR if warn else colors["HIGHLIGHT_COLOR"], rect, width=2, border_radius=10)

        font_obj = self.fonts[font]
        label = fit_text(label, font_obj, rect.width - 12)
        rendered = font_obj.render(label, True, colors["TEXT_COLOR"] if enabled else colors["SUBTEXT_COLOR"])
        self.screen.blit(rendered, rendered.get_rect(center=rect.center))
        return state

    def tile(self, item_id, rect, label, is_on, note=""):
        """A card with a name and an ON / OFF pill. Enter / click flips it (the tab does the flipping)."""
        colors = self.colors
        state = self.register(item_id, rect, "button")

        pygame.draw.rect(self.screen, colors["BUTTON_COLOR"] if state.hovered else colors["CARD_COLOR"], rect, border_radius=14)
        pygame.draw.rect(self.screen, colors["CARD_BORDER"], rect, width=1, border_radius=14)

        self.text(label, (rect.x + self.pad, rect.y + self.pad), "body", "TEXT_COLOR", max_w=rect.width - 2 * self.pad)

        pill_w = self.fonts["small"].size("OFF")[0] + 2 * self.pad
        pill = pygame.Rect(rect.x + self.pad, rect.bottom - self.pad - self.u - 6, pill_w, self.u + 6)
        pygame.draw.rect(self.screen, OK_COLOR if is_on else OFF_COLOR, pill, border_radius=pill.height // 2)
        rendered = self.fonts["small"].render("ON" if is_on else "OFF", True, (15, 15, 15))
        self.screen.blit(rendered, rendered.get_rect(center=pill.center))

        if note:
            self.text(note, (pill.right + self.pad, pill.y + 3), max_w=rect.right - pill.right - 2 * self.pad)
        return state

    def text_input(self, item_id, rect, store, key, placeholder="", mask=None, allowed=None,
                   max_len=300, upper=False, start_blank=False, dots=False):
        """
        A one-line text box showing store[key]. Typing doesn't touch the store
        until the edit is confirmed (Enter / Tab / clicking away) - then
        handle_event returns ("commit", id, old value). Esc throws the edit away.

        mask        : function(value) -> what to show while NOT typing (hiding API keys)
        allowed     : if set, only these characters can be typed
        start_blank : typing starts from an empty box rather than the current
                      value (for hidden keys). Confirming it empty changes nothing.
        dots        : show a dot per character, even while typing (PINs)
        """
        colors = self.colors
        state = self.register(
            item_id, rect, "text", store=store, key=key, allowed=allowed,
            max_len=max_len, upper=upper, start_blank=start_blank,
        )
        editing = self.edit is not None and self.edit["id"] == item_id

        pygame.draw.rect(self.screen, colors["CARD_COLOR"], rect, border_radius=8)
        border = colors["HIGHLIGHT_COLOR"] if editing else colors["CARD_BORDER"]
        pygame.draw.rect(self.screen, border, rect, width=2, border_radius=8)

        font_obj = self.fonts["body"]
        inner = rect.inflate(-2 * self.pad, -6)
        text_y = rect.y + (rect.height - font_obj.get_height()) // 2

        if editing:
            shown = self.edit["buf"]
            caret = self.edit["caret"]
            if dots:
                shown = "•" * len(shown)
            caret_x = font_obj.size(shown[:caret])[0]
            offset = max(0, caret_x - inner.width + 4)  # slide long text left so the caret stays in view

            old_clip = self.screen.get_clip()
            self.screen.set_clip(inner)
            self.screen.blit(font_obj.render(shown, True, colors["TEXT_COLOR"]), (inner.x - offset, text_y))
            if (pygame.time.get_ticks() // 500) % 2 == 0:
                x = inner.x - offset + caret_x
                pygame.draw.line(self.screen, colors["TEXT_COLOR"], (x, rect.y + 7), (x, rect.bottom - 8), 2)
            self.screen.set_clip(old_clip)
        else:
            value = str(store.get(key) or "")
            if dots:
                shown = "•" * len(value)
            else:
                shown = mask(value) if (mask and value) else value
            if shown:
                self.text(shown, (inner.x, text_y), "body", "TEXT_COLOR", max_w=inner.width)
            elif placeholder:
                self.text(placeholder, (inner.x, text_y), "body", "SUBTEXT_COLOR", max_w=inner.width)
        return state

    def is_editing(self, item_id=None):
        if self.edit is None:
            return False
        return item_id is None or self.edit["id"] == item_id

    def stop_editing(self):
        """Throw away whatever is being typed (used when the form underneath changes)."""
        self.edit = None

    # ── focus ──
    def item(self, item_id):
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def set_focus(self, item_id):
        self.focus = item_id

    def _fix_focus(self):
        """If the focused control isn't on screen any more, move to the nearest one that is."""
        if self.focus is not None and self.item(self.focus) is not None:
            return

        # typing in a box that's gone? stop
        self.edit = None

        if self.focus is not None and self._focus_rect is not None:
            was_tab = str(self.focus).startswith("tab:") or self.focus == "close"
            group = "tabs" if was_tab else "content"
            candidates = [item for item in self.items if item.group == group]
            if candidates:
                cx, cy = self._focus_rect.center
                best = min(candidates, key=lambda it: abs(it.rect.centerx - cx) + abs(it.rect.centery - cy))
                self.focus = best.id
                return

        self.focus = self.tab_anchor

    def _nearest(self, current, dx, dy, group):
        """The closest control in a direction, or None. Only looks at controls fully past the current one's edge."""
        cur = current.rect
        best = None
        best_score = None

        for item in self.items:
            if item.id == current.id or item.group != group:
                continue
            r = item.rect

            if dx:
                gap = r.left - cur.right if dx > 0 else cur.left - r.right
                side_gap = max(0, max(r.top - cur.bottom, cur.top - r.bottom))
                off_centre = abs(r.centery - cur.centery)
            else:
                gap = r.top - cur.bottom if dy > 0 else cur.top - r.bottom
                side_gap = max(0, max(r.left - cur.right, cur.left - r.right))
                off_centre = abs(r.centerx - cur.centerx)

            if gap < -2:
                continue  # not in that direction

            # mostly "how far in that direction", with a penalty for being off to the side
            score = max(0, gap) + 2 * side_gap + 0.01 * off_centre
            if best_score is None or score < best_score:
                best, best_score = item, score

        return best

    def _enter_content(self):
        """Down from the tab bar: go to where you last were in this tab, or its top-left control."""
        remembered = self.item(self._remembered.get(self.scope))
        if remembered is not None and remembered.group == "content":
            self.focus = remembered.id
            return
        content = [item for item in self.items if item.group == "content"]
        if content:
            self.focus = min(content, key=lambda it: (it.rect.y, it.rect.x)).id

    def _list_of(self, item_id):
        for view in self.lists.values():
            index = view.index_of(item_id)
            if index is not None:
                return view, index
        return None, None

    def _move(self, dx, dy):
        current = self.item(self.focus)
        if current is None:
            self.focus = self.tab_anchor
            return

        # inside a list, Up/Down step through every row (scrolling as needed), not just the visible ones
        view, index = self._list_of(current.id)
        if view is not None and dy:
            target = index + dy
            if 0 <= target < view.count:
                view.ensure_visible(target)
                self.focus = view.row_id(target)
                return

        if current.group == "tabs":
            if dy > 0:
                self._enter_content()
                return
            if dy < 0:
                return

        best = self._nearest(current, dx, dy, current.group)
        if best is None:
            if current.group == "content" and dy < 0:
                self.focus = self.tab_anchor  # nothing above -> back up to the tab bar
            return

        # arriving at a list from outside it: land on its selected row, not whichever row is level with us
        target_view, _ = self._list_of(best.id)
        if target_view is not None and target_view is not view and target_view.count:
            target_view.ensure_visible(target_view.current)
            self.focus = target_view.row_id(target_view.current)
            return

        self.focus = best.id

    def _page(self, direction):
        """PageUp / PageDown / Home / End inside a list. Returns True if it did something."""
        view, index = self._list_of(self.focus)
        if view is None or not view.count:
            return False
        if direction == "home":
            target = 0
        elif direction == "end":
            target = view.count - 1
        else:
            target = max(0, min(view.count - 1, index + direction * view.visible))
        view.ensure_visible(target)
        self.focus = view.row_id(target)
        return True

    # ── typing ──
    def _start_edit(self, item, first_char=""):
        opts = item.opts
        value = str(opts["store"].get(opts["key"]) or "")
        buf = "" if opts["start_blank"] else value
        self.edit = {
            "id": item.id, "store": opts["store"], "key": opts["key"], "orig": value,
            "buf": buf, "caret": len(buf), "allowed": opts["allowed"],
            "max_len": opts["max_len"], "upper": opts["upper"], "start_blank": opts["start_blank"],
        }
        self.focus = item.id
        if first_char:
            self._type(first_char)

    def _type(self, char):
        edit = self.edit
        if edit["upper"]:
            char = char.upper()
        if edit["allowed"] is not None and char not in edit["allowed"]:
            return
        if len(edit["buf"]) >= edit["max_len"]:
            return
        caret = edit["caret"]
        edit["buf"] = edit["buf"][:caret] + char + edit["buf"][caret:]
        edit["caret"] = caret + 1

    def _finish_edit(self, keep):
        """Close the text box. Returns the action to report."""
        edit, self.edit = self.edit, None
        if not keep:
            return ("cancel", edit["id"])
        if edit["start_blank"] and not edit["buf"]:
            return ("cancel", edit["id"])  # nothing typed over a hidden value = leave it alone
        if edit["buf"] == edit["orig"]:
            return ("cancel", edit["id"])  # unchanged - nothing to save
        edit["store"][edit["key"]] = edit["buf"]
        return ("commit", edit["id"], edit["orig"])

    def _edit_key(self, event, repeat):
        """A key press while typing. Returns a list of actions."""
        edit = self.edit
        key = event.key

        if key == pygame.K_ESCAPE:
            return [] if repeat else [self._finish_edit(False)]
        if key in ENTER_KEYS:
            return [] if repeat else [self._finish_edit(True)]
        if key == pygame.K_TAB:
            if repeat:
                return []
            actions = [self._finish_edit(True)]
            self._focus_next_text(edit["id"])
            return actions
        if key in (pygame.K_UP, pygame.K_DOWN):
            # leaving the box with Up/Down keeps what was typed, same as clicking away
            actions = [self._finish_edit(True)]
            self._move(*ARROWS[key])
            return actions

        if key == pygame.K_LEFT:
            edit["caret"] = max(0, edit["caret"] - 1)
        elif key == pygame.K_RIGHT:
            edit["caret"] = min(len(edit["buf"]), edit["caret"] + 1)
        elif key == pygame.K_HOME:
            edit["caret"] = 0
        elif key == pygame.K_END:
            edit["caret"] = len(edit["buf"])
        elif key == pygame.K_BACKSPACE:
            if edit["caret"] > 0:
                caret = edit["caret"]
                edit["buf"] = edit["buf"][:caret - 1] + edit["buf"][caret:]
                edit["caret"] = caret - 1
        elif key == pygame.K_DELETE:
            caret = edit["caret"]
            edit["buf"] = edit["buf"][:caret] + edit["buf"][caret + 1:]
        else:
            char = printable(event)
            if char:
                self._type(char)
        return []

    def _focus_next_text(self, item_id):
        """Tab: jump to the next text box on screen and start typing in it."""
        boxes = [item for item in self.items if item.kind == "text"]
        for position, item in enumerate(boxes):
            if item.id == item_id:
                self._start_edit(boxes[(position + 1) % len(boxes)])
                return

    # ── events ──
    def handle_event(self, event):
        """
        Feed one pygame event in. Returns a list of actions (often empty):
          ("activate", id, how)   a control was used. how = "enter", "space" or "click"
          ("commit", id, old)     a text box was confirmed with a new value (already in its store)
          ("cancel", id)          a text box was left without changing anything
          ("escape",)             Esc was pressed with nothing being typed
        """
        if event.type == pygame.MOUSEMOTION:
            self._pointer_seen = True
            self._pointer_active = True
            self.mouse = event.pos
            return []

        if event.type == pygame.KEYUP:
            self._held.discard(event.key)
            return []

        if event.type == pygame.MOUSEWHEEL:
            for view in self.lists.values():
                if view.rect is not None and view.rect.collidepoint(self.mouse):
                    view.scroll_by(-event.y * 3)
            return []

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._click(event.pos)

        if event.type == pygame.KEYDOWN:
            repeat = event.key in self._held
            self._held.add(event.key)
            if repeat and event.key not in REPEATING_KEYS and not (self.edit and printable(event)):
                return []
            self._pointer_active = False  # using the keyboard now - stop showing mouse hover
            if self.edit is not None:
                return self._edit_key(event, repeat)
            return self._key(event)

        return []

    def _click(self, pos):
        self._pointer_seen = True
        self._pointer_active = True
        self.mouse = pos
        self.click_pos = pos
        actions = []

        # last registered = drawn on top, so check from the end
        target = None
        for item in reversed(self.items):
            if item.rect.collidepoint(pos):
                target = item
                break

        if self.edit is not None:
            if target is not None and target.id == self.edit["id"]:
                return []  # clicked the box being typed in - carry on typing
            actions.append(self._finish_edit(True))  # clicking away keeps what was typed

        if target is None:
            return actions

        self.focus = target.id
        if target.kind == "text":
            self._start_edit(target)
        else:
            actions.append(("activate", target.id, "click"))
        return actions

    def _key(self, event):
        key = event.key

        if key in ARROWS:
            self._move(*ARROWS[key])
            return []
        if key == pygame.K_PAGEUP and self._page(-1):
            return []
        if key == pygame.K_PAGEDOWN and self._page(1):
            return []
        if key == pygame.K_HOME and self._page("home"):
            return []
        if key == pygame.K_END and self._page("end"):
            return []
        if key == pygame.K_ESCAPE:
            return [("escape",)]

        current = self.item(self.focus)
        if current is None:
            return []

        if key in ENTER_KEYS or key == pygame.K_SPACE:
            if current.kind == "text":
                self._start_edit(current)
                return []
            return [("activate", current.id, "space" if key == pygame.K_SPACE else "enter")]

        if key == pygame.K_TAB:
            boxes = [item for item in self.items if item.kind == "text"]
            if boxes:
                if current.kind == "text":
                    self._focus_next_text(current.id)
                else:
                    self._start_edit(boxes[0])
            return []

        # just start typing on a focused text box - no need to press Enter first
        if current.kind == "text":
            char = printable(event)
            if char:
                self._start_edit(current, first_char=char)
        return []

    # ── overlays ──
    def _draw_focus_ring(self, item):
        grow = 0 if item.kind == "row" else 8
        ring = item.rect.inflate(grow, grow)
        pygame.draw.rect(self.screen, self.colors["TEXT_COLOR"], ring, width=2, border_radius=6 if item.kind == "row" else 13)

    def _draw_pointer(self):
        """A plain arrow pointer. Drawn by us so it shows on the Pi, where the system pointer is hidden."""
        x, y = self.mouse
        s = max(16, self.u)
        shape = [
            (x, y), (x, y + s), (x + s * 0.28, y + s * 0.74),
            (x + s * 0.46, y + s * 1.12), (x + s * 0.60, y + s * 1.04),
            (x + s * 0.42, y + s * 0.68), (x + s * 0.72, y + s * 0.68),
        ]
        shape = [(int(px), int(py)) for px, py in shape]
        pygame.draw.polygon(self.screen, (255, 255, 255), shape)
        pygame.draw.polygon(self.screen, (0, 0, 0), shape, 2)


# ─── IMAGE PREVIEW ─────────────────────────────────────────────────────────────
class Preview:
    """
    Loads one image at a time for a preview box, scaled to fit.
    Waits until the selection has stayed put for a moment before loading, so
    holding the Down key through a long list doesn't load every photo on the way.
    """

    SETTLE_MS = 180

    def __init__(self, keep_alpha=False):
        self.keep_alpha = keep_alpha  # True for logos (transparent backgrounds)
        self._wanted = None
        self._wanted_since = 0
        self._loaded_key = None
        self._surface = None

    def get(self, path, max_w, max_h):
        """Returns ("ok", surface), ("loading", None) or ("error", None)."""
        key = (str(path), max_w, max_h)
        now = pygame.time.get_ticks()

        if key != self._wanted:
            self._wanted = key
            self._wanted_since = now

        if key != self._loaded_key:
            if now - self._wanted_since < self.SETTLE_MS:
                return "loading", None
            self._loaded_key = key
            try:
                image = pygame.image.load(str(path))
                image = image.convert_alpha() if self.keep_alpha else image.convert()
                img_w, img_h = image.get_size()
                scale = min(max_w / img_w, max_h / img_h, 1.0)  # never blow small images up
                size = (max(1, int(img_w * scale)), max(1, int(img_h * scale)))
                self._surface = pygame.transform.smoothscale(image, size)
            except Exception:
                self._surface = None

        if self._surface is None:
            return "error", None
        return "ok", self._surface


# ─── TAB BASE ──────────────────────────────────────────────────────────────────
class Tab:
    """
    What every admin panel tab looks like to the panel. A tab overrides the
    bits it needs - at minimum `name` and draw().
    """

    name = ""
    hint = "Arrows: move    Enter: select    Esc: back"

    def __init__(self, ctx):
        self.ctx = ctx          # shared: settings, colours, who's logged in (see admin_panel.Context)
        self.status = ""        # one-line message shown under the tab
        self.status_ok = True   # False = show it as an error

    def say(self, text, ok=True):
        self.status = text
        self.status_ok = ok

    def opened(self, ui):
        """Called each time the tab is switched to."""

    def draw(self, ui, area):
        """Draw the tab inside `area` (a pygame.Rect) using the ui toolkit."""

    def handle_action(self, action, ui):
        """An action from ui.handle_event(). May return "restart" / "exit" for the app to carry out."""
        return None

    def handle_raw(self, event, ui):
        """First look at every event. Return True to swallow it (e.g. while waiting for a hotkey press)."""
        return False

    def escape(self, ui):
        """Esc was pressed. Return True if the tab used it to close something of its own."""
        return False

    def tick(self):
        """Called after every frame is on screen - for slow jobs that need a 'please wait' showing first."""
        return None
