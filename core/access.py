"""
ynotPi — core/access.py
-----------------------
PIN lock for the admin panel.

Two levels, decided by which PIN gets typed:
- client PIN      -> Admin mode (every setting)
- technician PIN  -> Admin mode + the Technician tab (Ynot only)

Changed PINs are stored hashed (scrambled one-way) in config/pins.json,
never as plain numbers. Keep that file out of git (.gitignore).
Until a PIN has been changed from Technician mode, the preset is used.

Forgotten technician PIN? Run scripts/reset_pins.sh on the Pi (over SSH / Tailscale).
"""

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import pygame

BASE_DIR = Path(__file__).resolve().parent.parent
PINS_PATH = BASE_DIR / "config" / "pins.json"

CLIENT = "client"
TECHNICIAN = "technician"
ROLE_LABELS = {CLIENT: "Client", TECHNICIAN: "Technician"}
PIN_LENGTH = 4

# TODO(security): these presets are the same on every frame and readable by anyone
# who can see the repo. Sort out before real client installs, e.g. have install.sh
# set a unique technician PIN per frame and force a client PIN change on first use.
PRESET_PINS = {TECHNICIAN: "1738", CLIENT: "0000"}

MAX_ATTEMPTS = 5          # wrong PINs in a row before it locks
LOCKOUT_SECONDS = 5 * 60  # how long it stays locked
HASH_ITERATIONS = 100_000  # makes each guess slow to check if someone copies pins.json

# lockout state lives in memory - fine, because restarting the app now needs Technician mode
_failed_attempts = 0
_locked_until = 0.0


# ─── STORAGE ───────────────────────────────────────────────────────────────────
def _hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, HASH_ITERATIONS).hex()


def _load():
    if not PINS_PATH.exists():
        return {}
    try:
        with open(PINS_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception as error:
        print(f"[Access] Couldn't read pins.json — {error}")
        return {}


def _save(data):
    PINS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PINS_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def _matches(role, pin):
    record = _load().get(role)

    if record:
        try:
            salt = bytes.fromhex(record["salt"])
            return hmac.compare_digest(_hash(pin, salt), record["hash"])
        except Exception:
            print(f"[Access] Stored {role} PIN looks corrupted — run scripts/reset_pins.sh")
            return False

    return hmac.compare_digest(pin, PRESET_PINS[role])


def is_using_preset(role):
    return role not in _load()


def is_valid_format(pin):
    return len(pin) == PIN_LENGTH and pin.isdigit()


def set_pin(role, new_pin):
    """Change a PIN. Returns (ok, message) for showing on screen."""
    if not is_valid_format(new_pin):
        return False, f"PIN must be exactly {PIN_LENGTH} digits."

    # the PIN typed is what decides which mode opens, so the two can't match
    other = CLIENT if role == TECHNICIAN else TECHNICIAN
    if _matches(other, new_pin):
        return False, f"Must be different from the {ROLE_LABELS[other].lower()} PIN."

    salt = os.urandom(16)
    data = _load()
    data[role] = {"salt": salt.hex(), "hash": _hash(new_pin, salt)}
    _save(data)

    print(f"[Access] {ROLE_LABELS[role]} PIN changed")
    return True, f"{ROLE_LABELS[role]} PIN updated."


def reset_to_preset(role):
    """Used by scripts/reset_pins.sh — puts a PIN back to its preset."""
    data = _load()
    data.pop(role, None)
    _save(data)


# ─── CHECKING + LOCKOUT ────────────────────────────────────────────────────────
def lockout_remaining():
    return max(0.0, _locked_until - time.time())


def attempts_left():
    return MAX_ATTEMPTS - _failed_attempts


def check_pin(pin):
    """Returns TECHNICIAN, CLIENT, or None. Counts wrong attempts towards the lockout."""
    global _failed_attempts, _locked_until

    if lockout_remaining() > 0:
        return None

    # technician checked first, so if they somehow matched, the higher level wins
    for role in (TECHNICIAN, CLIENT):
        if _matches(role, pin):
            _failed_attempts = 0
            print(f"[Access] {ROLE_LABELS[role]} PIN accepted")
            return role

    _failed_attempts += 1
    print(f"[Access] Wrong PIN ({_failed_attempts}/{MAX_ATTEMPTS})")

    if _failed_attempts >= MAX_ATTEMPTS:
        _locked_until = time.time() + LOCKOUT_SECONDS
        _failed_attempts = 0
        print(f"[Access] Too many wrong PINs — locked for {LOCKOUT_SECONDS // 60} minutes")

    return None


# ─── PIN ENTRY SCREEN ──────────────────────────────────────────────────────────
ERROR_COLOR = (230, 120, 110)


def _draw_centered(surface, text, font, color, center_x, y):
    rendered = font.render(text, True, color)
    surface.blit(rendered, (center_x - rendered.get_width() // 2, y))


def prompt_for_pin(screen, fonts, colors):
    """
    Blocking PIN screen shown before the admin panel opens.
    Returns TECHNICIAN, CLIENT, or None if cancelled with Esc.
    """
    entered = ""
    message = ""
    clock = pygame.time.Clock()

    while True:
        # re-read every frame so it follows a dev-mode window resize
        screen = pygame.display.get_surface()
        screen_w, screen_h = screen.get_size()
        locked_for = lockout_remaining()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                if locked_for > 0:
                    continue
                if event.key == pygame.K_BACKSPACE:
                    entered = entered[:-1]
                elif event.unicode and event.unicode.isdigit() and len(entered) < PIN_LENGTH:
                    entered += event.unicode  # works for the number row and the numpad

        # ── draw ──
        screen.fill(colors["BACKGROUND_COLOR"])
        center_x = screen_w // 2

        _draw_centered(screen, "Enter PIN", fonts["title"], colors["TEXT_COLOR"], center_x, int(screen_h * 0.25))

        box_w, box_h, gap = 64, 76, 20
        total_w = PIN_LENGTH * box_w + (PIN_LENGTH - 1) * gap
        start_x = center_x - total_w // 2
        box_y = int(screen_h * 0.40)

        for i in range(PIN_LENGTH):
            box = pygame.Rect(start_x + i * (box_w + gap), box_y, box_w, box_h)
            is_next = i == len(entered) and locked_for == 0
            pygame.draw.rect(screen, colors["CARD_COLOR"], box, border_radius=12)
            pygame.draw.rect(
                screen,
                colors["HIGHLIGHT_COLOR"] if is_next else colors["CARD_BORDER"],
                box,
                width=2,
                border_radius=12,
            )
            if i < len(entered):
                pygame.draw.circle(screen, colors["TEXT_COLOR"], box.center, 10)  # dots, never the digit

        if locked_for > 0:
            minutes, seconds = divmod(int(locked_for) + 1, 60)
            status = f"Too many wrong attempts — try again in {minutes}:{seconds:02d}"
        else:
            status = message

        if status:
            _draw_centered(screen, status, fonts["body"], ERROR_COLOR, center_x, box_y + box_h + 40)

        _draw_centered(
            screen,
            f"Type the {PIN_LENGTH}-digit PIN  •  Esc to cancel",
            fonts["small"],
            colors["SUBTEXT_COLOR"],
            center_x,
            screen_h - 90,
        )

        pygame.display.flip()

        # checked after drawing so the 4th dot shows before the (deliberately slow) hash check
        if len(entered) == PIN_LENGTH:
            role = check_pin(entered)
            entered = ""
            if role:
                return role
            message = "" if lockout_remaining() > 0 else f"Incorrect PIN — {attempts_left()} attempt(s) left"

        clock.tick(30)
