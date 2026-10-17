#!/bin/bash
# ─────────────────────────────────────────────────────────────
# ynotPi — install.sh
# Run this once on a fresh Pi to get everything set up.
# It installs dependencies, clones the repo from GitHub, and sets up
# the permissions Technician mode needs. Safe to re-run on an existing Pi.
# Usage: bash install.sh
# ─────────────────────────────────────────────────────────────

set -e  # bail out immediately if anything fails — better than silently breaking

REPO_URL="https://github.com/callumm-thomas/ynotPi.git"
INSTALL_DIR="$HOME/ynotPi"

echo ""
echo "========================================"
echo "  ynotPi Installer"
echo "========================================"
echo ""

# ── step 1: make sure we have git ──
echo "[1/5] Checking for git..."
if ! command -v git &> /dev/null; then
    echo "  git not found — installing it now..."
    sudo apt-get update -qq && sudo apt-get install -y git
else
    echo "  git is already installed, nice."
fi

# ── step 2: install python deps ──
echo ""
echo "[2/5] Installing Python dependencies..."
sudo apt-get install -y python3 python3-pip python3-pygame
# pygame is also installable via pip if the apt version is too old:
# pip3 install pygame --break-system-packages

# ── step 3: clone or update the repo ──
echo ""
echo "[3/5] Fetching latest code from GitHub..."
if [ -d "$INSTALL_DIR/.git" ]; then
    # already cloned — just pull the latest changes
    echo "  Repo already exists at $INSTALL_DIR — pulling latest..."
    git -C "$INSTALL_DIR" pull origin main
else
    # fresh clone
    echo "  Cloning into $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# ── step 4: make the launcher executable ──
echo ""
echo "[4/5] Making scripts executable..."
chmod +x "$INSTALL_DIR/scripts/run.sh"
chmod +x "$INSTALL_DIR/scripts/reset_pins.sh" 2>/dev/null || true

# ── step 5: narrow permission rule for Technician mode ──
# Technician mode can reboot the Pi and stop its own service ("Exit to desktop").
# Both need root, so this rule allows EXACTLY those two commands for this user —
# nothing else. (The network share feature will add its mount script here later.)
echo ""
echo "[5/5] Setting up Technician mode permissions..."
SUDOERS_FILE="/etc/sudoers.d/ynotpi"
SUDOERS_TMP="$(mktemp)"

cat > "$SUDOERS_TMP" << EOF
# ynotPi — written by install.sh
# Lets the photo frame run these exact commands as root, and nothing else:
#   reboot the Pi, and stop its own service (Technician mode > Exit to desktop)
$USER ALL=(root) NOPASSWD: /usr/bin/systemctl reboot, /usr/bin/systemctl stop ynotpi.service
EOF

# check the rule is valid BEFORE installing it — a broken sudoers file can lock out sudo entirely
if sudo visudo -cf "$SUDOERS_TMP" > /dev/null; then
    sudo install -m 0440 -o root -g root "$SUDOERS_TMP" "$SUDOERS_FILE"
    echo "  Added $SUDOERS_FILE"
else
    echo "  ⚠️  The permission rule didn't pass validation — skipped it."
    echo "     Reboot / Exit to desktop in Technician mode won't work until this is fixed."
fi
rm -f "$SUDOERS_TMP"

echo ""
echo "========================================"
echo "  All done! To start ynotPi, run:"
echo "    bash ~/ynotPi/scripts/run.sh"
echo "========================================"
echo ""
