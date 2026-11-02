"""
ynotPi — core/branding.py
-------------------------
Company branding for the frame:
- two brand colours (primary + accent) -> a full colour theme for every slide
  and the admin panel
- a logo drawn in a bottom corner of every slide (optionally skipping photos)

Settings live in config/settings.json under "branding". A chosen logo is copied
into assets/branding/ so it keeps working after the USB stick is unplugged.

How the two colours are used:
- primary tints the backgrounds and cards (kept dark so text always reads well)
- accent is used for highlights: the accent tab on slide cards, card borders,
  selected buttons in the admin panel
If an accent is too dark to see against the background, it's lightened
automatically until it has enough contrast.
"""

import os
import shutil
from pathlib import Path

import pygame

BASE_DIR = Path(__file__).resolve().parent.parent
BRANDING_DIR = BASE_DIR / "assets" / "branding"

# the original ynotPi look - used whenever no brand colours are set
DEFAULT_PALETTE = {
    "BACKGROUND_COLOR": (18, 22, 28),
    "TEXT_COLOR": (245, 245, 245),
    "SUBTEXT_COLOR": (170, 176, 186),
    "HIGHLIGHT_COLOR": (70, 130, 200),
    "BUTTON_COLOR": (55, 55, 55),
    "BUTTON_HOVER": (75, 75, 75),
    "CARD_COLOR": (30, 35, 43),
    "CARD_BORDER": (55, 63, 75),
    "ANSWER_BOX_COLOR": (45, 50, 60),
}

DEFAULT_BRANDING = {
    "primary": None,        # hex string like "#1E3A8A", or None for the default look
    "accent": None,
    "logo": None,           # path relative to the repo, e.g. "assets/branding/logo.png"
    "logo_corner": "bottom-right",
    "logo_size": "medium",
    "logo_on_photos": True,
}

# preset swatches shown in the admin panel - common corporate colours
SWATCHES = [
    "#1E3A8A", "#2563EB", "#0EA5E9", "#0D9488", "#16A34A", "#65A30D", "#EAB308", "#B8860B",
    "#EA580C", "#DC2626", "#9F1239", "#DB2777", "#7C3AED", "#4F46E5", "#475569", "#1F2937",
]

LOGO_CORNERS = ["bottom-left", "bottom-right"]
LOGO_SIZES = {"small": 0.045, "medium": 0.065, "large": 0.085}  # logo height as a fraction of screen height
MAX_LOGO_WIDTH = 0.25  # very wide logos get capped at a quarter of the screen width
LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

# places to look for logo files - same folders photoframe.py uses for photos
# (listed here rather than imported, to avoid a circular import)
LOGO_SEARCH_PLACES = [
    ("Branding folder", BRANDING_DIR),
    ("Local photos", BASE_DIR / "assets" / "photos"),
    ("USB", Path("/media/pi")),
    ("USB", Path(f"/media/{os.environ.get('USER', 'pi')}")),
    ("Network share", Path("/mnt/photos")),
]
MAX_LOGO_CANDIDATES = 400  # stop scanning after this many - a big share could take forever

MIN_ACCENT_CONTRAST = 3.0  # WCAG "large text / UI element" level


# ─── SETTINGS ──────────────────────────────────────────────────────────────────
def get_branding(settings):
    """Branding settings with defaults filled in for anything missing."""
    merged = dict(DEFAULT_BRANDING)
    merged.update(settings.get("branding") or {})
    return merged


def card_bottom_margin(screen_h):
    """Space left under the slide card - where the logo sits. 90px at 720p, grows on bigger screens."""
    return max(90, int(screen_h * 0.12))


# ─── COLOUR MATHS ──────────────────────────────────────────────────────────────
def parse_hex(text):
    """'#1E5AA8', '1e5aa8' or '#abc' -> (r, g, b). None if it isn't a valid colour."""
    if not text:
        return None
    value = str(text).strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _mix(a, b, amount):
    """Blend colour a towards b. amount 0 = all a, 1 = all b."""
    return tuple(round(a[i] * (1 - amount) + b[i] * amount) for i in range(3))


