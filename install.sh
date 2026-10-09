#!/usr/bin/env bash
#
# Install msirgb (CLI + GTK panel) for the current user.
#
#   ./install.sh            install, enable autostart
#   ./install.sh --no-gui   install the CLI only
#
# No root required. Everything lands under ~/.local and a systemd *user* unit.
#
set -euo pipefail

PREFIX="${MSI_RGB_PREFIX:-$HOME/.local}"
LIBDIR="$PREFIX/lib/msi-rgb"
BINDIR="$PREFIX/bin"
UNITDIR="$HOME/.config/systemd/user"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_GUI=1
[ "${1:-}" = "--no-gui" ] && WITH_GUI=0

say()  { printf '  %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

echo "==> Checking prerequisites"
command -v openrgb >/dev/null || fail "openrgb is not installed (Arch: pacman -S openrgb)"
command -v gcc    >/dev/null || fail "gcc is not installed (Arch: pacman -S base-devel)"
command -v systemctl >/dev/null || fail "systemd is required for autostart"

# The board must be readable by this user. OpenRGB ships a udev rule that tags
# the controller uaccess; if it is missing, OpenRGB cannot open it either.
if ls /dev/hidraw* >/dev/null 2>&1; then
    say "hidraw nodes present"
fi

echo "==> Building the DMI shim"
mkdir -p "$LIBDIR"
gcc -shared -fPIC -O2 -Wall \
    -o "$LIBDIR/dmi_spoof.so" "$SRC/msi_rgb/spoof/dmi_spoof.c" -ldl
say "$LIBDIR/dmi_spoof.so"

# Work out which board we are on, and what OpenRGB needs to be told.
BOARD="$(cat /sys/devices/virtual/dmi/id/board_name 2>/dev/null \
      || cat /sys/class/dmi/id/board_name 2>/dev/null || true)"
[ -n "$BOARD" ] || fail "could not read the DMI board name"

SPOOF="$(MSI_RGB_SPOOF="$BOARD" python3 -c '
import sys
sys.path.insert(0, sys.argv[2] if len(sys.argv) > 2 else ".")
try:
    from msi_rgb.config import load_config
except Exception:
    import importlib.util as u
    s = u.spec_from_file_location("cfg", sys.argv[2] + "/msi_rgb/config.py")
    m = u.module_from_spec(s); s.loader.exec_module(m)
    print(m.load_config()["spoof_as"] or "")
    raise SystemExit
print(load_config()["spoof_as"] or "")
' "$SRC" 2>/dev/null || true)"

if [ -z "$SPOOF" ]; then
    echo
    echo "No spoof target is known for board: $BOARD" >&2
    echo "Pick any entry from OpenRGB's board table and re-run with:" >&2
    echo "    MSI_RGB_SPOOF='SOME BOARD (MS-XXXX)' ./install.sh" >&2
    echo "See README.md -> 'Adding your board'." >&2
    exit 1
fi

echo "==> Board"
say "reports as : $BOARD"
say "spoofed as: $SPOOF"

echo "==> Installing commands"
mkdir -p "$BINDIR"
# Console scripts via the package's own entry points, without pip: a tiny
# launcher keeps the package importable from anywhere.
cat > "$BINDIR/msirgb" <<EOF
#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.join("$LIBDIR"))
sys.path.insert(0, "$SRC")
from msi_rgb.cli import main
sys.exit(main())
EOF
cat > "$BINDIR/msirgb-gui" <<EOF
#!/usr/bin/env python3
import os, sys
sys.path.insert(0, "$SRC")
from msi_rgb.gui import main
sys.exit(main())
EOF
chmod +x "$BINDIR/msirgb" "$BINDIR/msirgb-gui"
say "$BINDIR/msirgb"

# Keep the package next to the shim so the launcher above stays valid even if
# the repo is moved.
mkdir -p "$LIBDIR/msi_rgb/spoof"
cp -r "$SRC/msi_rgb/." "$LIBDIR/msi_rgb/"

echo "==> Installing the systemd user unit"
mkdir -p "$UNITDIR"
sed -e "s|@LIBDIR@|$LIBDIR|g" \
    -e "s|@SPOOF@|$SPOOF|g" \
    "$SRC/systemd/openrgb-msi.service.in" > "$UNITDIR/openrgb-msi.service"
systemctl --user daemon-reload
systemctl --user enable --now openrgb-msi.service
say "enabled at login (systemctl --user status openrgb-msi)"

sleep 2
if [ "$WITH_GUI" = "1" ]; then
    if python3 -c 'import gi; gi.require_version("Gtk","4.0")' 2>/dev/null; then
        say "GTK4 available -- run: msirgb-gui"
    else
        say "GTK4 not available -- CLI only (install python-gobject + gtk4)"
    fi
fi

cat <<EOF

Done. Try:

  msirgb doctor          # confirm OpenRGB can see the board
  msirgb list            # zones and LED counts
  msirgb zone 3 --color ff0000
  msirgb rainbow --zone 3 --period 20
EOF