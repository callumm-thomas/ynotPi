"""
ynotPi — core/technician.py
---------------------------
The Technician tab in the admin panel (only opens with the technician PIN).

Pages:
- System : hostname, IP, Tailscale, code version, disk space
- PINs   : change the client + technician PINs
- Log    : recent messages from logs/ynotpi.log
- Power  : update now, restart app, reboot Pi, exit to desktop

Reboot + exit-to-desktop need root for one command each. install.sh adds a
narrow rule (/etc/sudoers.d/ynotpi) allowing exactly those commands and nothing
else. They're checked before running, with a clear message if the rule is missing.

Restart / exit are handed back to photoframe.py to carry out (it has to close
pygame first), which is why handle_event() and tick() can return an action.
"""

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pygame

from core import access, logbook

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_NAME = "ynotpi.service"
SYSTEMCTL = "/usr/bin/systemctl"

# these must match /etc/sudoers.d/ynotpi (written by install.sh) exactly
REBOOT_CMD = ["sudo", "-n", SYSTEMCTL, "reboot"]
STOP_SERVICE_CMD = ["sudo", "-n", SYSTEMCTL, "stop", SERVICE_NAME]

SUB_PAGES = ["System", "PINs", "Log", "Power"]

POWER_ACTIONS = [
    ("update", "Update now", "Pull the latest code from GitHub, then restart"),
    ("restart", "Restart app", "Close and reopen the photo frame"),
    ("reboot", "Reboot Pi", "Restart the whole Raspberry Pi"),
    ("exit", "Exit to desktop", "Close the photo frame and leave it closed"),
]

ERROR_COLOR = (230, 120, 110)
OK_COLOR = (110, 210, 130)
WARN_COLOR = (230, 180, 90)


