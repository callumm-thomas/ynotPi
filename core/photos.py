"""
ynotPi — core/photos.py
-----------------------
Finding photos in the three places the frame looks: the local folder, a USB
stick, and the network share. Used by the slideshow (photoframe.py) and by the
Photo Sources tab in the admin panel, so both always agree on what's there.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LOCAL_PHOTO_PATH = str(BASE_DIR / "assets" / "photos")  # anchored to the repo, not whatever folder we got launched from
NETWORK_SHARE_MOUNT = "/mnt/photos"
# dict.fromkeys = remove the duplicate when the user really is called "pi", keeping the order
USB_BASE_PATHS = list(dict.fromkeys(["/media/pi", f"/media/{os.environ.get('USER', 'pi')}"]))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".jfif", ".png", ".bmp", ".gif", ".webp"}

# source key -> (name shown in the admin panel, where it looks, folders to search)
SOURCES = {
    "local": ("Local Folder", "assets/photos", [LOCAL_PHOTO_PATH]),
    "usb": ("USB Drive", "/media/pi, /media/<user>", USB_BASE_PATHS),
    "network": ("Network Folder", NETWORK_SHARE_MOUNT, [NETWORK_SHARE_MOUNT]),
}


def _folder_has_something(folder):
    try:
        return os.path.isdir(folder) and bool(os.listdir(folder))
    except OSError:
        return False  # e.g. a network share that has dropped out


def is_available(source):
    """Is there anything plugged in / mounted for this source right now?"""
    return any(_folder_has_something(folder) for folder in SOURCES[source][2])


def find_photos(source):
    """Every image file for one source ('local', 'usb' or 'network'), sorted, as full paths."""
    found = []
    for base in SOURCES[source][2]:
        if not _folder_has_something(base):
            continue
        # onerror: skip folders we aren't allowed into instead of crashing the slideshow
        for root, _, files in os.walk(base, onerror=lambda error: None):
            for file_name in files:
                if Path(file_name).suffix.lower() in IMAGE_EXTENSIONS:
                    found.append(os.path.join(root, file_name))
    return sorted(set(found), key=str.lower)


def short_name(source, path):
    """A photo's path without the long folder prefix - what gets shown in the list."""
    for base in SOURCES[source][2]:
        try:
            return Path(path).relative_to(base).as_posix()
        except ValueError:
            continue
    return os.path.basename(path)
