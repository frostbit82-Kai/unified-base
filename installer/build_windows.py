"""Build the Windows installer. Developer-side script — end users run the
setup.exe it produces.

    py installer\\build_windows.py

Output: installer\\dist\\UnifiedBase-<version>-windows-x64-setup.exe and the
end-user README beside it.

The Windows twin of build_linux.sh, and not PyInstaller for the same reason:
the app runs helpers through sys.executable. The package is a standalone
CPython (python-build-standalone, via uv) with requirements.txt installed into
it, running main.py from source; Inno Setup installs it per user. Needs uv and
Inno Setup 6 on the build machine (see installer/README.md).
"""
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERE = REPO / "installer"
VERSION = (REPO / "VERSION").read_text().strip()
PYVER = os.environ.get("PYVER", "3.14")
BUILD = HERE / "build"
OUT = HERE / "dist"
STAGE = BUILD / "stage"          # becomes {app}
RT = STAGE / "runtime"
PY = RT / "python.exe"
# -E -s everywhere, as on Linux: without them the bundled Python reads
# PYTHONPATH and the build user's own site-packages.
PYI = [str(PY), "-E", "-s"]
QT = RT / "Lib" / "site-packages" / "PySide6"

# What the app imports (QtTest: test_core.py, run on this runtime below).
QT_ROOTS = ["QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtTest.pyd"]
# Plugins load by name, so nothing imports them: keep these whole folders
# (styles has the Windows 11 look; iconengines + imageformats draw the SVG
# icon) and, of platforms, the real one and the offscreen one the tests use.
QT_PLUGINS = {"styles", "imageformats", "iconengines"}
QT_PLATFORMS = {"qwindows.dll", "qoffscreen.dll"}


def step(n, text):
    print(f"==> [{n}/7] {text}", flush=True)


def run(cmd, **kw):
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def need(tool, hint):
    path = shutil.which(tool)
    if not path:
        sys.exit(f"Needs {tool}:  {hint}")
    return path


def iscc() -> str:
    cands = [os.environ.get("ISCC", ""),
             os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
             os.path.expandvars(r"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"),
             shutil.which("iscc") or ""]
    for c in cands:
        if c and Path(c).is_file():
            return c
    sys.exit("Needs Inno Setup 6:  winget install -e --id JRSoftware.InnoSetup --scope user")


def pe_imports(path: Path) -> list[str]:
    """DLL names a PE file imports (lower case) — ldd's job on Linux."""
    d = path.read_bytes()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec, optsize = struct.unpack_from("<H", d, pe + 6)[0], struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    ddir = opt + (112 if struct.unpack_from("<H", d, opt)[0] == 0x20B else 96)
    secs = [struct.unpack_from("<8xIIII", d, opt + optsize + 40 * i) for i in range(nsec)]

    def off(rva):
        for vsize, va, rsize, raw in secs:
            if va <= rva < va + max(vsize, rsize):
                return rva - va + raw
        return None
    names, o = [], off(struct.unpack_from("<I", d, ddir + 8)[0])
    while o is not None and struct.unpack_from("<I", d, o + 12)[0]:
        n = off(struct.unpack_from("<I", d, o + 12)[0])
        names.append(d[n:d.index(b"\0", n)].decode("ascii").lower())
        o += 20
    return names