# ─── SYSTEM HELPERS ────────────────────────────────────────────────────────────
def _run(cmd, timeout=5):
    """Run a command, return (exit code or None, stdout, stderr). Never raises."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
    except FileNotFoundError:
        return None, "", "not installed"
    except subprocess.TimeoutExpired:
        return None, "", "timed out"
    except Exception as error:
        return None, "", str(error)


def is_linux():
    return platform.system() == "Linux"


def running_under_systemd():
    # systemd sets this for every service it starts
    return bool(os.environ.get("INVOCATION_ID"))


def can_sudo(cmd):
    """True if the sudo rule allows this exact command. Only asks sudo - runs nothing."""
    code, _, _ = _run(["sudo", "-n", "-l"] + cmd[2:])
    return code == 0


def local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # UDP "connect" sends nothing - just picks the outgoing interface
        return sock.getsockname()[0]
    except OSError:
        return "No network"
    finally:
        sock.close()


def tailscale_status():
    code, out, err = _run(["tailscale", "ip", "-4"])
    if err == "not installed":
        return "Not installed"
    if code == 0 and out:
        return f"Connected — {out.splitlines()[0]}"
    return "Installed, not connected"


def code_version():
    code, out, _ = _run(
        ["git", "-C", str(BASE_DIR), "log", "-1", "--format=%h  (%cd)", "--date=format:%d %b %Y %H:%M"]
    )
    return out if code == 0 and out else "Unknown (not a git checkout?)"


def disk_space():
    try:
        usage = shutil.disk_usage(BASE_DIR)
        gb = 1024 ** 3
        percent = round(usage.used / usage.total * 100)
        return f"{usage.free / gb:.1f} GB free of {usage.total / gb:.1f} GB  ({percent}% used)"
    except Exception as error:
        return f"Unknown — {error}"


def system_info():
    return [
        ("Hostname", socket.gethostname()),
        ("IP address", local_ip()),
        ("Tailscale", tailscale_status()),
        ("Code version", code_version()),
        ("Disk", disk_space()),
        ("Python", platform.python_version()),
        ("System", platform.platform(terse=True)),
    ]


# ─── ACTIONS ───────────────────────────────────────────────────────────────────
def update_code():
    """git pull. Returns (ok, changed, message)."""
    print("[Technician] Checking GitHub for updates...")
    code, out, err = _run(["git", "-C", str(BASE_DIR), "pull", "origin", "main"], timeout=60)

    if code == 0:
        if "Already up to date" in out:
            return True, False, "Already up to date."
        print(f"[Technician] Update pulled:\n{out}")
        return True, True, "Updated — restarting..."

    detail = (err or out).splitlines()[-1] if (err or out) else "unknown error"
    print(f"[Technician] Update failed: {err or out}")
    return False, False, f"Update failed: {detail}"


def reboot():
    if not can_sudo(REBOOT_CMD):
        return False, "Reboot permission isn't set up on this Pi — re-run install.sh."

    print("[Technician] Rebooting")
    code, _, err = _run(REBOOT_CMD, timeout=10)
    if code == 0:
        return True, "Rebooting..."
    return False, f"Reboot failed: {err}"


def restart_app():
    """Called by photoframe.py after pygame has closed. Reopens the app with the same flags."""
    script = str(BASE_DIR / "core" / "photoframe.py")
    args = [sys.executable, script] + sys.argv[1:]
    print("[Technician] Restarting app")
    sys.stdout.flush()

    if os.name == "nt":
        # os.execv is unreliable on Windows (paths with spaces) - start a fresh copy instead
        subprocess.Popen(args)
        sys.exit(0)

    os.execv(sys.executable, args)  # replaces this process, so systemd / run.sh don't notice a gap


def exit_to_desktop():
    """Called by photoframe.py after pygame has closed."""
    print("[Technician] Exiting to desktop")
    sys.stdout.flush()

    if running_under_systemd():
        # if we just quit, the service could start us straight back up - so stop it properly
        subprocess.Popen(STOP_SERVICE_CMD)

    sys.exit(0)


# ─── SMALL DRAW HELPERS ────────────────────────────────────────────────────────
def _text(surface, text, font, color, pos):
    surface.blit(font.render(text, True, color), pos)


def _button(surface, rect, label, font, colors, active=False, highlight=False):
    bg = colors["BUTTON_HOVER"] if active else colors["BUTTON_COLOR"]
    pygame.draw.rect(surface, bg, rect, border_radius=10)
    if active or highlight:
        pygame.draw.rect(surface, colors["HIGHLIGHT_COLOR"], rect, width=2, border_radius=10)
    rendered = font.render(label, True, colors["TEXT_COLOR"])
    surface.blit(rendered, rendered.get_rect(center=rect.center))


# ─── THE TAB ───────────────────────────────────────────────────────────────────
class TechnicianTab:
    def __init__(self, dev_mode=False):
        self.dev_mode = dev_mode
        self.page = "System"
        self.info = None
        self.log_lines = []
        self.log_scroll = 0  # how many lines up from the newest
        self.status = ""
        self.status_ok = True
        self.confirming = None  # power action waiting for its second click
        self.pending = None     # slow action to run once the "please wait" message has been drawn
        self.pin_text = {access.CLIENT: "", access.TECHNICIAN: ""}
        self.active_pin = None

    def has_active_field(self):
        return self.active_pin is not None

    def _set_status(self, text, ok=True):
        self.status = text
        self.status_ok = ok

    def _open_page(self, name):
        self.page = name
        self.confirming = None
        self.active_pin = None
        self._set_status("")

        if name == "System":
            self.info = system_info()
        elif name == "Log":
            self.log_lines = logbook.recent_lines()
            self.log_scroll = 0

    # ── layout (worked out every frame so it follows window resizes) ──
    def _page_rects(self, fonts):
        rects = []
        x = 60
        for name in SUB_PAGES:
            width = fonts["small"].size(name)[0] + 36
            rects.append((pygame.Rect(x, 96, width, 38), name))
            x += width + 10
        return rects

    @staticmethod
    def _refresh_rect(screen_w):
        return pygame.Rect(screen_w - 200, 96, 140, 38)

    @staticmethod
    def _pin_rects(role_index):
        y = 170 + role_index * 170
        return pygame.Rect(60, y + 70, 200, 50), pygame.Rect(280, y + 70, 160, 50)

    @staticmethod
    def _power_rect(index):
        return pygame.Rect(60, 170 + index * 80, 240, 56)

    def _log_rect(self, screen_w, screen_h):
        return pygame.Rect(60, 150, screen_w - 120, screen_h - 150 - 160)  # leaves room for the hint + status line

    # ── events ──
    def handle_event(self, event, screen, fonts):
        """Returns "restart" / "exit" if the app needs to do that, otherwise None."""
        screen_w, screen_h = screen.get_size()

        if event.type == pygame.KEYDOWN:
            if self.active_pin:
                if event.key == pygame.K_ESCAPE:
                    self.active_pin = None
                elif event.key == pygame.K_RETURN:
                    self._save_pin(self.active_pin)
                elif event.key == pygame.K_BACKSPACE:
                    self.pin_text[self.active_pin] = self.pin_text[self.active_pin][:-1]
                elif event.unicode and event.unicode.isdigit() and len(self.pin_text[self.active_pin]) < access.PIN_LENGTH:
                    self.pin_text[self.active_pin] += event.unicode
                return None

            if self.page == "Log":
                if event.key == pygame.K_UP:
                    self._scroll_log(3, screen_h, fonts)
                elif event.key == pygame.K_DOWN:
                    self._scroll_log(-3, screen_h, fonts)
            return None

        if event.type == pygame.MOUSEWHEEL and self.page == "Log":
            self._scroll_log(event.y * 3, screen_h, fonts)
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos

            for rect, name in self._page_rects(fonts):
                if rect.collidepoint(pos):
                    self._open_page(name)
                    return None

            if self.page in ("System", "Log") and self._refresh_rect(screen_w).collidepoint(pos):
                self._open_page(self.page)
                return None

            if self.page == "PINs":
                self.active_pin = None
                for i, role in enumerate((access.CLIENT, access.TECHNICIAN)):
                    field_rect, save_rect = self._pin_rects(i)
                    if field_rect.collidepoint(pos):
                        self.active_pin = role
                    elif save_rect.collidepoint(pos):
                        self._save_pin(role)

            elif self.page == "Power":
                for i, (action, label, _) in enumerate(POWER_ACTIONS):
                    if self._power_rect(i).collidepoint(pos):
                        return self._power_clicked(action, label)

        return None

    def _scroll_log(self, amount, screen_h, fonts):
        visible = max(1, self._log_rect(0, screen_h).height // (fonts["small"].get_height() + 4))
        max_scroll = max(0, len(self.log_lines) - visible)
        self.log_scroll = max(0, min(max_scroll, self.log_scroll + amount))

    def _save_pin(self, role):
        ok, message = access.set_pin(role, self.pin_text[role])
        self._set_status(message, ok)
        if ok:
            self.pin_text[role] = ""
            self.active_pin = None

    def _power_clicked(self, action, label):
        if action == "update":
            if self.dev_mode:
                self._set_status("Update is off in dev mode — it would pull into your working copy. Use git.", False)
                return None
            self.pending = "update"
            self._set_status("Checking GitHub for updates...")
            return None

        if action == "reboot" and (self.dev_mode or not is_linux()):
            self._set_status("Not available on this computer.", False)
            return None

        # everything below needs a second click, so a stray click can't take the frame down
        if self.confirming != action:
            self.confirming = action
            self._set_status(f"Click '{label}' again to confirm.")
            return None
        self.confirming = None

        if action == "restart":
            return "restart"

        if action == "reboot":
            self.pending = "reboot"
            self._set_status("Rebooting...")
            return None

        if action == "exit":
            if running_under_systemd() and not can_sudo(STOP_SERVICE_CMD):
                self._set_status("Exit permission isn't set up on this Pi — re-run install.sh.", False)
                return None
            return "exit"

        return None

    def tick(self):
        """Runs slow actions after their 'please wait' message is on screen. May return an app action."""
        action, self.pending = self.pending, None

        if action == "update":
            ok, changed, message = update_code()
            self._set_status(message, ok)
            if changed:
                return "restart"

        elif action == "reboot":
            ok, message = reboot()
            self._set_status(message, ok)

        return None

    # ── drawing ──
    def draw(self, screen, fonts, colors):
        screen_w, screen_h = screen.get_size()

        for rect, name in self._page_rects(fonts):
            _button(screen, rect, name, fonts["small"], colors, active=(name == self.page))

        if self.page in ("System", "Log"):
            _button(screen, self._refresh_rect(screen_w), "Refresh", fonts["small"], colors)

        if self.page == "System":
            self._draw_system(screen, fonts, colors)
        elif self.page == "PINs":
            self._draw_pins(screen, fonts, colors)
        elif self.page == "Log":
            self._draw_log(screen, fonts, colors)
        elif self.page == "Power":
            self._draw_power(screen, fonts, colors)

        if self.status:
            color = colors["HIGHLIGHT_COLOR"] if self.status_ok else ERROR_COLOR
            _text(screen, self.status, fonts["body"], color, (60, screen_h - 115))

    def _draw_system(self, screen, fonts, colors):
        if self.info is None:
            self.info = system_info()

        y = 170
        row_h = fonts["body"].get_height() + 18
        for label, value in self.info:
            _text(screen, label, fonts["small"], colors["SUBTEXT_COLOR"], (60, y + 4))
            _text(screen, str(value), fonts["body"], colors["TEXT_COLOR"], (260, y))
            y += row_h

        if self.dev_mode:
            _text(screen, "Dev mode — running on this computer, not the Pi.", fonts["small"], WARN_COLOR, (60, y + 10))

    def _draw_pins(self, screen, fonts, colors):
        rows = [
            (access.CLIENT, "Client PIN — opens Admin mode"),
            (access.TECHNICIAN, "Technician PIN — opens Admin + Technician mode"),
        ]

        for i, (role, title) in enumerate(rows):
            y = 170 + i * 170
            field_rect, save_rect = self._pin_rects(i)

            _text(screen, title, fonts["body"], colors["TEXT_COLOR"], (60, y))
            if access.is_using_preset(role):
                _text(screen, "Still using the preset PIN — change it before handing the frame over.", fonts["small"], WARN_COLOR, (60, y + 36))
            else:
                _text(screen, "Custom PIN set.", fonts["small"], OK_COLOR, (60, y + 36))

            active = self.active_pin == role
            pygame.draw.rect(screen, colors["CARD_COLOR"], field_rect, border_radius=8)
            pygame.draw.rect(screen, colors["HIGHLIGHT_COLOR"] if active else colors["CARD_BORDER"], field_rect, width=2, border_radius=8)

            typed = self.pin_text[role]
            if typed or active:
                shown = "•  " * len(typed) + ("|" if active and int(pygame.time.get_ticks() / 500) % 2 == 0 else "")
                _text(screen, shown.strip(), fonts["body"], colors["TEXT_COLOR"], (field_rect.x + 14, field_rect.y + 10))
            else:
                _text(screen, "New PIN", fonts["small"], colors["SUBTEXT_COLOR"], (field_rect.x + 14, field_rect.y + 14))

            _button(screen, save_rect, "Save", fonts["body"], colors)

        _text(
            screen,
            "Forgotten the technician PIN? Run scripts/reset_pins.sh on the Pi over SSH.",
            fonts["small"],
            colors["SUBTEXT_COLOR"],
            (60, 170 + 2 * 170),
        )

    def _draw_log(self, screen, fonts, colors):
        screen_w, screen_h = screen.get_size()
        box = self._log_rect(screen_w, screen_h)
        pygame.draw.rect(screen, colors["CARD_COLOR"], box, border_radius=10)
        pygame.draw.rect(screen, colors["CARD_BORDER"], box, width=1, border_radius=10)

        font = fonts["small"]
        line_h = font.get_height() + 4
        visible = max(1, (box.height - 20) // line_h)
        max_chars = max(10, (box.width - 30) // max(1, font.size("0")[0]))  # rough cut-off, cheap every frame

        end = len(self.log_lines) - self.log_scroll
        start = max(0, end - visible)

        y = box.y + 10
        for line in self.log_lines[start:end]:
            lowered = line.lower()
            is_problem = any(word in lowered for word in ("error", "failed", "couldn't", "traceback"))
            text = line if len(line) <= max_chars else line[: max_chars - 3] + "..."
            _text(screen, text, font, ERROR_COLOR if is_problem else colors["TEXT_COLOR"], (box.x + 15, y))
            y += line_h

        hint = "Newest at the bottom  •  scroll with the mouse wheel or Up/Down"
        if self.log_scroll:
            hint += f"  •  {self.log_scroll} line(s) up"
        _text(screen, hint, font, colors["SUBTEXT_COLOR"], (box.x, box.bottom + 8))

    def _draw_power(self, screen, fonts, colors):
        for i, (action, label, description) in enumerate(POWER_ACTIONS):
            rect = self._power_rect(i)
            _button(screen, rect, label, fonts["body"], colors, highlight=(self.confirming == action))
            _text(screen, description, fonts["small"], colors["SUBTEXT_COLOR"], (rect.right + 30, rect.y + 16))
