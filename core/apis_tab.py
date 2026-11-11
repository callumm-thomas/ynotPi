"""
ynotPi — core/apis_tab.py
-------------------------
The APIs tab in the admin panel: everything about where the frame's live data
comes from, so nobody has to open a config file.

Left  : every feed - the built-in ones (Weather, Crypto, News, NASA, Trivia)
        then the custom ones from apis.json - plus "Add new API".
Right : the selected feed's settings. Move onto a feed to see it.

Saving:
- an existing feed saves each box as soon as it's confirmed (Enter, Tab, or
  clicking away) - same "saves straight away" rule as the rest of the panel
- a brand new API is only saved when "Save API" is pressed (it needs a name
  and an address before it can exist)

API keys:
- typed here, stored in config/secrets.env (never in apis.json, never in git)
- Admin mode shows only the last 4 characters; Technician mode shows the lot
- to replace a key just type the new one over it

Weather town:
- type a town, press Enter, pick the right one from the matches. That stores
  the exact location, so "Newcastle" means the one in NSW rather than England.
"""

import pygame

from core import api_manager
from core import settings as settings_store
from core import ui

BUILTIN_FEEDS = [
    ("weather", "Weather"),
    ("crypto", "Crypto"),
    ("news", "News"),
    ("apod", "NASA APOD"),
    ("trivia", "Trivia"),
]

# shown under each built-in feed's key box
KEY_HELP = {
    "weather": "Free key from openweathermap.org/api",
    "crypto": "Optional — works without one. Pro keys from coingecko.com/en/api",
    "news": "Free key from newsapi.org",
    "apod": "Free key from api.nasa.gov",
}

NEWS_CATEGORIES = ["general", "business", "technology", "science", "health", "sports", "entertainment"]
LETTERS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
SAVE_FAILED = "Couldn't save that change — see the log in Technician mode."


# ─── "a=1&b=2" <-> {"a": "1", "b": "2"} ────────────────────────────────────────
# '&' between settings (like in a web address) because values often contain
# commas themselves, e.g. symbols=USD,EUR,NZD
def pairs_to_text(pairs):
    if not isinstance(pairs, dict):
        return ""
    return "&".join(f"{key}={value}" for key, value in pairs.items())


def text_to_pairs(text):
    """Returns (dict, error message). Empty text is fine -> ({}, "")."""
    pairs = {}
    for piece in text.split("&"):
        piece = piece.strip()
        if not piece:
            continue
        if "=" not in piece:
            return None, f"'{piece}' needs to look like name=value."
        key, _, value = piece.partition("=")
        if not key.strip():
            return None, f"'{piece}' is missing its name before the '='."
        pairs[key.strip()] = value.strip()
    return pairs, ""


