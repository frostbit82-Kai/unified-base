#!/usr/bin/env bash
# Unified Base — uninstaller. Removes what install.sh added.
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
APPDIR="$PREFIX/share/UnifiedBase"
DATA="$HOME/.unified_base"

if pgrep -f "$APPDIR/app/main.py" >/dev/null 2>&1; then
    echo "Unified Base is running. Quit it (File > Exit), then run this again." >&2
    exit 1
fi

rm -rf "${APPDIR:?}"
rm -f "$PREFIX/bin/unified-base" \
      "$PREFIX/share/applications/unified-base.desktop" \
      "$PREFIX/share/icons/hicolor/scalable/apps/unified-base.svg"
command -v update-desktop-database >/dev/null && \
    update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true

echo "Removed Unified Base from $PREFIX."
# Left alone on purpose: the module list, layouts, blank-tab projects, every
# module's environment and the Wine prefix. Reinstalling picks them all up.
[ -d "$DATA" ] && echo "Your modules, settings and environments are kept in $DATA ($(du -sh "$DATA" 2>/dev/null | cut -f1)). Delete it yourself if you want them gone."
exit 0
