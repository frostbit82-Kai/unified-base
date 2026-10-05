#!/usr/bin/env bash
# Build the Linux release tarball. Developer-side script — end users run the
# install.sh that comes inside the tarball it produces.
#
#   bash installer/build_linux.sh
#
# Output: installer/dist/UnifiedBase-<version>-linux-x86_64.tar.gz
#
# Not PyInstaller, on purpose: the package carries a standalone CPython
# (python-build-standalone, via uv) with PySide6 pip-installed into it, and runs
# main.py from source. Two reasons, both measured — see installer/README.md:
# the app runs its own helpers through sys.executable, which a frozen build
# turns into the app itself; and a frozen build inherits this machine's glibc.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERE="$REPO/installer"
VERSION="$(cat "$REPO/VERSION")"
NAME="UnifiedBase-${VERSION}-linux-x86_64"
PYVER="${PYVER:-3.14}"
# Linux Mint 21 / Ubuntu 22.04. PySide6's wheels set the real floor (2.34 for
# 6.10+); this catches an upgrade that quietly raises it.
GLIBC_MAX="${GLIBC_MAX:-2.35}"
BUILD="$HERE/build"
OUT="$HERE/dist"
STAGE="$OUT/$NAME"

command -v uv >/dev/null || {
    echo "Needs uv:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }

echo "==> [1/6] Python $PYVER"
rm -rf "${BUILD:?}" "${STAGE:?}"
mkdir -p "$BUILD" "$STAGE"
# --no-bin: otherwise uv also links python$PYVER into ~/.local/bin, pointing
# at a build folder that is deleted at the end.
uv python install "$PYVER" --install-dir "$BUILD/py" --no-bin
PYSRC="$(find "$BUILD/py" -maxdepth 1 -type d -name "cpython-$PYVER.*-linux-x86_64-gnu" | head -1)"
[ -n "$PYSRC" ] || { echo "uv did not produce a CPython $PYVER" >&2; exit 1; }
cp -a "$PYSRC" "$STAGE/runtime"
# -E -s everywhere: without them this Python sees the build user's own
# ~/.local packages, pip counts those as installed and leaves them out (six,
# python-xlib's dependency, went missing that way), and the tests pass on them.
PY="$STAGE/runtime/bin/python3"
PYI=("$PY" -E -s)

echo "==> [2/6] Dependencies"
# The runtime is private to this package, so its EXTERNALLY-MANAGED marker
# (which guards a distro's own Python) does not apply.
"${PYI[@]}" -m pip install -q --no-cache-dir --break-system-packages \
    --no-warn-script-location -r "$REPO/requirements.txt"
"${PYI[@]}" -m pip freeze > "$BUILD/freeze.txt"
# PyQt6 is GPL. One that slipped in would also be a second Qt in the process.
! grep -qi '^pyqt' "$BUILD/freeze.txt" || { echo "PyQt6 got into the runtime" >&2; exit 1; }

echo "==> [3/6] Trimming Qt"
# PySide6-Essentials is 233 MB: Qt Quick, QML, Designer and the Qt tools. The
# app uses Widgets. Delete the big unused modules, then anything left that
# links one of them, until nothing changes; the ldd pass is the safety net, so
# this list can be blunt. Every library stays a separate, unmodified .so —
# that is what the LGPL asks of a bundle.
# QtTest stays (400 KB): test_core.py, run below on this runtime, needs it.
QT="$(echo "$STAGE"/runtime/lib/python3*/site-packages/PySide6)"
rm -rf "$QT"/Qt/{qml,translations,libexec,metatypes} \
       "$QT"/{assistant,designer,linguist,lrelease,lupdate,qmlformat,qmllint,qmlls,svgtoqml} \
       "$QT"/{doc,include,glue,typesystems,scripts}
find "$QT" -name '*.pyi' -delete
for m in Concurrent Designer Help Labs Lottie PrintSupport Qml Quick Sql UiTools \
         Network Xml EglFS EglFs WaylandCompositor WaylandEgl; do
    rm -f "$QT"/Qt/lib/libQt6"$m"*.so* "$QT"/Qt"$m"*.abi3.so
done
rm -f "$STAGE"/runtime/bin/pyside6-* "$STAGE"/runtime/bin/shiboken6*
while :; do
    gone=0
    while IFS= read -r -d '' f; do
        # Anything Qt that does not resolve inside the bundle: deleted above,
        # or about to come from a system Qt that the target may not have.
        if ldd "$f" 2>/dev/null | grep 'libQt6' | grep -vqF "=> $QT/"; then
            rm -f "$f"; gone=1
        fi
    done < <(find "$QT" -name '*.so*' -type f -print0)
    [ "$gone" = 0 ] && break
done
find "$QT/Qt/plugins" -type d -empty -delete
for need in QtCore.abi3.so QtGui.abi3.so QtWidgets.abi3.so QtSvg.abi3.so \
            Qt/plugins/platforms/libqxcb.so Qt/plugins/imageformats/libqsvg.so \
            Qt/plugins/iconengines/libqsvgicon.so; do
    [ -e "$QT/$need" ] || { echo "Trimming removed $need" >&2; exit 1; }
done

echo "==> [4/6] The app"
mkdir -p "$STAGE/app"
# Tracked files only: the demos' node_modules, target, .venv and the rest stay
# behind, and each rebuilds for the OS it runs on.
(cd "$REPO" && git ls-files -z -- main.py winplat.py unified-base.svg VERSION \
    README.md demo_module | xargs -0 cp --parents -t "$STAGE/app")
git -C "$REPO" describe --always --dirty > "$STAGE/app/BUILD"
cp "$HERE/linux/install.sh" "$HERE/linux/uninstall.sh" "$HERE/linux/unified-base" \
   "$HERE/linux/unified-base.desktop" "$HERE/linux/README.txt" "$STAGE/"
# The two double-click launchers. They have to be executable in the archive:
# a .desktop file without the bit set is a text file to every file manager.
cp "$HERE/linux/Install Unified Base.desktop" \
   "$HERE/linux/Uninstall Unified Base.desktop" "$STAGE/"
chmod +x "$STAGE/install.sh" "$STAGE/uninstall.sh" "$STAGE/unified-base" \
         "$STAGE/Install Unified Base.desktop" "$STAGE/Uninstall Unified Base.desktop"
printf '%s\n' "$VERSION" > "$STAGE/VERSION"
cp "$BUILD/freeze.txt" "$STAGE/app/PACKAGES"
cp -r "$HERE/licenses" "$STAGE/app/licenses"

echo "==> [5/6] Checks"
# objdump fails on the scripts and .exe files in the list; only its output counts.
floor="$(find "$STAGE" -type f \( -name '*.so*' -o -perm -u+x \) -print0 |
         { xargs -0 objdump -T 2>/dev/null || true; } | grep -oE 'GLIBC_[0-9]+\.[0-9]+' |
         sort -Vu | tail -1 | cut -d_ -f2)"
