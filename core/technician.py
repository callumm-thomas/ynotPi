"""
ynotPi — core/technician.py
---------------------------
The Technician tab in the admin panel (only opens with the technician PIN).

Pages:
- System : hostname, IP, Tailscale, code version, disk space
- PINs   : change the client + technician PINs
- Log    : recent messages from logs/ynotpi.log
- Power  : update now, restart app, reboot Pi, exit to desktop

Drawn with the shared toolkit in ui.py, so keyboard + mouse work like every other tab.

Reboot + exit-to-desktop need root for one command each. install.sh adds a
narrow rule (/etc/sudoers.d/ynotpi) allowing exactly those commands and nothing
else. They're checked before running, with a clear message if the rule is missing.

Restart / exit are handed back to photoframe.py to carry out (it has to close
pygame first), which is why handle_action() and tick() can return an action.
"""

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pygame

from core import access, logbook, ui

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


# ─── THE TAB ───────────────────────────────────────────────────────────────────
class TechnicianTab(ui.Tab):
    name = "Technician"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.dev_mode = ctx.dev_mode
        self.page = "System"
        self.info = None
        self.log_lines = []
        self.log_scroll = 0  # how many lines up from the newest
        self.log_visible = 1
        self.confirming = None  # power action waiting for its second press
        self.pending = None     # slow action to run once the "please wait" message has been drawn
        self.pin_form = {access.CLIENT: "", access.TECHNICIAN: ""}

    @property
    def hint(self):
        if self.page == "Log":
            return "Up/Down: scroll the log    Esc: back"
        return "Arrows: move    Enter: select    Esc: back"

    def _open_page(self, name):
        self.page = name
        self.confirming = None
        self.say("")

        if name == "System":
            self.info = system_info()
        elif name == "Log":
            self.log_lines = logbook.recent_lines()
            self.log_scroll = 0

    def opened(self, ui_):
        self.confirming = None

    # ── events ──
    def handle_raw(self, event, ui_):
        if event.type == pygame.MOUSEWHEEL:
            self.handle_wheel(event)
            return False  # let the toolkit see it too (it ignores it - there are no lists on this tab)

        # on the Log page, Up/Down scroll the log while the focus is on the log box
        if self.page != "Log" or ui_.focus != "log:box":
            return False
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            step = {pygame.K_UP: 3, pygame.K_DOWN: -3,
                    pygame.K_PAGEUP: self.log_visible, pygame.K_PAGEDOWN: -self.log_visible}[event.key]
            if event.key == pygame.K_DOWN and self.log_scroll == 0:
                return False  # already at the newest line - let Down move on as normal
            self._scroll_log(step)
            return True
        return False

    def handle_action(self, action, ui_):
        """Returns "restart" / "exit" if the app needs to do that, otherwise None."""
        kind, item_id = action[0], str(action[1])

        if not (kind == "activate" and item_id.startswith("power:")):
            self.confirming = None

        if kind == "commit" and item_id.startswith("pin:field:"):
            self._save_pin(item_id.rsplit(":", 1)[1])
            return None
        if kind != "activate":
            return None

        if item_id.startswith("page:"):
            self._open_page(item_id.split(":", 1)[1])
        elif item_id == "refresh":
            self._open_page(self.page)
        elif item_id.startswith("pin:save:"):
            self._save_pin(item_id.rsplit(":", 1)[1])
        elif item_id.startswith("power:"):
            action_name = item_id.split(":", 1)[1]
            label = next(label for name, label, _ in POWER_ACTIONS if name == action_name)
            return self._power_clicked(action_name, label)
        return None

    def _scroll_log(self, amount):
        max_scroll = max(0, len(self.log_lines) - self.log_visible)
        self.log_scroll = max(0, min(max_scroll, self.log_scroll + amount))

    def _save_pin(self, role):
        ok, message = access.set_pin(role, self.pin_form[role])
        self.say(message, ok)
        self.pin_form[role] = ""  # cleared either way - a PIN never sits on screen

    def _power_clicked(self, action, label):
        if action == "update":
            if self.dev_mode:
                self.say("Update is off in dev mode — it would pull into your working copy. Use git.", False)
                return None
            self.pending = "update"
            self.say("Checking GitHub for updates...")
            return None

        if action == "reboot" and (self.dev_mode or not is_linux()):
            self.say("Not available on this computer.", False)
            return None

        # everything below needs a second press, so a stray click can't take the frame down
        if self.confirming != action:
            self.confirming = action
            self.say(f"Press '{label}' again to confirm.")
            return None
        self.confirming = None

        if action == "restart":
            return "restart"

        if action == "reboot":
            self.pending = "reboot"
            self.say("Rebooting...")
            return None

        if action == "exit":
            if running_under_systemd() and not can_sudo(STOP_SERVICE_CMD):
                self.say("Exit permission isn't set up on this Pi — re-run install.sh.", False)
                return None
            return "exit"

        return None

    def tick(self):
        """Runs slow actions after their 'please wait' message is on screen. May return an app action."""
        action, self.pending = self.pending, None

        if action == "update":
            ok, changed, message = update_code()
            self.say(message, ok)
            if changed:
                return "restart"

        elif action == "reboot":
            ok, message = reboot()
            self.say(message, ok)

        return None

    # ── drawing ──
    def draw(self, ui_, area):
        x = area.x
        for name in SUB_PAGES:
            width = ui_.button_w(name, "small")
            ui_.button(f"page:{name}", pygame.Rect(x, area.y, width, ui_.h_small), name, font="small", active=(name == self.page))
            x += width + 6

        if self.page in ("System", "Log"):
            width = ui_.button_w("Refresh", "small")
            ui_.button("refresh", pygame.Rect(area.right - width, area.y, width, ui_.h_small), "Refresh", font="small")

        body = pygame.Rect(area.x, area.y + ui_.h_small + ui_.u, area.width, area.height - ui_.h_small - ui_.u)
        if self.page == "System":
            self._draw_system(ui_, body)
        elif self.page == "PINs":
            self._draw_pins(ui_, body)
        elif self.page == "Log":
            self._draw_log(ui_, body)
        elif self.page == "Power":
            self._draw_power(ui_, body)

    def _draw_system(self, ui_, rect):
        if self.info is None:
            self.info = system_info()

        label_w = max(ui_.fonts["small"].size(label)[0] for label, _ in self.info) + 2 * ui_.pad
        row_h = ui_.fonts["body"].get_height() + max(4, ui_.pad // 2)
        y = rect.y
        for label, value in self.info:
            if y + row_h > rect.bottom:
                break
            ui_.text(label, (rect.x, y + 4))
            ui_.text(str(value), (rect.x + label_w, y), "body", "TEXT_COLOR", max_w=rect.width - label_w)
            y += row_h

        if self.dev_mode and y + ui_.u <= rect.bottom:
            ui_.text("Dev mode — running on this computer, not the Pi.", (rect.x, y + 6), color=ui.WARN_COLOR)

    def _draw_pins(self, ui_, rect):
        rows = [
            (access.CLIENT, "Client PIN — opens Admin mode"),
            (access.TECHNICIAN, "Technician PIN — opens Admin + Technician mode"),
        ]
        body_h = ui_.fonts["body"].get_height()
        y = rect.y

        for role, title in rows:
            ui_.text(title, (rect.x, y), "body", "TEXT_COLOR", max_w=rect.width)
            y += body_h + 4
            if access.is_using_preset(role):
                ui_.text("Still using the preset PIN — change it before handing the frame over.", (rect.x, y),
                         color=ui.WARN_COLOR, max_w=rect.width)
            else:
                ui_.text("Custom PIN set.", (rect.x, y), color=ui.OK_COLOR)
            y += ui_.u + ui_.pad

            field_w = ui_.fonts["body"].size("0000")[0] + 8 * ui_.pad
            ui_.text_input(f"pin:field:{role}", pygame.Rect(rect.x, y, field_w, ui_.h_body), self.pin_form, role,
                           placeholder="New PIN", allowed=set("0123456789"), max_len=access.PIN_LENGTH, dots=True)
            ui_.button(f"pin:save:{role}", pygame.Rect(rect.x + field_w + ui_.pad, y, ui_.button_w("Save"), ui_.h_body), "Save")
            y += ui_.h_body + 2 * ui_.u

        ui_.text("Forgotten the technician PIN? Run scripts/reset_pins.sh on the Pi over SSH.",
                 (rect.x, y), max_w=rect.width)

    def _draw_log(self, ui_, rect):
        colors = ui_.colors
        box = pygame.Rect(rect.x, rect.y, rect.width, rect.height - ui_.u - 8)
        state = ui_.register("log:box", box, kind="row")
        pygame.draw.rect(ui_.screen, colors["CARD_COLOR"], box, border_radius=10)
        pygame.draw.rect(ui_.screen, colors["CARD_BORDER"], box, width=1, border_radius=10)

        font = ui_.fonts["small"]
        line_h = font.get_height() + 4
        self.log_visible = max(1, (box.height - 20) // line_h)
        self._scroll_log(0)  # keeps the scroll in range if the window changed size

        end = len(self.log_lines) - self.log_scroll
        start = max(0, end - self.log_visible)

        y = box.y + 10
        for line in self.log_lines[start:end]:
            lowered = line.lower()
            is_problem = any(word in lowered for word in ("error", "failed", "couldn't", "traceback"))
            ui_.text(line, (box.x + 15, y), color=ui.ERROR_COLOR if is_problem else "TEXT_COLOR", max_w=box.width - 30)
            y += line_h

        hint = "Newest at the bottom  •  scroll with the mouse wheel, or select the log and use Up/Down"
        if self.log_scroll:
            hint += f"  •  {self.log_scroll} line(s) up"
        ui_.text(hint, (box.x, box.bottom + 6), max_w=box.width)

        # mouse wheel over the log scrolls it (the toolkit's wheel handling is for lists)
        self._log_box = box

    def handle_wheel(self, event):
        box = getattr(self, "_log_box", None)
        if self.page == "Log" and box is not None and box.collidepoint(pygame.mouse.get_pos()):
            self._scroll_log(event.y * 3)

    def _draw_power(self, ui_, rect):
        width = max(ui_.button_w(label) for _, label, _ in POWER_ACTIONS)
        y = rect.y
        for action, label, description in POWER_ACTIONS:
            button = pygame.Rect(rect.x, y, width, ui_.h_body)
            ui_.button(f"power:{action}", button, label, warn=(self.confirming == action))
            ui_.text(description, (button.right + 2 * ui_.pad, y + (ui_.h_body - ui_.u) // 2),
                     max_w=rect.right - button.right - 2 * ui_.pad)
            y += ui_.h_body + ui_.pad
