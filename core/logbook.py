"""
ynotPi — core/logbook.py
------------------------
Keeps a copy of everything the app prints in logs/ynotpi.log, so the
Technician tab can show recent messages without needing access to the
system journal (which normally needs extra permissions).

Nothing else has to change — every existing print() still shows in the
terminal as normal, it just also lands in the log file with a timestamp.
Keep logs/ out of git (.gitignore).
"""

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_PATH = LOG_DIR / "ynotpi.log"
MAX_LOG_BYTES = 512 * 1024  # past this the old log gets moved to ynotpi.log.1 at startup

_started = False


class _Tee:
    """Wraps stdout/stderr: text still prints as normal, and also gets written to the log file."""

    def __init__(self, stream, log_file, label=""):
        self.stream = stream
        self.log_file = log_file
        self.label = label
        self._at_line_start = True

    def write(self, text):
        if self.stream:
            self.stream.write(text)

        try:
            for chunk in text.splitlines(keepends=True):
                if self._at_line_start:
                    self.log_file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + self.label)
                self.log_file.write(chunk)
                self._at_line_start = chunk.endswith("\n")
            self.log_file.flush()
        except Exception:
            pass  # never let logging be the thing that crashes the frame

        return len(text)

    def flush(self):
        if self.stream:
            self.stream.flush()
        try:
            self.log_file.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        # anything else (encoding, isatty, ...) goes to the real stream
        return getattr(self.stream, name)


def start():
    """Start copying stdout/stderr into the log file. Safe to call more than once."""
    global _started
    if _started:
        return

    try:
        LOG_DIR.mkdir(exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_LOG_BYTES:
            LOG_PATH.replace(LOG_PATH.with_name("ynotpi.log.1"))
        log_file = open(LOG_PATH, "a", encoding="utf-8")
    except Exception as error:
        print(f"[Log] Couldn't open the log file — {error}")
        return

    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file, label="ERROR ")  # crashes/tracebacks get flagged
    _started = True
    print("[Log] ──────── ynotPi started ────────")


def recent_lines(count=300):
    """Last `count` lines of the log, oldest first."""
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as file:
            return [line.rstrip("\n") for line in file.readlines()[-count:]]
    except FileNotFoundError:
        return ["(no log file yet)"]
    except Exception as error:
        return [f"(couldn't read the log — {error})"]