def trim_qt():
    """PySide6-Essentials down to Widgets. Keep what the roots and kept
    plugins import, transitively; delete every other binary. Each library
    stays a separate, unmodified DLL, as the LGPL asks of a bundle."""
    # resources: icudtl.dat, QtWebEngine's ICU data (Qt Core uses Windows').
    for sub in ("qml", "translations", "metatypes", "include", "glue",
                "typesystems", "doc", "scripts", "lib", "resources"):
        shutil.rmtree(QT / sub, ignore_errors=True)
    for p in [*QT.rglob("*.pyi"), *QT.glob("*.lib")]:
        p.unlink()
    plugins = QT / "plugins"
    for d in plugins.iterdir():
        if d.name != "platforms" and d.name not in QT_PLUGINS:
            shutil.rmtree(d)
    for f in (plugins / "platforms").iterdir():
        if f.name.lower() not in QT_PLATFORMS:
            f.unlink()
    local = {p.name.lower(): p for p in QT.iterdir() if p.suffix.lower() in (".dll", ".pyd")}
    # A plugin for a Qt module the wheel does not ship (qpdf needs Qt6Pdf,
    # which is in PySide6-Addons) could never load: drop it.
    for p in list(plugins.rglob("*.dll")):
        if any(n.startswith("qt6") and n not in local for n in pe_imports(p)):
            p.unlink()
    keep, todo = set(), [QT / r for r in QT_ROOTS] + [p for p in plugins.rglob("*.dll")]
    while todo:
        p = todo.pop()
        if p in keep:
            continue
        keep.add(p)
        todo += [local[n] for n in pe_imports(p) if n in local]
    for p in list(QT.iterdir()):
        if p.suffix.lower() in (".dll", ".pyd", ".exe") and p not in keep:
            p.unlink()
    for exe in (RT / "Scripts").glob("pyside6-*"):
        exe.unlink()
    # The safety net: every Qt/PySide/MSVC library anything left imports must
    # still be here (or in Python's folder, which also has vcruntime140).
    have = {p.name.lower() for p in QT.iterdir()} | \
           {p.name.lower() for p in (QT.parent / "shiboken6").iterdir()} | \
           {p.name.lower() for p in RT.iterdir()}
    ours = ("qt6", "pyside6", "shiboken6", "msvcp", "vcruntime", "concrt", "python3")
    for p in [*QT.glob("*.dll"), *QT.glob("*.pyd"), *plugins.rglob("*.dll")]:
        missing = [n for n in pe_imports(p) if n.startswith(ours) and n not in have]
        if missing:
            sys.exit(f"Trimming broke {p.relative_to(QT)}: needs {missing}")
    for need_ in [*QT_ROOTS, "plugins/platforms/qwindows.dll",
                  "plugins/iconengines/qsvgicon.dll", "plugins/imageformats/qsvg.dll"]:
        if not (QT / need_).exists():
            sys.exit(f"Trimming removed {need_}")


ICON_PY = r"""
import struct, sys
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QIcon, QImage,
                           QLinearGradient, QPainter)
app = QGuiApplication([])
icon = QIcon(sys.argv[1])
def png(img):
    b = QBuffer(); b.open(QIODevice.OpenModeFlag.WriteOnly); img.save(b, "PNG")
    return bytes(b.data())
sizes = [16, 20, 24, 32, 40, 48, 64, 256]
blobs = [png(icon.pixmap(s, s).toImage()) for s in sizes]
head, off = struct.pack("<HHH", 0, 1, len(sizes)), 6 + 16 * len(sizes)
for s, b in zip(sizes, blobs):
    head += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), off)
    off += len(b)
open(sys.argv[2], "wb").write(head + b"".join(blobs))
# The wizard's images are BMPs, so no transparency. The corner one sits on
# white; the side one (Welcome/Finish pages) is the icon's own dark gradient,
# at 100% and 200% DPI — Setup picks the closer.
img = QImage(110, 110, QImage.Format.Format_RGB32); img.fill(Qt.GlobalColor.white)
p = QPainter(img); icon.paint(p, 7, 7, 96, 96); p.end()
img.save(sys.argv[3] + "/wizard-small.bmp", "BMP")
for scale, name in ((1, "wizard-large.bmp"), (2, "wizard-large-2x.bmp")):
    w, h = 164 * scale, 314 * scale
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, QColor("#1c2030")); g.setColorAt(1, QColor("#0d0f16"))
    p.fillRect(0, 0, w, h, g)
    s = 112 * scale
    icon.paint(p, (w - s) // 2, (h - s) // 2 - 20 * scale, s, s)
    p.end()
    img.save(sys.argv[3] + "/" + name, "BMP")
"""