def _luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    lighter, darker = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def derive_palette(primary_hex, accent_hex):
    """Two brand colours -> every colour the slides and admin panel use."""
    primary = parse_hex(primary_hex)
    accent = parse_hex(accent_hex)

    if primary is None and accent is None:
        return dict(DEFAULT_PALETTE)

    # only one set? use it for both jobs
    primary = primary or accent
    accent = accent or primary

    near_black = (10, 12, 16)
    white = (245, 245, 245)
    dark_text = (20, 20, 20)

    # backgrounds stay dark with a tint of the primary colour, so text is always readable
    background = _mix(near_black, primary, 0.16)
    card = _mix(near_black, primary, 0.26)

    text = white if contrast_ratio(white, card) >= contrast_ratio(dark_text, card) else dark_text
    subtext = _mix(text, card, 0.38)

    # lighten the accent until it stands out from the background
    highlight = accent
    for _ in range(12):
        if contrast_ratio(highlight, background) >= MIN_ACCENT_CONTRAST:
            break
        highlight = _mix(highlight, (255, 255, 255), 0.15)

    return {
        "BACKGROUND_COLOR": background,
        "TEXT_COLOR": text,
        "SUBTEXT_COLOR": subtext,
        "HIGHLIGHT_COLOR": highlight,
        "BUTTON_COLOR": _mix(card, text, 0.12),
        "BUTTON_HOVER": _mix(card, highlight, 0.30),
        "CARD_COLOR": card,
        "CARD_BORDER": _mix(card, highlight, 0.35),
        "ANSWER_BOX_COLOR": _mix(card, text, 0.08),
    }


def palette_for(brand):
    return derive_palette(brand.get("primary"), brand.get("accent"))


# ─── LOGO ──────────────────────────────────────────────────────────────────────
_logo_cache = {"key": None, "surface": None}
_logo_error_shown = set()


def logo_for_size(brand, target_w, target_h):
    """The logo scaled for a screen (or preview) of this size. None if there's no usable logo."""
    rel_path = brand.get("logo")
    if not rel_path:
        return None

    path = BASE_DIR / rel_path
    try:
        stat = path.stat()
    except OSError:
        if rel_path not in _logo_error_shown:
            print(f"[Branding] Logo file missing: {path}")
            _logo_error_shown.add(rel_path)
        return None

    fraction = LOGO_SIZES.get(brand.get("logo_size"), LOGO_SIZES["medium"])
    key = (str(path), stat.st_mtime, stat.st_size, fraction, target_w, target_h)
    if _logo_cache["key"] == key:
        return _logo_cache["surface"]

    try:
        image = pygame.image.load(str(path)).convert_alpha()
    except Exception as error:
        if rel_path not in _logo_error_shown:
            print(f"[Branding] Couldn't load logo {path}: {error}")
            _logo_error_shown.add(rel_path)
        return None

    img_w, img_h = image.get_size()
    new_h = max(1, int(target_h * fraction))
    new_w = max(1, int(img_w * new_h / img_h))

    max_w = int(target_w * MAX_LOGO_WIDTH)
    if new_w > max_w:
        new_h = max(1, int(new_h * max_w / new_w))
        new_w = max_w

    surface = pygame.transform.smoothscale(image, (new_w, new_h))
    _logo_cache["key"] = key
    _logo_cache["surface"] = surface
    return surface


def draw_logo(surface, brand, is_photo=False):
    """Draw the logo in its corner. Call after the slide itself has been drawn."""
    if is_photo and not brand.get("logo_on_photos", True):
        return

    screen_w, screen_h = surface.get_size()
    logo = logo_for_size(brand, screen_w, screen_h)
    if logo is None:
        return

    margin = max(16, int(screen_h * 0.02))
    y = screen_h - margin - logo.get_height()
    if brand.get("logo_corner") == "bottom-left":
        x = margin
    else:
        x = screen_w - margin - logo.get_width()

    surface.blit(logo, (x, y))


def find_logo_candidates():
    """Every image file in the usual places, as (source label, Path). Capped at MAX_LOGO_CANDIDATES."""
    found = []
    seen = set()

    for label, folder in LOGO_SEARCH_PLACES:
        if not folder.is_dir():
            continue
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            for name in sorted(files):
                path = Path(root) / name
                if path.suffix.lower() not in LOGO_EXTENSIONS or path in seen:
                    continue
                seen.add(path)
                found.append((label, path))
                if len(found) >= MAX_LOGO_CANDIDATES:
                    return found

    return found


def install_logo(source):
    """
    Copy a chosen image into assets/branding/ as logo.<ext>.
    Returns (relative path for settings, message), or (None, error message).
    """
    source = Path(source)
    try:
        pygame.image.load(str(source))  # make sure it actually opens before replacing the current logo
    except Exception as error:
        return None, f"Couldn't open that image — {error}"

    BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    dest = BRANDING_DIR / f"logo{source.suffix.lower()}"

    try:
        if source.resolve() != dest.resolve():
            for old in BRANDING_DIR.glob("logo.*"):
                if old.resolve() != source.resolve():
                    old.unlink(missing_ok=True)
            shutil.copyfile(source, dest)  # copyfile (not copy2) so the file gets a fresh timestamp
    except Exception as error:
        return None, f"Couldn't copy the logo — {error}"

    print(f"[Branding] Logo set from {source}")
    return dest.relative_to(BASE_DIR).as_posix(), "Logo updated."