class ApisTab(ui.Tab):
    name = "APIs"
    hint = "Arrows: move    Enter: edit / select    Esc: back"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.list = ui.ListView("api")
        self.configs = api_manager.load_custom_api_configs()
        self.draft = None           # the form for a new API that hasn't been saved yet (dict), or None
        self.form = {}              # text box values for whichever feed is selected
        self._form_for = None       # which feed self.form currently belongs to
        self.confirm_delete = None  # index of the custom API waiting for its second "Delete" press
        self.towns = None           # weather look-up results (list), or None when there's no look-up showing
        self.town_query = ""        # what was typed for that look-up
        self.pending = None         # slow job to run once its "please wait" message is on screen
        self.focus_next = None      # control to move the focus to once it's on screen (set by slow jobs / saves)

    # ── which feeds exist ──
    def _entries(self):
        """Everything in the list, in order: ("builtin", feed) / ("custom", index) / ("draft", None)."""
        entries = [("builtin", feed) for feed, _ in BUILTIN_FEEDS]
        entries += [("custom", index) for index in range(len(self.configs))]
        if self.draft is not None:
            entries.append(("draft", None))
        return entries

    def _selected(self):
        entries = self._entries()
        return entries[max(0, min(len(entries) - 1, self.list.current))]

    def _select(self, ui_, entry):
        entries = self._entries()
        if entry in entries:
            index = entries.index(entry)
            self.list.current = index
            self.list.count = len(entries)
            self.list.ensure_visible(index)
            ui_.stop_editing()
            ui_.set_focus(self.list.row_id(index))

    def opened(self, ui_):
        self.configs = api_manager.load_custom_api_configs()
        self._form_for = None  # rebuild the form from what's saved
        self.confirm_delete = None

    # ── form values ──
    def _key_names_in_use(self):
        names = {key_name for key_name, _ in api_manager.BUILTIN_KEYS.values()}
        names.update(config.get("key_name") for config in self.configs if config.get("key_name"))
        return names

    def _custom_form(self, config):
        key_name = config.get("key_name", "")
        return {
            "name": config.get("name", ""),
            "url": config.get("url", ""),
            "key": api_manager.get_key_value(key_name) if key_name else "",
            "key_location": config.get("key_location", "query"),
            "key_param_name": config.get("key_param_name", "") if key_name else "",
            "params": pairs_to_text(config.get("params")),
            "headers": pairs_to_text(config.get("headers")),
            "result_path": config.get("result_path", "") if isinstance(config.get("result_path", ""), str)
            else ".".join(str(part) for part in config.get("result_path")),
        }

    def _build_form(self, entry):
        kind, which = entry
        settings = self.ctx.settings

        if kind == "draft":
            self.form = self.draft
        elif kind == "custom":
            self.form = self._custom_form(self.configs[which])
        else:
            self.form = {}
            if which in api_manager.BUILTIN_KEYS:
                self.form["key"] = api_manager.get_key_value(api_manager.BUILTIN_KEYS[which][0])
            if which == "weather":
                self.form["town"] = ""
            elif which == "crypto":
                options = settings_store.feed_options(settings, "crypto")
                self.form["coins"] = str(options.get("coins", ""))
                self.form["currency"] = str(options.get("currency", ""))
            elif which == "news":
                self.form["country"] = str(settings_store.feed_options(settings, "news").get("country", ""))

        self._form_for = entry
        self.towns = None
        self.confirm_delete = None

    # ── drawing ──
    def draw(self, ui_, area):
        self._draw_everything(ui_, area)
        # move the focus somewhere useful after a look-up / save (now that the control is on screen)
        if self.focus_next is not None:
            if any(item.id == self.focus_next for item in ui_._new_items):
                ui_.set_focus(self.focus_next)
            self.focus_next = None

    def _draw_everything(self, ui_, area):
        entries = self._entries()
        gap = ui_.pad

        list_w = max(13 * ui_.u, int(area.width * 0.30))
        add_rect = pygame.Rect(area.x, area.bottom - ui_.h_small, list_w, ui_.h_small)
        list_rect = pygame.Rect(area.x, area.y, list_w, add_rect.y - gap - area.y)
        row_h = ui_.u + ui_.pad + 4

        def draw_row(index, row_rect, state, selected):
            label, tag, tag_colour = self._row_text(entries[index])
            tag_w = ui_.fonts["small"].size(tag)[0] + ui_.pad if tag else 0
            y = row_rect.y + (row_rect.height - ui_.u) // 2
            ui_.text(label, (row_rect.x + ui_.pad, y), "small", "TEXT_COLOR", max_w=row_rect.width - tag_w - 2 * ui_.pad)
            if tag:
                ui_.text(tag, (row_rect.right - tag_w, y), color=tag_colour)

        self.list.draw(ui_, list_rect, len(entries), row_h, draw_row)
        ui_.button("api:add", add_rect, "+ Add new API", font="small", enabled=self.draft is None)

        # the form always shows whichever feed the list is on
        entry = self._selected()
        if entry != self._form_for:
            self._build_form(entry)

        form_rect = pygame.Rect(list_rect.right + 2 * gap, area.y, area.right - list_rect.right - 2 * gap, area.height)
        if form_rect.width < 12 * ui_.u:
            return
        if entry[0] == "builtin":
            self._draw_builtin(ui_, form_rect, entry[1])
        else:
            self._draw_custom(ui_, form_rect, entry)

    def _row_text(self, entry):
        """(name, status tag, tag colour) for one row of the list."""
        kind, which = entry
        if kind == "draft":
            return (self.draft.get("name") or "New API"), "not saved", ui.WARN_COLOR

        if kind == "builtin":
            label = dict(BUILTIN_FEEDS)[which]
            if which not in api_manager.BUILTIN_KEYS:
                return label, "", "SUBTEXT_COLOR"
            key_name, required = api_manager.BUILTIN_KEYS[which]
            if api_manager.has_key(key_name):
                return label, "key set", ui.OK_COLOR
            return label, ("no key" if required else ""), ui.WARN_COLOR

        config = self.configs[which]
        key_name = config.get("key_name")
        if not key_name:
            return config.get("name", "?"), "", "SUBTEXT_COLOR"
        if api_manager.has_key(key_name):
            return config.get("name", "?"), "key set", ui.OK_COLOR
        return config.get("name", "?"), "no key", ui.WARN_COLOR

    # layout helpers - every box is "small label, then the box", stacked down the form
    def _spacing(self, ui_, rect, rows):
        """Gap between form rows: roomy if there's space, tighter on a short window."""
        label_h = ui_.u + 3
        needed = rows * (label_h + ui_.h_body)
        spare = rect.height - needed - ui_.fonts["body"].get_height() - ui_.pad
        return label_h, max(4, min(ui_.pad, spare // max(1, rows)))

    def _box(self, ui_, item_id, label, rect, key, **options):
        ui_.text(label, (rect.x, rect.y - ui_.u - 3), max_w=rect.width)
        ui_.text_input(item_id, rect, self.form, key, **options)

    def _key_box(self, ui_, rect, label, note=""):
        """An API key box + its 'Clear key' button. rect covers both."""
        has_value = bool(self.form.get("key"))
        clear_w = ui_.button_w("Clear key", "small")
        box = pygame.Rect(rect.x, rect.y, rect.width - clear_w - ui_.pad, rect.height)
        ui_.text(label, (box.x, box.y - ui_.u - 3), max_w=rect.width)

        if self.ctx.is_technician:
            # technicians see and edit the whole key
            ui_.text_input("field:key", box, self.form, "key", placeholder="No key set", max_len=400)
        else:
            # admin mode: last 4 characters only. Typing replaces the key rather than revealing it.
            ui_.text_input(
                "field:key", box, self.form, "key", placeholder="No key set — type one here",
                mask=api_manager.mask_key, start_blank=True, max_len=400,
            )

        clear_rect = pygame.Rect(box.right + ui_.pad, rect.y + (rect.height - ui_.h_small) // 2, clear_w, ui_.h_small)
        ui_.button("key:clear", clear_rect, "Clear key", font="small", enabled=has_value)
        if note:
            ui_.text(note, (rect.x, rect.bottom + 3), max_w=rect.width)

    # ── built-in feeds ──
    def _draw_builtin(self, ui_, rect, feed):
        settings = self.ctx.settings
        label = dict(BUILTIN_FEEDS)[feed]
        body_h = ui_.fonts["body"].get_height()
        label_h = ui_.u + 3
        gap = ui_.pad + 2

        ui_.text(label, (rect.x, rect.y), "body", "TEXT_COLOR", max_w=rect.width)
        y = rect.y + body_h + ui_.pad

        if feed == "weather":
            options = settings_store.feed_options(settings, "weather")
            place = options.get("label") or options.get("town") or "not set"
            ui_.text(f"Showing weather for:  {place}", (rect.x, y), "small", "TEXT_COLOR", max_w=rect.width)
            y += ui_.u + gap + label_h

            find_w = ui_.button_w("Find town")
            box = pygame.Rect(rect.x, y, rect.width - find_w - ui_.pad, ui_.h_body)
            self._box(ui_, "field:town", "Change town — type a name, then press Enter", box, "town",
                      placeholder="e.g. Newcastle", max_len=60)
            ui_.button("town:find", pygame.Rect(box.right + ui_.pad, y, find_w, ui_.h_body), "Find town")
            y += ui_.h_body + gap

            if self.towns is not None:
                y = self._draw_town_results(ui_, rect, y)

        elif feed == "crypto":
            y += label_h
            currency_w = max(6 * ui_.u, ui_.fonts["small"].size("Currency")[0] + ui_.pad)
            coins = pygame.Rect(rect.x, y, rect.width - currency_w - ui_.pad, ui_.h_body)
            self._box(ui_, "field:coins", "Coins (CoinGecko names, commas between)", coins, "coins",
                      placeholder="bitcoin,ethereum", max_len=200)
            self._box(ui_, "field:currency", "Currency", pygame.Rect(coins.right + ui_.pad, y, currency_w, ui_.h_body),
                      "currency", placeholder="aud", allowed=LETTERS, max_len=5)
            y += ui_.h_body + gap

        elif feed == "news":
            y += label_h
            country_w = max(6 * ui_.u, ui_.fonts["small"].size("Country code")[0] + ui_.pad)
            self._box(ui_, "field:country", "Country code", pygame.Rect(rect.x, y, country_w, ui_.h_body),
                      "country", placeholder="au", allowed=LETTERS, max_len=2)
            y += ui_.h_body + gap

            ui_.text("Category", (rect.x, y))
            y += label_h
            chosen = settings_store.feed_options(settings, "news").get("category")
            x = rect.x
            for category in NEWS_CATEGORIES:
                width = ui_.button_w(category.title(), "small")
                if x + width > rect.right and x > rect.x:  # wrap onto the next line
                    x = rect.x
                    y += ui_.h_small + 6
                ui_.button(f"news:{category}", pygame.Rect(x, y, width, ui_.h_small), category.title(),
                           font="small", active=(category == chosen))
                x += width + 6
            y += ui_.h_small + gap

        elif feed == "trivia":
            y = ui_.paragraph("Trivia questions come from Open Trivia DB. There's nothing to set up and no key needed.",
                              (rect.x, y), rect.width)

        if feed in api_manager.BUILTIN_KEYS and y + label_h + ui_.h_body <= rect.bottom:
            y += label_h
            self._key_box(ui_, pygame.Rect(rect.x, y, rect.width, ui_.h_body), "API key", note=KEY_HELP.get(feed, ""))
            y += ui_.h_body + ui_.u + gap

        if y + ui_.u <= rect.bottom:
            ui_.text(f"Turn {label} on or off in the Content tab.", (rect.x, y + 4), max_w=rect.width)

    def _draw_town_results(self, ui_, rect, y):
        """The list of matching towns under the town box. Returns the y below it."""
        if self.towns:
            ui_.text("Pick the right one:", (rect.x, y))
            y += ui_.u + 4
        for index, town in enumerate(self.towns):
            if y + ui_.h_small > rect.bottom:
                break
            width = min(rect.width, ui_.button_w(town["label"], "small"))
            ui_.button(f"town:pick:{index}", pygame.Rect(rect.x, y, width, ui_.h_small), town["label"], font="small")
            y += ui_.h_small + 4

        # always offered, so a town can still be set if the look-up can't run (no key yet, no internet)
        if self.town_query and y + ui_.h_small <= rect.bottom:
            text = f"Use \"{self.town_query}\" exactly as typed"
            width = min(rect.width, ui_.button_w(text, "small"))
            ui_.button("town:astyped", pygame.Rect(rect.x, y, width, ui_.h_small), text, font="small")
            y += ui_.h_small + 4
        return y + ui_.pad

    # ── custom APIs (saved ones and the new-API draft) ──
    def _draw_custom(self, ui_, rect, entry):
        is_draft = entry[0] == "draft"
        label_h, gap = self._spacing(ui_, rect, 6)
        half = (rect.width - ui_.pad) // 2
        step = label_h + ui_.h_body + gap
        y = rect.y + label_h

        self._box(ui_, "field:name", "Name (shown as the slide title)", pygame.Rect(rect.x, y, rect.width, ui_.h_body),
                  "name", placeholder="e.g. Exchange Rates", max_len=40)
        y += step
        self._box(ui_, "field:url", "Web address", pygame.Rect(rect.x, y, rect.width, ui_.h_body),
                  "url", placeholder="https://...", max_len=500)
        y += step

        key_label = "API key (leave empty if this API doesn't need one)"
        key_name = "" if is_draft else self.configs[entry[1]].get("key_name", "")
        if key_name:
            key_label = f"API key (saved as {key_name})"
        self._key_box(ui_, pygame.Rect(rect.x, y, rect.width, ui_.h_body), key_label)
        y += step

        # where the key goes in the request - two buttons, the lit one is the current choice
        ui_.text("Send the key in the", (rect.x, y - ui_.u - 3), max_w=half)
        choice_w = (half - 6) // 2
        location = self.form.get("key_location", "query")
        ui_.button("keyloc:query", pygame.Rect(rect.x, y, choice_w, ui_.h_body), "Address", font="small", active=location == "query")
        ui_.button("keyloc:header", pygame.Rect(rect.x + choice_w + 6, y, choice_w, ui_.h_body), "Header", font="small", active=location == "header")
        self._box(ui_, "field:key_param_name", "Key's name in the request", pygame.Rect(rect.x + half + ui_.pad, y, rect.width - half - ui_.pad, ui_.h_body),
                  "key_param_name", placeholder="apiKey", max_len=60)
        y += step

        self._box(ui_, "field:params", "Extra settings (name=value, with & between)", pygame.Rect(rect.x, y, rect.width, ui_.h_body),
                  "params", placeholder="base=AUD&symbols=USD,EUR", max_len=500)
        y += step

        self._box(ui_, "field:headers", "Extra headers (optional)", pygame.Rect(rect.x, y, half, ui_.h_body),
                  "headers", placeholder="name=value", max_len=500)
        self._box(ui_, "field:result_path", "Only show this part (optional)", pygame.Rect(rect.x + half + ui_.pad, y, rect.width - half - ui_.pad, ui_.h_body),
                  "result_path", placeholder="e.g. rates", max_len=120)
        y += ui_.h_body + max(gap, 6)

        if y + ui_.h_small > rect.bottom + ui_.u + ui_.pad:
            return  # no room for the buttons (window far too short)

        if is_draft:
            save_w = ui_.button_w("Save API", "small")
            ui_.button("api:save", pygame.Rect(rect.x, y, save_w, ui_.h_small), "Save API", font="small")
            ui_.button("api:cancel", pygame.Rect(rect.x + save_w + 6, y, ui_.button_w("Cancel", "small"), ui_.h_small), "Cancel", font="small")
        else:
            confirming = self.confirm_delete == entry[1]
            text = "Press again to delete" if confirming else "Delete this API"
            width = max(ui_.button_w("Press again to delete", "small"), ui_.button_w("Delete this API", "small"))
            ui_.button("api:delete", pygame.Rect(rect.x, y, width, ui_.h_small), text, font="small", warn=confirming)
            ui_.text("Changes save as you go.", (rect.x + width + ui_.pad, y + (ui_.h_small - ui_.u) // 2),
                     max_w=rect.right - rect.x - width - ui_.pad)

    # ── actions ──
    def handle_action(self, action, ui_):
        kind, item_id = action[0], str(action[1])

        # any action other than the second "Delete" press calls the delete off
        if not (kind == "activate" and item_id == "api:delete"):
            self.confirm_delete = None

        if kind == "commit":
            self._commit(ui_, item_id.split(":", 1)[1], action[2])
            return None
        if kind != "activate":
            return None

        entry = self._selected()

        if item_id == "api:add":
            self.draft = {"name": "", "url": "", "key": "", "key_location": "query",
                          "key_param_name": "", "params": "", "headers": "", "result_path": ""}
            self._select(ui_, ("draft", None))
            self.say("Fill in the name and web address, then press Save API.")
        elif item_id == "api:cancel":
            self.draft = None
            self._form_for = None
            self.say("New API cancelled.")
        elif item_id == "api:save":
            self._save_draft(ui_)
        elif item_id == "api:delete" and entry[0] == "custom":
            self._delete(ui_, entry[1])
        elif item_id == "key:clear":
            self._clear_key(entry)
        elif item_id.startswith("keyloc:"):
            self._set_key_location(entry, item_id.split(":")[1])
        elif item_id.startswith("news:"):
            self._set_feed_option("news", "category", item_id.split(":")[1], "News category set to {}.")
        elif item_id == "town:find":
            self._start_town_lookup(self.form.get("town", ""))
        elif item_id == "town:astyped":
            self._set_town({"name": self.town_query, "label": self.town_query, "lat": None, "lon": None})
        elif item_id.startswith("town:pick:"):
            index = int(item_id.rsplit(":", 1)[1])
            if self.towns and index < len(self.towns):
                self._set_town(self.towns[index])
        return None

    def tick(self):
        job, self.pending = self.pending, None
        if job == "town-lookup":
            matches, error = api_manager.find_towns(self.town_query)
            self.towns = matches
            # land on the first match (or "use as typed" if there were none), so Enter picks it
            self.focus_next = "town:pick:0" if matches else "town:astyped"
            if error:
                self.say(error, False)
            else:
                self.say(f"Found {len(matches)} match{'es' if len(matches) != 1 else ''} — pick the right one.")
        return None

    # ── weather town ──
    def _start_town_lookup(self, text):
        text = " ".join(text.split())
        if not text:
            self.say("Type a town name first.", False)
            return
        self.town_query = text
        self.towns = []
        self.pending = "town-lookup"  # runs in tick(), once this message is showing
        self.say(f"Looking up '{text}'...")

    def _set_town(self, town):
        feeds = self.ctx.settings.setdefault("feeds", {})
        feeds["weather"] = {
            "town": town["name"],
            "label": town["label"],
            "lat": town.get("lat"),
            "lon": town.get("lon"),
        }
        self.towns = None
        self.form["town"] = ""
        self.focus_next = "field:town"
        if self.ctx.save():
            self.say(f"Weather town set to {town['label']}.")
        else:
            self.say(SAVE_FAILED, False)

    # ── built-in feed options ──
    def _set_feed_option(self, feed, option, value, message):
        feeds = self.ctx.settings.setdefault("feeds", {})
        feeds.setdefault(feed, {})[option] = value
        if self.ctx.save():
            self.say(message.format(value))
        else:
            self.say(SAVE_FAILED, False)

    # ── keys ──
    def _key_name_for(self, entry, create=False):
        """The secrets.env name this feed's key is stored under ('' if it has none yet)."""
        kind, which = entry
        if kind == "builtin":
            return api_manager.BUILTIN_KEYS.get(which, ("", False))[0]
        if kind == "custom":
            config = self.configs[which]
            if not config.get("key_name") and create:
                config["key_name"] = api_manager.make_key_name(config.get("name", ""), self._key_names_in_use())
                config.setdefault("key_location", "query")
                config.setdefault("key_param_name", "apiKey")
            return config.get("key_name", "")
        return ""

    def _clear_key(self, entry):
        if entry[0] == "draft":
            self.form["key"] = ""
            return
        key_name = self._key_name_for(entry)
        if not key_name:
            return
        ok, message = api_manager.set_key(key_name, "")
        if ok:
            self.form["key"] = ""
        self.say(message, ok)

    def _set_key_location(self, entry, location):
        self.form["key_location"] = location
        if entry[0] != "custom":
            return  # a draft just remembers it until Save
        self.configs[entry[1]]["key_location"] = location
        if api_manager.save_custom_api_configs(self.configs):
            self.say("Saved — the key is sent in the " + ("header." if location == "header" else "web address."))
        else:
            self.say(SAVE_FAILED, False)

    # ── a text box was confirmed ──
    def _commit(self, ui_, field, old_value):
        entry = self._selected()
        value = " ".join(str(self.form.get(field, "")).split()) if field != "key" else "".join(str(self.form.get(field, "")).split())
        self.form[field] = value

        def reject(message):
            self.form[field] = old_value  # put the box back how it was
            self.say(message, False)

        # the town box is a search box - confirming it starts the look-up
        if field == "town":
            self._start_town_lookup(value)
            return

        if field == "key" and entry[0] != "draft":
            if not value:
                self.form[field] = old_value  # emptied by hand - "Clear key" is the way to remove one
                self.say("Key not changed. Use 'Clear key' to remove it.")
                return
            key_name = self._key_name_for(entry, create=True)
            ok, message = api_manager.set_key(key_name, value)
            if not ok:
                reject(message)
                return
            if entry[0] == "custom" and not api_manager.save_custom_api_configs(self.configs):
                self.say(SAVE_FAILED, False)
                return
            self.say("Key saved.")
            return

        if entry[0] == "builtin":
            self._commit_builtin(entry[1], field, value, reject)
        elif entry[0] == "custom":
            self._commit_custom(entry[1], field, value, reject)
        # a draft keeps its values in self.form until Save API - nothing to do yet

    def _commit_builtin(self, feed, field, value, reject):
        if feed == "crypto" and field == "coins":
            coins = ",".join(part.strip().lower() for part in value.split(",") if part.strip())
            if not coins:
                reject("List at least one coin, e.g. bitcoin")
                return
            self.form[field] = coins
            self._set_feed_option("crypto", "coins", coins, "Coins saved.")
        elif feed == "crypto" and field == "currency":
            if not value:
                reject("Type a currency code, e.g. aud")
                return
            self.form[field] = value.lower()
            self._set_feed_option("crypto", "currency", value.lower(), "Currency set to {}.")
        elif feed == "news" and field == "country":
            if len(value) != 2:
                reject("The country code is 2 letters, e.g. au")
                return
            self.form[field] = value.lower()
            self._set_feed_option("news", "country", value.lower(), "News country set to {}.")

    def _check_custom(self, form, ignore_index=None):
        """Check a custom API form. Returns (config fields dict, error message)."""
        name = form.get("name", "").strip()
        url = form.get("url", "").strip()
        if not name:
            return None, "The API needs a name."
        if not url:
            return None, "The API needs a web address."
        if not url.lower().startswith(("http://", "https://")):
            return None, "The web address must start with https:// (or http://)."

        taken = {label.lower() for _, label in BUILTIN_FEEDS} | {"photos"}
        taken.update(config.get("name", "").lower() for index, config in enumerate(self.configs) if index != ignore_index)
        if name.lower() in taken:
            return None, f"There's already something called '{name}' — pick a different name."

        params, error = text_to_pairs(form.get("params", ""))
        if error:
            return None, "Extra settings: " + error
        headers, error = text_to_pairs(form.get("headers", ""))
        if error:
            return None, "Extra headers: " + error

        fields = {"name": name, "url": url}
        if params:
            fields["params"] = params
        if headers:
            fields["headers"] = headers
        if form.get("result_path", "").strip():
            fields["result_path"] = form["result_path"].strip()
        return fields, ""

    def _commit_custom(self, index, field, value, reject):
        config = self.configs[index]
        fields, error = self._check_custom(self.form, ignore_index=index)
        if error:
            reject(error)
            return

        old_name = config.get("name", "")
        # rebuild from the checked fields, keeping the key details and anything this form doesn't know about
        updated = {key: item for key, item in config.items() if key not in ("name", "url", "params", "headers", "result_path")}
        updated = {**fields, **updated}
        if updated.get("key_name"):
            updated["key_param_name"] = self.form.get("key_param_name", "").strip() or "apiKey"
        elif field == "key_param_name":
            self.say("That's used once this API has a key — add the key first.")
        self.configs[index] = updated

        if not api_manager.save_custom_api_configs(self.configs):
            self.say(SAVE_FAILED, False)
            return

        # renamed? its on/off switch on the Content tab is stored under the name, so move that too
        if fields["name"] != old_name:
            custom = self.ctx.settings["content"].setdefault("custom", {})
            if old_name in custom:
                custom[fields["name"]] = custom.pop(old_name)
                self.ctx.save()

        if not (field == "key_param_name" and not updated.get("key_name")):
            self.say("Saved.")

    # ── new API ──
    def _save_draft(self, ui_):
        fields, error = self._check_custom(self.draft)
        if error:
            self.say(error, False)
            return

        key_value = "".join(self.draft.get("key", "").split())
        if key_value:
            key_name = api_manager.make_key_name(fields["name"], self._key_names_in_use())
            ok, message = api_manager.set_key(key_name, key_value)
            if not ok:
                self.say(message, False)
                return
            fields["key_name"] = key_name
            fields["key_location"] = self.draft.get("key_location", "query")
            fields["key_param_name"] = self.draft.get("key_param_name", "").strip() or "apiKey"

        self.configs.append(fields)
        if not api_manager.save_custom_api_configs(self.configs):
            self.configs.pop()
            self.say(SAVE_FAILED, False)
            return

        self.draft = None
        self._form_for = None
        self._select(ui_, ("custom", len(self.configs) - 1))
        self.say(f"Added '{fields['name']}'. It's switched on — see the Content tab.")

    # ── delete ──
    def _delete(self, ui_, index):
        config = self.configs[index]
        name = config.get("name", "this API")

        if self.confirm_delete != index:
            self.confirm_delete = index
            self.say(f"Delete '{name}'? Press Delete again to confirm, or anything else to keep it.")
            return
        self.confirm_delete = None

        remaining = self.configs[:index] + self.configs[index + 1:]
        if not api_manager.save_custom_api_configs(remaining):
            self.say(SAVE_FAILED, False)
            return
        self.configs = remaining

        # tidy up after it: its saved key (unless another API shares it) and its on/off switch
        key_name = config.get("key_name")
        if key_name and key_name not in self._key_names_in_use() and api_manager.has_key(key_name):
            api_manager.set_key(key_name, "")
        custom = self.ctx.settings["content"].setdefault("custom", {})
        if name in custom:
            del custom[name]
            self.ctx.save()

        self._form_for = None
        entries = self._entries()
        self._select(ui_, entries[min(len(BUILTIN_FEEDS) + index, len(entries) - 1)])
        self.say(f"Deleted '{name}'.")
