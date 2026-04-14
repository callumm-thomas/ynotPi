#!/usr/bin/env python3
"""
Photo Frame v1.0 — Source Selector Edition
-------------------------------------------
Boots into a simple pygame menu where the user picks their photo source:
  - USB stick
  - Network share
  - Both (why not!)

After picking, it jumps straight into the slideshow — fullscreen, crop-to-fill,
auto-advances every 10 seconds, spacebar to skip manually.
No clock yet, that's coming later. Just pure photo goodness for now.
"""

import pygame
import os
import sys
import time
import random
from pathlib import Path


# ─── CONFIG ────────────────────────────────────────────────────────────────────
# all the knobs you might want to turn

SLIDE_DURATION = 10              # seconds each photo stays on screen
BACKGROUND_COLOR = (30, 30, 30)  # dark background used everywhere
TEXT_COLOR       = (255, 255, 255)  # white — main text
SUBTEXT_COLOR    = (160, 160, 160)  # grey — secondary / hint text
HIGHLIGHT_COLOR  = (70, 130, 200)   # blue — selected menu button
BUTTON_COLOR     = (55, 55, 55)     # unselected button background
BUTTON_HOVER     = (75, 75, 75)     # button when mouse hovers over it

# change this to wherever your network share is mounted
NETWORK_SHARE_MOUNT = "/mnt/photos"

# photo file types we care about
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}

# Pi usually mounts USB drives here — adjust if yours is different
USB_BASE_PATHS = ["/media/pi", f"/media/{os.environ.get('USER', 'pi')}"]


# ─── PHOTO DISCOVERY ───────────────────────────────────────────────────────────

def find_usb_photos():
    # walk all known USB mount locations and collect every image file found
    photos = []
    for base in USB_BASE_PATHS:
        if os.path.isdir(base):
            for root, _, files in os.walk(base):
                for f in files:
                    if Path(f).suffix.lower() in IMAGE_EXTENSIONS:
                        photos.append(os.path.join(root, f))
    return photos


def find_network_photos():
    # check the network share — if it's not mounted or empty, bail out quietly
    photos = []
    if os.path.isdir(NETWORK_SHARE_MOUNT) and os.listdir(NETWORK_SHARE_MOUNT):
        for root, _, files in os.walk(NETWORK_SHARE_MOUNT):
            for f in files:
                if Path(f).suffix.lower() in IMAGE_EXTENSIONS:
                    photos.append(os.path.join(root, f))
    return photos


def get_photos(source):
    # grab photos from whichever source the user picked
    # 'usb', 'network', or 'both' — then shuffle so it's not the same order every time
    if source == "usb":
        photos = find_usb_photos()
    elif source == "network":
        photos = find_network_photos()
    else:
        # both — combine, deduplicate, done
        photos = list(set(find_usb_photos() + find_network_photos()))

    random.shuffle(photos)
    print(f"[PhotoFrame] Loaded {len(photos)} photo(s) from source: {source}")
    return photos


# ─── IMAGE HELPERS ─────────────────────────────────────────────────────────────

def crop_to_fill(image, target_w, target_h):
    # scale the image so it fills the whole area, then centre-crop
    # the result — no black bars, no squishing
    img_w, img_h = image.get_size()
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    scaled = pygame.transform.smoothscale(image, (new_w, new_h))
    # trim the overflow equally from both sides
    x = (new_w - target_w) // 2
    y = (new_h - target_h) // 2
    cropped = scaled.subsurface(pygame.Rect(x, y, target_w, target_h))
    return cropped.copy()  # .copy() so we're not holding onto the giant scaled surface


def load_image(path, target_w, target_h):
    # try to load and prep a photo — returns None if something goes wrong
    # so the caller can just skip over broken files without crashing
    try:
        img = pygame.image.load(path).convert()  # .convert() makes blitting faster
        return crop_to_fill(img, target_w, target_h)
    except Exception as e:
        print(f"[PhotoFrame] Skipping {path} — couldn't load it: {e}")
        return None


# ─── MENU SCREEN ───────────────────────────────────────────────────────────────

class Button:
    # a simple clickable button — tracks hover state and returns True when clicked
    def __init__(self, rect, label, value):
        self.rect  = pygame.Rect(rect)
        self.label = label
        self.value = value  # what this button represents (e.g. "usb", "network", "both")

    def draw(self, surface, font, selected=False):
        # pick the right colour depending on whether this button is selected or hovered
        mouse_pos = pygame.mouse.get_pos()
        if selected:
            color = HIGHLIGHT_COLOR
        elif self.rect.collidepoint(mouse_pos):
            color = BUTTON_HOVER
        else:
            color = BUTTON_COLOR

        # draw the rounded rectangle background
        pygame.draw.rect(surface, color, self.rect, border_radius=10)

        # centre the label text inside the button
        text_surf = font.render(self.label, True, TEXT_COLOR)
        tx = self.rect.centerx - text_surf.get_width() // 2
        ty = self.rect.centery - text_surf.get_height() // 2
        surface.blit(text_surf, (tx, ty))

    def is_clicked(self, event):
        # returns True if this button was clicked with the left mouse button
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(event.pos)
        )