echo "    glibc floor $floor (limit $GLIBC_MAX)"
[ "$(printf '%s\n%s\n' "$floor" "$GLIBC_MAX" | sort -V | tail -1)" = "$GLIBC_MAX" ] || {
    echo "Needs glibc $floor, above the $GLIBC_MAX limit" >&2; exit 1; }
# The app's own checks, on the trimmed runtime: proof the trim kept what runs.
(cd "$STAGE/app" && QT_QPA_PLATFORM=offscreen "${PYI[@]}" -c 'import main') >/dev/null
QT_QPA_PLATFORM=offscreen "${PYI[@]}" "$REPO/test_core.py" > "$BUILD/test_core.log" 2>&1 || {
    tail -20 "$BUILD/test_core.log" >&2; echo "test_core.py failed on the packaged runtime" >&2; exit 1; }
grep -q "ALL CHECKS PASS" "$BUILD/test_core.log" || {
    echo "test_core.py did not finish, see $BUILD/test_core.log" >&2; exit 1; }
echo "    test_core: $(grep -c '^ok ' "$BUILD/test_core.log") pass, $(grep -c '^skip ' "$BUILD/test_core.log") skipped"

echo "==> [6/6] Compressing"
tar -C "$OUT" -czf "$OUT/$NAME.tar.gz" "$NAME"
rm -rf "${STAGE:?}"

echo
echo "Built $OUT/$NAME.tar.gz  ($(du -h "$OUT/$NAME.tar.gz" | cut -f1)) from $(git -C "$REPO" describe --always --dirty)"
