#!/bin/bash
# ─────────────────────────────────────────────────────────────
# ynotPi — install.sh
# Run this once on a fresh Pi to get everything set up.
# It installs dependencies and clones the repo from GitHub.
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
echo "[1/4] Checking for git..."
if ! command -v git &> /dev/null; then
    echo "  git not found — installing it now..."
    sudo apt-get update -qq && sudo apt-get install -y git
else
    echo "  git is already installed, nice."
fi

# ── step 2: install python deps ──
echo ""
echo "[2/4] Installing Python dependencies..."
sudo apt-get install -y python3 python3-pip python3-pygame
# pygame is also installable via pip if the apt version is too old:
# pip3 install pygame --break-system-packages

# ── step 3: clone or update the repo ──
echo ""
echo "[3/4] Fetching latest code from GitHub..."
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
echo "[4/4] Making launcher script executable..."
chmod +x "$INSTALL_DIR/scripts/run.sh"

echo ""
echo "========================================"
echo "  All done! To start ynotPi, run:"
echo "    bash ~/ynotPi/scripts/run.sh"
echo "========================================"
echo ""