def show_menu(screen, screen_w, screen_h):
    """
    Draw the source selection menu and wait for the user to pick one.
    Returns one of: 'usb', 'network', 'both'
    """
    title_font  = pygame.font.SysFont("dejavusans", 48, bold=True)
    button_font = pygame.font.SysFont("dejavusans", 32)
    hint_font   = pygame.font.SysFont("dejavusans", 22)

    # lay out three buttons vertically in the centre of the screen
    btn_w, btn_h = 340, 70
    btn_x = screen_w // 2 - btn_w // 2
    spacing = 24  # gap between buttons

    # total block height so we can vertically centre the whole group
    total_h = 3 * btn_h + 2 * spacing
    start_y = screen_h // 2 - total_h // 2 + 40  # +40 to leave room for the title above

    buttons = [
        Button((btn_x, start_y,                        btn_w, btn_h), "📁  USB Stick",    "usb"),
        Button((btn_x, start_y + btn_h + spacing,      btn_w, btn_h), "🌐  Network Share", "network"),
        Button((btn_x, start_y + 2 * (btn_h + spacing),btn_w, btn_h), "✨  Both",          "both"),
    ]

    selected_value = None  # we'll set this when the user clicks something

    while selected_value is None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()  # let them quit from the menu at least
            for btn in buttons:
                if btn.is_clicked(event):
                    selected_value = btn.value  # got a pick — exit the loop

        # draw the menu fresh each frame so hover effects update
        screen.fill(BACKGROUND_COLOR)

        # title up top
        title = title_font.render("Photo Frame", True, TEXT_COLOR)
        screen.blit(title, (screen_w // 2 - title.get_width() // 2, start_y - 100))

        # subtitle / instruction
        sub = hint_font.render("Where are your photos?", True, SUBTEXT_COLOR)
        screen.blit(sub, (screen_w // 2 - sub.get_width() // 2, start_y - 50))

        # draw all three buttons
        for btn in buttons:
            btn.draw(screen, button_font)

        # little hint at the bottom
        hint = hint_font.render("Click a source to begin", True, SUBTEXT_COLOR)
        screen.blit(hint, (screen_w // 2 - hint.get_width() // 2, screen_h - 60))

        pygame.display.flip()
        pygame.time.Clock().tick(30)

    return selected_value


# ─── SLIDESHOW ─────────────────────────────────────────────────────────────────

def run_slideshow(screen, screen_w, screen_h, photos):
    """
    The main slideshow loop — fullscreen photos, auto-advance every 10s,
    spacebar to skip. No exit keys because kiosk mode.
    """
    if not photos:
        # nothing to show — put up a message and hang around
        _show_no_photos_screen(screen, screen_w, screen_h)
        return

    photo_index   = 0
    current_surf  = None
    last_advance  = time.time()
    needs_reload  = True

    # re-scan every 60s in case someone plugs in a USB mid-session
    rescan_interval = 60
    last_rescan     = time.time()

    def load_current():
        # try to load the photo at photo_index — skip broken ones automatically
        nonlocal current_surf
        surf     = None
        attempts = 0
        while surf is None and attempts < len(photos):
            path = photos[photo_index % len(photos)]
            surf = load_image(path, screen_w, screen_h)
            if surf is None:
                # file was bad — ditch it from the list so we never try again
                photos.pop(photo_index % max(len(photos), 1))
                attempts += 1
        current_surf = surf

    fps_clock = pygame.time.Clock()
    running   = True

    while running:
        now = time.time()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pass  # kiosk mode — ignore the window close button
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    # spacebar skips to the next photo immediately
                    photo_index  = (photo_index + 1) % max(len(photos), 1)
                    needs_reload = True
                    last_advance = now  # reset timer so new photo gets a full 10s

        # time's up — move on to the next photo
        if photos and (now - last_advance) >= SLIDE_DURATION:
            photo_index  = (photo_index + 1) % len(photos)
            needs_reload = True
            last_advance = now

        # load the new photo if something asked for it
        if needs_reload:
            load_current()
            needs_reload = False

        # periodically check for new photos (e.g. USB just got plugged in)
        if now - last_rescan >= rescan_interval:
            # re-use the same source as before — we'd need to store it to be smarter here
            last_rescan = now

        # ── draw ──
        screen.fill(BACKGROUND_COLOR)  # clear first

        if current_surf:
            screen.blit(current_surf, (0, 0))  # photo fills the whole screen
        else:
            _show_no_photos_screen(screen, screen_w, screen_h)

        pygame.display.flip()
        fps_clock.tick(30)  # 30fps — enough for a photo frame, won't stress the Pi


def _show_no_photos_screen(screen, screen_w, screen_h):
    # friendly message when there's nothing to display
    screen.fill(BACKGROUND_COLOR)
    font = pygame.font.SysFont("dejavusans", 34)
    msg  = font.render("No photos found. Check your source and try again.", True, SUBTEXT_COLOR)
    screen.blit(msg, (screen_w // 2 - msg.get_width() // 2, screen_h // 2 - msg.get_height() // 2))
    pygame.display.flip()
    time.sleep(3)  # pause so the user can actually read it


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    pygame.init()
    pygame.mouse.set_visible(True)  # keep the cursor visible during the menu

    # go fullscreen using whatever resolution the display is running at
    screen_info = pygame.display.Info()
    screen_w, screen_h = screen_info.current_w, screen_info.current_h
    screen = pygame.display.set_mode((screen_w, screen_h), pygame.FULLSCREEN)
    pygame.display.set_caption("Photo Frame")

    # step 1: show the source menu and wait for a pick
    source = show_menu(screen, screen_w, screen_h)
    print(f"[PhotoFrame] User chose: {source}")

    # hide the cursor once we're into the slideshow — no need for it anymore
    pygame.mouse.set_visible(False)

    # step 2: load photos from the chosen source
    photos = get_photos(source)

    # step 3: run the slideshow until the end of time (or power off)
    run_slideshow(screen, screen_w, screen_h, photos)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
