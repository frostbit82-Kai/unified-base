#!/usr/bin/env bash
# Unified Base — installer.
#
#   ./install.sh              install for this user (no root needed)
#   PREFIX=/opt ./install.sh  install somewhere else (may need sudo)
#   ./install.sh --uninstall  same as ./uninstall.sh
set -euo pipefail

[ "${1:-}" = "--uninstall" ] && exec "$(dirname "$0")/uninstall.sh"

SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APPDIR="$PREFIX/share/UnifiedBase"
BINDIR="$PREFIX/bin"
DESKTOP="$PREFIX/share/applications"
ICONDIR="$PREFIX/share/icons/hicolor/scalable/apps"
EXE="$APPDIR/unified-base"
PY="$APPDIR/runtime/bin/python3"

echo "Unified Base $(cat "$SRC/VERSION") (beta)"
echo "Installing to $APPDIR"
echo

# An upgrade replaces the whole folder, and the running copy imports from it.
if pgrep -f "$APPDIR/app/main.py" >/dev/null 2>&1; then
    echo "Unified Base is running. Quit it (File > Exit), then run this again." >&2
    exit 1
fi

# Everything under PREFIX is created up front so a permission problem surfaces
# here rather than half way through a copy. APPDIR itself is not, because an
# upgrade has to replace it wholesale rather than merge into an older build.
mkdir -p "$(dirname "$APPDIR")" "$BINDIR" "$DESKTOP" "$ICONDIR"

echo "==> Copying files"
rm -rf "${APPDIR:?}"
mkdir "$APPDIR"
cp -a "$SRC/runtime" "$SRC/app" "$APPDIR/"
cp "$SRC/unified-base" "$SRC/README.txt" "$APPDIR/"
chmod +x "$EXE"

echo "==> Adding the launcher and menu entry"
ln -sf "$EXE" "$BINDIR/unified-base"
cp "$SRC/app/unified-base.svg" "$ICONDIR/unified-base.svg"
sed -e "s|@EXEC@|$EXE|" "$SRC/unified-base.desktop" > "$DESKTOP/unified-base.desktop"
command -v update-desktop-database >/dev/null && \
    update-desktop-database "$DESKTOP" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && \
    gtk-update-icon-cache -qtf "$PREFIX/share/icons/hicolor" 2>/dev/null || true

# A smoke test, not a formality: this imports the app and opens Qt on this
# display, so a host missing a system library says so now instead of on a
# double-click that appears to do nothing.
echo "==> Checking it runs"
plat=offscreen
[ -n "${DISPLAY:-}" ] && plat=xcb
if ! QT_QPA_PLATFORM=$plat "$PY" -E -s -c '
import sys; sys.path.insert(0, sys.argv[1])
import main
from PyQt6.QtWidgets import QApplication
QApplication(["unified-base"])' "$APPDIR/app"; then
    echo
    echo "Unified Base did not start. The error above is the real reason." >&2
    missing="$(ldd "$APPDIR"/runtime/lib/python3*/site-packages/PyQt6/Qt6/plugins/platforms/libqxcb.so \
               2>/dev/null | awk '/not found/ {print $1}' | tr '\n' ' ')"
    if [ -n "$missing" ]; then
        echo "Missing system libraries: $missing" >&2
        # The one Qt 6 needs that desktops most often lack.
        case "$missing" in *libxcb-cursor*)
            echo "On Ubuntu, Mint or Debian:  sudo apt install libxcb-cursor0" >&2 ;;
        esac
        echo "Install them, then run this installer again." >&2
    fi
    exit 1
fi
echo "    ok"

echo
case ":$PATH:" in
    *":$BINDIR:"*) ;;
    *) echo "Note: $BINDIR is not on your PATH, so the \`unified-base\` command"
       echo "      will not be found. The menu entry works regardless." ;;
esac
[ "${XDG_SESSION_TYPE:-}" = "wayland" ] && cat <<'MSG'
Note: this is a Wayland session. Unified Base runs through XWayland so it can
      embed windows, and most programs embed fine. If one will not, log in to
      an X11 session ("on Xorg" at the login screen) for full embedding.
MSG

cat <<MSG

Installed. Launch it from your applications menu (Development), or run:  unified-base

New here? File > Load Demo Modules shows what it does with programs in a dozen
languages. A module whose language is not installed yet gets an Install button
in its pane (your password is asked for there, by the system).

Your modules, settings and environments live in ~/.unified_base and survive
upgrades and uninstalling.

To remove: $SRC/uninstall.sh
MSG