def main():
    need("git", "winget install -e --id Git.Git")
    need("uv", "winget install -e --id astral-sh.uv")
    compiler = iscc()

    step(1, f"Python {PYVER}")
    shutil.rmtree(BUILD, ignore_errors=True)
    STAGE.mkdir(parents=True)
    # --no-bin: otherwise uv also puts python3.x on PATH, pointing into this
    # build folder, which the next build deletes.
    run(["uv", "python", "install", PYVER, "--install-dir", BUILD / "py", "--no-bin"])
    src = next((p for p in (BUILD / "py").glob(f"cpython-{PYVER}.*-windows-x86_64-none")
                if p.is_dir() and not p.is_symlink()), None)
    if src is None:
        sys.exit(f"uv did not produce a CPython {PYVER}")
    shutil.copytree(src, RT, symlinks=True)

    step(2, "Dependencies")
    # uv, not pip: PySide6 has paths past Windows' 260-character limit, which
    # pip cannot write (WinError 206). The runtime is private to this package,
    # so its EXTERNALLY-MANAGED marker (a distro guard) does not apply.
    run(["uv", "pip", "install", "--python", PY, "--break-system-packages",
         "--link-mode", "copy", "-q", "-r", REPO / "requirements.txt"])
    freeze = subprocess.run(["uv", "pip", "freeze", "--python", str(PY)],
                            capture_output=True, text=True, check=True).stdout
    if any(line.lower().startswith("pyqt") for line in freeze.splitlines()):
        sys.exit("PyQt6 got into the runtime (GPL, and a second Qt)")

    step(3, "Trimming Qt")
    trim_qt()

    step(4, "The app")
    app = STAGE / "app"
    files = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "--", "main.py", "winplat.py",
         "setup-wsl.ps1", "unified-base.svg", "VERSION", "LICENSE", "README.md",
         "demo_module"],
        capture_output=True, check=True).stdout.decode().split("\0")
    for f in filter(None, files):
        (app / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / f, app / f)
    (app / "BUILD").write_text(subprocess.run(
        ["git", "-C", str(REPO), "describe", "--always", "--dirty"],
        capture_output=True, text=True, check=True).stdout)
    (app / "PACKAGES").write_text(freeze)
    shutil.copytree(HERE / "licenses", app / "licenses")
    for f in ("README.txt", "selftest.bat"):
        shutil.copy2(HERE / "windows" / f, STAGE / f)

    step(5, "Icon")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    run([*PYI, "-c", ICON_PY, REPO / "unified-base.svg", STAGE / "unified-base.ico",
         BUILD], env=env)

    step(6, "Checks")
    run([*PYI, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import main",
         app], env=env, stdout=subprocess.DEVNULL)
    run([*PYI, "-c", "import tkinter; tkinter.Tcl().eval('info patchlevel')"])
    log = BUILD / "test_core.log"
    with open(log, "w", encoding="utf-8") as f:
        r = subprocess.run([*PYI, str(REPO / "test_core.py")], env=env,
                           stdout=f, stderr=subprocess.STDOUT)
    text = log.read_text(encoding="utf-8", errors="replace")
    if r.returncode or "ALL CHECKS PASS" not in text or "Traceback" in text:
        print("\n".join(text.splitlines()[-20:]))
        sys.exit(f"test_core.py failed on the packaged runtime, see {log}")
    lines = text.splitlines()
    print(f"    test_core: {sum(l.startswith('ok ') for l in lines)} pass, "
          f"{sum(l.startswith('skip ') for l in lines)} skipped")
    # Byte-code made by the checks is the build machine's; first start makes its own.
    for d in list(STAGE.rglob("__pycache__")):
        shutil.rmtree(d, ignore_errors=True)

    step(7, "Installer")
    OUT.mkdir(exist_ok=True)
    run([compiler, "/Q", f"/DAppVersion={VERSION}", f"/DStage={STAGE}",
         f"/DArt={BUILD}", f"/O{OUT}",
         HERE / "windows" / "UnifiedBase.iss"])
    shutil.copy2(HERE / "windows" / "README.txt",
                 OUT / f"UnifiedBase-{VERSION}-windows-README.txt")
    exe = OUT / f"UnifiedBase-{VERSION}-windows-x64-setup.exe"
    size = sum(p.stat().st_size for p in STAGE.rglob("*") if p.is_file())
    print(f"\nBuilt {exe}  ({exe.stat().st_size / 2**20:.0f} MB; "
          f"{size / 2**20:.0f} MB installed)")


if __name__ == "__main__":
    main()
