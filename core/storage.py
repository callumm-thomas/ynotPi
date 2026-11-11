"""
ynotPi — core/storage.py
------------------------
Where this frame's own files live, and a safe way to save them.

Two kinds of config file:
- factory defaults, shipped with the code and tracked in git:
      config/settings.json, config/apis.json
- this frame's own copies, changed from the admin panel and NOT in git:
      config/local/settings.json, config/local/apis.json

The app reads the local copy if there is one, otherwise the factory default,
and it only ever writes to config/local/. That way changing a setting on the
frame never leaves git with a modified tracked file, so the "git pull" that
runs on every boot can't get blocked by it.

(A frame that was set up before config/local/ existed just carries on: its old
config/settings.json is read as the "default" until the first save, which
writes the local copy with everything in it.)
"""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
LOCAL_DIR = CONFIG_DIR / "local"

SETTINGS_PATH = LOCAL_DIR / "settings.json"
APIS_PATH = LOCAL_DIR / "apis.json"
FACTORY_SETTINGS_PATH = CONFIG_DIR / "settings.json"
FACTORY_APIS_PATH = CONFIG_DIR / "apis.json"
SECRETS_PATH = CONFIG_DIR / "secrets.env"


def write_text_safely(path, text, private=False):
    """
    Write to a temp file, then swap it into place in one step. If the power is
    pulled half way through a save, the old file is still there in one piece
    (a plain open(...,"w") would leave it empty or cut off).
    private=True makes the file readable by this user only - used for API keys.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")

    with open(temp_path, "w", encoding="utf-8") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())

    if private:
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass  # Windows dev machines don't do unix permissions - not a problem

    os.replace(temp_path, path)


def write_json_safely(path, data):
    write_text_safely(path, json.dumps(data, indent=2) + "\n")


def read_json(local_path, factory_path, label="config"):
    """
    The frame's own copy if it exists and opens, otherwise the factory default.
    Returns None if neither can be read.
    """
    for path in (local_path, factory_path):
        if not Path(path).exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as error:
            print(f"[Storage] Couldn't read {label} file {path} — {error}")
    return None


# ─── ONE-OFF MOVE FOR FRAMES SET UP BEFORE config/local/ ───────────────────────
def migrate_to_local():
    """
    Frames set up before config/local/ existed saved their settings straight
    into the tracked files (config/settings.json, config/apis.json). This copies
    those into config/local/ once, then puts the tracked files back to the
    version in git, so the next "git pull" can't be blocked by them.

    Safe to call on every start - it only does anything the first time.
    """
    import subprocess

    restore = []
    for local_path, factory_path in ((SETTINGS_PATH, FACTORY_SETTINGS_PATH), (APIS_PATH, FACTORY_APIS_PATH)):
        if local_path.exists() or not factory_path.exists():
            continue
        try:
            with open(factory_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            write_json_safely(local_path, data)
            restore.append(str(factory_path.relative_to(BASE_DIR)))
            print(f"[Storage] Moved this frame's {factory_path.name} into config/local/")
        except Exception as error:
            print(f"[Storage] Couldn't move {factory_path.name} into config/local/ — {error}")

    if not restore:
        return

    # only restore files git says are changed - and quietly skip if there's no git (dev machine, zip copy)
    try:
        changed = subprocess.run(
            ["git", "-C", str(BASE_DIR), "diff", "--name-only", "--"] + restore,
            capture_output=True, text=True, timeout=10,
        )
        to_restore = [name for name in changed.stdout.split() if name]
        if changed.returncode == 0 and to_restore:
            subprocess.run(["git", "-C", str(BASE_DIR), "checkout", "--"] + to_restore,
                           capture_output=True, text=True, timeout=10)
            print(f"[Storage] Reset {', '.join(to_restore)} to the git version (this frame's copy is in config/local/)")
    except Exception as error:
        print(f"[Storage] Skipped resetting the tracked config files — {error}")
