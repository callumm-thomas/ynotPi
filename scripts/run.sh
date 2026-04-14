#!/bin/bash
# ─────────────────────────────────────────────────────────────
# ynotPi — run.sh
# Pulls the latest code from GitHub then launches the photo frame.
# Run this every time you want to start ynotPi — it self-updates!
# Usage: bash ~/ynotPi/scripts/run.sh
# ─────────────────────────────────────────────────────────────

INSTALL_DIR="$HOME/ynotPi"
MAIN_SCRIPT="$INSTALL_DIR/core/photoframe.py"

echo ""
echo "[ynotPi] Checking for updates..."

# pull the latest from GitHub before launching — so the Pi is always up to date
# without needing to SSH in and update manually
if git -C "$INSTALL_DIR" pull origin main; then
    echo "[ynotPi] Up to date!"
else
    # if the pull fails (e.g. no internet), just warn and carry on with what we have
    echo "[ynotPi] Couldn't reach GitHub — running with existing local version."
fi

echo "[ynotPi] Starting photo frame..."
echo ""

# launch the app — using python3 explicitly just to be safe
python3 "$MAIN_SCRIPT"
