#!/bin/bash
# ─────────────────────────────────────────────────────────────
# ynotPi — reset_pins.sh
# Puts a PIN back to its preset, for when it's been forgotten.
# Run on the Pi itself (e.g. over SSH / Tailscale).
# Usage:
#   bash ~/ynotPi/scripts/reset_pins.sh              → resets the technician PIN
#   bash ~/ynotPi/scripts/reset_pins.sh client       → resets the client PIN
#   bash ~/ynotPi/scripts/reset_pins.sh both         → resets both
# ─────────────────────────────────────────────────────────────

INSTALL_DIR="$HOME/ynotPi"
WHICH="${1:-technician}"

case "$WHICH" in
    technician) ROLES="technician" ;;
    client)     ROLES="client" ;;
    both)       ROLES="technician client" ;;
    *)
        echo "Usage: bash reset_pins.sh [technician|client|both]"
        exit 1
        ;;
esac

echo ""
read -p "Reset the $WHICH PIN(s) back to the preset? (y/n): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Nothing changed."
    exit 0
fi

# reuse access.py so this always matches how the app stores PINs
cd "$INSTALL_DIR" || exit 1
for role in $ROLES; do
    python3 -c "from core import access; access.reset_to_preset('$role')" \
        && echo "  $role PIN reset to preset."
done

echo ""
echo "Done. Change it again from Technician mode > PINs as soon as you can."
echo ""
