#!/usr/bin/env python3
"""
Unified Base — a tabbed shell that hosts standalone Python GUI modules.

Each module = a project folder with an entry script (main.py etc.).
For every module the base:
  1. creates a private venv (no sudo, no prompts),
  2. installs deps (requirements.txt if present, else AST import scan),
  3. launches the entry script with that venv's interpreter,
  4. embeds the module's window into its tab (via XWayland / X11),
     falling back to a control-panel tab (logs + start/stop) if
     embedding isn't possible.

Modules persist in ~/.unified_base/modules.json. Double-click a tab
to rename it.
"""

import ast
import hashlib
import json
import locale
import logging
import logging.handlers
import os
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import weakref
from dataclasses import dataclass, asdict, field
from pathlib import Path
from urllib.parse import unquote

# ponytail: minimal logging setup, no config files
logger = logging.getLogger("unified_base")
logger.setLevel(logging.DEBUG)
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setLevel(logging.WARNING)
_log_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
logger.addHandler(_log_handler)

# ---------------------------------------------------------------------------
# Platform detection and atomic write helpers
# ---------------------------------------------------------------------------
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
IS_WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY")) and not os.environ.get("QT_QPA_PLATFORM")
# True whenever the session is Wayland, regardless of the Qt platform we force.
IS_WAYLAND_SESSION = bool(os.environ.get("WAYLAND_DISPLAY"))
# SIGKILL does not exist on Windows at all, so `SIGKILL` there is
# an AttributeError the first time anything is stopped. These two are what the
# tree-kill helpers take on every OS; Windows maps them to WM_CLOSE (polite)
# and TerminateProcess (forced).
SIGTERM = signal.SIGTERM
SIGKILL = getattr(signal, "SIGKILL", 9)

def atomic_write(path: Path, data: str) -> None:
    """Write file atomically: temp + fsync + rename prevents corruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # ponytail: os.replace is atomic on both POSIX and Windows
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise

# Force X11 (XWayland) BEFORE Qt loads, so foreign-window embedding works.
# If there's no X server at all, stay native and disable embedding.
# Falls back gracefully to panel mode if embedding fails on Wayland.
# Windows can embed via Qt's createWindowContainer (HWND parenting); macOS
# can't embed foreign windows reliably, so it stays panel-mode.
HAS_X = bool(os.environ.get("DISPLAY"))
EMBEDDING_OK = HAS_X or IS_WINDOWS
# Full embedded terminal: a real xterm reparented in on Linux/X, a real conhost
# console embedded the same way on Windows (winplat.ConsoleTerminal). macOS has
# only the one-shot command bar.
TERMINAL_OK = (HAS_X and IS_LINUX) or IS_WINDOWS
# Only force xcb on Linux with a real X server; on Windows it would break Qt.
FORCE_X11 = HAS_X and IS_LINUX and not os.environ.get("UNIFIED_BASE_NATIVE")
if FORCE_X11:
    os.environ["QT_QPA_PLATFORM"] = "xcb"

# Toolkit backend hints that push a launched app onto XWayland, so its window
# gets a real X11 id we can reparent. Removing WAYLAND_DISPLAY is the universal
# lever (every toolkit falls back to X11 via DISPLAY); the explicit hints cover
# toolkits that cache the backend some other way. Covers Qt, GTK, SDL, Clutter,
# Rust/winit, Electron and Firefox — i.e. "any app" the launcher can host.
X11_BACKEND_HINTS = {
    "QT_QPA_PLATFORM": "xcb",              # Qt 5/6
    "GDK_BACKEND": "x11",                  # GTK 3/4
    "SDL_VIDEODRIVER": "x11",              # SDL 1/2 (games, pygame, love2d)
    "CLUTTER_BACKEND": "x11",              # Clutter / older GNOME apps
    "WINIT_UNIX_BACKEND": "x11",           # Rust winit (egui, wgpu, minifb, bevy)
    "ELECTRON_OZONE_PLATFORM_HINT": "x11",  # Electron <= 37
    # Electron 38+ ignores the hint above and picks Wayland from the session
    # type — then finds the compositor's default socket even with
    # WAYLAND_DISPLAY removed, and its window opens on the real desktop.
    "XDG_SESSION_TYPE": "x11",
    "MOZ_ENABLE_WAYLAND": "0",             # Firefox / XUL
}

def force_x11_env(env) -> None:
    """Force a child QProcess's env onto XWayland when we're embedding on Linux.
    No-op on Windows/macOS or when UNIFIED_BASE_NATIVE is set."""
    if not FORCE_X11:
        return
    for k, v in X11_BACKEND_HINTS.items():
        env.insert(k, v)
    env.remove("WAYLAND_DISPLAY")  # universal fallback-to-X11 lever

# uv (if present) creates venvs and installs deps far faster than venv+pip.
USE_UV = bool(shutil.which("uv"))

from PyQt6.QtCore import (QByteArray, QEvent, QObject, QPointF, QProcess,
                          QProcessEnvironment, QRect, QRectF, QSize,
                          QSocketNotifier, Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont,
                         QGuiApplication, QIcon, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QWindow)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog,
                             QDialogButtonBox, QFileDialog,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMainWindow, QMenu,
                             QMessageBox, QPlainTextEdit, QPushButton,
                             QScrollArea, QSizePolicy, QSplitter,
                             QStackedWidget, QStyle, QTabBar,
                             QToolButton, QVBoxLayout, QWIDGETSIZE_MAX,
                             QWidget)

BASE_DIR = Path(__file__).resolve().parent   # repo root (holds apps/, demo_module/)
BLANK_DIR = BASE_DIR / "apps"                 # created empty tabs live here
DEMO_DIR = BASE_DIR / "demo_module"           # bundled showcase apps, grouped
                                              # by OS: demo_module/<Linux|Windows>/
APP_DIR = Path.home() / ".unified_base"
ENVS_DIR = APP_DIR / "envs"
SHARED_ENV_DIR = ENVS_DIR / "_shared"
CONFIG_FILE = APP_DIR / "modules.json"
LOG_DIR = APP_DIR / "logs"   # per-module output, kept after the tab closes
GRID_MIN_H = 140     # smallest a grid row may be dragged to, in px
PANE_MIN_W = 160     # smallest a pane may be *dragged* to, in px
ENTRY_CANDIDATES = ["main.py", "app.py", "run.py", "start.py", "__main__.py"]

# import name -> PyPI package name (extend as needed)
PYPI_ALIASES = {
    "cv2": "opencv-python", "PIL": "Pillow", "yaml": "PyYAML",
    "bs4": "beautifulsoup4", "sklearn": "scikit-learn",
    "skimage": "scikit-image", "gi": "PyGObject", "dotenv": "python-dotenv",
    "dateutil": "python-dateutil", "serial": "pyserial", "usb": "pyusb",
    "Crypto": "pycryptodome", "OpenGL": "PyOpenGL", "mpv": "python-mpv",
    "vlc": "python-vlc", "magic": "python-magic", "Xlib": "python-xlib",
    "fitz": "PyMuPDF", "github": "PyGithub", "jwt": "PyJWT",
    "socks": "PySocks", "webview": "pywebview", "cairo": "pycairo",
    "yt_dlp": "yt-dlp", "qtpy": "QtPy", "win32com": "pywin32",
    "sdl2": "PySDL2", "projectM": "projectM-python", "gst": "PyGObject",
}

STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


# ---------------------------------------------------------------------------
# Dependency scanning
# ---------------------------------------------------------------------------
def scan_imports(project_dir: Path) -> list[str]:
    """AST-scan all .py files; return PyPI package names (best effort)."""
    local: set[str] = set()
    for item in project_dir.iterdir():
        if item.is_dir():
            local.add(item.name)
        elif item.suffix == ".py":
            local.add(item.stem)
    found = raw_imports(project_dir)
    pkgs = set()
    for name in found:
        if name in STDLIB or name in local or not name:
            continue
        pkgs.add(PYPI_ALIASES.get(name, name))
    return sorted(pkgs)


def raw_imports(project_dir: Path) -> set[str]:
    """Top-level names every .py file imports, stdlib included."""
    found: set[str] = set()
    for py in project_dir.rglob("*.py"):
        if any(p in (".venv", "venv", "env", "__pycache__", "node_modules")
               for p in py.parts):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 \
                    and node.module:
                found.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                # dynamic imports: __import__("x"), import_module("x")
                fn = node.func
                dynamic = (
                    (isinstance(fn, ast.Name)
                     and fn.id in ("__import__", "import_module"))
                    or (isinstance(fn, ast.Attribute)
                        and fn.attr == "import_module"))
                if dynamic and node.args \
                        and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    found.add(node.args[0].value.split(".")[0])
    return found


def venv_python(env_dir: Path, windows: bool = IS_WINDOWS) -> Path:
    """A venv's interpreter: bin/python on POSIX, Scripts\\python.exe on Windows."""
    if windows:
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def project_venv_python(project_dir: Path) -> Path | None:
    """If the module ships its own venv, return its interpreter."""
    for name in (".venv", "venv", "env"):
        py = venv_python(project_dir / name)
        if py.is_file():
            return py
    return None


def find_requirement_files(project_dir: Path) -> list[Path]:
    """All requirements*.txt anywhere in the project tree (skipping venvs).

    Prefers version-locked files (requirements.lock, requirements.freeze)
    for reproducible environments.
    """
    out = []
    for f in project_dir.rglob("requirements*.txt"):
        if not any(p in (".venv", "venv", "env", "__pycache__",
                         "node_modules") for p in f.parts):
            out.append(f)
    # ponytail: prioritize locked/frozen files for reproducibility
    locked = [f for f in out if "lock" in f.name or "freeze" in f.name]
    if locked:
        return sorted(locked)
    return sorted(out)


def _dep_name(spec: str) -> str:
    """PEP 508 requirement string -> bare package name (drop version/extras)."""
    return re.split(r"[<>=!~;\[\( ]", spec.strip(), 1)[0].strip()


def declared_python_deps(project_dir: Path) -> list[str]:
    """Dependencies declared in pyproject.toml (PEP 621 or poetry) and
    requirements*.in. Complements the AST scan for projects that only
    declare deps in metadata (poetry / pdm / uv / hatch)."""
    try:
        import tomllib
    except ImportError:      # Python < 3.11; skip pyproject parsing
        return []
    deps: set[str] = set()
    pyproject = project_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as e:
            logger.warning(f"Cannot parse {pyproject}: {e}")
            data = {}
        for spec in (data.get("project", {}) or {}).get("dependencies", []):
            if _dep_name(spec):
                deps.add(_dep_name(spec))
        poetry = ((data.get("tool", {}) or {}).get("poetry", {}) or {})
        for name in (poetry.get("dependencies", {}) or {}):
            if name.lower() != "python":
                deps.add(name)
    for inf in project_dir.glob("requirements*.in"):
        for line in inf.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-") and _dep_name(line):
                deps.add(_dep_name(line))
    return sorted(deps)


def find_submodule_candidates(project_dir: Path,
                              exclude: str = "") -> list[str]:
    """Relative paths of runnable .py files (with a __main__ guard)."""
    out = []
    for py in sorted(project_dir.rglob("*.py")):
        if any(p in (".venv", "venv", "env", "__pycache__", "node_modules")
               for p in py.parts):
            continue
        rel = py.relative_to(project_dir).as_posix()
        if rel == exclude:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "__name__" in text and "__main__" in text:
            out.append(rel)
    return out


def find_entry_candidates(project_dir: Path) -> list[str]:
    hits = [c for c in ENTRY_CANDIDATES if (project_dir / c).is_file()]
    if hits:
        return hits
    return sorted(p.name for p in project_dir.glob("*.py"))


# ---------------------------------------------------------------------------
# Runtimes — how to detect, set up (install/build), and launch a module in a
# given language ecosystem. Embedding is identical for all of them (we find
# the window by process id once it appears), so a runtime only has to say
# what command(s) to run.
# ---------------------------------------------------------------------------
# Chromium-family browsers we can embed (for the "web" runtime), best first.
BROWSERS = ["chromium", "chromium-browser", "google-chrome",
            "google-chrome-stable", "brave-browser", "microsoft-edge"]
# Web dev-server frameworks that imply the "web" runtime over plain node.
WEB_FRAMEWORKS = ["vite", "next", "react-scripts", "@angular", "vue",
                  "webpack-dev-server", "parcel", "@sveltejs", "astro",
                  "nuxt", "gatsby"]
# Match a localhost dev-server URL printed on stdout.
SERVER_URL_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?(?:/\S*)?")


def free_port(preferred: int) -> int:
    """`preferred` if nothing holds it, else any free port.

    Both PHP demos hardcoded :8000, so mounting the second one killed it with
    "Address already in use" — and the same collision hits any two PHP
    projects. Preferred-first keeps the familiar URL for the common case of
    one server at a time.
    """
    # ponytail: bind-and-release, so another program can in principle take the
    # port in the gap before the server binds it. The retry is Start. Our own
    # servers can't: a port handed out in the last 30 s is skipped (a layout
    # starts every module in one go, and two PHP servers both got :8000).
    now = time.monotonic()
    for port in (preferred, 0):
        if port and now - _PORTS_GIVEN.get(port, -1e9) < 30:
            continue
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))
                port = s.getsockname()[1]
                _PORTS_GIVEN[port] = now
                return port
        except OSError:
            continue
    return preferred


_PORTS_GIVEN: dict[int, float] = {}     # port -> when free_port handed it out


def _read_json(path: Path) -> dict:
    """Load JSON with error logging (non-fatal)."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        logger.warning(f"Corrupted JSON in {path}: {e}, using empty dict")
        return {}
    except OSError as e:
        logger.warning(f"Cannot read {path}: {e}")
        return {}


# Build by-products that carry an execute bit but are never the app itself.
NOT_PROGRAMS = (".py", ".sh", ".js", ".so", ".o", ".a", ".cmake", ".txt",
                ".dll", ".pdb", ".lib", ".def", ".exp", ".manifest")


def is_program_file(f: Path) -> bool:
    """A file this machine can launch as a program.

    `.exe` counts everywhere — natively on Windows, through Wine on Linux.
    Windows has no execute bit (os.access says yes to every readable file), so
    there an ELF header is the signal for the other kind: a Linux program,
    runnable through WSL. Elsewhere it is the execute bit.
    """
    if not f.is_file() or f.suffix.lower() in NOT_PROGRAMS:
        return False
    if f.suffix.lower() == ".exe":
        return True
    if IS_WINDOWS:
        return is_elf_file(f)
    return os.access(f, os.X_OK)


def _executable_files(proj: Path) -> list[str]:
    """Top-level files that are programs (see is_program_file)."""
    try:
        return [p.name for p in sorted(proj.iterdir()) if is_program_file(p)]
    except OSError:
        return []


# What a Windows program writes when it isn't writing UTF-8: the ANSI code
# page (Python's own stdio on a pipe, most C runtimes).
_OUTPUT_FALLBACK = locale.getpreferredencoding(False) if IS_WINDOWS else "utf-8"


def proc_text(data) -> str:
    """A child process's output as text for the log.

    UTF-8 first; output that isn't is the ANSI code page on Windows. CRLF
    becomes LF, or every Windows line ends in a blank line in the log pane
    and in \r\r\n in the log file.
    ponytail: decoded per read, so a character split across two reads falls
    back too; an incremental decoder per process would fix that.
    """
    raw = bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode(_OUTPUT_FALLBACK, errors="replace")
    return _ANSI_ESCAPE.sub("", text.replace("\r\n", "\n"))


# Terminal escape sequences — colours, cursor moves, window titles. The log
# pane is plain text, where they showed as "[36m" litter around every word.
# ponytail: stripped, not rendered; colour in the pane would need a parser.
# CSI (ESC [ ... final), OSC (ESC ] ... BEL/ST), and the short ones
# (ESC [intermediates] final: ESC 7, ESC ( B ...).
_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[ -/]*[0-~])")


def shell_command(cmd: str, forward_args: bool = False) -> tuple[str, list]:
    """Program + args that run `cmd` through the user's shell.

    A *login* shell: PATH set up in ~/.profile (nvm, rbenv, pyenv, cargo, sdkman)
    is exactly what makes a hand-written command behave here the way it does in
    a terminal. `forward_args` appends a "$@" tail so anything added to argv
    afterwards — a module's startup args — lands where the shell expands it,
    instead of becoming inert positional parameters.
    """
    if IS_WINDOWS:
        # cmd.exe, not PowerShell: Windows PowerShell 5.1 has no `&&`, and the
        # commands people paste from READMEs assume it. /d skips AutoRun hooks;
        # /s strips exactly the outer quotes start_qprocess wraps the line in.
        # Startup args are appended to that same line, so forward_args needs
        # nothing extra — and there is no login shell to ask for, because
        # Windows PATH already comes from the registry via the environment.
        return "cmd.exe", ["/d", "/s", "/c", cmd]
    sh = os.environ.get("SHELL", "/bin/sh")
    if forward_args:
        return sh, ["-lc", f'{cmd} "$@"', "ub-custom"]   # $0 for the shell
    return sh, ["-lc", cmd]


# ---------------------------------------------------------------------------
# Cross-OS bridges. A module says what it needs; this machine decides how:
#   needs windows, running on Linux   -> Wine (its windows are X11 windows,
#                                        so they embed like any other app)
#   needs linux, running on Windows   -> WSL (WSLg windows, owned by msrdc.exe)
#   anything else                     -> natively
# ---------------------------------------------------------------------------
PLATFORM_NEEDS = {"": "Runs anywhere", "linux": "Linux only",
                  "windows": "Windows only"}


# Windows toolchains for Windows-only programs in interpreted languages. Wine
# runs .exe files, not a Python or Ruby project, so the first start of such a
# module on Linux installs that language's official Windows build into the
# module's Wine prefix, under C:\ub\<dir> — the mirror of WSL, where a Linux
# module's toolchain lives in the distro. Pinned builds, each checked against
# its publisher's checksum (python.org's Sigstore signature, Adoptium's and
# GitHub's SHA-256) before it was pinned here and against that pin before any
# of it runs. Downloads are cached in APP_DIR/downloads.
#   install  — an installer's quiet arguments ({dir} = the C:\ub folder);
#              without one the download is a zip, unpacked minus its top folder
#   extras   — single files taken from other zips: Ruby's UCRT build checks the
#              C runtime's internals, which Wine's own ucrtbase fails, so it
#              gets Microsoft's (from the .NET Core 3.1 runtime pack, a plain
#              zip — the VC++ redistributable needs cabextract)
#   env      — added to the launch; native_build — the build still runs on
#              Linux (Maven makes a jar; only running it needs Windows Java)
WINE_TOOLCHAINS = {
    "python": {
        "label": "Python 3.12 for Windows", "mb": 26,
        "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe",
        "sha256": "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb",
        "dir": "python312", "exe": "python.exe",
        "install": ["/quiet", "InstallAllUsers=0", "TargetDir={dir}",
                    "Include_test=0", "Include_launcher=0", "Shortcuts=0",
                    "AssociateFiles=0", "PrependPath=0"],
    },
    "java": {
        "label": "Temurin JDK 25 for Windows", "mb": 135, "swap": "java",
        "url": "https://github.com/adoptium/temurin25-binaries/releases/download/"
               "jdk-25.0.4.1%2B1/OpenJDK25U-jdk_x64_windows_hotspot_25.0.4.1_1.zip",
        "sha256": "00c847d804f4a78e9f04f2683faf14fed898535b177b7fc704486cb0284e9283",
        "dir": "jdk25", "exe": "bin/java.exe", "native_build": True,
    },
    "ruby": {
        "label": "Ruby 3.4 for Windows (RubyInstaller)", "mb": 20, "swap": "ruby",
        "url": "https://github.com/oneclick/rubyinstaller2/releases/download/"
               "RubyInstaller-3.4.11-1/rubyinstaller-3.4.11-1-x64.exe",
        "sha256": "f873a6c15b79123ffa736b8c82b8fc80a6b304b81864f6c11a549c69b063ddb5",
        "dir": "ruby34", "exe": "bin/ruby.exe",
        "install": ["/verysilent", "/currentuser", "/dir={dir}", "/tasks=",
                    "/noicons"],
        "extras": [{
            "url": "https://api.nuget.org/v3-flatcontainer/microsoft.netcore.app."
                   "runtime.win-x64/3.1.32/microsoft.netcore.app.runtime.win-x64."
                   "3.1.32.nupkg",
            "sha256": "1cefabea41de8d5507bb24add822556ed461a3b603dba636ead819d4df005563",
            "member": "runtimes/win-x64/native/ucrtbase.dll", "to": "bin",
            "mb": 31}],
        "env": {"WINEDLLOVERRIDES": "ucrtbase=n,b"},
    },
}

# Runtimes with no Windows toolchain above: their Windows-only programs can't
# run under Wine.
WINE_NEEDS_WINDOWS_TOOLCHAIN = {"node": "Node.js", "web": "Node.js", "php": "PHP"}

# Fetches one pinned download (run by the launcher's own Python as a logged
# setup step): download unless the cached copy matches, refuse a file whose
# SHA-256 differs from the pin, then optionally unzip all of it (minus the top
# folder) or one member into a folder.
# ponytail: needs sys.executable to be a Python — a frozen build needs another runner.
WINE_FETCH = r"""
import hashlib, os, shutil, sys, urllib.request, zipfile
url, dest, sha = sys.argv[1:4]
def digest(p):
    with open(p, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
if not (os.path.isfile(dest) and digest(dest) == sha):
    print("Downloading " + url, flush=True)
    part = dest + ".part"
    with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
        total, got, shown = int(r.headers.get("Content-Length") or 0), 0, 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            if total and got * 10 // total > shown:
                shown = got * 10 // total
                print(f"  {shown * 10}% of {total >> 20} MB", flush=True)
    if digest(part) != sha:
        os.remove(part)
        sys.exit(f"Checksum mismatch: {url} is not the pinned file. Nothing "
                 "of it was used.")
    os.replace(part, dest)
if len(sys.argv) > 4:
    out, member = os.path.abspath(sys.argv[4]), (sys.argv[5:] or [None])[0]
    with zipfile.ZipFile(dest) as z:
        for m in z.infolist():
            if member and m.filename != member:
                continue
            # one member by its own name, or everything minus the top folder
            name = (os.path.basename(member) if member
                    else m.filename.partition("/")[2])
            path = os.path.abspath(os.path.join(out, name))
            if m.is_dir() or not name or not path.startswith(out + os.sep):
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with z.open(m) as src, open(path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    print("Unpacked into " + out, flush=True)
"""


# Runs one toolchain step under that toolchain's lock, unless `marker` (what
# the step makes) appeared meanwhile: two tabs of one Windows language started
# together (a layout) raced the same download, and would run one installer
# twice into C:\ub\<dir>, rewriting DLLs the first tab's program has loaded.
# Linux only, as is everything Wine.
WINE_ONCE = r"""
import fcntl, os, subprocess, sys
lock, marker, cmd = sys.argv[1], sys.argv[2], sys.argv[3:]
with open(lock, "w") as f:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Waiting for another module setting up the same toolchain...",
              flush=True)
        fcntl.flock(f, fcntl.LOCK_EX)
    if os.path.exists(marker):
        print("Already done by another module.", flush=True)
        sys.exit(0)
    sys.exit(subprocess.call(cmd))
"""


def wine_path(p) -> str:
    """A Linux path as Wine programs see it: drive Z: is the root."""
    return "Z:" + str(p).replace("/", "\\")


def bridge_for(need: str) -> str:
    """How a module that needs `need` runs on this machine."""
    if need == "windows" and not IS_WINDOWS:
        return "wine"
    if need == "linux" and IS_WINDOWS:
        return "wsl"
    return "native"


# Files Windows itself would launch; Wine runs them the same way.
WINDOWS_PROGRAMS = (".exe", ".bat", ".cmd", ".com", ".msi")


def _magic(path: Path, n: int = 4) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


def is_pe_file(path: Path) -> bool:
    """A Windows executable (MZ header), whatever its name says."""
    return _magic(path, 2) == b"MZ"


def is_elf_file(path: Path) -> bool:
    """A Linux executable (ELF header)."""
    return _magic(path, 4) == b"\x7fELF"


# Python imports that only make sense on Linux.
LINUX_ONLY_IMPORTS = {"gi", "Xlib", "dbus", "evdev", "pyudev", "fcntl", "pty",
                      "termios", "grp", "pwd"}

# Windows-only Python modules. Anywhere in a file they prove nothing — they
# usually sit behind a platform guard (this launcher's own win32 code does) —
# but imported at module level, outside any if/try, the program cannot start
# anywhere else.
WINDOWS_ONLY_IMPORTS = {"winreg", "winsound", "msvcrt", "_winapi", "win32api",
                        "win32con", "win32gui", "win32process", "pythoncom",
                        "pywintypes", "win32com", "wmi", "comtypes"}

# Other languages say it just as plainly: Ruby aborts `unless
# Gem.win_platform?` or loads win32ole; Java binds Windows DLLs through
# FFM/JNA; a crate depends on the Windows API crates outside any
# [target.'cfg(windows)'] table; a Dockerfile starts from a Windows image.
_RUBY_WINDOWS = re.compile(
    r"^(?:(?:abort|exit!?|raise)\b[^\n]*\bunless\s+Gem\.win_platform\?"
    r"|require\s+['\"]win32ole['\"])", re.M)
_JAVA_WINDOWS = re.compile(
    r'(?:libraryLookup|Native\.load)\(\s*"(?:user32|kernel32|gdi32|dwmapi|'
    r'advapi32|shell32|ole32|comctl32|winmm)(?:\.dll)?"', re.I)
_DOCKER_WINDOWS = re.compile(
    r"^\s*FROM\s+\S*(?:nanoserver|servercore|mcr\.microsoft\.com/windows)",
    re.M | re.I)
WINDOWS_CRATES = {"windows", "windows-sys", "winapi"}


def module_level_imports(project_dir: Path) -> set[str]:
    """Names the project's top-level .py files import unconditionally — at
    module level, not inside an if, try or function."""
    found: set[str] = set()
    for py in project_dir.glob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        for node in tree.body:
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 \
                    and node.module:
                found.add(node.module.split(".")[0])
    return found


def _any_file_matches(files, pattern) -> bool:
    for f in files:
        try:
            if pattern.search(f.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def detect_platform(proj: Path, runtime: str, entry: str) -> str:
    """What a freshly added module needs: "", "linux" or "windows".

    Only strong evidence counts — the binary's own header, a .csproj that
    targets Windows, a GTK/X11 import. Everything else is "" and runs natively
    wherever the launcher is; the tab's "Runs on" menu overrides any guess.
    """
    f = proj / entry if entry else None
    if f is not None and f.is_file():
        if is_pe_file(f):
            return "windows"
        if is_elf_file(f):
            return "linux"
    elif runtime == "binary":
        # A build entry (make, cmake): judge by the programs already in the
        # folder — a prebuilt app.exe beside its Makefile says "Windows".
        progs = [proj / n for n in _executable_files(proj)]
        if progs and all(is_pe_file(x) for x in progs):
            return "windows"
        if progs and all(is_elf_file(x) for x in progs):
            return "linux"
    if runtime == "csharp":
        for cp in proj.glob("*.csproj"):
            try:
                text = cp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(r"<TargetFrameworks?>[^<]*-windows", text) or \
                    re.search(r"<Use(WindowsForms|WPF)>\s*true", text, re.I):
                return "windows"
    if runtime == "python" and raw_imports(proj) & LINUX_ONLY_IMPORTS:
        return "linux"
    if runtime == "python" and module_level_imports(proj) & WINDOWS_ONLY_IMPORTS:
        return "windows"
    if runtime == "ruby" and _any_file_matches(proj.glob("*.rb"), _RUBY_WINDOWS):
        return "windows"
    if runtime == "java" and _any_file_matches(proj.glob("src/**/*.java"),
                                               _JAVA_WINDOWS):
        return "windows"
    if runtime == "docker" and _any_file_matches(proj.glob("Dockerfile*"),
                                                 _DOCKER_WINDOWS):
        return "windows"
    if runtime == "binary" and (proj / "Cargo.toml").is_file():
        import tomllib
        try:
            deps = tomllib.loads((proj / "Cargo.toml").read_text(
                encoding="utf-8")).get("dependencies", {})
        except (tomllib.TOMLDecodeError, OSError):
            deps = {}
        if WINDOWS_CRATES & set(deps):
            return "windows"
    return ""


def wine_program() -> str | None:
    return shutil.which("wine") or shutil.which("wine64")


def wsl_ready() -> bool:
    """Can Linux modules run through WSL here? Only on Windows — winplat's
    version, bound below, checks for a real distro, not just wsl.exe."""
    return False


def wsl_x_display() -> str | None:
    """A Windows X server's DISPLAY for Linux modules — Windows only, see
    winplat. None leaves them on WSLg, whose windows can't be embedded."""
    return None


def wsl_display_env() -> dict:
    """Env that sends a Linux module's windows to the Windows X server."""
    d = wsl_x_display()
    return {**X11_BACKEND_HINTS, "DISPLAY": d, "WAYLAND_DISPLAY": ""} if d else {}


def wine_prefix() -> Path:
    """The Wine prefix modules share. A module can point WINEPREFIX elsewhere
    from its Environment variables, which override this."""
    return APP_DIR / "wine" / "default"


def wine_wrap(program: str, args: list, prefix: Path) -> tuple[str, list, dict]:
    """(program, args, env) that run a Windows program through Wine.

    Only Windows programs are wrapped. A module's build tool or shell command
    still runs natively — that is how a Windows app gets *built* on Linux
    (mingw, `dotnet publish -r win-x64`) before Wine runs the result.
    """
    path = Path(program)
    suf = path.suffix.lower()
    if suf not in WINDOWS_PROGRAMS and not (path.is_file() and is_pe_file(path)):
        return program, list(args), {"WINEPREFIX": str(prefix)}
    wine = wine_program() or "wine"
    env = {"WINEPREFIX": str(prefix), "WINEDEBUG": "-all"}
    if suf in (".bat", ".cmd"):
        return wine, ["cmd", "/c", program, *args], env
    if suf == ".msi":
        return wine, ["msiexec", "/i", program, *args], env
    return wine, [program, *args], env


_WIN_ABS = re.compile(r"^[A-Za-z]:[\\/]")
_WSL_UNC = re.compile(r"^[\\/]{2}wsl(?:\$|\.localhost)[\\/][^\\/]+([\\/].*)?$", re.I)


def to_wsl_path(p: str) -> str:
    r"""A Windows path as WSL sees the same file.

    C:\Users\me\proj         -> /mnt/c/Users/me/proj
    \\wsl$\Ubuntu\home\me     -> /home/me     (also \\wsl.localhost\...)
    anything else (POSIX, relative, a flag) comes back unchanged.
    """
    m = _WSL_UNC.match(p)
    if m:
        return (m.group(1) or "/").replace("\\", "/")
    if _WIN_ABS.match(p):
        return "/mnt/" + p[0].lower() + p[2:].replace("\\", "/")
    return p


def wsl_wrap(program: str, args: list, cwd, env: dict | None = None,
             track_pid: bool = False, setup: bool = False) -> tuple[str, list]:
    """(program, args) that run `program args` in the default WSL distro.

    Through a login bash, so the distro's profile PATH (nvm, pyenv, cargo) is
    there, with the arguments passed as "$@" instead of being re-joined into
    one string. Windows paths are translated. Environment variables do not
    cross into WSL by themselves, so they ride in through `env`. track_pid
    prints UBPID:<pid> first: the Linux pid is the only handle that can stop
    the app — killing wsl.exe on the Windows side leaves it running.
    """
    argv = [to_wsl_path(str(a)) for a in (program, *args)]
    script = 'echo "UBPID:$$"; exec "$@"' if track_pid else 'exec "$@"'
    if setup:
        # Exported, not `env K=V prog`: the guard tests "$1", which has to be
        # the program — behind `env` a missing tool failed the whole chain
        # (exit 127) instead of skipping its step.
        script = "".join(f"export {k}={shlex.quote(to_wsl_path(str(v)))}; "
                         for k, v in (env or {}).items()
                         if _ENV_NAME.fullmatch(k)) + wsl_setup_guard(
            TOOLCHAIN_PKGS.get(Path(str(program)).name, {}).get("apt"))
    elif env:
        argv = ["env"] + [f"{k}={to_wsl_path(str(v))}"
                          for k, v in env.items()] + argv
    head = ["--cd", to_wsl_path(str(cwd))] if cwd else []
    return "wsl.exe", head + ["--exec", "bash", "-lc", WSL_LINUX_PATH + script,
                              "ub"] + argv


_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")   # safe to `export`

# WSL appends Windows' PATH (/mnt/c/...) inside the distro, so a Linux module
# found Windows tools by name — mvn (Windows Maven's sh script, no Linux java
# behind it), bundle (Windows Ruby's), npm — and the missing-tool guard took
# them as installed. Every launcher command in WSL drops those entries; a
# Windows program is still reachable by its full path.
WSL_LINUX_PATH = ('PATH=$(printf %s "$PATH" | tr : "\\n" | '
                  'grep -v "^/mnt/[a-z]/" | paste -sd: -); ')

def wsl_setup_guard(apt_pkgs: str | None) -> str:
    """For setup steps only: a tool missing inside the distro skips its step
    with a note — and the install line when the package is known — exactly
    as missing_setup_msg does natively, instead of failing the chain. `make`
    is not in a stock Ubuntu WSL image, for one."""
    hint = (f'echo "    To install it:  wsl -u root apt-get install -y '
            f'{apt_pkgs}"; ' if apt_pkgs else "")
    return ('command -v "$1" >/dev/null 2>&1 || { echo "Setup step needs '
            "'$1', which isn't installed in WSL - skipping it.\"; " + hint +
            'exit 0; }; exec "$@"')


def wsl_kill_script(pid: int, sig: int) -> str:
    """sh line that signals a WSL process and its whole tree, children before
    parents. `pkill -P` reached only direct children, so npm -> sh -> electron
    left electron running."""
    name = "KILL" if sig == SIGKILL else "TERM"
    return ("t(){ for c in $(pgrep -P $1); do t $c; done; "
            f"kill -{name} $1; }}; t {int(pid)}")


def wsl_shell(script: str, cwd, extra: list | None = None,
              track_pid: bool = False) -> tuple[str, list]:
    """(program, args) that run a shell *line* in WSL — custom commands and
    the command bar, where pipes and && are the point."""
    pre = 'echo "UBPID:$$"; ' if track_pid else ""
    head = ["--cd", to_wsl_path(str(cwd))] if cwd else []
    return "wsl.exe", head + ["--exec", "bash", "-lc",
                              f'{WSL_LINUX_PATH}{pre}{script} "$@"', "ub"] + \
        list(extra or [])


def wsl_mount_args(path: str) -> list | None:
    """wsl.exe args that make sure `path`'s Windows drive is mounted in WSL.

    WSL automounts fixed drives only. A removable one (USB stick, SD card)
    has no /mnt/<letter> until someone mounts it, and every command for a
    module on it failed to chdir. Runs as root (wsl -u root: no password),
    is a no-op when the drive is already there, lasts until WSL shuts down.
    Owned like the automounted /mnt/c (the default user): root-owned files
    make every chmod fail — npm's bin links, for one.
    """
    if not _WIN_ABS.match(path):
        return None
    d = path[0].lower()
    return ["--cd", "~", "-u", "root", "-e", "sh", "-c",
            f"mountpoint -q /mnt/{d} || {{ o=$(stat -c uid=%u,gid=%g /mnt/c "
            f"2>/dev/null); mkdir -p /mnt/{d} && "
            f"mount -t drvfs {d.upper()}: /mnt/{d} ${{o:+-o $o}}; }}"]


UBPID_RE = re.compile(r"^UBPID:(\d+)\s*$", re.M)


def builds_on_windows(cfg) -> bool:
    """Build steps run on Windows: natively there, unless bridged into WSL.

    Under Wine the *build* still runs on Linux; only the finished .exe goes
    through Wine. So output names (.exe or not) follow this, not the bridge.
    """
    return IS_WINDOWS and bridge_for(getattr(cfg, "platform", "")) != "wsl"


def resolve_program(program: str) -> str:
    """Full path for a bare program name on Windows.

    CreateProcess appends only `.exe`, so `npm` (really npm.cmd), `mvn.cmd`,
    `gradle.bat`, `bundle.bat` all fail to start by bare name. shutil.which
    walks PATHEXT the way a shell does. Elsewhere the OS searches PATH itself.
    """
    if not IS_WINDOWS or os.path.dirname(program):
        return program
    return shutil.which(program) or program


def _is_cmd_line(program: str, args: list) -> bool:
    return Path(program).name.lower() in ("cmd", "cmd.exe") \
        and [str(a).lower() for a in args[:3]] == ["/d", "/s", "/c"]


_CMD_META = re.compile(r"[&|<>^()]")


def _cmd_arg(a: str) -> str:
    """One startup arg for a cmd.exe line. list2cmdline quotes only on
    whitespace, but cmd also splits commands at & | < > ^ — `--q=a&b` would
    run `b` as a command.
    ponytail: % still expands inside quotes, and an arg holding both a quote
    and a metacharacter can still break out; no cmd quoting survives both."""
    q = subprocess.list2cmdline([a])
    return q if q.startswith('"') or not _CMD_META.search(a) else f'"{q}"'


def start_qprocess(p, program: str, args: list) -> None:
    """Every child process starts here.

    On Windows cmd.exe gets its command line verbatim: QProcess quotes each
    argument MSVC-style, escaping an inner quote as \\", which cmd.exe does not
    understand — `echo "hi there"` would arrive as `echo \\"hi there\\"`.
    """
    program = resolve_program(str(program))
    args = [str(a) for a in args]
    if IS_WINDOWS and _is_cmd_line(program, args) \
            and hasattr(p, "setNativeArguments"):
        line = args[3] if len(args) > 3 else ""
        if len(args) > 4:            # startup args, appended after the command
            line += " " + " ".join(_cmd_arg(a) for a in args[4:])
        p.setProgram(program)
        p.setArguments([])
        p.setNativeArguments(f'/d /s /c "{line}"')
        p.start()
        return
    p.start(program, args)


class Runtime:
    """Base class. Subclasses describe one language ecosystem."""
    id = ""
    label = ""
    is_web = False

    @classmethod
    def detect(cls, proj: Path) -> bool:
        return False

    @classmethod
    def entries(cls, proj: Path) -> list[str]:
        """Selectable launch entries; first is the default. May be empty."""
        return []

    @classmethod
    def submodules(cls, proj: Path, exclude: str) -> list[str]:
        return []

    @classmethod
    def setup_steps(cls, cfg) -> list[tuple]:
        """List of (label, program, args, cwd) build/install commands."""
        return []

    @classmethod
    def launch(cls, cfg) -> "LaunchSpec":
        raise NotImplementedError

    @classmethod
    def serves(cls, cfg) -> bool:
        """Whether launch() serves a URL — asked before setup, so a runtime
        whose launch() has side effects (PHP reserves a port) overrides it."""
        return cls.launch(cfg).serves


@dataclass
class LaunchSpec:
    program: str
    args: list[str]
    workdir: str
    extra_env: dict | None = None
    # True when the process serves a URL rather than opening a window, so the
    # launcher should watch stdout for that URL and embed a browser on it.
    serves: bool = False


# --- Toolchain preflight -----------------------------------------------------
# Project *dependencies* (pip/npm/cargo/gem/composer packages) are auto-installed
# per runtime in setup_steps(). The language *toolchain* itself (node, dotnet,
# ruby, …) is a system package we can't pip-install — so when it's missing we
# detect it up front and hand the user the exact install command for their OS,
# instead of letting the launch fail with a cryptic "No such file" error.
# python is omitted (the launcher runs on it, so it's always present); binary
# is omitted (the needed tool — cargo/go/make/cmake — varies per project).
TOOLCHAIN_CMD = {
    "node": "node", "web": "node", "java": "java", "csharp": "dotnet",
    "ruby": "ruby", "php": "php", "docker": "docker",
}
# cmd -> {package-manager: package name(s)}
TOOLCHAIN_PKGS = {
    "node":   {"apt": "nodejs npm", "dnf": "nodejs npm", "pacman": "nodejs npm",
               "zypper": "nodejs npm", "brew": "node", "winget": "OpenJS.NodeJS"},
    "java":   {"apt": "default-jdk", "dnf": "java-latest-openjdk-devel",
               "pacman": "jdk-openjdk", "zypper": "java-openjdk-devel",
               "brew": "openjdk", "winget": "EclipseAdoptium.Temurin.25.JDK"},
    "dotnet": {"apt": "dotnet-sdk-10.0", "dnf": "dotnet-sdk-10.0",
               "pacman": "dotnet-sdk", "zypper": "dotnet-sdk-10.0",
               "brew": "dotnet", "winget": "Microsoft.DotNet.SDK.10"},
    "ruby":   {"apt": "ruby-full", "dnf": "ruby", "pacman": "ruby",
               "zypper": "ruby", "brew": "ruby", "winget": "RubyInstallerTeam.Ruby.3.4"},
    "php":    {"apt": "php-cli", "dnf": "php-cli", "pacman": "php",
               "zypper": "php8", "brew": "php", "winget": "PHP.PHP.8.3"},
    "docker": {"apt": "docker.io", "dnf": "docker", "pacman": "docker",
               "zypper": "docker", "brew": "docker", "winget": "Docker.DockerDesktop"},
    "xterm":  {"apt": "xterm", "dnf": "xterm", "pacman": "xterm",
               "zypper": "xterm"},   # for the embedded full terminal (Linux/X)
    # Programs that only setup steps need. Debian ships bundler as a default
    # gem but no `bundle` binstub, so `ruby` on PATH does not imply `bundle`.
    "bundle": {"apt": "ruby-bundler", "dnf": "rubygem-bundler",
               "pacman": "ruby-bundler", "brew": "ruby"},
    "npm":    {"apt": "npm", "dnf": "npm", "pacman": "npm",
               "zypper": "npm", "brew": "node", "winget": "OpenJS.NodeJS"},
    "mvn":    {"apt": "maven", "dnf": "maven", "pacman": "maven",
               "zypper": "maven", "brew": "maven"},
    # Windows: the GNU toolchain links with its own bundled MinGW. Rustup's
    # default (MSVC) needs Visual Studio's linker, a multi-GB install.
    "cargo":  {"apt": "cargo", "dnf": "cargo", "pacman": "rust",
               "zypper": "cargo", "brew": "rust", "winget": "Rustlang.Rust.GNU"},
    # No winget package exists for composer, gradle or mvn (the IDs once
    # here made a dead Install button): WINDOWS_DOWNLOADS points at them.
    "composer": {"apt": "composer", "dnf": "composer", "pacman": "composer",
                 "zypper": "php-composer2", "brew": "composer"},
    "gradle": {"apt": "gradle", "dnf": "gradle", "pacman": "gradle",
               "zypper": "gradle", "brew": "gradle"},
    "make":   {"apt": "make", "dnf": "make", "pacman": "make",
               "zypper": "make", "brew": "make", "winget": "ezwinports.make"},
    "cmake":  {"apt": "cmake", "dnf": "cmake", "pacman": "cmake",
               "zypper": "cmake", "brew": "cmake", "winget": "Kitware.CMake"},
    "go":     {"apt": "golang-go", "dnf": "golang", "pacman": "go",
               "zypper": "go", "brew": "go", "winget": "GoLang.Go"},
    "wine":   {"apt": "wine wine64", "dnf": "wine", "pacman": "wine",
               "zypper": "wine", "brew": "--cask wine-stable"},
    "docker-compose": {"apt": "docker-compose-v2", "dnf": "docker-compose",
                       "pacman": "docker-compose", "zypper": "docker-compose",
                       "brew": "docker-compose"},
}

# Windows tools winget doesn't carry: where to get them instead.
WINDOWS_DOWNLOADS = {"composer": "https://getcomposer.org/download/",
                     "gradle": "https://gradle.org/install/",
                     "mvn": "https://maven.apache.org/download.cgi"}


def _manual_hint(cmd: str) -> str:
    """The no-package-manager fallback: a download page on Windows (it has
    no system package manager to name), else the generic advice."""
    url = WINDOWS_DOWNLOADS.get(cmd) if IS_WINDOWS else None
    return (f"Get '{cmd}' from {url} (winget has no package for it)" if url
            else f"Install '{cmd}' via your system package manager")


def _pkg_manager() -> str | None:
    if IS_WINDOWS:
        return "winget"
    if IS_MACOS:
        return "brew"
    for pm in ("apt", "dnf", "pacman", "zypper"):
        if shutil.which(pm):
            return pm
    return None

def can_gui_install() -> bool:
    """Can the Install button run an installer with its own privilege prompt?"""
    if IS_WINDOWS:
        return bool(shutil.which("winget"))
    return not IS_MACOS and bool(shutil.which("pkexec"))


def gui_install_command(cmd: str) -> tuple[str, list]:
    """(program, args) that run an install command from toolchain_install_cmd
    with a graphical privilege prompt."""
    if IS_WINDOWS:
        parts = shlex.split(cmd)              # winget install -e --id X
        return "winget", parts[1:] + ["--accept-source-agreements",
                                      "--accept-package-agreements"]
    return "pkexec", ["sh", "-c", cmd]


def toolchain_install_cmd(cmd: str) -> str | None:
    """Copy-pasteable install command for a missing toolchain, or None."""
    pm = _pkg_manager()
    pkgs = TOOLCHAIN_PKGS.get(cmd, {}).get(pm) if pm else None
    if not pkgs:
        return None
    if pm in ("apt", "dnf", "zypper"):
        return f"sudo {pm} install -y {pkgs}"
    if pm == "pacman":
        return f"sudo pacman -S --noconfirm {pkgs}"
    if pm == "winget":
        return f"winget install -e --id {pkgs}"
    return f"{pm} install {pkgs}"   # brew

def which_fresh(cmd: str) -> str | None:
    """shutil.which, except that on Windows a miss first re-reads the
    environment from the registry: a toolchain installed since launch (by
    winget, an MSI, another shell) is otherwise invisible until a restart."""
    found = shutil.which(cmd)
    if found is None and IS_WINDOWS and winplat.refresh_path():
        found = shutil.which(cmd)
    return found


def missing_toolchain_msg(runtime_id: str) -> str | None:
    """Actionable message if this runtime's toolchain isn't installed, else None."""
    cmd = TOOLCHAIN_CMD.get(runtime_id)
    if not cmd or which_fresh(cmd):
        return None
    hint = toolchain_install_cmd(cmd)
    base = f"{runtime_id!r} runtime needs '{cmd}', which isn't on PATH."
    return (f"{base}\n    Install it with:  {hint}" if hint else
            f"{base} {_manual_hint(cmd)}, then Start again.")


def missing_setup_msg(cmd: str) -> str | None:
    """Message for a setup step whose program isn't installed, else None.

    A setup step is dependency prep, not the app. Its program going missing is
    worth saying out loud but not worth blocking on: the dependencies may
    already be satisfied system-wide.
    """
    if which_fresh(cmd):
        return None
    hint = toolchain_install_cmd(cmd)
    base = (f"Setup step needs '{cmd}', which isn't on PATH. Skipping it and "
            "starting anyway — the module's dependencies may already be "
            "installed.")
    if hint:
        return f"{base}\n    To run that step next time:  {hint}"
    return f"{base}\n    {_manual_hint(cmd)}." if cmd in WINDOWS_DOWNLOADS \
        and IS_WINDOWS else base


class PythonRuntime(Runtime):
    id, label = "python", "Python"

    @classmethod
    def detect(cls, proj):
        return bool(find_entry_candidates(proj))

    @classmethod
    def entries(cls, proj):
        return find_entry_candidates(proj)

    @classmethod
    def submodules(cls, proj, exclude):
        return find_submodule_candidates(proj, exclude)
    # setup/launch handled by ModuleTab's bespoke Python path.


def npm_setup(proj: Path, windows: bool = IS_WINDOWS) -> list:
    """`npm install` until it has succeeded since package.json or its lock
    last changed. npm writes its hidden lockfile last: a failed install
    leaves a node_modules behind that must not count, and a pulled
    dependency bump (git rewrites the manifests) must reach node_modules.

    `windows`: the OS the install runs on (builds_on_windows). A
    node_modules another OS installed — the same folder run through WSL, a
    flipped "Runs on", a copied project — has the wrong .bin shims and
    native packages (esbuild, rollup), and npm calls it up to date. npm on
    Windows always writes .cmd shims into .bin, elsewhere never: that
    tells them apart, and the other OS's copy is cleared first.

    Electron's ~100 MB binary comes from its own install.js: a postinstall
    up to Electron 41 (npm 11.19 blocks dependency scripts), the first start
    from 42 (which ate the 40 s embed wait). As a setup step it is logged
    and untimed; path.txt is the last thing install.js writes, and after a
    fresh npm install it runs regardless (it returns at once if current)."""
    steps = []
    nm = proj / "node_modules"
    bins = list((nm / ".bin").iterdir()) if (nm / ".bin").is_dir() else []
    foreign = bool(bins) and any(b.suffix == ".cmd" for b in bins) != windows
    if foreign:
        prog, args = ((sys.executable, ["-c", "import shutil; "
                                        "shutil.rmtree('node_modules')"])
                      if windows else ("rm", ["-rf", "node_modules"]))
        steps.append((f"clearing node_modules installed by "
                      f"{'Linux' if windows else 'Windows'}", prog, args,
                      str(proj)))
    hidden = nm / ".package-lock.json"
    done_at = hidden.stat().st_mtime if hidden.is_file() else None
    if foreign or done_at is None or any(
            m.is_file() and m.stat().st_mtime > done_at
            for m in (proj / "package.json", proj / "package-lock.json")):
        steps.append(("npm install", "npm", ["install"], str(proj)))
    pkg = _read_json(proj / "package.json")
    if "electron" in {**(pkg.get("dependencies") or {}),
                      **(pkg.get("devDependencies") or {})} and (steps or
            not (proj / "node_modules" / "electron" / "path.txt").is_file()):
        steps.append(("Electron download", "node",
                      ["node_modules/electron/install.js"], str(proj)))
    return steps


class NodeRuntime(Runtime):
    id, label = "node", "Node.js / Electron"

    @classmethod
    def detect(cls, proj):
        return (proj / "package.json").is_file()

    @classmethod
    def entries(cls, proj):
        pkg = _read_json(proj / "package.json")
        out = ["(default)"]
        for s in (pkg.get("scripts") or {}):
            out.append(f"npm:{s}")
        if pkg.get("main"):
            out.append(pkg["main"])
        return out

    @classmethod
    def submodules(cls, proj, exclude):
        pkg = _read_json(proj / "package.json")
        return [f"npm:{s}" for s in (pkg.get("scripts") or {})]

    @classmethod
    def setup_steps(cls, cfg):
        return npm_setup(Path(cfg.project_dir), builds_on_windows(cfg))

    @classmethod
    def launch(cls, cfg):
        proj = Path(cfg.project_dir)
        pkg = _read_json(proj / "package.json")
        entry = cfg.entry or "(default)"
        deps = {**(pkg.get("dependencies") or {}),
                **(pkg.get("devDependencies") or {})}
        if entry.startswith("npm:"):
            return LaunchSpec("npm", ["run", entry[4:]], str(proj))
        if entry.endswith(".js") or entry.endswith(".mjs"):
            # An Electron app's `main` is loaded BY electron; plain `node
            # main.js` leaves `app` undefined. Only the declared main gets
            # this treatment, so build/CLI scripts still run under node.
            if entry == pkg.get("main") and "electron" in deps:
                return LaunchSpec("npx", ["electron", entry], str(proj))
            return LaunchSpec("node", [entry], str(proj))
        if entry == "(default)":
            scripts = pkg.get("scripts") or {}
            if "start" in scripts:
                return LaunchSpec("npm", ["start"], str(proj))
            if "electron" in deps:
                return LaunchSpec("npx", ["electron", "."], str(proj))
            if pkg.get("main"):
                return LaunchSpec("node", [pkg["main"]], str(proj))
        return LaunchSpec("node", [entry], str(proj))


class BinaryRuntime(Runtime):
    id, label = "binary", "Native binary (Rust / Go / C/C++)"
    CARGO, GO = "(cargo build & run)", "(go build & run)"
    MAKE, CMAKE = "(make & run)", "(cmake build & run)"
    WIN_TARGET = "x86_64-pc-windows-gnu"   # MinGW links it; no Visual Studio

    @classmethod
    def detect(cls, proj):
        return bool((proj / "Cargo.toml").is_file()
                    or (proj / "go.mod").is_file()
                    or (proj / "Makefile").is_file()
                    or (proj / "CMakeLists.txt").is_file()
                    or _executable_files(proj))

    @classmethod
    def entries(cls, proj):
        out = []
        if (proj / "Cargo.toml").is_file():
            out.append(cls.CARGO)
        if (proj / "go.mod").is_file():
            out.append(cls.GO)
        # Before the first build a Makefile/CMake project has no executable to
        # list, so without these entries it offered nothing to launch and the
        # launcher ended up trying to execute the project folder itself.
        if (proj / "Makefile").is_file() or (proj / "makefile").is_file():
            out.append(cls.MAKE)
        if (proj / "CMakeLists.txt").is_file():
            out.append(cls.CMAKE)
        out += _executable_files(proj)
        return out

    @classmethod
    def _newest_exe(cls, where: Path, deep: bool) -> Path | None:
        """Newest executable under `where` — what the build just produced.

        make and cmake don't say which artifact is *the* app, and CMake's own
        compiler probes leave executables lying around in build/, so newest
        wins. A project that builds several binaries can pick one by name from
        the entry list instead.
        """
        best = None
        try:
            names = where.rglob("*") if deep else where.iterdir()
            for f in names:
                if not is_program_file(f):
                    continue
                if best is None or f.stat().st_mtime > best.stat().st_mtime:
                    best = f
        except OSError as e:
            logger.debug(f"Cannot scan {where} for build output: {e}")
        return best

    @classmethod
    def _go_out(cls, cfg) -> str:
        return ".ub_app.exe" if builds_on_windows(cfg) else ".ub_app"

    @classmethod
    def _cargo_bin(cls, proj):
        # crude [package] name parse from Cargo.toml
        name = proj.name
        try:
            in_pkg = False
            for line in (proj / "Cargo.toml").read_text().splitlines():
                s = line.strip()
                if s.startswith("["):
                    in_pkg = s == "[package]"
                elif in_pkg and s.startswith("name"):
                    name = s.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except (OSError, ValueError) as e:
            logger.debug(f"Cannot parse Cargo.toml: {e}, using {name}")
        return name

    @classmethod
    def setup_steps(cls, cfg):
        proj = Path(cfg.project_dir)
        entry = cfg.entry
        if entry == cls.CARGO and bridge_for(cfg.platform) == "wine":
            # A Windows-only crate (windows-sys, ...) off Windows: build it
            # for Windows with the MinGW linker, then Wine runs the .exe — as
            # CsharpRuntime does for WinForms.
            return [(f"rustup target add {cls.WIN_TARGET}", "rustup",
                     ["target", "add", cls.WIN_TARGET], str(proj)),
                    (f"cargo build --release --target {cls.WIN_TARGET}",
                     "cargo", ["build", "--release", "--target",
                               cls.WIN_TARGET], str(proj))]
        if entry == cls.CARGO:
            return [("cargo build --release", "cargo",
                     ["build", "--release"], str(proj))]
        if entry == cls.GO:
            return [("go build", "go",
                     ["build", "-o", cls._go_out(cfg), "."], str(proj))]
        if entry == cls.MAKE:
            return [("make", "make", [], str(proj))]
        if entry == cls.CMAKE:
            return [("cmake build",
                     *shell_command("cmake -B build && cmake --build build"),
                     str(proj))]
        # Prebuilt executable: build first if a build file exists and the
        # target isn't there yet.
        if entry and not (proj / entry).exists():
            if (proj / "Makefile").is_file():
                return [("make", "make", [], str(proj))]
            if (proj / "CMakeLists.txt").is_file():
                return [("cmake build",
                         *shell_command("cmake -B build && cmake --build build"),
                         str(proj))]
        return []

    @classmethod
    def launch(cls, cfg):
        proj = Path(cfg.project_dir)
        if cfg.entry == cls.CARGO and bridge_for(cfg.platform) == "wine":
            return LaunchSpec(str(proj / "target" / cls.WIN_TARGET / "release"
                                  / (cls._cargo_bin(proj) + ".exe")), [], str(proj))
        if cfg.entry == cls.CARGO:
            name = cls._cargo_bin(proj) + (".exe" if builds_on_windows(cfg)
                                           else "")
            return LaunchSpec(str(proj / "target" / "release" / name),
                              [], str(proj))
        if cfg.entry == cls.GO:
            return LaunchSpec(str(proj / cls._go_out(cfg)), [], str(proj))
        if cfg.entry in (cls.MAKE, cls.CMAKE):
            deep = cfg.entry == cls.CMAKE
            where = (proj / "build") if deep else proj
            exe = cls._newest_exe(where, deep)
            # Nothing built yet: name the folder we looked in, so the failure
            # message points somewhere useful.
            return LaunchSpec(str(exe or where), [], str(proj))
        exe = proj / cfg.entry
        return LaunchSpec(str(exe), [], str(proj))


class JavaRuntime(Runtime):
    id, label = "java", "Java (.jar)"
    BUILD = "(build)"

    @classmethod
    def detect(cls, proj):
        return bool((proj / "pom.xml").is_file()
                    or (proj / "build.gradle").is_file()
                    or (proj / "build.gradle.kts").is_file()
                    or list(proj.glob("*.jar")))

    @classmethod
    def entries(cls, proj):
        out = []
        if (proj / "pom.xml").is_file() or (proj / "build.gradle").is_file() \
                or (proj / "build.gradle.kts").is_file():
            out.append(cls.BUILD)
        out += [p.name for p in sorted(proj.glob("*.jar"))]
        return out

    @classmethod
    def _find_jar(cls, proj):
        for pat in ("*.jar", "target/*.jar", "build/libs/*.jar"):
            hits = sorted(proj.glob(pat))
            # skip sources/javadoc jars
            hits = [h for h in hits if not h.name.endswith(
                ("-sources.jar", "-javadoc.jar"))]
            if hits:
                return hits[0]
        return None

    @classmethod
    def setup_steps(cls, cfg):
        proj = Path(cfg.project_dir)
        if cfg.entry == cls.BUILD or (cfg.entry and
                                      not (proj / cfg.entry).is_file()):
            if (proj / "pom.xml").is_file():
                return [("mvn package", "mvn",
                         ["-q", "-DskipTests", "package"], str(proj))]
            gradlew = proj / "gradlew"
            prog = str(gradlew) if gradlew.is_file() else "gradle"
            if (proj / "build.gradle").is_file() or \
                    (proj / "build.gradle.kts").is_file():
                return [("gradle build", prog, ["build"], str(proj))]
        return []

    @classmethod
    def launch(cls, cfg):
        proj = Path(cfg.project_dir)
        jar = (proj / cfg.entry) if cfg.entry.endswith(".jar") \
            else cls._find_jar(proj)
        return LaunchSpec("java", ["-jar", str(jar) if jar else cfg.entry],
                          str(proj))


class WebRuntime(Runtime):
    id, label, is_web = "web", "Web app (server + browser)", True

    @classmethod
    def detect(cls, proj):
        pkg = _read_json(proj / "package.json")
        if not pkg:
            return False
        deps = {**(pkg.get("dependencies") or {}),
                **(pkg.get("devDependencies") or {})}
        has_fw = any(any(fw in d for d in deps) for fw in WEB_FRAMEWORKS)
        scripts = pkg.get("scripts") or {}
        has_dev = any(s in scripts for s in ("dev", "serve", "start"))
        return has_fw and has_dev

    @classmethod
    def entries(cls, proj):
        scripts = (_read_json(proj / "package.json").get("scripts") or {})
        pref = [s for s in ("dev", "serve", "start") if s in scripts]
        rest = [s for s in scripts if s not in pref]
        return [f"npm:{s}" for s in pref + rest]

    @classmethod
    def setup_steps(cls, cfg):
        return npm_setup(Path(cfg.project_dir), builds_on_windows(cfg))

    @classmethod
    def launch(cls, cfg):
        proj = Path(cfg.project_dir)
        script = cfg.entry[4:] if cfg.entry.startswith("npm:") else \
            (cfg.entry or "dev")
        return LaunchSpec("npm", ["run", script], str(proj), serves=True)


class CsharpRuntime(Runtime):
    id, label = "csharp", "C# / .NET Core"

    @classmethod
    def detect(cls, proj):
        return bool(list(proj.glob("*.csproj")) or list(proj.glob("*.sln")))

    @classmethod
    def entries(cls, proj):
        # .csproj filenames — dotnet run --project takes a path.
        projs = sorted(p.name for p in proj.glob("*.csproj"))
        return projs or ["(default)"]

    WIN_OUT = ".ub-win-x64"     # where a cross-built Windows app lands

    @classmethod
    def _cross(cls, cfg) -> bool:
        """A Windows-only .NET app (WinForms/WPF) off Windows: build it for
        win-x64 with this machine's SDK, then Wine runs the .exe."""
        return bridge_for(cfg.platform) == "wine"

    @classmethod
    def _assembly(cls, proj: Path, entry: str) -> str:
        csproj = proj / entry if entry.endswith(".csproj") else \
            next(iter(sorted(proj.glob("*.csproj"))), None)
        if csproj is None:
            return proj.name
        try:
            m = re.search(r"<AssemblyName>([^<]+)</AssemblyName>",
                          csproj.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            m = None
        return m.group(1).strip() if m else csproj.stem

    @classmethod
    def setup_steps(cls, cfg):
        proj = Path(cfg.project_dir)
        if cls._cross(cfg):
            target = [cfg.entry] if cfg.entry.endswith(".csproj") else []
            # Self-contained single file: Wine then needs no .NET installed in
            # its prefix. EnableWindowsTargeting lets a Linux SDK build it.
            return [("dotnet publish (win-x64)", "dotnet",
                     ["publish", *target, "-c", "Release", "-r", "win-x64",
                      "--self-contained", "true", "-p:PublishSingleFile=true",
                      "-p:EnableWindowsTargeting=true", "-o", cls.WIN_OUT],
                     str(proj))]
        return [("dotnet restore", "dotnet", ["restore"], str(proj))]

    @classmethod
    def launch(cls, cfg):
        proj = Path(cfg.project_dir)
        if cls._cross(cfg):
            exe = proj / cls.WIN_OUT / (cls._assembly(proj, cfg.entry) + ".exe")
            return LaunchSpec(str(exe), [], str(proj))
        if cfg.entry and cfg.entry != "(default)":
            return LaunchSpec("dotnet", ["run", "--project", cfg.entry],
                              str(proj))
        return LaunchSpec("dotnet", ["run"], str(proj))


class RubyRuntime(Runtime):
    id, label = "ruby", "Ruby"

    @classmethod
    def detect(cls, proj):
        return (proj / "Gemfile").is_file() or \
            bool(list(proj.glob("*.rb"))) or \
            (proj / "Rakefile").is_file()

    @classmethod
    def entries(cls, proj):
        out = ["rake"] if (proj / "Rakefile").is_file() else []
        # Full filenames — launch runs `ruby <entry>` verbatim.
        out += sorted(p.name for p in proj.glob("*.rb"))
        return out or ["(default)"]

    @classmethod
    def setup_steps(cls, cfg):
        proj = Path(cfg.project_dir)
        if (proj / "Gemfile").is_file():
            return [("bundle install", "bundle", ["install"], str(proj))]
        return []

    @classmethod
    def launch(cls, cfg):
        proj = Path(cfg.project_dir)
        if cfg.entry == "rake":
            return LaunchSpec("rake", [], str(proj))
        entry = cfg.entry
        if not entry or entry == "(default)":
            rbs = sorted(proj.glob("*.rb"))
            entry = rbs[0].name if rbs else "main.rb"
        return LaunchSpec("ruby", [entry], str(proj))


class PhpRuntime(Runtime):
    id, label = "php", "PHP"

    @classmethod
    def detect(cls, proj):
        return (proj / "composer.json").is_file() or \
            (proj / "index.php").is_file() or \
            bool(list(proj.glob("*.php")))

    @classmethod
    def entries(cls, proj):
        if (proj / "composer.json").is_file():
            return ["composer (dev server)"]
        phpfiles = [p.name for p in proj.glob("*.php")]
        return phpfiles or ["index.php"]

    @classmethod
    def setup_steps(cls, cfg):
        """`composer install` only for a composer.json that asks for
        something — packages or an autoloader. One that just names the
        project (every PHP demo's) needs no Composer, and without one
        installed each start logged a missing-tool warning for nothing."""
        proj = Path(cfg.project_dir)
        spec = _read_json(proj / "composer.json")
        if any(spec.get(k) for k in ("require", "require-dev",
                                     "autoload", "autoload-dev")):
            return [("composer install", "composer", ["install"], str(proj))]
        return []

    @classmethod
    def launch(cls, cfg):
        proj = Path(cfg.project_dir)
        if cfg.entry == "composer (dev server)":
            return LaunchSpec("php", ["-S", f"localhost:{free_port(8000)}"],
                              str(proj), serves=True)
        entry = cfg.entry or "index.php"
        return LaunchSpec("php", [entry], str(proj))

    @classmethod
    def serves(cls, cfg):
        return cfg.entry == "composer (dev server)"


# Bumped per `docker run`, so two tabs of one image get different container
# names instead of docker refusing the second as a duplicate.
_DOCKER_RUNS = [0]


class DockerRuntime(Runtime):
    id, label = "docker", "Docker (container)"

    @classmethod
    def _tag(cls, proj: Path) -> str:
        """Image tag for this project: `ub-<folder>-<hash of path>`.

        The folder name alone is not safe. A module in a folder called
        `docker` built an image tagged literally `docker`, and a folder named
        `nginx` would shadow the official image for every later
        `docker run nginx` on the machine. The prefix keeps our tags in their
        own namespace; the hash stops two same-named folders overwriting each
        other's image.
        """
        slug = re.sub(r"[^a-z0-9_.-]+", "-", proj.name.lower()).strip("-.")
        h = hashlib.md5(str(proj).encode()).hexdigest()[:8]
        return f"ub-{slug or 'module'}-{h}"

    @classmethod
    def detect(cls, proj):
        return (proj / "Dockerfile").is_file() or \
            (proj / "docker-compose.yml").is_file() or \
            (proj / "docker-compose.yaml").is_file()

    @classmethod
    def _compose(cls) -> tuple[str, list[str]]:
        """How to invoke Compose here: v1 binary, or the v2 docker plugin.

        Compose v2 ships *as a docker plugin* — `docker compose`, with no
        binary on PATH — and v1 (`docker-compose`) is end-of-life. So
        which("docker-compose") is exactly the "is this a v1 box" test, and
        anything else gets the plugin form.
        """
        if shutil.which("docker-compose"):
            return "docker-compose", []
        return "docker", ["compose"]

    @classmethod
    def entries(cls, proj):
        if (proj / "docker-compose.yml").is_file() or \
           (proj / "docker-compose.yaml").is_file():
            return ["docker-compose up"]
        return ["docker build & run"]

    @classmethod
    def setup_steps(cls, cfg):
        proj = Path(cfg.project_dir)
        if cfg.entry == "docker-compose up":
            return []
        # Build docker image
        return [("docker build", "docker", ["build", "-t", cls._tag(proj), "."],
                 str(proj))]

    @classmethod
    def launch(cls, cfg):
        proj = Path(cfg.project_dir)
        if cfg.entry == "docker-compose up":
            prog, pre = cls._compose()
            return LaunchSpec(prog, pre + ["up"], str(proj))
        tag = cls._tag(proj)
        _DOCKER_RUNS[0] += 1
        # No -t: QProcess has no TTY (docker errors out). --rm: no litter.
        # --name: killing `docker run` only detaches the client — the
        # container keeps running (and keeps its ports). The launcher removes
        # it by name on stop; without a name there is no handle to do that.
        return LaunchSpec("docker", ["run", "--rm", "--name",
                                     f"{tag}-{_DOCKER_RUNS[0]}", tag],
                          str(proj))


class CustomRuntime(Runtime):
    """Any language the launcher has no class for — you supply the commands.

    Never auto-detected: a module is only custom because someone chose it. That
    keeps detection honest and makes this the deliberate escape hatch for Perl,
    Lua, Tcl, Elixir, R, Zig, a hand-rolled build script — anything with a
    command line. Both commands run through the login shell (see
    shell_command), so `&&`, pipes and profile PATH all work.
    """
    id, label = "custom", "Custom (your own commands)"

    @classmethod
    def detect(cls, proj):
        return False

    @classmethod
    def setup_steps(cls, cfg):
        cmd = (cfg.custom_setup or "").strip()
        if not cmd:
            return []
        prog, args = shell_command(cmd)
        return [(f"custom setup: {cmd}", prog, args, str(cfg.project_dir))]

    @classmethod
    def launch(cls, cfg):
        # `true` for the empty case: start() refuses to get this far, and a
        # LaunchSpec with no program would crash the .serves check above it.
        cmd = (cfg.custom_run or "").strip() or "true"
        prog, args = shell_command(cmd, forward_args=True)
        return LaunchSpec(prog, args, str(cfg.project_dir),
                          serves=bool(cfg.custom_serves))


RUNTIMES: dict[str, type[Runtime]] = {
    r.id: r for r in (PythonRuntime, NodeRuntime, BinaryRuntime,
                      JavaRuntime, WebRuntime, CsharpRuntime, RubyRuntime,
                      PhpRuntime, DockerRuntime, CustomRuntime)
}


# Per-language tab chip colors (dual-tone: split circle). Loosely GitHub-linguist
# brand colors, with a second tone per language for the dual look the user asked for.
LANG_COLORS: dict[str, tuple[str, str]] = {
    "python": ("#3572A5", "#FFD43B"),   # blue + yellow
    "node":   ("#F7DF1E", "#68A063"),   # JS yellow + node green
    "web":    ("#E34C26", "#264DE4"),   # HTML orange + CSS blue
    "java":   ("#B07219", "#5382A1"),   # java brown + blue
    "csharp": ("#178600", "#512BD4"),   # C# green + .NET purple
    "ruby":   ("#CC342D", "#701516"),   # ruby reds
    "php":    ("#8892BF", "#4F5D95"),   # php purples
    "docker": ("#2496ED", "#0DB7ED"),   # docker blues
    "binary": ("#DEA584", "#CE422B"),   # rust tan + rust red
    "custom": ("#7E57C2", "#B39DDB"),   # purple: not a brand, deliberately
}
_LANG_ICON_CACHE: dict[str, QIcon] = {}


def border_colors(runtime_id: str) -> tuple[QColor, QColor]:
    """The tab chip's two tones, floored so dark brands stay visible.

    Ruby's #701516 and Java's #B07219 disappear against the dark theme at
    3px, so anything below the floor is lifted to it.
    """
    floor = 120
    out = []
    for name in LANG_COLORS.get(runtime_id, ("#9AA0A6", "#9AA0A6")):
        c = QColor(name)
        h, sat, light, alpha = c.getHsl()
        if light < floor:
            # setHsl, not lighter(): a percentage factor rounds short of the
            # floor and the check fails by a point.
            c.setHsl(h, sat, floor, alpha)
        out.append(c)
    return out[0], out[1]


def lang_icon(runtime_id: str) -> QIcon:
    """Small dual-tone split-circle chip that color-codes a top tab by language."""
    if runtime_id in _LANG_ICON_CACHE:
        return _LANG_ICON_CACHE[runtime_id]
    c1, c2 = LANG_COLORS.get(runtime_id, ("#9AA0A6", "#9AA0A6"))
    pm = QPixmap(12, 12)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(c1))
    p.drawPie(0, 0, 12, 12, 90 * 16, 180 * 16)     # left half
    p.setBrush(QColor(c2))
    p.drawPie(0, 0, 12, 12, -90 * 16, 180 * 16)    # right half
    p.end()
    icon = QIcon(pm)
    _LANG_ICON_CACHE[runtime_id] = icon
    return icon


_OS_BADGE_CACHE: dict[tuple, QPixmap] = {}
OS_BADGE_TIPS = {
    ("windows", "native"): "Windows app",
    ("windows", "wine"): "Windows app · runs through Wine here",
    ("linux", "native"): "Linux app",
    ("linux", "wsl"): "Linux app · runs in WSL here",
}


def os_badge(need: str, dpr: float = 1.0) -> QPixmap | None:
    """The tab's OS mark: Windows' four panes or a small Tux, painted here so
    no image files ship. None for a module that runs anywhere — the mark
    only says "this one is bound to an OS"."""
    if need not in ("windows", "linux"):
        return None
    key = (need, round(dpr, 2))
    if key in _OS_BADGE_CACHE:
        return _OS_BADGE_CACHE[key]
    pm = QPixmap(max(1, round(12 * dpr)), max(1, round(12 * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(0.5, 0.5)                       # drawn on a 24x24 grid
    p.setPen(Qt.PenStyle.NoPen)
    if need == "windows":
        p.setBrush(QColor("#1A86F0"))
        for x, y in ((2, 2), (14, 2), (2, 14), (14, 14)):   # whole pixels
            p.drawRect(QRectF(x, y, 10, 10))                 # at 1x and 2x
    else:
        # A light rim keeps the black body visible on a dark tab bar.
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.4))
        p.setBrush(QColor("#1C1C1C"))
        p.drawEllipse(QRectF(3.5, 0.5, 17, 21.5))     # body + head
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#F4F4F4"))
        p.drawEllipse(QRectF(7, 8.5, 10, 12))         # belly
        p.drawEllipse(QRectF(7.8, 3.4, 3.6, 4.2))     # eyes
        p.drawEllipse(QRectF(12.6, 3.4, 3.6, 4.2))
        p.setBrush(QColor("#1C1C1C"))
        p.drawEllipse(QRectF(9.4, 5, 1.6, 2))         # pupils
        p.drawEllipse(QRectF(13, 5, 1.6, 2))
        p.setBrush(QColor("#F5B800"))
        p.drawEllipse(QRectF(9, 7.4, 6, 3.2))         # beak
        p.drawEllipse(QRectF(1.5, 18.5, 9.5, 5))      # feet
        p.drawEllipse(QRectF(13, 18.5, 9.5, 5))
    p.end()
    _OS_BADGE_CACHE[key] = pm
    return pm


class LangTabBar(QTabBar):
    """Tab bar with a per-language color mode:
    'none'  — plain tabs.
    'chips' — a small dual-tone chip icon per tab (set via setTabIcon elsewhere).
    'full'  — the whole tab filled with the language's two colors, the label on
              a dark pill so it stays readable on any color.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color_mode = "chips"
        self.tab_colors: dict[int, tuple[str, str]] = {}
        self.hl_index: int | None = None    # tab outlined along with its pane
        self.hl_colors: tuple[QColor, QColor] | None = None

    def set_highlight(self, index: "int | None", colors):
        """Outline one tab in the same two tones as its pane's border."""
        if (index, colors) == (self.hl_index, self.hl_colors):
            return
        self.hl_index, self.hl_colors = index, colors
        self.update()

    def _paint_highlight(self):
        i = self.hl_index
        if i is None or not (0 <= i < self.count()) or not self.hl_colors:
            return
        # Inset by the pen width so the outline lands inside the tab and
        # doesn't bleed onto its neighbour.
        r = self.tabRect(i).adjusted(2, 2, -3, -3)
        grad = QLinearGradient(float(r.left()), float(r.top()),
                               float(r.right()), float(r.bottom()))
        grad.setColorAt(0.0, self.hl_colors[0])
        grad.setColorAt(1.0, self.hl_colors[1])
        p = QPainter(self)
        p.setPen(QPen(QBrush(grad), 3))
        p.drawRect(r)
        p.end()

    def paintEvent(self, ev):
        if self.color_mode != "full":
            super().paintEvent(ev)
            self._paint_highlight()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(self.count()):
            r = self.tabRect(i)
            c1, c2 = self.tab_colors.get(i, ("#9AA0A6", "#9AA0A6"))
            hw = r.width() // 2
            p.fillRect(QRect(r.left(), r.top(), hw, r.height()), QColor(c1))
            p.fillRect(QRect(r.left() + hw, r.top(), r.width() - hw,
                             r.height()), QColor(c2))
            # The label goes between the tab's buttons (OS badge, close), or
            # its end hides under the close button.
            tr = QRect(r)
            for side in (QTabBar.ButtonPosition.LeftSide,
                         QTabBar.ButtonPosition.RightSide):
                b = self.tabButton(i, side)
                if b is not None and b.isVisible():
                    if side == QTabBar.ButtonPosition.LeftSide:
                        tr.setLeft(b.geometry().right() + 1)
                    else:
                        tr.setRight(b.geometry().left() - 1)
            fm = p.fontMetrics()
            txt = fm.elidedText(self.tabText(i), Qt.TextElideMode.ElideRight,
                                max(tr.width() - 14, 0))
            pill = QRect(0, 0, fm.horizontalAdvance(txt) + 14, fm.height() + 4)
            pill.moveCenter(tr.center())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))       # dark pill = readable text
            p.drawRoundedRect(pill, 6, 6)
            p.setPen(QColor("#ffffff"))
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, txt)
            if i == self.currentIndex():
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QColor("#ffffff"))
                p.drawRect(r.adjusted(0, 0, -1, -1))
        p.end()
        self._paint_highlight()


def project_dirs_in(base: Path) -> list[Path]:
    """Project folders under `base`, looking one group level deeper.

    A folder with no runtime of its own but runnable subfolders is a group
    (demo_module/Linux, a "projects/" folder of projects), so its children are
    what count. Two levels and no further: deeper than that is a project's own
    internals, not more projects.
    """
    out = []
    try:
        subs = sorted(base.iterdir())
    except OSError:
        return out
    for sub in subs:
        if not sub.is_dir() or sub.name.startswith((".", "__")):
            continue
        if detect_runtimes(sub):
            out.append(sub)
            continue
        try:
            inner = sorted(sub.iterdir())
        except OSError:
            continue
        out += [d for d in inner if d.is_dir()
                and not d.name.startswith((".", "__")) and detect_runtimes(d)]
    return out


def detect_runtimes(proj: Path) -> list[str]:
    """Runtime ids that match this project, best-guess order first."""
    # Order matters: docker/web before lang-specific (containers wrap any lang)
    # python last so script helpers don't shadow the real runtime.
    order = ["docker", "web", "node", "csharp", "ruby", "php", "binary",
             "java", "python"]
    return [rid for rid in order if RUNTIMES[rid].detect(proj)]


# ---------------------------------------------------------------------------
# X11 window lookup (for embedding)
# ---------------------------------------------------------------------------
def descendant_pids(root_pid: int) -> set[int]:
    """root_pid plus every descendant process (modules may spawn children)."""
    children: dict[int, list[int]] = {}
    try:
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            try:
                stat = (p / "stat").read_text()
                ppid = int(stat.rsplit(")", 1)[1].split()[1])
                children.setdefault(ppid, []).append(int(p.name))
            except (OSError, ValueError, IndexError):
                # Ignore malformed /proc entries or races with process exit
                continue
    except OSError as e:
        logger.debug(f"Cannot read /proc: {e}, using root pid only")
        return {root_pid}
    out = {root_pid}
    stack = [root_pid]
    while stack:
        for c in children.get(stack.pop(), []):
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


# ---------------------------------------------------------------------------
# Resource meters
# ---------------------------------------------------------------------------
CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
METER_MS = 1500          # sample period
METER_HISTORY = 40       # samples kept for the sparkline (one minute at 1.5 s)
METER_SWEEP_EVERY = 5    # fallback only: full /proc walks cost ~15 ms
# The aggregate strip is not any one language, so it gets the base's own tones.
AGG_COLORS = (QColor("#4FC3F7"), QColor("#7E57C2"))


def _proc_table(pids=None) -> dict:
    """pid -> (ppid, cpu_ticks, rss_pages), read straight from /proc.

    `pids=None` walks every process, which is what finds newly spawned
    descendants but costs ~25 ms on a busy desktop — far too much to do at
    every tick. Passing a pid list reads only those and costs microseconds.
    """
    # Windows: winplat.proc_table returns the same shape from psutil.
    out = {}
    try:
        names = [str(x) for x in pids] if pids is not None \
            else os.listdir("/proc")
    except OSError as e:
        logger.debug(f"Cannot list /proc: {e}")
        return out
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as fh:
                # comm can hold spaces and parens, so split after the last ")".
                tail = fh.read().rsplit(b")", 1)[1].split()
            out[int(name)] = (int(tail[1]),                      # ppid
                              int(tail[11]) + int(tail[12]),     # utime+stime
                              int(tail[21]))                     # rss, pages
        except (OSError, ValueError, IndexError):
            continue          # a process exiting mid-read is normal, not an error
    return out


def _children_of(pid: int):
    """Direct children of `pid`, read from /proc/<pid>/task/*/children.

    ~34 us against ~15 ms for a full /proc walk, and unlike a periodic sweep it
    sees a child the moment it is forked — which matters because a module that
    does its real work in a child (npm start -> vite, mvn -> java) would
    otherwise read as idle until the next sweep. Every thread is checked, not
    just the main one: a runtime is free to fork off any of them.

    Returns None when the kernel has no children file at all, so the caller can
    fall back to walking /proc; an empty list means the process simply has no
    children.
    """
    base = f"/proc/{pid}/task"
    try:
        tids = os.listdir(base)
    except OSError:
        return []            # process is gone; not a reason to fall back
    out, readable = [], False
    for tid in tids:
        try:
            with open(f"{base}/{tid}/children", "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        readable = True
        try:
            out.extend(int(x) for x in data.split())
        except ValueError:
            continue
    return out if readable else None


def _tree_from_children(roots):
    """Tree under `roots` walked through the children files. None = fall back."""
    out, stack = set(roots), list(roots)
    while stack:
        kids = _children_of(stack.pop())
        if kids is None:
            return None
        for c in kids:
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


def _tree_of(roots, kids: dict) -> set:
    """Every pid at or under `roots`, given a ppid -> children map."""
    out, stack = set(roots), list(roots)
    while stack:
        for c in kids.get(stack.pop(), ()):
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


class ResourceSampler(QObject):
    """One /proc read per tick, shared by every meter on screen.

    Meters are per-module but sampling is not: letting each pane sample itself
    would walk /proc once per module. The window owns the single timer and the
    meters read the results out of `usage`.
    """
    sampled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.roots: dict = {}        # owner key -> set of root pids
        self.trees: dict = {}        # owner key -> every pid at or under them
        self.usage: dict = {}        # owner key -> (cpu percent, rss bytes)
        self.total = (0.0, 0)
        self._prev: dict = {}        # owner key -> previous tick total
        self._last = 0.0
        self._countdown = 0
        self.timer = QTimer(self)
        self.timer.setInterval(METER_MS)
        self.timer.timeout.connect(self.tick)

    def set_roots(self, key, pids) -> None:
        """Declare which processes belong to one owner. Empty list unwatches."""
        pids = {int(p) for p in pids if p}
        if pids == self.roots.get(key):
            return
        if pids:
            self.roots[key] = pids
        else:
            self.roots.pop(key, None)
            self.usage.pop(key, None)
            self._prev.pop(key, None)
        self.trees.pop(key, None)
        self._countdown = 0          # rediscover descendants on the next tick

    def _discover(self) -> bool:
        """Refresh tree membership the cheap way. False means this kernel has
        no children files and the caller must walk /proc."""
        trees = {}
        for key, pids in self.roots.items():
            found = _tree_from_children(pids)
            if found is None:
                return False
            trees[key] = found
        self.trees = trees
        return True

    def tick(self) -> None:
        if not self.roots:
            if self.usage or self.total != (0.0, 0):
                self.usage, self.total = {}, (0.0, 0)
                self.sampled.emit()
            return
        if not self._discover():
            # No children files on this kernel. Walk all of /proc instead, but
            # throttled — it costs ~15 ms and blocks the GUI thread.
            self._countdown -= 1
            if self._countdown <= 0 or set(self.trees) != set(self.roots):
                self._countdown = METER_SWEEP_EVERY
                kids: dict = {}
                for pid, row in _proc_table().items():
                    kids.setdefault(row[0], []).append(pid)
                self.trees = {k: _tree_of(v, kids)
                              for k, v in self.roots.items()}
        want = set()
        for pids in self.trees.values():
            want |= pids
        table = _proc_table(want)

        now = time.monotonic()
        dt = (now - self._last) if self._last else 0.0
        self._last = now
        usage, cpu_sum, rss_sum = {}, 0.0, 0
        for key, pids in self.roots.items():
            ticks = rss = 0
            for pid in self.trees.get(key, pids):
                row = table.get(pid)
                if row is not None:
                    ticks += row[1]
                    rss += row[2]
            prev = self._prev.get(key)
            self._prev[key] = ticks
            # A child exiting shrinks the tree total, so clamp: a negative
            # delta means "processes left", not "negative CPU".
            pct = 0.0 if prev is None or dt <= 0 \
                else max(0.0, (ticks - prev) / CLK_TCK / dt * 100.0)
            usage[key] = (pct, rss * PAGE_SIZE)
            cpu_sum += pct
            rss_sum += rss
        self.usage = usage
        self.total = (cpu_sum, rss_sum * PAGE_SIZE)
        self.sampled.emit()


def human_bytes(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f}G"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.0f}M"
    return f"{max(0, n) // 1024}K"


class ResourceMeter(QWidget):
    """CPU sparkline with the numbers laid over it, in its module's own tones.

    Deliberately one strip, not two: a pane can be dragged to 160px, and two
    stacked bars plus labels stop being readable long before that.
    """

    def __init__(self, colors=None, parent=None):
        super().__init__(parent)
        self.colors = colors or AGG_COLORS
        self.history: list = []
        self.cpu = 0.0
        self.rss = 0
        self.setFixedHeight(20)
        self.setMinimumWidth(58)
        self.setMaximumWidth(168)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        f = QFont(self.font())
        f.setPointSizeF(max(6.5, f.pointSizeF() - 1.5))
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.setToolTip(
            "CPU and resident memory for this module's whole process tree.\n"
            "The chart scales to its own recent peak, so an idle module still "
            "shows shape;\nthe dotted line, when present, marks one full core.")

    def set_colors(self, colors) -> None:
        if colors != self.colors:
            self.colors = colors
            self.update()

    def push(self, cpu: float, rss: int) -> None:
        self.cpu, self.rss = cpu, rss
        self.history.append(cpu)
        del self.history[:-METER_HISTORY]
        self.update()

    def clear(self) -> None:
        self.history.clear()
        self.cpu, self.rss = 0.0, 0
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 20))
        p.drawRoundedRect(0, 0, w, h, 4, 4)

        if len(self.history) > 1:
            # Scale to this module's own recent peak, not to 100%: pinned to an
            # absolute axis, everything that isn't compiling reads as a flat
            # line at the bottom. The floor keeps an idle module calm instead
            # of turning 0.4% jitter into mountains, and the number beside the
            # chart is always the absolute truth.
            top = max(12.0, max(self.history) * 1.25)
            step = w / (len(self.history) - 1)
            pts = [QPointF(i * step, h - (v / top) * (h - 3) - 1.5)
                   for i, v in enumerate(self.history)]
            grad = QLinearGradient(0.0, 0.0, float(w), 0.0)
            grad.setColorAt(0.0, self.colors[0])
            grad.setColorAt(1.0, self.colors[1])
            if top > 100.0:      # the axis left one core behind: say so
                y = h - (100.0 / top) * (h - 3) - 1.5
                # Derived from the text colour, not a fixed black: a hard-coded
                # dark line vanishes completely on a dark theme.
                ref = QColor(self.palette().windowText().color())
                ref.setAlpha(80)
                p.setPen(QPen(ref, 1, Qt.PenStyle.DotLine))
                p.drawLine(0, int(y), w, int(y))
                p.setPen(Qt.PenStyle.NoPen)
            area = QPainterPath(QPointF(0.0, float(h)))
            for pt in pts:
                area.lineTo(pt)
            area.lineTo(QPointF(float(w), float(h)))
            area.closeSubpath()
            p.save()
            p.setOpacity(0.40)
            p.fillPath(area, QBrush(grad))
            p.restore()
            line = QPainterPath(pts[0])
            for pt in pts[1:]:
                line.lineTo(pt)
            p.strokePath(line, QPen(QBrush(grad), 1.4))
            p.setBrush(self.colors[1])       # "now" marker
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(pts[-1], 1.9, 1.9)

        p.setPen(self.palette().windowText().color())
        p.drawText(QRect(5, 0, w - 10, h),
                   int(Qt.AlignmentFlag.AlignVCenter
                       | Qt.AlignmentFlag.AlignLeft),
                   f"{self.cpu:.0f}%  {human_bytes(self.rss)}")
        p.end()


class LogWindow(QWidget):
    """An undocked log pane.

    Wears its module's border gradient, the same two tones as that module's tab
    chip and pane outline, so several open at once stay tellable apart.
    """
    redock = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, name: str, colors, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.setWindowTitle(f"{name} — log")
        self.resize(760, 460)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        title = QLabel(f"<b>{name}</b> — log")
        btn_dock = QToolButton()
        btn_dock.setText("⧉")
        btn_dock.setToolTip("Dock this log back beside the module")
        btn_dock.clicked.connect(self.redock)
        btn_close = QToolButton()
        btn_close.setText("✕")
        btn_close.setToolTip("Close the log")
        btn_close.clicked.connect(self.close)
        bar.addWidget(title, 1)
        bar.addWidget(btn_dock)
        bar.addWidget(btn_close)
        v.addLayout(bar)
        self.host = QWidget()          # the log widget is moved in here
        hv = QVBoxLayout(self.host)
        hv.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.host, 1)

    def paintEvent(self, event):
        super().paintEvent(event)
        grad = QLinearGradient(0.0, 0.0, float(self.width()),
                               float(self.height()))
        grad.setColorAt(0.0, self.colors[0])
        grad.setColorAt(1.0, self.colors[1])
        p = QPainter(self)
        p.setPen(QPen(QBrush(grad), 3))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


def kill_pid(pid: int, sig: int) -> str:
    """Signal one process: 'ok', 'gone', or 'denied'."""
    try:
        os.kill(pid, sig)
        return "ok"
    except ProcessLookupError:
        return "gone"
    except OSError:
        return "denied"


def kill_process_tree(pid: int, sig: int = SIGTERM) -> int:
    """Signal a process and everything it spawned. Returns how many were hit.

    QProcess only signals its direct child. A module launched as `npm start`
    or `npx electron` forks the real app one or two levels down, so killing
    the wrapper leaves vite still holding :5173 and electron still holding an
    X window — reparented onto systemd, invisible to the launcher. Those
    leftovers are what make a module that worked earlier refuse to load later.
    """
    # Windows replaces this whole function (winplat.kill_process_tree).
    return sum(kill_pid(p, sig) == "ok"
               for p in sorted(descendant_pids(pid), reverse=True))  # kids first


def pids_with_arg(needle: str) -> set[int]:
    """Pids whose command line contains `needle` (never our own).

    Snap-packaged Chromium re-execs itself into its own systemd scope, so the
    browser we launched is not a descendant of the QProcess we started and a
    tree kill misses all twelve of its processes. Its throwaway
    `--user-data-dir` is unique per launch, which makes it a safe handle.
    """
    # Windows: winplat.pids_with_arg (psutil).
    out: set[int] = set()
    if len(needle) < 8:          # too generic to match on safely
        return out
    mine = os.getpid()
    raw = needle.encode()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return out
    for p in entries:
        if not p.name.isdigit() or int(p.name) == mine:
            continue
        try:
            if raw in (p / "cmdline").read_bytes():
                out.add(int(p.name))
        except OSError:
            continue             # raced with exit, or not ours to read
    return out


# Wine's own per-prefix services. Whichever program starts a prefix's
# wineserver starts these too, so they inherit that module's environment —
# launch tag included — while serving every Windows module in the prefix.
WINE_SERVICES = {"services.exe", "winedevice.exe", "plugplay.exe",
                 "explorer.exe", "svchost.exe", "rpcss.exe"}


def wine_family(tag: str) -> set[int]:
    """Windows processes whose environment holds `tag` ("NAME=value").

    Wine starts every Windows process detached from its parent (double fork,
    own session), so the app.exe a .bat runs — or anything an .exe launches —
    is not in the launched process's tree: the window lookup fell back to a
    guess, Stop left the app running, the meter missed it. Wine does hand the
    environment down. Only .exe processes count: a Linux program the app
    opened (the browser behind a link) inherits the tag too, and isn't ours.
    """
    out: set[int] = set()
    raw = tag.encode()
    mine = os.getpid()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return out
    for p in entries:
        if not p.name.isdigit() or int(p.name) == mine:
            continue
        try:
            if raw not in (p / "environ").read_bytes().split(b"\0"):
                continue
            argv0 = (p / "cmdline").read_bytes().split(b"\0", 1)[0]
        except OSError:
            continue             # raced with exit, or not ours to read
        name = re.split(r"[\\/]", argv0.decode(errors="replace"))[-1].lower()
        if name.endswith(".exe") and name not in WINE_SERVICES:
            out.add(int(p.name))
    return out


def x_close_clients(pids: set[int]) -> int:
    """Disconnect the X clients these processes hold: the stop that needs no
    signal permission. A snap's AppArmor profile takes signals only from
    senders it calls "unconfined" — a confined or sandboxed launcher is
    refused — but a browser that loses its X connection exits all the same.
    By XRes client, not by window: once its pane is gone a browser may hold
    nothing but 10px helper windows. Returns how many clients were closed."""
    if IS_WINDOWS or not HAS_X:
        return 0
    try:
        from Xlib import display
        d = display.Display()
    except Exception as e:
        logger.debug(f"X client close: no display: {e}")
        return 0
    n = 0
    try:
        for base, _mask, pid in _xres_client_pids(d):
            if pid in pids and pid != os.getpid():
                d.create_resource_object("window", base).kill_client()
                n += 1
        d.sync()
    except Exception as e:
        logger.debug(f"X client close failed: {e}")
    finally:
        d.close()
    return n


def in_sandboxed_env() -> bool:
    """Detect if running in Flatpak, Snap, or other sandboxed environment."""
    return bool(os.environ.get("FLATPAK_ID") or
                os.environ.get("SNAP") or
                Path("/.dockerenv").exists() or
                Path("/run/ostree-booted").exists())

def embed_diagnostics() -> str:
    """One-line report of which window-lookup backends are available."""
    try:
        import Xlib  # noqa: F401
        xlib = "python-xlib OK"
    except ImportError:
        xlib = "python-xlib MISSING"
    xdo = "xdotool OK" if shutil.which("xdotool") else "xdotool missing"
    platform_info = "Wayland" if IS_WAYLAND else "X11"
    display = os.environ.get('DISPLAY', '(none)')
    sandbox = " [sandboxed]" if in_sandboxed_env() else ""
    return f"window lookup: {xlib}, {xdo}, {platform_info}, DISPLAY={display}{sandbox}"


# Windows already pulled into a tab. A module that is still building has no
# window yet, and its "grab any new window" fallback happily took a
# neighbour's — java-table's data table came up inside the C# tab.
_CLAIMED_WINDOWS: set[int] = set()

# Linux windows on a Windows X server all belong to vcxsrv.exe, and Tk or
# plain-Xlib windows carry no _NET_WM_PID (over TCP the server can't tell
# either): "new since my launch" is all that ties one to its module. WSL
# modules started together (a layout) took each other's windows — five at
# once came out in a full circle. So they take turns: one looks for its
# window at a time, the next launches once that one has its window, gives
# up, or stops. Setup still runs in parallel.
_WSL_TURN: dict = {"searching": None, "queue": []}   # queue: (tab, launch)

# Every module tab, for the "any new window" fallback to ask whose a window
# is: java-table-win's table came up in csharp-winrt's tab (still compiling,
# past its 10 s head start) and the C# window then in Java's.
_LIVE_TABS: "weakref.WeakSet" = weakref.WeakSet()


def windows_for_pids(pids: set[int]) -> list[int]:
    """Return viewable X11 window ids owned by any pid, largest first."""
    wids = _xlib_windows_for_pids(pids)
    if wids:
        return wids
    return _xdotool_windows_for_pids(pids)


def _xres_client_pids(d) -> list[tuple[int, int, int]]:
    """(resource_base, resource_mask, pid) for every client on this display.

    Tk, SDL, minifb and winit apps never set _NET_WM_PID — python, ruby and
    rust modules all land in that bucket — so pid matching missed them and
    the launcher fell back to "newest window on screen". With several modules
    starting at once that fallback hands a window to whichever tab polls
    first, and modules appear in each other's panes. XRes asks the X server
    which client owns a resource, which is authoritative. Resource ids carry
    their client's base in the high bits, so one query per client (a dozen or
    so) attributes every window on the display.
    """
    # X11-only. Windows attributes windows directly: winplat.windows_for_pids.
    try:
        from Xlib.ext import res
    except ImportError:
        return []
    out: list[tuple[int, int, int]] = []
    try:
        for c in res.query_clients(d).clients:
            reply = res.query_client_ids(
                d, [{"client": c.resource_base,
                     "mask": res.LocalClientPIDMask}])
            pid = next((int(v) for item in reply.ids for v in item.value), 0)
            if pid:
                out.append((c.resource_base, c.resource_mask, pid))
    except Exception as e:
        # No XRes (old/remote server) — callers fall back to the old guess.
        logger.debug(f"XRes client lookup failed: {e}")
    return out


def _xlib_windows_for_pids(pids: set[int]) -> list[int]:
    try:
        from Xlib import X, display
    except ImportError:
        return []
    try:
        d = display.Display()
    except Exception as e:
        logger.debug(f"Cannot connect to X display: {e}")
        return []
    try:
        net_wm_pid = d.intern_atom("_NET_WM_PID")
        # WM_STATE marks a real top-level window the window manager is
        # managing. AWT/Swing also owns an internal "Content window" that is
        # *larger* than its frame (800x637 vs 800x600), so ranking by area
        # alone embedded that instead and java modules drew a blank pane.
        wm_state = d.intern_atom("WM_STATE")
        # Windows of ours that never advertise a pid, found via XRes instead.
        owners = [(base, mask) for base, mask, pid in _xres_client_pids(d)
                  if pid in pids]
        out: list[tuple[int, int, int]] = []

        def owned(wid: int) -> bool:
            return any((wid & ~mask) == base for base, mask in owners)

        def walk(w, depth=0):
            if depth > 6:
                return
            try:
                prop = w.get_full_property(net_wm_pid, X.AnyPropertyType)
                claimed = bool(prop and prop.value
                               and int(prop.value[0]) in pids)
                if claimed or owned(w.id):
                    if w.get_attributes().map_state == X.IsViewable:
                        g = w.get_geometry()
                        top = 1 if w.get_full_property(
                            wm_state, X.AnyPropertyType) else 0
                        out.append((w.id, g.width * g.height, top))
                for child in w.query_tree().children:
                    walk(child, depth + 1)
            except Exception as e:
                logger.debug(f"X window walk failed at depth {depth}: {e}")

        walk(d.screen().root)
        # Managed top-levels first, then largest.
        return [wid for wid, _, _ in sorted(out, key=lambda t: (-t[2], -t[1]))]
    except Exception as e:
        logger.debug(f"Xlib window lookup failed: {e}")
        return []
    finally:
        try:
            d.close()
        except Exception as e:
            logger.debug(f"X display close failed: {e}")


def _xdotool_windows_for_pids(pids: set[int]) -> list[int]:
    if not shutil.which("xdotool"):
        return []
    out: list[int] = []
    for pid in pids:
        try:
            r = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--pid", str(pid)],
                capture_output=True, text=True, timeout=5)
            out += [int(line) for line in r.stdout.split() if line.isdigit()]
        except subprocess.TimeoutExpired:
            logger.debug(f"xdotool timeout for pid {pid}")
        except Exception as e:
            logger.debug(f"xdotool lookup failed for pid {pid}: {e}")
    return out


def all_window_ids(max_depth: int = 6) -> set[int]:
    """Snapshot of every window id in the tree (best effort, for diffing)."""
    try:
        from Xlib import display
    except ImportError:
        return set()
    try:
        d = display.Display()
    except Exception as e:
        logger.debug(f"Cannot connect to X display for window snapshot: {e}")
        return set()
    try:
        ids: set[int] = set()

        def walk(w, depth=0):
            if depth > max_depth:
                return
            try:
                for child in w.query_tree().children:
                    ids.add(child.id)
                    walk(child, depth + 1)
            except Exception as e:
                logger.debug(f"X window snapshot failed at depth {depth}: {e}")

        walk(d.screen().root)
        return ids
    except Exception as e:
        logger.debug(f"Window snapshot failed: {e}")
        return set()
    finally:
        try:
            d.close()
        except Exception as e:
            logger.debug(f"X display close failed: {e}")


# WM_CLASS values that belong to a window manager's own decoration frame, never
# to a real client. GNOME/XWayland wraps each X client in a `mutter-x11-frames`
# window that is larger than the client and also carries a WM_CLASS, so without
# this it outranks the client — embedding an empty frame, and (worse) reparenting
# the compositor's own window on teardown, which froze the session.
# ponytail: GNOME only; add other WMs' frame classes if they ever surface.
FRAME_CLASSES = {"mutter-x11-frames"}


def is_wm_frame(wm_class) -> bool:
    """True if this WM_CLASS is a decoration frame rather than a real client."""
    return bool(wm_class) and wm_class[0] in FRAME_CLASSES


def rank_new_windows(cands: list[tuple]) -> list[int]:
    """(wid, area, wm_class) candidates -> best-first ids, WM frames dropped.

    Real clients (WM_CLASS set) rank above unnamed windows, then largest first.
    """
    keep = [(wid, area, 1 if cls else 0)
            for wid, area, cls in cands if not is_wm_frame(cls)]
    keep.sort(key=lambda t: (-t[2], -t[1]))
    return [wid for wid, _, _ in keep]


# Processes that own the windows of *Linux* apps on a Windows desktop: WSLg's
# RDP client, plus the common third-party X servers.
LINUX_WINDOW_OWNERS = ("msrdc.exe", "vcxsrv.exe", "x410.exe", "xming.exe")


def new_windows_since(baseline: set[int], own_pid: int,
                      max_depth: int = 6, owners=None,
                      skip_owners=()) -> list[int]:
    """Viewable, app-like windows that appeared since `baseline`.
    (`owners`/`skip_owners` name Windows executables: Windows only.)

    Fallback for modules whose window never sets _NET_WM_PID (common with
    SDL/OpenGL apps), so the pid-based lookup can't find them. We pick the
    newest visible window that isn't ours and looks like a real client
    (has WM_CLASS, reasonable size), preferring larger / decorated ones.
    """
    try:
        from Xlib import X, display
    except ImportError:
        return []
    try:
        d = display.Display()
    except Exception as e:
        logger.debug(f"Cannot connect to X display for new window lookup: {e}")
        return []
    try:
        net_wm_pid = d.intern_atom("_NET_WM_PID")
        # (wid, area, wm_class) candidates; rank_new_windows() filters + orders.
        out: list[tuple] = []

        def walk(w, depth=0):
            if depth > max_depth:
                return
            try:
                children = w.query_tree().children
            except Exception as e:
                logger.debug(f"X query_tree failed at depth {depth}: {e}")
                return
            for child in children:
                try:
                    if child.id not in baseline:
                        attrs = child.get_attributes()
                        if attrs.map_state == X.IsViewable:
                            g = child.get_geometry()
                            if g.width > 32 and g.height > 32:
                                prop = child.get_full_property(
                                    net_wm_pid, X.AnyPropertyType)
                                wpid = (int(prop.value[0])
                                        if prop and prop.value else None)
                                if wpid != own_pid:
                                    # WM frames are dropped by rank_new_windows;
                                    # the real client is found by the recursion.
                                    out.append((child.id,
                                                g.width * g.height,
                                                child.get_wm_class()))
                except Exception as e:
                    logger.debug(f"X window check failed: {e}")
                walk(child, depth + 1)

        walk(d.screen().root)
        return rank_new_windows(out)
    except Exception as e:
        logger.debug(f"New window lookup failed: {e}")
        return []
    finally:
        try:
            d.close()
        except Exception as e:
            logger.debug(f"X display close failed: {e}")


# ---------------------------------------------------------------------------
# Platform-specific window embedding
# X11 embedding host — raw reparent via python-xlib.
# Qt 6's QWindow.fromWinId + createWindowContainer silently no-ops on xcb
# for foreign windows, so we move the child window into a native widget
# ourselves (classic XReparentWindow technique).
# Gracefully falls back to panel mode on Wayland or when reparenting fails.
# ---------------------------------------------------------------------------
class XEmbedHost(QWidget):
    clicked = pyqtSignal()      # a button press landed inside the child

    def __init__(self, child_wid: int, parent=None, log=None):
        super().__init__(parent)
        from Xlib import display
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.disp = display.Display()
        # The child can vanish at any moment (the app exits, Stop kills it);
        # requests still queued for it then fail with BadWindow, which
        # python-xlib would print as "X protocol error" at every Stop.
        self.disp.set_error_handler(
            lambda err, *_a: logger.debug(f"X error on embedded window: {err}"))
        self.child_wid = child_wid
        self.child = self.disp.create_resource_object("window", child_wid)
        self._log = log or (lambda _msg: None)
        self._warned_fixed = False   # only nag about a fixed-size client once
        self._last_want: tuple[int, int] | None = None   # last size we asked for
        self._grabbed = False
        self._notifier: QSocketNotifier | None = None
        self._pump: QTimer | None = None
        self._attach()
        self._watch_clicks()
        # Self-healing: keep nudging the child back under us for a few
        # seconds. Covers two real-world cases that used to leave windows
        # floating outside the tab — Qt recreating our native window when a
        # sibling pane's layout/visibility changes, and the window manager
        # re-grabbing a freshly mapped window into its own decoration frame.
        self._heal_timer = QTimer(self)
        self._heal_timer.setInterval(400)
        self._heal_timer.timeout.connect(self._heal_tick)
        self._heal_ticks = 0
        self._heal_timer.start()

    def _host_wid(self) -> int:
        return int(self.winId())

    # -- click detection ----------------------------------------------------
    # A click inside the embedded child is delivered by X straight to the
    # module, so Qt never hears about it and the launcher can't tell which
    # pane the user is working in. A passive button grab -- exactly what a
    # click-to-focus window manager does -- lets us see the press first;
    # ReplayPointer then hands the very same click on to the app, so nothing
    # is swallowed.
    # Windows does this with WM_PARENTNOTIFY instead (winplat.Win32EmbedHost).
    def _watch_clicks(self):
        if self._grabbed:
            return
        try:
            from Xlib import X
            self.child.grab_button(1, X.AnyModifier, True, X.ButtonPressMask,
                                   X.GrabModeSync, X.GrabModeAsync,
                                   X.NONE, X.NONE)
            self.disp.sync()
        except Exception as e:
            logger.debug(f"Button grab failed: {e}")
            return
        self._grabbed = True
        self._notifier = QSocketNotifier(self.disp.fileno(),
                                         QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(lambda *_a: self._drain_x())
        # Sync-mode grab freezes the pointer until we reply, and a sync()
        # elsewhere in this class can pull our ButtonPress off the socket
        # before the notifier ever fires. Poll as well, so a missed wake-up
        # costs 200 ms instead of a dead mouse.
        self._pump = QTimer(self)
        self._pump.setInterval(200)
        self._pump.timeout.connect(self._drain_x)
        self._pump.start()

    def _drain_x(self):
        if not self._grabbed:
            return
        try:
            from Xlib import X
            while self.disp.pending_events():
                ev = self.disp.next_event()
                if ev.type == X.ButtonPress:
                    self.clicked.emit()
                # Unconditional: replaying when nothing is frozen is a no-op,
                # and never leaving a freeze behind is what matters here.
                self.disp.allow_events(X.ReplayPointer, X.CurrentTime)
            self.disp.flush()
        except Exception as e:
            logger.debug(f"X event drain failed: {e}")

    def _stop_watching(self):
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._pump is not None:
            self._pump.stop()
            self._pump = None
        if not self._grabbed:
            return
        self._grabbed = False
        try:
            from Xlib import X
            self.child.ungrab_button(1, X.AnyModifier)
            self.disp.sync()
        except Exception as e:
            logger.debug(f"Button ungrab failed: {e}")

    def _attach(self):
        try:
            self.child.unmap()
            self.disp.sync()
            self.child.reparent(self._host_wid(), 0, 0)
            self.child.map()
            self.disp.sync()
            self._resize_child()
        except Exception as e:
            logger.debug(f"Window reparent failed: {e}")

    def child_alive(self) -> bool:
        try:
            self.child.query_tree()
            return True
        except Exception as e:
            logger.debug(f"Child window check failed: {e}")
            return False

    def _parent_id(self):
        try:
            p = self.child.query_tree().parent
            return p.id if p is not None else None
        except Exception as e:
            logger.debug(f"Parent ID lookup failed: {e}")
            return None

    def reattach_if_needed(self) -> bool:
        """Re-parent the child if it has drifted away. Returns False only if
        the child window no longer exists (truly destroyed/recreated)."""
        pid = self._parent_id()
        if pid is None and not self.child_alive():
            return False
        if pid != self._host_wid():
            self._attach()
        return True

    def _heal_tick(self):
        self._heal_ticks += 1
        if not self.child_alive() or self._heal_ticks > 15:  # ~6 s
            self._heal_timer.stop()
            return
        self.reattach_if_needed()
        self._claim_state()      # the WM may withdraw it after our _attach
        try:
            self._check_fits()
        except Exception as e:
            logger.debug(f"Fixed-size check failed: {e}")

    def _claim_state(self):
        """Tell the client it is shown, as a window manager would.

        Unmapping it out of the WM's frame left WM_STATE at Withdrawn (or, with
        no WM at all, never set). Most toolkits don't care; Wine does — it
        ignores every resize of a window it believes is withdrawn, so a
        Windows app would stay at its launch size inside the pane.
        """
        try:
            a = self.disp.intern_atom("WM_STATE")
            self.child.change_property(a, a, 32, [1, 0])   # NormalState, no icon
        except Exception as e:
            logger.debug(f"WM_STATE update failed: {e}")

    def _resize_child(self):
        try:
            r = self.devicePixelRatioF()
            want = (max(1, int(self.width() * r)), max(1, int(self.height() * r)))
            self._claim_state()
            self.child.configure(width=want[0], height=want[1])
            self.disp.sync()
            self._last_want = want      # checked later by _heal_tick
        except Exception as e:
            logger.debug(f"Window resize failed: {e}")

    def _check_fits(self):
        """Warn once if the client refuses to shrink to the pane (it gets clipped).

        Apps that fix their window size (Avalonia `CanResize=false`, SDL windows
        with no resize flag, …) ignore our configure, so the pane crops them.
        Nothing the host can do about it — say so instead of looking broken.

        Called from the heal tick, not straight after configure(): a toolkit
        handles ConfigureNotify asynchronously, so reading the geometry
        immediately would still see the old size and warn about nothing.
        ponytail: only while the heal timer runs (~6 s from mount, the case that
        matters); a much-later manual pane resize won't re-check.
        """
        if self._warned_fixed or self._last_want is None:
            return
        want = self._last_want
        got = self.child.get_geometry()
        if got.width <= want[0] + 2 and got.height <= want[1] + 2:
            return
        self._warned_fixed = True
        self._log(f"This app keeps its window at {got.width}x{got.height} and "
                  f"won't shrink to the {want[0]}x{want[1]} pane, so its edges "
                  "are cut off. Widen the pane, set the tab Independent "
                  "(right-click ▸ Independent), or make the app resizable.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reattach_if_needed()
        self._resize_child()

    def showEvent(self, event):
        super().showEvent(event)
        self.reattach_if_needed()
        self._resize_child()

    def mousePressEvent(self, event):
        self.focus_child()
        super().mousePressEvent(event)

    def focus_child(self):
        try:
            from Xlib import X
            self.disp.set_input_focus(self.child, X.RevertToParent,
                                      X.CurrentTime)
            self.disp.sync()
        except Exception as e:
            logger.debug(f"Window focus failed: {e}")

    def verify(self) -> bool:
        """True if the child really is parented under this widget."""
        try:
            return self.child.query_tree().parent.id == self._host_wid()
        except Exception as e:
            logger.debug(f"Window verification failed: {e}")
            return False

    def detach(self):
        self._stop_watching()
        try:
            self._heal_timer.stop()
        except Exception as e:
            logger.debug(f"Heal timer stop failed: {e}")
        try:
            self.disp.close()
        except Exception as e:
            logger.debug(f"X display close failed: {e}")


class TerminalHost(QWidget):
    """Full interactive terminal, by embedding a real `xterm` (its `-into`
    option makes xterm reparent itself into our native X window). A real
    terminal means real TUIs — vim, htop, ssh, interactive prompts all work —
    with zero terminal-emulator code to maintain. Linux/X11 only; the one-shot
    command bar stays the cross-platform fallback.

    ponytail: needs `xterm` installed. The heal loop reparents xterm back if Qt
    recreates our native window (same failure mode XEmbedHost handles). xterm is
    launched on first show so winId is stable and mapped.

    X11-only (python-xlib + xterm -into). On Windows, TerminalHost is
    winplat.ConsoleTerminal: an embedded conhost console, same idea."""
    closed = pyqtSignal()       # the shell ended (`exit`), not shutdown()

    def __init__(self, cwd: str, parent=None, log=None):
        super().__init__(parent)
        self._log = log or (lambda m: None)   # optional sink for give-up notice
        self._find_attempts = 0
        from Xlib import display
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(140)
        self.disp = display.Display()
        self.cwd = cwd
        self.child = None          # xterm's X window, once it maps under us
        self._started = False
        self._last_size = (0, 0)   # skip redundant XConfigure from the heal loop
        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        force_x11_env(env)
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(cwd)
        self.proc.finished.connect(self.closed)
        self._heal = QTimer(self)
        self._heal.setInterval(400)
        self._heal.timeout.connect(self._heal_tick)

    def _host_wid(self) -> int:
        return int(self.winId())

    def _ensure_started(self):
        if self._started:
            return
        self._started = True
        shell = os.environ.get("SHELL", "/bin/bash")
        # -into: xterm reparents itself into our window. -sb: scrollback bar.
        self.proc.start("xterm", ["-into", str(self._host_wid()),
                                  "-fa", "Monospace", "-fs", "11", "-sb",
                                  "-e", shell])
        self._heal.start()

    def _find_child(self):
        try:
            host = self.disp.create_resource_object("window", self._host_wid())
            kids = host.query_tree().children
            if not kids:
                return
            # Prefer the child whose _NET_WM_PID is our xterm — robust when the
            # host briefly has more than one child. Fall back to topmost if xterm
            # doesn't advertise a pid (then it's the only child anyway).
            pid = self.proc.processId()
            if pid:
                from Xlib import Xatom
                atom = self.disp.intern_atom("_NET_WM_PID")
                for w in kids:
                    try:
                        p = w.get_full_property(atom, Xatom.CARDINAL)
                        if p and p.value and int(p.value[0]) == pid:
                            self.child = w
                            return
                    except Exception:
                        continue
            self.child = kids[-1]
        except Exception as e:
            logger.debug(f"Terminal child lookup failed: {e}")

    def _resize_child(self):
        if self.child is None:
            return
        r = self.devicePixelRatioF()
        size = (max(1, int(self.width() * r)), max(1, int(self.height() * r)))
        if size == self._last_size:
            return
        try:
            self.child.configure(width=size[0], height=size[1])
            self.disp.sync()
            self._last_size = size
        except Exception as e:
            logger.debug(f"Terminal resize failed: {e}")

    def _heal_tick(self):
        if self.proc.state() == QProcess.ProcessState.NotRunning:
            self._heal.stop()
            return
        if self.child is None:
            self._find_child()
            if self.child is None:
                # Bound discovery: xterm should map within a second or two. If it
                # never becomes our child (e.g. host window recreated before it
                # mapped), stop polling and tell the user instead of an infinite
                # 400 ms X round-trip and a silently blank pane.
                self._find_attempts += 1
                if self._find_attempts >= 40:   # ~16 s
                    self._heal.stop()
                    self._log("Terminal did not attach — toggle it off/on to "
                              "retry (is xterm working?).")
                return
        else:
            try:
                if self.child.query_tree().parent.id != self._host_wid():
                    self.child.reparent(self._host_wid(), 0, 0)
                    self.disp.sync()
                    self._last_size = (0, 0)   # force a resize after reattach
            except Exception as e:
                logger.debug(f"Terminal reattach failed: {e}")
                self.child = None
                return
        self._resize_child()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_child()

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_started()
        self._resize_child()

    def mousePressEvent(self, event):
        try:
            from Xlib import X
            if self.child is not None:
                self.disp.set_input_focus(self.child, X.RevertToParent,
                                          X.CurrentTime)
                self.disp.sync()
        except Exception as e:
            logger.debug(f"Terminal focus failed: {e}")
        super().mousePressEvent(event)

    def shutdown(self):
        self._heal.stop()
        self.proc.finished.disconnect(self.closed)
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.terminate()
            if not self.proc.waitForFinished(1500):
                self.proc.kill()
                self.proc.waitForFinished(1000)
        try:
            self.disp.close()
        except Exception as e:
            logger.debug(f"Terminal X display close failed: {e}")


def find_browser() -> str | None:
    """A Chromium-family browser on PATH (Windows overrides: Edge is never on
    PATH there)."""
    return next((shutil.which(b) for b in BROWSERS if shutil.which(b)), None)


# The embedding host for this platform. X11 reparenting here; Windows swaps in
# SetParent below.
EmbedHost = XEmbedHost

# Windows: same names, Windows implementations. Every call site in this file
# looks these up at call time, so rebinding the module globals is the whole
# integration — no `if IS_WINDOWS` scattered through the module code.
if IS_WINDOWS:
    import winplat
    (descendant_pids, kill_process_tree, pids_with_arg, windows_for_pids,
     all_window_ids, new_windows_since, embed_diagnostics, find_browser,
     _tree_from_children) = (
        winplat.descendant_pids, winplat.kill_process_tree,
        winplat.pids_with_arg, winplat.windows_for_pids,
        winplat.all_window_ids, winplat.new_windows_since,
        winplat.embed_diagnostics, winplat.find_browser,
        winplat.tree_from_children)
    _proc_table = winplat.proc_table
    wsl_ready = winplat.wsl_ready
    wsl_x_display = winplat.wsl_x_display
    kill_pid = winplat.kill_pid
    EmbedHost = winplat.Win32EmbedHost
    TerminalHost = winplat.ConsoleTerminal


# ---------------------------------------------------------------------------
# Module config / persistence
# ---------------------------------------------------------------------------
@dataclass
class ModuleConfig:
    name: str
    project_dir: str
    entry: str
    runtime: str = "python"    # python | node | binary | java | web | ...
    embed: bool = True         # pull window into the tab
    use_shared: bool = False   # use the shared venv instead of a private one
    independent: bool = False  # fill the whole base window (vs. merge/tile)
    # Per-module overrides (all optional; old configs load fine without them).
    extra_env: dict = field(default_factory=dict)      # env vars for launch
    startup_args: list = field(default_factory=list)   # appended to argv
    # Custom runtime only: the commands the user supplied.
    custom_setup: str = ""     # optional build/fetch step, runs first
    custom_run: str = ""       # the command that starts the app
    custom_serves: bool = False  # prints a URL instead of opening a window
    # What the module needs to run: "" anywhere, "linux", or "windows". The
    # launcher picks the bridge from this (see bridge_for), so a config saved on
    # one OS still means the right thing when opened on the other.
    platform: str = ""
    # View options that belong to the module, not the window.
    show_meter: bool = True    # CPU/RAM strip in this pane's header
    log_mode: str = "embedded"   # embedded | docked | undocked

    @property
    def env_dir(self) -> Path:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", Path(self.project_dir).name)
        h = hashlib.md5(self.project_dir.encode()).hexdigest()[:8]
        return ENVS_DIR / f"{slug}-{h}"

    @property
    def env_python(self) -> Path:
        return venv_python(self.env_dir)


LIBRARY_FILE = APP_DIR / "library.json"
LAYOUTS_FILE = APP_DIR / "layouts.json"
PREFS_FILE = APP_DIR / "prefs.json"


def _load_json(path: Path, default):
    """Load JSON with graceful fallback to default."""
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        logger.warning(f"Corrupted JSON in {path}: {e}, using default")
        return default
    except OSError as e:
        logger.warning(f"Cannot read {path}: {e}, using default")
        return default


def _save_json(path: Path, data) -> None:
    """Save JSON atomically (prevents corruption on power loss)."""
    try:
        atomic_write(path, json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save {path}: {e}")


def load_library() -> list[dict]:
    return [{**e, "project_dir": resolve_path(e.get("project_dir", ""))}
            for e in _load_json(LIBRARY_FILE, [])]


def save_library(entries: list[dict]) -> None:
    _save_json(LIBRARY_FILE, [{**e,
                               "project_dir": portable_path(e.get("project_dir", ""))}
                              for e in entries])


def load_layouts() -> dict[str, list[dict]]:
    return _load_json(LAYOUTS_FILE, {})


def save_layouts(layouts: dict[str, list[dict]]) -> None:
    _save_json(LAYOUTS_FILE, layouts)


def load_prefs() -> dict:
    return _load_json(PREFS_FILE, {})


def save_prefs(prefs: dict) -> None:
    _save_json(PREFS_FILE, prefs)


def push_recent(dirs: list, d: str, limit: int = 8) -> list:
    """`d` at the front, no duplicates, oldest dropped past `limit`."""
    return [d] + [x for x in dirs if x != d][:limit - 1]


# Paths inside the repo (demo_module/, apps/) are stored with this marker instead
# of an absolute path, so moving the checkout — or running the same config on
# Windows — doesn't break every entry. Paths outside the repo stay absolute.
BASE_MARK = "<base>/"


def portable_path(p: str) -> str:
    """Absolute path -> '<base>/rel' when it lives inside the repo."""
    try:
        return BASE_MARK + Path(p).resolve().relative_to(BASE_DIR).as_posix()
    except (ValueError, OSError):
        return p            # outside the repo (or unresolvable): leave as-is


def resolve_path(p: str) -> str:
    """'<base>/rel' -> absolute path for this checkout. Absolute paths pass through."""
    if not p.startswith(BASE_MARK):
        return p
    return _moved_demo(str(BASE_DIR / p[len(BASE_MARK):]))


def _moved_demo(path: str) -> str:
    """Point a pre-2026-10 demo path at the folder's new home.

    Demos moved from demo_module/<name> to demo_module/<Linux|Windows>/<name>,
    and every saved module, library entry and layout still names the old spot.
    Only a path that no longer exists *directly* under demo_module is touched;
    the next save then stores the new location.
    """
    old = Path(path)
    if old.exists() or old.parent != DEMO_DIR or not DEMO_DIR.is_dir():
        return path
    for group in sorted(DEMO_DIR.iterdir()):
        if (group / old.name).is_dir():
            return str(group / old.name)
    return path


def _config_from_dict(d: dict) -> ModuleConfig:
    """Build a ModuleConfig, ignoring unknown keys (forward/backward compat)."""
    fields = ModuleConfig.__dataclass_fields__
    cfg = ModuleConfig(**{k: v for k, v in d.items() if k in fields})
    cfg.project_dir = resolve_path(cfg.project_dir)
    return cfg


def load_configs() -> list[ModuleConfig]:
    """Load module configs with graceful fallback."""
    if not CONFIG_FILE.is_file():
        return []
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8", errors="replace"))
        return [_config_from_dict(m) for m in data]
    except json.JSONDecodeError as e:
        logger.error(f"Corrupted modules.json: {e}, starting fresh")
        return []
    except Exception as e:
        logger.error(f"Error loading configs: {e}")
        return []


def save_configs(configs: list[ModuleConfig]) -> None:
    """Save module configs atomically."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        out = []
        for c in configs:
            d = asdict(c)
            d["project_dir"] = portable_path(d["project_dir"])
            out.append(d)
        atomic_write(CONFIG_FILE, json.dumps(out, indent=2))
    except Exception as e:
        logger.error(f"Failed to save configs: {e}")


# ---------------------------------------------------------------------------
# Module tab
# ---------------------------------------------------------------------------
def compose_args(program: str, args: list, startup_args: list) -> list:
    """Append a module's startup args, inserting `--` for npm.

    `npm start --no-sandbox` silently swallows the flag: npm treats unknown
    options as its own. `npm start -- --no-sandbox` forwards everything after
    the separator to the script being run. Every other program takes the args
    as-is.
    """
    extra = [str(a) for a in (startup_args or [])]
    out = list(args)
    if not extra:
        return out
    if Path(str(program)).name.split(".")[0] == "npm" and "--" not in out:
        out.append("--")
    return out + extra


def docker_hint(text: str) -> str | None:
    """A failed docker build, said plainly. Docker Desktop needn't start at
    sign-in, and it runs Linux *or* Windows containers, never both: an image
    of the other kind fails talking about manifests, or (BuildKit pulling a
    Windows image anyway) a missing ContainerUser."""
    if re.search(r"failed to connect to the docker API|"
                 r"Cannot connect to the Docker daemon", text):
        return ("Docker's engine isn't running. Start Docker Desktop (Linux: "
                "sudo systemctl start docker), wait until it's up, then Restart.")
    if re.search(r"permission denied while trying to connect to the docker",
                 text, re.I):
        return ("Docker refused the connection: your account isn't in its "
                "group (Linux: sudo usermod -aG docker $USER; Windows: "
                "docker-users). Sign out and back in, then Restart.")
    if "unable to find user ContainerUser" in text or \
            "no matching manifest for linux" in text:
        if not IS_WINDOWS:
            return ("This is a Windows container image. Docker on Linux runs "
                    "Linux containers only — it needs Docker Desktop on "
                    "Windows, in Windows-containers mode.")
        return ("This is a Windows image and Docker is running Linux "
                "containers: Docker Desktop's tray icon ▸ Switch to Windows "
                "containers…, then Restart.")
    if "no matching manifest for windows" in text or \
            'image operating system "linux" cannot be used' in text:
        return ("This is a Linux image and Docker is running Windows "
                "containers: Docker Desktop's tray icon ▸ Switch to Linux "
                "containers…, then Restart.")
    return None


def chrome_sandbox_hint(text: str) -> str | None:
    """Turn Chromium's cryptic SUID-sandbox abort into instructions.

    npm-installed Electron ships `chrome-sandbox` owned by the user and mode
    0755. That only breaks on distros that block unprivileged user namespaces
    (Ubuntu: kernel.apparmor_restrict_unprivileged_userns=1) — Chromium can't
    build a namespace sandbox, falls back to the SUID helper, finds it not
    root-owned, and aborts before any app code runs. That abort is Linux-only.

    Windows has its own: sandboxed Chromium processes run as app containers,
    which may only read a folder that grants the ALL APPLICATION PACKAGES
    groups. An installed Chrome/Edge has that; a portable Chromium (or an
    Electron app) unzipped elsewhere often doesn't, and the page never loads.
    """
    m = re.search(r"Sandbox cannot access executable (.+)\\[^\\]+\. Check", text)
    if m:
        folder = m.group(1).strip()
        return ("Chromium's sandbox can't read its own program folder:\n"
                f"    {folder}\n"
                "Windows runs the sandboxed browser processes as app "
                "containers, and this folder doesn't let them in (an installed "
                "Chrome or Edge does; a portable copy often doesn't), so pages "
                "stay blank. Fix it once, sandbox stays on — from any "
                "terminal, then Restart:\n"
                f'    icacls "{folder}" /grant "*S-1-15-2-1:(OI)(CI)(RX)" '
                '/grant "*S-1-15-2-2:(OI)(CI)(RX)"')
    if "failed to execvp" in text and "zygote_host_impl_linux" in text:
        # Second act of the same story: once the SUID helper IS configured,
        # it re-execs the browser by splitting a command line on whitespace,
        # so a project path containing a space dies as a truncated execvp.
        # The namespace sandbox has no such bug — this is SUID-path only.
        return ("This Electron app died launching its sandbox zygote. "
                "Chromium's SUID sandbox splits its command line on spaces, "
                "and this project's path contains one, so it tried to exec a "
                "truncated path. Either add --no-sandbox to the tab's startup "
                "args (fine for an app that loads local content), or move the "
                "project to a path with no spaces to keep the sandbox on.")
    if "SUID sandbox helper binary was found" not in text:
        return None
    # Match the whole path out of Chromium's sentence: a `\\S+` stops at the
    # first space and hands back a truncated command that silently fails.
    m = re.search(r"make sure that (.+?) is owned by root", text, re.S)
    path = m.group(1).strip() if m \
        else "<app>/node_modules/electron/dist/chrome-sandbox"
    if " " in path:
        # The SUID helper re-execs by splitting its command line on spaces, so
        # chown/chmod here just trades this abort for the execvp one.
        return ("This Electron app aborted because its Chromium sandbox helper "
                "isn't set up — and making it SUID root won't help, because "
                "the helper then re-execs by splitting its command line on "
                "spaces and this project's path contains one:\n"
                f"    {path}\n"
                "Add --no-sandbox to the tab's startup args (right-click the "
                "tab ▸ Startup args…) — fine for an app that loads local "
                "content — or move the project to a path with no spaces.")
    return ("This Electron app aborted because its Chromium sandbox helper "
            "isn't set up. Your kernel blocks unprivileged user namespaces, so "
            "Chromium needs the SUID helper instead. Fix it once (keeps the "
            "sandbox ON, redo after any npm install that reinstalls electron):\n"
            f"    sudo chown root:root '{path}'\n"
            f"    sudo chmod 4755 '{path}'\n"
            "Or, to skip the sandbox entirely for this module (only sensible "
            "for an app that loads local content), add --no-sandbox via "
            "right-click the tab ▸ Startup args…")


def visible_pane_count(independent: list[bool], current: int) -> int:
    """How many module panes _refresh_view will put on screen.

    An independent module takes the whole window alone; otherwise every
    merge-mode module is shown side by side. Used to skip the click
    highlight when there is only one pane — nothing to locate.
    """
    if not (0 <= current < len(independent)):
        return 0
    if independent[current]:
        return 1
    return sum(1 for f in independent if not f)


class ModuleTab(QWidget):
    state_changed = pyqtSignal()
    config_changed = pyqtSignal()   # cfg edited in-tab; window persists it
    pane_clicked = pyqtSignal()     # user clicked inside the embedded module

    def __init__(self, cfg: ModuleConfig, parent=None):
        super().__init__(parent)
        _LIVE_TABS.add(self)
        self.cfg = cfg
        self.setup_proc: QProcess | None = None
        self._cancel_setup = False                  # Stop pressed mid-setup
        self.app_proc: QProcess | None = None       # primary process
        self.browser_proc: QProcess | None = None   # web runtime: the browser
        self._web_profile: str | None = None    # its temp profile dir
        self._warned_sandbox = False   # nag once per tab, not per line
        self._stopping = False         # we asked for the exit; not a crash
        self.embed_proc: QProcess | None = None      # whose window we embed
        self.foreign_win: QWindow | None = None
        self.container: QWidget | None = None
        self.embed_timer = QTimer(self)
        self.embed_timer.setInterval(250)
        self.embed_timer.timeout.connect(self._try_embed)
        self._embed_attempts = 0
        self._max_embed_attempts = 160   # ~40 s at 250 ms
        self._vanished = 0               # windows that went away mid-embed
        self._reembed_rounds = 0
        self._max_reembed_rounds = 8
        self._win_baseline: set[int] = set()
        self._own_pid = os.getpid()
        self._await_url = False          # web: watching stdout for a URL
        self._browser_launched = False
        self._url_tail = ""              # rolling stdout buffer for URL match
        self._pending_install = None     # toolchain install cmd, if offered
        self._install_purpose = None     # "toolchain" | "xterm" — drives done handler
        self._install_proc: QProcess | None = None
        self._term_proc: QProcess | None = None   # mini command-bar process
        self.terminal: "TerminalHost | None" = None  # full xterm, lazy
        self._highlight = False      # border drawn while this tab is picked
        self._docker_name = None     # container name, while one is running
        self._claimed_wid = None     # window this tab took, so peers skip it
        # The header bar needs ~430px; a tiled pane can be dragged to 160.
        # _btn_wanted remembers which buttons the tab *would* show at full
        # width, so collapsing and re-expanding doesn't resurrect Install.
        self._btn_wanted: dict = {}
        self._labels: dict = {}       # whole labels of buttons showing a glyph
        self._compact = None
        self.sampler = None           # set by UnifiedBase._add_tab
        self.meter_on = bool(cfg.show_meter)
        self.log_window = None        # LogWindow while the log is undocked
        self._wsl_pid = None          # Linux pid of a WSL-bridged app
        self._wine_tag = None         # "UB_LAUNCH=..." of a Wine launch
        self._doomed = None           # the app_proc stop() is stopping
        self._logmode_acts: list = []
        self._logfile = None          # lazily opened; see _log_to_disk
        self._logfile_failed = False
        self._build_ui()
        self._apply_compact()
        self._set_status("idle")

    def set_highlight(self, on: bool):
        """Outline this pane so the clicked tab's module is easy to spot."""
        if self._highlight != on:
            self._highlight = on
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._highlight:
            return
        # The 4px layout margin is empty, so the border never covers the
        # embedded child window. Same two tones as this module's tab chip,
        # corner to corner, so tab and pane read as the same thing.
        c1, c2 = border_colors(self.cfg.runtime)
        grad = QLinearGradient(0, 0, float(self.width()), float(self.height()))
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        p = QPainter(self)
        p.setPen(QPen(QBrush(grad), 3))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()

    # -- UI -----------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        self.header = QWidget()
        bar = QHBoxLayout(self.header)
        bar.setContentsMargins(0, 0, 0, 0)
        # Module name at upper-left of the tab, colored by run state
        # (green=running, red=error, grey=idle). Sits left of Status.
        self.name_label = QLabel()
        self.name_label.setToolTip("Module name — green running, red error")
        self.status_label = QLabel()
        self.meter = ResourceMeter(border_colors(self.cfg.runtime))
        self.btn_start = QPushButton("▶ Start")
        self.btn_stop = QPushButton("■ Stop")
        self.btn_restart = QPushButton("↻ Restart")
        self.btn_env = QPushButton("Rebuild Env")
        self.btn_embed = QPushButton("⊞ Embed")
        self.btn_embed.setToolTip("Retry pulling the module's window "
                                  "into this tab")
        # Shown only when this runtime's toolchain is missing (see _offer_install).
        self.btn_install = QPushButton("⤓ Install")
        self._btn_wanted[self.btn_install] = False
        self.btn_install.setToolTip("Install the missing toolchain via a "
                                    "graphical password prompt (pkexec)")
        # Shown only after Chromium's sandbox abort (see _handle_stdout).
        self.btn_nosandbox = QPushButton("⚑ Retry without sandbox")
        self._btn_wanted[self.btn_nosandbox] = False
        self.btn_nosandbox.setToolTip("Add --no-sandbox to this module's "
                                      "startup args and start it again")
        self.chk_logs = QCheckBox("Logs")
        self.btn_logmode = QToolButton()
        self.btn_logmode.setText("▾")
        self.btn_logmode.setToolTip("Where the log shows: in the pane, docked "
                                    "beside the module, or its own window")
        self.btn_logmode.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_logmode.setMenu(self._build_logmode_menu(self, track=True))
        # Stands in for the whole button row once the pane is too narrow for it.
        self.btn_more = QToolButton()
        self.btn_more.setText("☰")
        self.btn_more.setToolTip("Module actions")
        self.btn_more.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_more = QMenu(self)
        self.menu_more.aboutToShow.connect(self._fill_more_menu)
        self.btn_more.setMenu(self.menu_more)
        self.btn_more.hide()
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_restart.clicked.connect(self.restart)
        self.btn_env.clicked.connect(self.rebuild_env)
        self.btn_embed.clicked.connect(self.retry_embed)
        self.btn_install.clicked.connect(self._do_install)
        self.btn_nosandbox.clicked.connect(self._use_no_sandbox)
        self.chk_logs.toggled.connect(self._toggle_logs)
        bar.addWidget(self.name_label)
        bar.addWidget(self.status_label)
        bar.addWidget(self.meter)
        bar.addStretch(1)
        self._bar_buttons = (self.btn_start, self.btn_stop, self.btn_restart,
                             self.btn_env, self.btn_embed, self.btn_install,
                             self.btn_nosandbox)
        self._tips = {b: b.toolTip() for b in self._bar_buttons}
        for b in self._bar_buttons:
            bar.addWidget(b)
        bar.addWidget(self.chk_logs)
        bar.addWidget(self.btn_logmode)
        bar.addWidget(self.btn_more)
        root.addWidget(self.header)
        # Their own width when there's room, clipped (down to 1px) when not.
        # Ignored did the clipping too, but an Ignored label beside a
        # stretch is given nothing at all: Status never showed.
        for lab in (self.name_label, self.status_label):
            lab.setMinimumWidth(1)

        self.stack = QStackedWidget()
        self.panel = QWidget()
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(0, 0, 0, 0)
        self.info_label = QLabel(
            f"<b>{self.cfg.name}</b> — {self.cfg.project_dir} "
            f"({self.cfg.runtime}"
            f"{', entry: ' + self.cfg.entry if self.cfg.entry else ''})")
        self.info_label.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        pv.addWidget(self.info_label)
        # Log and the optional full terminal share a resizable vertical split.
        self.io_split = QSplitter(Qt.Orientation.Vertical)
        self.io_split.addWidget(self.log)
        pv.addWidget(self.io_split, 1)
        # Command bar. Left: one-shot commands in the module's source folder
        # (quick dep installs the auto-detector missed) — pipes/&&/env work,
        # but no PTY so TUIs don't. Right: "Terminal" toggles a real embedded
        # xterm in that same folder for anything interactive (vim/htop/ssh).
        self.cmd_row = QWidget()      # one widget, so it hides as a unit
        term = QHBoxLayout(self.cmd_row)
        term.setContentsMargins(0, 0, 0, 0)
        self.cmd_input = QLineEdit()
        self.cmd_input.setClearButtonEnabled(True)
        self.cmd_input.setPlaceholderText(
            f"run in {self.cfg.project_dir}  —  e.g. pip install rich, npm i, gem install …")
        self.cmd_input.returnPressed.connect(self._run_shell_cmd)
        btn_run = QPushButton("Run")
        btn_run.clicked.connect(self._run_shell_cmd)
        self.chk_term = QCheckBox("⌨ Terminal")
        self.chk_term.setToolTip("Full interactive terminal (xterm) in this "
                                 "folder — vim, htop, ssh, prompts all work")
        self.chk_term.toggled.connect(self._toggle_terminal)
        self.chk_term.setVisible(TERMINAL_OK)
        term.addWidget(self.cmd_input, 1)
        term.addWidget(btn_run)
        term.addWidget(self.chk_term)
        pv.addWidget(self.cmd_row)
        self.embed_page = QWidget()
        self.embed_layout = QVBoxLayout(self.embed_page)
        self.embed_layout.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.panel)
        self.stack.addWidget(self.embed_page)
        # A docked log sits beside the module instead of replacing it, so the
        # stack shares a splitter with a dock the log widget is moved into.
        self.body = QSplitter(Qt.Orientation.Horizontal)
        self.body.setChildrenCollapsible(False)
        self.body.addWidget(self.stack)
        self.log_dock = QWidget()
        dv = QVBoxLayout(self.log_dock)
        dv.setContentsMargins(0, 0, 0, 0)
        self.log_dock.hide()
        self.body.addWidget(self.log_dock)
        self.body.setStretchFactor(0, 3)
        self.body.setStretchFactor(1, 2)
        root.addWidget(self.body, 1)
        # These three rows must not set the pane's minimum width, or
        # _apply_compact can never fire: resize() is clamped to the layout
        # minimum, so a 640px button row pins width() at 640 forever and the
        # tier never changes. Ignored = "give me what's left"; the rows the
        # width can't hold are hidden by _apply_compact, not squeezed.
        for w in (self.header, self.cmd_row, self.info_label):
            w.setSizePolicy(QSizePolicy.Policy.Ignored,
                            w.sizePolicy().verticalPolicy())

    def _set_status(self, text: str):
        self.status = text
        via = {"wine": " · Wine", "wsl": " · WSL"}.get(self.bridge, "")
        self.status_label.setText(f"Status: <b>{text}</b>{via}")
        low = text.lower()
        if any(k in low for k in ("error", "failed", "crash", "missing")):
            color = "#E05555"   # red
        elif "running" in low or "embedded" in low:
            color = "#3FB950"   # green
        else:
            color = "#9AA0A6"   # grey (idle/stopped/starting/waiting/stopping)
        self.name_label.setText(f"<b>{self.cfg.name}</b>")
        self.name_label.setStyleSheet(f"color: {color};")
        # In a narrow pane the name is clipped and Status is hidden entirely,
        # so the tooltip is the only place both still read in full.
        self.name_label.setToolTip(f"{self.cfg.name} — {text}")
        running = self.app_proc is not None and \
            self.app_proc.state() != QProcess.ProcessState.NotRunning
        busy = self.setup_proc is not None and \
            self.setup_proc.state() != QProcess.ProcessState.NotRunning \
            or self._wsl_queued()
        self.btn_start.setEnabled(not running and not busy)
        self.btn_stop.setEnabled(running or busy)    # busy: cancels the setup
        self.btn_restart.setEnabled(running)
        self.btn_env.setEnabled(not running and not busy)
        self.btn_embed.setEnabled(EMBEDDING_OK and running
                                  and self.container is None)
        self._sync_meter()
        # Update tab title with running indicator
        self.state_changed.emit()

    def _log(self, text: str):
        self.log.appendPlainText(text.rstrip("\n"))
        self._log_to_disk(text)

    def _log_to_disk(self, text: str):
        """Tee the pane's log to LOG_DIR. The widget keeps 5000 blocks and dies
        with the tab, which is no use for a module that failed 20 minutes ago."""
        fh = self._logfile
        if fh is None:
            if self._logfile_failed:
                return
            try:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                # env_dir.name is the <slug>-<hash8> of the project path, so two
                # modules with the same name never share a file.
                path = LOG_DIR / f"{self.cfg.env_dir.name}.log"
                if path.is_file() and path.stat().st_size > 2_000_000:
                    path.unlink()       # ponytail: truncate, not rotate
                fh = self._logfile = open(path, "a", encoding="utf-8",
                                          errors="replace", buffering=1)
            except OSError as e:
                self._logfile_failed = True
                logger.debug(f"Log file unavailable: {e}")
                return
            # Straight to the widget: _log would recurse back into here.
            self.log.appendPlainText(f"[log file: {path}]")
        try:
            fh.write(text.rstrip("\n") + "\n")
        except OSError as e:
            logger.debug(f"Log write failed: {e}")

    # -- narrow-pane header ---------------------------------------------------
    def _show_btn(self, b: QPushButton, on: bool):
        """Set whether a header button is wanted, and show it if there's room."""
        self._btn_wanted[b] = on
        self._apply_compact(force=True)

    def _header_widths(self):
        """(full, short, wanted, glyphs): the pane width the whole header
        needs, the width its glyph-only form needs, the buttons it shows and
        their glyphs. Depends on style and font — Ubuntu Sans 11pt needs
        ~790px, Windows 11's 81px-minimum buttons more."""
        wanted = [b for b in self._bar_buttons if self._btn_wanted.get(b, True)]
        glyphs = {b: g for b in wanted if (g := self._glyph(b))}
        gap = self.header.layout().spacing()
        m = self.layout().contentsMargins()
        # ponytail: a flat 160 for name + status; the status text changes
        # with every state, and the row must not reflow each time it does.
        base = 160 + 3 * gap + m.left() + m.right() + \
            (self.meter.minimumWidth() + gap if self.meter_on else 0)
        full = base + sum(self._full_width(x) + gap for x in
                          (*wanted, self.chk_logs, self.btn_logmode))
        short = base + self.btn_more.sizeHint().width() + \
            sum(self._glyph_width(b, g) + gap for b, g in glyphs.items())
        return full, short, wanted, glyphs

    def _apply_compact(self, force: bool = False):
        """Fold the header down as the pane narrows: whole buttons, then
        their glyphs alone (▶ ■ ↻ ⊞), then nothing but the ☰ menu.

        Tiling drags a pane to PANE_MIN_W (160px) but the full header needs
        ~640, so without this the buttons survive as unreadable 13px slivers.
        Widths come from the buttons themselves: a fixed threshold fit one
        style only, and Windows 11's 81px-minimum buttons were cut off.
        """
        full, short, wanted, glyphs = self._header_widths()
        w = self.width()
        tier = 0 if w >= full else 1 if w >= max(short, 300) else 2
        if tier == self._compact and not force:
            return
        self._compact = tier
        for b in self._bar_buttons:
            g = glyphs.get(b) if tier == 1 else None
            if g:
                self._labels.setdefault(b, b.text())
                b.setText(g)
                b.setToolTip(self._labels[b])
                b.setFixedWidth(self._glyph_width(b, g))
            elif b in self._labels:
                b.setText(self._labels.pop(b))
                b.setToolTip(self._tips[b])
                b.setMinimumWidth(0)
                b.setMaximumWidth(QWIDGETSIZE_MAX)
            b.setVisible(b in wanted and (tier == 0 or bool(g)))
        self.chk_logs.setVisible(tier == 0)
        self.btn_logmode.setVisible(tier == 0)
        self.meter.setVisible(self.meter_on and tier != 2)
        self.btn_more.setVisible(tier > 0)
        narrow = w < 300
        self.status_label.setVisible(not narrow)
        self.info_label.setVisible(not narrow)
        self.cmd_row.setVisible(not narrow)

    def _label(self, b) -> str:
        """A header button's whole label, even while it shows a glyph."""
        return self._labels.get(b, b.text())

    def _glyph(self, b) -> str:
        """"▶" for "▶ Start"; "" for a label that has none ("Rebuild Env")."""
        first = self._label(b).split(" ", 1)[0]
        return first if first and not first[0].isalnum() else ""

    def _full_width(self, b) -> int:
        """Width `b` wants with its whole label — measured with that label
        put back for a moment, since the style decides (81px minimum on
        Windows 11) and sizeHint only knows the text showing now."""
        lab = self._labels.get(b)
        if lab is None:
            return b.sizeHint().width()
        g = b.text()
        b.setText(lab)
        w = b.sizeHint().width()
        b.setText(g)
        return w

    @staticmethod
    def _glyph_width(b, g: str) -> int:
        fm = b.fontMetrics()
        return fm.horizontalAdvance(g) + fm.height()

    def _fill_more_menu(self):
        """Rebuilt on every open so it mirrors the buttons' current state."""
        m = self.menu_more
        m.clear()
        for b in self._bar_buttons:
            if not self._btn_wanted.get(b, True):
                continue
            a = m.addAction(self._label(b))
            a.setEnabled(b.isEnabled())
            a.triggered.connect(lambda _=False, btn=b: btn.click())
        m.addSeparator()
        m.addMenu(self._build_logmode_menu(m))
        for chk in (self.chk_logs, self.chk_term):
            if chk is self.chk_term and not TERMINAL_OK:
                continue
            a = m.addAction(chk.text())
            a.setCheckable(True)
            a.setChecked(chk.isChecked())
            a.toggled.connect(chk.setChecked)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_compact()

    def _toggle_logs(self, _show: bool):
        self._apply_log_mode()

    # -- where the log lives --------------------------------------------------
    def _build_logmode_menu(self, parent, track: bool = False) -> QMenu:
        """The same three choices wherever they are offered — the ▾ button, the
        ☰ menu and the tab's context menu. Only the ▾ menu outlives the click,
        so only its actions are tracked for later re-checking."""
        m = QMenu("Log view", parent)
        grp = QActionGroup(m)
        grp.setExclusive(True)
        for mode, label in (("embedded", "In the pane"),
                            ("docked", "Docked beside the module"),
                            ("undocked", "Separate window")):
            act = m.addAction(label)
            act.setCheckable(True)
            act.setData(mode)
            act.setChecked(self.cfg.log_mode == mode)
            act.triggered.connect(
                lambda _c=False, md=mode: self._set_log_mode(md))
            grp.addAction(act)
            if track:
                self._logmode_acts.append(act)
        return m

    def _set_log_mode(self, mode: str):
        """Pick where the log shows. Choosing a mode also switches it on: the
        checkbox is the switch, the mode is only what it switches to."""
        if mode not in ("embedded", "docked", "undocked"):
            return
        self.cfg.log_mode = mode
        for act in self._logmode_acts:
            act.setChecked(act.data() == mode)
        self.config_changed.emit()
        if self.chk_logs.isChecked():
            self._apply_log_mode()
        else:
            self.chk_logs.setChecked(True)     # fires _apply_log_mode

    def _ensure_log_window(self):
        if self.log_window is None:
            win = LogWindow(self.cfg.name, border_colors(self.cfg.runtime))
            win.redock.connect(lambda: self._set_log_mode("docked"))
            win.closed.connect(self._log_window_closed)
            self.log_window = win
        if self.log.parent() is not self.log_window.host:
            self.log_window.host.layout().addWidget(self.log)
            self.log.show()
        self.log_window.show()
        self.log_window.raise_()

    def _log_window_closed(self):
        """Its own ✕ means the same thing as clearing the Logs checkbox."""
        if self.chk_logs.isChecked():
            self.chk_logs.setChecked(False)    # fires _apply_log_mode
        else:
            self._close_log_window()

    def _close_log_window(self):
        win, self.log_window = self.log_window, None
        if win is None:
            return
        # Rescue the log widget first — it is a child of that window, so
        # destroying the window without this takes the log with it.
        self.io_split.insertWidget(0, self.log)
        try:
            win.closed.disconnect()
        except TypeError:
            pass
        win.hide()
        win.deleteLater()

    def _apply_log_mode(self):
        """The one place that decides where self.log lives and what the pane
        shows.

        off             log back in the panel, module page if there is one
        on + embedded   log takes over the pane (the original behaviour)
        on + docked     log beside the module, splitter handle between them
        on + undocked   log in its own window, module keeps the pane
        """
        on = self.chk_logs.isChecked()
        mode = self.cfg.log_mode if on else "embedded"
        if mode == "undocked":
            self._ensure_log_window()
        else:
            self._close_log_window()
            target = self.log_dock if mode == "docked" else self.io_split
            if self.log.parent() is not target:
                if mode == "docked":
                    self.log_dock.layout().addWidget(self.log)
                else:
                    self.io_split.insertWidget(0, self.log)
                self.log.show()
        docked = on and mode == "docked"
        self.log_dock.setVisible(docked)
        # Sizes must be set after the show: a splitter ignores setSizes for a
        # child that is still hidden, which left the dock at zero width.
        if docked and self.body.sizes()[1] < 40:
            span = max(self.width(), 400)
            self.body.setSizes([span * 3 // 5, span * 2 // 5])
        show_panel = self.container is None or (on and mode == "embedded")
        self.stack.setCurrentWidget(self.panel if show_panel
                                    else self.embed_page)

    # -- resource meter -------------------------------------------------------
    def _meter_pids(self) -> list:
        """Roots of this module's process tree — the app, plus the browser a
        web module drives. Docker modules run in a container, so their work
        does not show up here."""
        pids = [proc.processId() for proc in (self.app_proc, self.browser_proc)
                if proc is not None
                and proc.state() != QProcess.ProcessState.NotRunning]
        return pids + sorted(self._wine_family() - set(pids)) if pids else pids

    def _sync_meter(self):
        """Tell the shared sampler which processes this pane owns. Called from
        _set_status, which every state change already goes through."""
        if self.sampler is None:
            return
        pids = self._meter_pids() if self.meter_on else []
        self.sampler.set_roots(id(self), pids)
        if not pids:
            self.meter.clear()

    def set_meter_enabled(self, master: bool):
        """Master switch (View menu) AND this module's own setting."""
        self.meter_on = bool(master and self.cfg.show_meter)
        self._apply_compact(force=True)
        self._sync_meter()

    # -- toolchain install + mini terminal ----------------------------------
    def _offer_install(self, cmd: str | None = None):
        """Reveal the one-click Install button when we can drive a GUI installer
        (pkexec on Linux). Elsewhere the logged install command is the guidance.

        `cmd` names the missing program; it defaults to this runtime's own
        toolchain, but a setup step can pass its own (e.g. 'bundle').
        """
        cmd = cmd or TOOLCHAIN_CMD.get(self.cfg.runtime)
        install = toolchain_install_cmd(cmd) if cmd else None
        if install and can_gui_install():
            self._pending_install = install
            self._install_purpose = "toolchain"
            self.btn_install.setText(f"⤓ Install {cmd}")
            self._show_btn(self.btn_install, True)
        else:
            self._pending_install = None
            self._show_btn(self.btn_install, False)

    def _do_install(self):
        if not self._pending_install:
            return
        if self._install_proc is not None and \
                self._install_proc.state() != QProcess.ProcessState.NotRunning:
            self._log("Install already running — finish the password prompt.")
            return
        # Linux: strip the leading "sudo " — pkexec supplies privilege via a
        # graphical prompt (a QProcess has no TTY for sudo to read a password
        # from). Windows: winget raises its own UAC prompt per installer.
        cmd = self._pending_install
        cmd = cmd[5:] if cmd.startswith("sudo ") else cmd
        prog, args = gui_install_command(cmd)
        self.btn_install.setEnabled(False)
        self._set_status("installing toolchain")
        self._log(f"$ {prog} {' '.join(args)}")
        # Parent to the QApplication, NOT this tab: closing the tab (or quitting)
        # destroys tab-owned QProcesses, and ~QProcess kill()s + blocks on a
        # still-running child. This child is root pkexec — kill() fails EPERM and
        # waitForFinished() would freeze the GUI ~30s, and where it IS signalable
        # it's the mid-transaction apt/dnf kill the shutdown() skip warns against.
        p = QProcess(QApplication.instance())
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        p.readyReadStandardOutput.connect(
            lambda: self._log(proc_text(p.readAllStandardOutput())))
        p.finished.connect(self._on_install_done)
        p.errorOccurred.connect(
            lambda e: self._log(f"Install error: {e} "
                                + ("(is winget available?)" if IS_WINDOWS
                                   else "(is pkexec/polkit available?)")))
        self._install_proc = p
        start_qprocess(p, prog, args)

    def _on_install_done(self, code, _status):
        self.btn_install.setEnabled(True)
        if IS_WINDOWS:
            # The installer changed PATH in the registry; this process would
            # never see it, and the toolchain would still read as missing.
            added = winplat.refresh_path()
            if added:
                self._log("PATH picked up: " + "; ".join(added))
        if code == 0:
            self._show_btn(self.btn_install, False)
            self._pending_install = None
            purpose, self._install_purpose = self._install_purpose, None
            if purpose == "xterm":
                # User wanted the terminal, not the app — re-check the box to open
                # it now that xterm exists (triggers _toggle_terminal(True)).
                self._log("xterm installed. Opening terminal…")
                self.chk_term.setChecked(True)
            else:
                self._log("Toolchain installed. Starting…")
                self.start()
        else:
            # pkexec exits 126 when the user dismisses the password dialog.
            self._log(f"Install did not complete (exit {code}). Run it "
                      f"manually if needed:\n    {self._pending_install}")
            self._set_status("missing toolchain")

    def _use_no_sandbox(self):
        """One click for the fix the sandbox hint spells out.

        Typing --no-sandbox into the Startup args dialog is the same decision,
        just slower. The button only appears once Chromium has actually
        aborted for that reason, so this never silently drops the sandbox.
        """
        if "--no-sandbox" not in self.cfg.startup_args:
            self.cfg.startup_args = list(self.cfg.startup_args) + \
                ["--no-sandbox"]
            self.config_changed.emit()
        self._show_btn(self.btn_nosandbox, False)
        self._log("Startup args: " + " ".join(self.cfg.startup_args)
                  + " — starting again.")
        if self.app_proc is not None and \
                self.app_proc.state() != QProcess.ProcessState.NotRunning:
            self.restart()
        else:
            # restart() would wait on a `finished` that already fired.
            self.start()

    def _run_shell_cmd(self):
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return
        if self._term_proc is not None and \
                self._term_proc.state() != QProcess.ProcessState.NotRunning:
            self._log("A command is still running in this tab — wait for it.")
            return
        self.cmd_input.clear()
        self._log(f"$ {cmd}")
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        p.setWorkingDirectory(str(self.cfg.project_dir))
        p.readyReadStandardOutput.connect(
            lambda: self._log(proc_text(p.readAllStandardOutput())))
        p.finished.connect(lambda code, _s: self._log(f"[exit {code}]"))
        p.errorOccurred.connect(lambda e: self._log(f"Command error: {e}"))
        if self._term_proc is not None:
            self._term_proc.deleteLater()   # don't accumulate finished QProcesses
        self._term_proc = p
        # Run through a shell so pipes, globs, &&, and env expansion work.
        prog, args, run_env = self._wrap(*shell_command(cmd),
                                         str(self.cfg.project_dir),
                                         self._venv_env())
        if run_env:
            qenv = QProcessEnvironment.systemEnvironment()
            for k, v in run_env.items():
                qenv.insert(k, str(v))
            p.setProcessEnvironment(qenv)
        start_qprocess(p, prog, args)

    def _venv_env(self) -> dict:
        """The module's venv first on PATH, so the command bar's `pip install
        rich` lands where the module runs — not in the system Python, which
        Debian/Ubuntu refuse (externally managed). Native Python modules only:
        a bridged one's interpreter lives in Wine or the WSL distro."""
        if self.cfg.runtime != "python" or self.bridge != "native":
            return {}
        own = project_venv_python(Path(self.cfg.project_dir))
        py = own if own is not None and not self.cfg.use_shared \
            else self._env_paths()[1]
        if not py.is_file():
            return {}
        return {"VIRTUAL_ENV": str(py.parent.parent),
                "PATH": str(py.parent) + os.pathsep + os.environ.get("PATH", "")}

    def _toggle_terminal(self, on: bool):
        if not on:
            if self.terminal is not None:
                self.terminal.setVisible(False)
            return
        if not IS_WINDOWS and not shutil.which("xterm"):
            hint = toolchain_install_cmd("xterm")
            self._log("Full terminal needs 'xterm'. Install it, then toggle "
                      f"again:\n    {hint or 'install xterm via your package manager'}")
            # Offer the same one-click pkexec install used for toolchains, but
            # tagged "xterm" so the done handler opens the terminal (not start()).
            if hint and can_gui_install():
                self._pending_install = hint
                self._install_purpose = "xterm"
                self.btn_install.setText("⤓ Install xterm")
                self._show_btn(self.btn_install, True)
            self.chk_term.setChecked(False)
            return
        if self.terminal is None:
            self.terminal = TerminalHost(str(self.cfg.project_dir),
                                         self.io_split, log=self._log)
            self.terminal.closed.connect(self._terminal_closed)
            self.io_split.addWidget(self.terminal)
            self.io_split.setSizes([180, 260])
        self.terminal.setVisible(True)

    def _terminal_closed(self):
        """`exit` in the terminal folds it away, instead of leaving a blank
        area behind; the toggle starts a fresh one."""
        t, self.terminal = self.terminal, None
        if t is not None:
            t.shutdown()
            t.deleteLater()
        self.chk_term.setChecked(False)

    # -- cross-OS bridge -------------------------------------------------------
    @property
    def bridge(self) -> str:
        """"native", "wine" or "wsl" — see bridge_for."""
        return bridge_for(self.cfg.platform)

    def _wrap(self, program, args, cwd, env: dict | None = None,
              launch: bool = False) -> tuple[str, list, dict]:
        """Route one command through this module's bridge.

        Returns (program, args, env-to-set). Under Wine only the launch is
        wrapped — builds run natively. Under WSL everything runs in the
        distro, and env is folded into the command, since Windows environment
        variables do not reach WSL.
        """
        args = [str(a) for a in args]
        env = dict(env or {})
        b = self.bridge
        if b == "wine":
            if launch:
                prog, wargs, wenv = wine_wrap(str(program), args, wine_prefix())
                return prog, wargs, {**wenv, **env}     # the module's own wins
            return str(program), args, {"WINEPREFIX": str(wine_prefix()), **env}
        if b == "wsl":
            if launch:
                env = {**wsl_display_env(), **env}      # the module's own wins
            if Path(str(program)).name.lower() == "wsl.exe":
                return str(program), args, {}           # already wrapped
            if _is_cmd_line(str(program), args):        # a shell line: bash
                exports = "".join(f"export {k}={shlex.quote(str(v))}; "
                                  for k, v in env.items())
                prog, wargs = wsl_shell(exports + args[3], cwd, args[4:],
                                        track_pid=launch)
                return prog, wargs, {}
            prog, wargs = wsl_wrap(program, args, cwd, env, track_pid=launch,
                                   setup=not launch)
            return prog, wargs, {}
        return str(program), args, env

    def _wine_family(self) -> set:
        """Every Windows process the current Wine launch started, wherever
        Wine put it (see wine_family). Empty for any other bridge."""
        return wine_family(self._wine_tag) if self._wine_tag else set()

    def _bridge_problem(self) -> str | None:
        """Why this module can't run here, or None."""
        b = self.bridge
        if b == "wine" and not wine_program():
            hint = toolchain_install_cmd("wine")
            return ("This is a Windows module; on Linux it runs through Wine, "
                    "which isn't installed." +
                    (f"\n    Install it with:  {hint}" if hint else ""))
        if b == "wsl" and not wsl_ready():
            return ("This is a Linux module; on Windows it runs inside WSL, "
                    "which isn't set up (no Linux distro installed). In an "
                    "administrator PowerShell run:"
                    "\n    wsl --install\nthen restart and Start again.")
        if b == "wine" and self.cfg.runtime == "docker":
            return ("This module builds Windows containers. Those run only on "
                    "Windows, in Docker Desktop's Windows-containers mode — "
                    "Docker on Linux runs Linux containers.")
        if b == "wine" and self.cfg.runtime in WINE_NEEDS_WINDOWS_TOOLCHAIN:
            lang = WINE_NEEDS_WINDOWS_TOOLCHAIN[self.cfg.runtime]
            return (f"This is a Windows-only {lang} program: it calls Windows "
                    "itself. Wine runs Windows .exe programs, but a "
                    f"{lang} one needs the Windows {lang} to run under it. Run "
                    "it on Windows — or right-click ▸ Runs on ▸ Anywhere to "
                    "try it here anyway.")
        return None

    def _prefix(self) -> Path:
        """This module's Wine prefix. Its own WINEPREFIX (Environment
        variables) wins, as it does at launch; checking only the shared prefix
        let a fresh private one get built mid-launch, and its "updating"
        window got embedded."""
        return Path((self.cfg.extra_env or {}).get("WINEPREFIX")
                    or wine_prefix())

    def _wine_toolchain(self) -> dict | None:
        """The Windows toolchain this module runs on under Wine, if any."""
        return WINE_TOOLCHAINS.get(self.cfg.runtime) \
            if self.bridge == "wine" else None

    def _wine_tool(self) -> Path | None:
        """That toolchain's program (python.exe, java.exe ...) in the prefix."""
        tc = self._wine_toolchain()
        return None if tc is None else \
            self._prefix() / "drive_c" / "ub" / tc["dir"] / tc["exe"]

    def _wine_tool_win(self) -> str:
        """The same program by its C: path, which is how Windows programs get
        it: run from its Z: path (under ~/.unified_base) Python's Tcl can't
        find init.tcl and Tk fails; from C:\\ub it starts."""
        tc = self._wine_toolchain()
        return "C:\\ub\\" + tc["dir"] + "\\" + tc["exe"].replace("/", "\\")

    def _toolchain_steps(self) -> list:
        """Fetch and install the Windows toolchain into the prefix, once."""
        tc = self._wine_toolchain()
        if tc is None:
            return []
        folder = self._prefix() / "drive_c" / "ub" / tc["dir"]
        cache = APP_DIR / "downloads"
        cache.mkdir(parents=True, exist_ok=True)
        wenv = {"WINEPREFIX": str(self._prefix()), "WINEDEBUG": "-all"}
        lock = str(cache / f"{tc['dir']}.lock")

        def once(marker, label, prog, args, *rest):
            return (label, sys.executable,
                    ["-c", WINE_ONCE, lock, str(marker), prog] + args,
                    str(cache), *rest)
        steps = []
        tool = self._wine_tool()
        if not tool.is_file():
            file = cache / unquote(tc["url"].rsplit("/", 1)[-1])
            steps.append(once(
                tool, f"downloading {tc['label']} ({tc['mb']} MB, first run)",
                sys.executable,
                ["-c", WINE_FETCH, tc["url"], str(file), tc["sha256"]]
                + ([] if tc.get("install") else [str(folder)])))
            if tc.get("install"):
                win_dir = "C:\\ub\\" + tc["dir"]
                steps.append(once(
                    tool, f"installing {tc['label']} into Wine",
                    wine_program() or "wine",
                    [wine_path(file)] + [a.replace("{dir}", win_dir)
                                         for a in tc["install"]], wenv))
        for x in tc.get("extras", ()):
            dll = folder / x["to"] / Path(x["member"]).name
            if dll.is_file():
                continue
            file = cache / unquote(x["url"].rsplit("/", 1)[-1])
            steps.append(once(
                dll, f"downloading {dll.name} for {tc['label']} ({x['mb']} MB)",
                sys.executable,
                ["-c", WINE_FETCH, x["url"], str(file), x["sha256"],
                 str(folder / x["to"]), x["member"]]))
        return steps

    def _bridge_steps(self) -> list:
        """Setup the bridge itself needs before the module's own steps."""
        prefix = self._prefix()
        if self.bridge == "wine" and not (prefix / "system.reg").is_file():
            # First use: build the prefix up front, headless, so its ~20 s and
            # Wine's own dialogs don't land inside the app's launch. mscoree/
            # mshtml off skips the Mono/Gecko download prompts — a .NET
            # Framework app then wants `winetricks dotnet48` in that prefix.
            prefix.mkdir(parents=True, exist_ok=True)
            return [("preparing Wine prefix (first run)", wine_program() or "wine",
                     ["wineboot", "--init"], str(self.cfg.project_dir),
                     {"WINEPREFIX": str(prefix), "WINEDEBUG": "-all",
                      "WINEDLLOVERRIDES": "mscoree,mshtml="})] + \
                self._toolchain_steps()
        if self.bridge == "wine":
            return self._toolchain_steps()
        mount = wsl_mount_args(str(self.cfg.project_dir)) \
            if self.bridge == "wsl" else None
        if mount:
            return [("making the project's drive visible to WSL", "wsl.exe",
                     mount, str(self.cfg.project_dir))]
        return []

    # -- env setup ----------------------------------------------------------
    def _env_paths(self) -> tuple[Path, Path]:
        """Base-managed env for this module: (env_dir, python)."""
        d = SHARED_ENV_DIR if self.cfg.use_shared else self.cfg.env_dir
        return d, venv_python(d)

    def start(self):
        # Already setting up or running: F5 (and any other caller) used to
        # start a second copy, orphaning the first — Stop reached only the
        # newest, and the old one ran on untracked.
        if any(p is not None and p.state() != QProcess.ProcessState.NotRunning
               for p in (self.setup_proc, self.app_proc)) or self._wsl_queued():
            return
        proj = Path(self.cfg.project_dir)
        if not proj.is_dir():
            self._log(f"Project folder missing: {self.cfg.project_dir}")
            return
        if not self.cfg.runtime:
            # Blank tab: try to detect a runtime now that files may exist.
            found = detect_runtimes(proj)
            if not found:
                self._log("Blank tab — no runnable project detected yet. Use "
                          "the terminal to add files/deps, then right-click the "
                          "tab ▸ Re-detect runtime.")
                self._set_status("blank")
                return
            self.cfg.runtime = found[0]
            self._log(f"Detected runtime: {found[0]}")
        problem = self._bridge_problem()
        if problem:
            self._log(problem)
            self._set_status("missing bridge")
            if self.bridge == "wine":
                self._offer_install("wine")
            return
        # The native toolchain check is meaningless inside WSL: node or dotnet
        # living in the distro is invisible from the Windows PATH.
        tc = self._wine_toolchain()
        miss = None if self.bridge == "wsl" or (tc and not tc.get(
            "native_build")) else missing_toolchain_msg(self.cfg.runtime)
        if miss:
            self._log(miss)
            self._set_status("missing toolchain")
            self._offer_install()
            return
        if self.cfg.runtime == "custom" and \
                not (self.cfg.custom_run or "").strip():
            self._log("Custom module has no run command yet — right-click the "
                      "tab ▸ Custom commands… to set one.")
            self._set_status("needs a run command")
            return
        self._show_btn(self.btn_install, False)
        self._show_btn(self.btn_nosandbox, False)
        self._warned_sandbox = False        # re-offer if it aborts again
        self._browser_launched = False
        self._await_url = False
        self._stopping = False
        self._wsl_pid = None
        if self.bridge != "native":
            self._log(f"Runs on {self.cfg.platform}; bridging through "
                      + ("Wine" if self.bridge == "wine" else "WSL") + ".")
        if self.cfg.runtime == "python":
            if self.bridge == "wsl":
                self._start_python_wsl(proj)
            elif self.bridge == "wine":
                self._start_python_wine(proj)
            else:
                self._start_python(proj)
            return
        rt = RUNTIMES.get(self.cfg.runtime)
        # PHP's dev server serves a URL exactly like a JS dev server does; it
        # never opens a window, so without this the tab just sat blank.
        if rt is not None and rt.serves(self.cfg):
            self._start_server(rt)
        else:
            self._start_generic(proj)

    def _start_python(self, proj: Path):
        own = project_venv_python(proj)
        if own is not None and not self.cfg.use_shared:
            # Module ships a working venv — use it as-is, skip installs.
            self.run_python = own
            self._log(f"Using module's own venv: {own}")
            self._launch()
            return
        env_dir, env_py = self._env_paths()
        self.run_python = env_py
        if self.cfg.use_shared:
            self._log(f"Using shared environment: {env_dir}")
        if env_py.is_file():
            self._install_deps()
        else:
            self._create_env()

    def _start_generic(self, proj: Path):
        rt = RUNTIMES.get(self.cfg.runtime)
        if rt is None:
            self._log(f"Unknown runtime: {self.cfg.runtime}")
            self._set_status("setup failed")
            return
        tc = self._wine_toolchain()

        def launch():
            # Asked after setup, not before: what a build entry runs (the jar
            # mvn makes, the newest program make leaves) doesn't exist until
            # the build has run, and a fresh clone ran `java -jar (build)`.
            spec = rt.launch(self.cfg)
            program, env = spec.program, dict(spec.extra_env or {})
            if tc and Path(program).name == tc.get("swap"):
                program = self._wine_tool_win()     # java -> its java.exe
                env.update(tc.get("env", {}))
            # A container gets no display, so there is never a window to
            # find — and under WSL the hunt took the next Linux window to open.
            windowless = self.cfg.runtime == "docker"
            self._launch_process(program, spec.args, spec.workdir, env,
                                 embed=False if windowless else None)
            if windowless:
                self._set_status("running (output in log)")
        # ponytail: under Wine a Ruby module's Gemfile isn't bundled (the
        # native `bundle` is the wrong Ruby); add a Windows bundle step when a
        # Windows-only Ruby module brings one.
        native = rt.setup_steps(self.cfg) \
            if not tc or tc.get("native_build") else []
        self._run_command_chain(self._bridge_steps() + native, on_ok=launch)

    def _start_server(self, rt):
        def go():
            spec = rt.launch(self.cfg)         # after setup, as above
            self._await_url = True
            self._url_tail = ""
            self._log("Starting server; will embed a browser window "
                      "once its URL appears…")
            self._launch_process(spec.program, spec.args, spec.workdir,
                                 spec.extra_env, embed=False)
            self._set_status("starting (web server)")
            QTimer.singleShot(30000, self._web_url_timeout)
        self._run_command_chain(self._bridge_steps() + rt.setup_steps(self.cfg),
                                on_ok=go)

    def _python_packages(self, proj: Path, path=str) -> list:
        """pip install arguments for a project: its requirement files (paths
        via `path`), declared deps, scanned imports, EXTRA_PIP_PACKAGES."""
        pkgs = []
        for r in find_requirement_files(proj):
            pkgs += ["-r", path(r)]
        declared = declared_python_deps(proj)
        scanned = [d for d in scan_imports(proj) if d not in declared]
        return pkgs + declared + scanned + \
            self.cfg.extra_env.get("EXTRA_PIP_PACKAGES", "").split()

    def _wine_env_dir(self) -> Path:
        return ENVS_DIR / f"{self.cfg.env_dir.name}-wine"

    def _start_python_wine(self, proj: Path):
        """A Windows-only Python program on Linux: the Windows Python in the
        module's Wine prefix (installed on first use, see WINE_TOOLCHAINS),
        with a venv of its own built by that Python — a Linux venv is useless
        to it, as a Windows one is to WSL."""
        env_dir = self._wine_env_dir()
        env_py = env_dir / "Scripts" / "python.exe"
        wine = wine_program() or "wine"
        wenv = {"WINEPREFIX": str(self._prefix()), "WINEDEBUG": "-all"}
        steps = self._bridge_steps()
        # Scripts/pip.exe, not python.exe: a venv whose ensurepip failed has
        # the one without the other (the WSL lesson).
        if not (env_dir / "Scripts" / "pip.exe").is_file():
            ENVS_DIR.mkdir(parents=True, exist_ok=True)
            steps.append(("creating a Windows venv", wine,
                          [self._wine_tool_win(), "-m", "venv", "--clear",
                           wine_path(env_dir)], str(proj), wenv))
        pkgs = self._python_packages(proj, path=wine_path)
        if pkgs:
            self._log("Packages for Windows Python: " + " ".join(pkgs))
            steps.append(("installing deps (Windows Python)", wine,
                          [wine_path(env_py), "-m", "pip", "install",
                           "--disable-pip-version-check", "--no-input", *pkgs],
                          str(proj), wenv))

        def launch():
            self.run_python = env_py
            self._launch()
        self._run_command_chain(steps, on_ok=launch)

    def _start_python_wsl(self, proj: Path):
        """Python inside WSL. The venv lives in the distro's own home and is
        built by the distro's python3 — a Windows venv is useless to Linux, and
        one on /mnt/c is painfully slow. Same dependency discovery as native."""
        env_name = "_shared" if self.cfg.use_shared else self.cfg.env_dir.name
        venv = f'"$HOME/.unified_base/envs/{env_name}"'
        pkgs = self._python_packages(proj, path=lambda r: to_wsl_path(str(r)))
        # bin/pip, not bin/python: a venv that failed for want of ensurepip
        # (no python3-venv in the distro) leaves bin/python behind, and was
        # then taken as ready forever after the package was installed.
        script = f"test -x {venv}/bin/pip || python3 -m venv --clear {venv}"
        if pkgs:
            self._log("Packages for WSL: " + " ".join(pkgs))
            script += (f" && {venv}/bin/python -m pip install "
                       "--disable-pip-version-check --no-input "
                       + " ".join(shlex.quote(x) for x in pkgs))
        prog, args = wsl_shell(script, proj)
        entry = self.cfg.entry

        def launch():
            # sh -c, not exec "$@": $HOME has to expand inside the distro.
            self._launch_process(
                "sh", ["-c", f'exec {venv}/bin/python "$@"', "ub-py", entry],
                self.cfg.project_dir,
                {"PYTHONPATH": to_wsl_path(self.cfg.project_dir)})
        self._run_command_chain(
            self._bridge_steps()
            + [("preparing Python env in WSL", prog, args, str(proj))],
            on_ok=launch)

    def rebuild_env(self):
        # Ctrl+Shift+R bypasses the greyed-out button: deleting a running
        # app's deps under it, then a start() that refuses, left it broken.
        if any(p is not None and p.state() != QProcess.ProcessState.NotRunning
               for p in (self.setup_proc, self.app_proc)) or self._wsl_queued():
            self._log("Stop the module first, then Rebuild Env.")
            return
        if self.cfg.runtime == "python" and self.bridge == "wine":
            shutil.rmtree(self._wine_env_dir(), ignore_errors=True)
            self.start()
            return
        if self.cfg.runtime == "python":
            env_dir, _ = self._env_paths()
            if env_dir.exists():
                self._log(f"Removing {env_dir} ...")
                shutil.rmtree(env_dir, ignore_errors=True)
            self._create_env()
            return
        # Non-python: clear the ecosystem's installed deps / build output,
        # then start fresh (setup steps will rebuild). These are folders in
        # the user's own project — `build`, `out` may hold real files — so
        # the list is shown and confirmed first.
        proj = Path(self.cfg.project_dir)
        doomed = [proj / rel for rel in (
            "node_modules", ".ub_app", ".ub_app.exe", "target", "build",
            "dist", "out", CsharpRuntime.WIN_OUT) if (proj / rel).exists()]
        if doomed and QMessageBox.question(
                self, "Rebuild Env",
                "Delete these from the project folder and build them again?"
                "\n\n" + "\n".join(f"  {p.name}" for p in doomed)) \
                != QMessageBox.StandardButton.Yes:
            return
        for p in doomed:
            self._log(f"Removing {p} ...")
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        self.start()

    def _create_env(self):
        env_dir, env_py = self._env_paths()
        self.run_python = env_py
        ENVS_DIR.mkdir(parents=True, exist_ok=True)
        self._set_status("creating venv")
        if USE_UV:
            # --seed: uv's venvs have no pip otherwise, and the command bar's
            # `pip install x` then reached the system pip instead.
            self._log(f"$ uv venv --seed {env_dir}")
            self._run_setup("uv", ["venv", "--seed", str(env_dir)],
                            on_ok=self._install_deps)
        else:
            # Windows has no `python3` on PATH by default (it is `python` or
            # the `py` launcher), so there the launcher's own interpreter
            # builds the venv — it is the one Python guaranteed to exist.
            base = sys.executable if IS_WINDOWS else "python3"
            self._log(f"$ {base} -m venv {env_dir}")
            self._run_setup(base, ["-m", "venv", str(env_dir)],
                            on_ok=self._install_deps)

    def _install_deps(self):
        proj = Path(self.cfg.project_dir)
        py = str(getattr(self, "run_python", None) or self.cfg.env_python)
        # uv installs into the venv via --python; pip runs as that interpreter.
        if USE_UV:
            prog, args = "uv", ["pip", "install", "--python", py]
        else:
            prog = py
            args = ["-m", "pip", "install", "--disable-pip-version-check",
                    "--no-input"]
        req_files = find_requirement_files(proj)
        for r in req_files:
            self._log(f"Found requirements file: {r}")
            args += ["-r", str(r)]
        # Declared deps (pyproject.toml / requirements*.in) + AST scan.
        declared = declared_python_deps(proj)
        if declared:
            self._log("Declared deps (pyproject/requirements.in): "
                      + ", ".join(declared))
            args += declared
        scanned = scan_imports(proj)
        # Skip scanned names already covered by a declared dep.
        scanned = [d for d in scanned if d not in declared]
        if scanned:
            self._log("Scanned imports (recursive): " + ", ".join(scanned))
            args += scanned
        # Per-module extra packages (config override).
        extra_pkgs = self.cfg.extra_env.get("EXTRA_PIP_PACKAGES", "").split()
        if extra_pkgs:
            self._log("Extra packages (config): " + ", ".join(extra_pkgs))
            args += extra_pkgs
        if not req_files and not declared and not scanned and not extra_pkgs:
            self._log("No third-party imports detected; skipping install.")
            self._launch()
            return
        self._set_status("installing deps"
                         + (" (uv)" if USE_UV else ""))
        self._run_setup(prog, args, on_ok=self._launch)

    def _run_setup(self, prog: str, args: list[str], on_ok, cwd=None,
                   env: dict | None = None):
        # Inside WSL the program lives in the distro, invisible to which().
        skip = None if self.bridge == "wsl" else missing_setup_msg(prog)
        if skip:
            self._log(skip)
            self._offer_install(prog)
            on_ok()          # keep the chain going; the app reports the truth
            return
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        if cwd:
            p.setWorkingDirectory(str(cwd))
        # Builds need the overrides too, not just the launch (CARGO_HOME,
        # NODE_ENV, a private registry URL ...).
        step_env = {**(env or {}), **(self.cfg.extra_env or {})}
        step_env.pop("EXTRA_PIP_PACKAGES", None)
        prog, args, run_env = self._wrap(prog, args, cwd or self.cfg.project_dir,
                                         step_env)
        if run_env:
            qenv = QProcessEnvironment.systemEnvironment()
            for k, v in run_env.items():
                qenv.insert(k, str(v))
            p.setProcessEnvironment(qenv)
        tail = [""]

        def out():
            text = proc_text(p.readAllStandardOutput())
            tail[0] = (tail[0] + text)[-4000:]
            self._log(text)
        p.readyReadStandardOutput.connect(out)

        def done(code, _status):
            self.setup_proc = None
            if self._cancel_setup:          # Stop ended it: no launch, no blame
                self._cancel_setup = False
                self._log("Setup cancelled.")
                self._set_status("stopped")
                return
            if code == 0:
                on_ok()
            else:
                self._log(f"Setup step failed with exit code {code}.")
                hint = docker_hint(tail[0])
                if hint:
                    self._log(hint)
                logger.warning(f"Setup failed: {prog} exited with code {code}")
                self._set_status("setup failed")

        p.finished.connect(done)
        p.errorOccurred.connect(          # Stop's kill reads as Crashed: not a failure
            lambda e: self._cancel_setup or
            self._log(f"Setup step '{prog}' failed to run: {e}"))
        self.setup_proc = p
        start_qprocess(p, prog, args)
        self._set_status(self.status)  # refresh button states

    def _run_command_chain(self, steps, on_ok):
        """Run (label, prog, args, cwd) setup steps in order, then on_ok().

        Used by the non-Python runtimes for install/build commands
        (npm install, cargo build, mvn package, …).
        """
        queue = list(steps)

        def run_next():
            if not queue:
                on_ok()
                return
            label, prog, args, cwd, *opt = queue.pop(0)
            self._set_status(label)
            shown = " ".join("<script>" if "\n" in a else a for a in args)
            self._log(f"$ {prog} {shown}  (in {cwd})")
            self._run_setup(prog, args, on_ok=run_next, cwd=cwd,
                            env=opt[0] if opt else None)
        run_next()

    # -- run + embed ----------------------------------------------------------
    def _launch(self):
        """Python launch — kept thin; the heavy lifting is _launch_process."""
        py = getattr(self, "run_python", self.cfg.env_python)
        # Project root on PYTHONPATH so entries in subfolders can use
        # package-absolute imports (e.g. "from player.core import …").
        old_pp = os.environ.get("PYTHONPATH", "")
        extra = {"PYTHONPATH": self.cfg.project_dir +
                 (os.pathsep + old_pp if old_pp else "")}
        if self.bridge == "wine":       # Windows Python: Z:\ paths, ; lists
            extra = {"PYTHONPATH": wine_path(self.cfg.project_dir)}
        self._log(f"$ {py} {self.cfg.entry}")
        self._launch_process(str(py), [self.cfg.entry],
                             self.cfg.project_dir, extra)

    def _tree_pids(self) -> set:
        """Every process this module runs: its app's and browser's trees."""
        out = set()
        for p in (self.app_proc, self.browser_proc):
            try:
                if p is not None and p.processId() > 0 and \
                        p.state() != QProcess.ProcessState.NotRunning:
                    out |= descendant_pids(int(p.processId()))
            except RuntimeError:              # its QProcess already deleted
                pass
        return out | self._wine_family()

    def _others_windows(self) -> set:
        """Windows the other running modules' own processes have open."""
        pids = set()
        for t in list(_LIVE_TABS):
            if t is not self:
                pids |= t._tree_pids()
        return set(windows_for_pids(pids)) if pids else set()

    def _take_wsl_turn(self, launch) -> bool:
        """True when this WSL module may launch, and look for its window,
        now; otherwise `launch` waits its turn (see _WSL_TURN)."""
        if _WSL_TURN["searching"] in (None, self):
            _WSL_TURN["searching"] = self
            return True
        _WSL_TURN["queue"].append((self, launch))
        self._set_status("queued — another Linux window is opening")
        return False

    def _end_wsl_turn(self):
        """Found its window, gave up, stopped or closed: leave the queue, and
        if this tab held the turn, launch the next one."""
        _WSL_TURN["queue"] = [q for q in _WSL_TURN["queue"] if q[0] is not self]
        if _WSL_TURN["searching"] is not self:
            return
        _WSL_TURN["searching"] = None
        if _WSL_TURN["queue"]:
            QTimer.singleShot(0, _WSL_TURN["queue"].pop(0)[1])

    def _wsl_queued(self) -> bool:
        return any(t is self for t, _ in _WSL_TURN["queue"])

    def _launch_process(self, program, args, workdir, extra_env=None,
                       embed=None):
        """Start a module process and (optionally) embed its window. Shared
        by every runtime — only the program/args/env differ."""
        if embed is None:
            embed = self.cfg.embed
        if self.bridge == "wsl" and embed and EMBEDDING_OK and \
                not self._take_wsl_turn(lambda: self._launch_process(
                    program, args, workdir, extra_env, embed)):
            return
        self._set_status("starting")
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        force_x11_env(env)
        if IS_WINDOWS and not env.contains("PYTHONIOENCODING"):
            # Python writes a pipe in the ANSI code page; proc_text reads UTF-8.
            env.insert("PYTHONIOENCODING", "utf-8")
        mod_env = {k: str(v) for k, v in (extra_env or {}).items()}
        # Per-module env overrides (EXTRA_PIP_PACKAGES is install-only, skip it).
        mod_env.update({k: str(v) for k, v in (self.cfg.extra_env or {}).items()
                        if k != "EXTRA_PIP_PACKAGES"})
        p.setWorkingDirectory(str(workdir))
        p.readyReadStandardOutput.connect(lambda: self._handle_stdout(p))
        p.finished.connect(self._on_app_finished)
        p.errorOccurred.connect(
            lambda e, prog=program: self._proc_error(prog, e))
        self.app_proc = p
        self.embed_proc = p
        # Append per-module startup args (config override) — to the real
        # program, before any bridge wraps it.
        args = compose_args(program, args, self.cfg.startup_args)
        # Killing `docker run` detaches the client and leaves the container
        # running — one stray container per mount, still burning CPU and
        # still holding its ports. Remember the name so stop() can remove it.
        self._docker_name = (args[args.index("--name") + 1]
                             if "--name" in args[:-1] else None)
        program, args, run_env = self._wrap(program, args, workdir, mod_env,
                                            launch=True)
        self._wine_tag = None
        if self.bridge == "wine":
            tag = f"{os.getpid()}-{id(p)}-{time.monotonic_ns()}"
            run_env["UB_LAUNCH"] = tag
            self._wine_tag = f"UB_LAUNCH={tag}"
        for k, v in run_env.items():
            env.insert(k, str(v))
        p.setProcessEnvironment(env)
        # Snapshot existing windows so we can spot the module's new window
        # even if it never advertises its pid (SDL/OpenGL apps often don't).
        self._win_baseline = all_window_ids() if EMBEDDING_OK else set()
        start_qprocess(p, program, args)
        self._begin_embed(embed)

    def _proc_error(self, program: str, err):
        """Report a process error without inventing a cause.

        Killing a module made QProcess emit Crashed, and the old handler
        answered that with "is 'php' installed and on PATH?" — about a server
        that had just printed its own startup banner.
        """
        if self._stopping:
            return                       # we asked for this exit
        if err == QProcess.ProcessError.FailedToStart:
            self._log(f"'{program}' failed to start — is it installed and "
                      "on PATH?")
        else:
            self._log(f"Process error: {err}")

    def _begin_embed(self, embed: bool):
        if EMBEDDING_OK and embed:
            self._embed_attempts = 0
            self._vanished = 0
            self._reembed_rounds = 0
            self.embed_timer.start()
            self._set_status("waiting for window")
        elif EMBEDDING_OK:
            self._set_status("running (own window)")
        else:
            reason = "Wayland" if IS_WAYLAND else "no X"
            self._set_status(f"running (panel mode — {reason})")

    def _handle_stdout(self, p: QProcess):
        text = proc_text(p.readAllStandardOutput())
        if self.bridge == "wsl" and self._wsl_pid is None:
            m = UBPID_RE.search(text)
            if m:
                self._wsl_pid = int(m.group(1))
                text = UBPID_RE.sub("", text, count=1).lstrip("\n")
        if text:
            self._log(text)
        if not self._warned_sandbox:
            hint = chrome_sandbox_hint(text)
            if hint:
                self._warned_sandbox = True
                self._log(hint)
                if "--no-sandbox" not in self.cfg.startup_args:
                    self._show_btn(self.btn_nosandbox, True)
        # Web runtime: watch the dev server's output for a localhost URL,
        # then launch and embed a browser window pointed at it.
        if self._await_url and not self._browser_launched:
            self._url_tail = (self._url_tail + text)[-4000:]
            m = SERVER_URL_RE.search(self._url_tail)
            if m:
                url = m.group(0).replace("0.0.0.0", "localhost")
                self._await_url = False
                self._log(f"Dev server URL detected: {url}")
                self._spawn_browser(url)

    def _spawn_browser(self, url: str):
        browser = find_browser()
        if not browser:
            self._log("No chromium-family browser found to embed the web "
                      f"app. Open {url} manually, or install chromium / "
                      "google-chrome / brave / Edge to embed it.")
            self._set_status("running (server only)")
            return
        self._browser_launched = True
        prof = tempfile.mkdtemp(prefix="ub_web_")
        self._web_profile = prof      # throwaway profile; removed when it exits
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        force_x11_env(env)
        p.setProcessEnvironment(env)
        p.readyReadStandardOutput.connect(lambda: self._handle_browser_output(p))
        p.finished.connect(self._on_browser_finished)
        p.errorOccurred.connect(lambda e: self._log(f"Browser error: {e}"))
        # No sign-in, no sync: Edge signed the Windows account into each
        # throwaway profile and announced it in a modal dialog, which (its
        # window being our child) locked the whole launcher.
        args = [f"--app={url}", f"--user-data-dir={prof}", "--new-window",
                "--no-first-run", "--no-default-browser-check",
                "--disable-sync", "--disable-features=msImplicitSignin"]
        # Force Chromium's window onto X11 (not a Wayland surface) so it has a
        # real X11 id to reparent. Without this the web tab never embeds on
        # Wayland — the browser opens but stays a floating Wayland window.
        if FORCE_X11:
            args.insert(0, "--ozone-platform=x11")
        self._log(f"$ {browser} {' '.join(args)}")
        self.browser_proc = p
        self.embed_proc = p
        self._win_baseline = all_window_ids() if EMBEDDING_OK else set()
        start_qprocess(p, browser, args)
        self._begin_embed(self.cfg.embed)

    def _handle_browser_output(self, p: QProcess):
        text = proc_text(p.readAllStandardOutput())
        self._log(text)
        # No Retry-without-sandbox button here: startup args go to the dev
        # server, not the browser, so the hint's own fix is the way.
        if not self._warned_sandbox:
            hint = chrome_sandbox_hint(text)
            if hint:
                self._warned_sandbox = True
                self._log(hint)

    def _web_url_timeout(self):
        if self._await_url and not self._browser_launched:
            self._await_url = False
            self._log("No server URL seen within 30 s. If it is serving, "
                      "hit the Embed button once it's up, or check the entry "
                      "(the npm script / PHP dev-server option).")

    def _try_embed(self):
        self._embed_attempts += 1
        proc = self.embed_proc
        if proc is None or \
                proc.state() == QProcess.ProcessState.NotRunning:
            self.embed_timer.stop()
            return
        if self._embed_attempts == 1:
            self.embed_timer.setInterval(250)       # after a slow watch
            self._log(embed_diagnostics())
        pids = descendant_pids(int(proc.processId())) | self._wine_family()
        # A WSLg window belongs to msrdc.exe, never to anything we started, so
        # the pid path cannot succeed: go straight to "new window since launch",
        # restricted to the processes that draw Linux windows on Windows.
        # Not for a web module's browser: that is Edge, our own Windows child,
        # and the WSL path never took its window — the server in WSL is all.
        wsl = self.bridge == "wsl" and proc is not self.browser_proc
        wids = [] if wsl else [w for w in windows_for_pids(pids)
                               if w not in _CLAIMED_WINDOWS]
        # Fallback: if the module's window never advertised its pid, grab the
        # new app-like window that appeared since launch. It is a guess, so
        # give the pid path a long head start (~10 s): XRes now attributes
        # even tk/SDL/winit windows, and a module that is still building
        # would otherwise steal whichever neighbour opened a window first.
        # Only while still searching: after that a new window is anyone's.
        guessing = self._embed_attempts <= self._max_embed_attempts
        if not wids and guessing and (wsl or self._embed_attempts >= 40):
            wids = [w for w in new_windows_since(
                        self._win_baseline, self._own_pid,
                        owners=LINUX_WINDOW_OWNERS if wsl else None,
                        skip_owners=() if wsl else LINUX_WINDOW_OWNERS)
                    if w not in _CLAIMED_WINDOWS]
            if wids:          # a guess, but never a neighbour's own window
                theirs = self._others_windows()
                wids = [w for w in wids if w not in theirs]
            if wids:
                self._log("No pid match — embedding a new window that "
                          f"appeared after launch (0x{wids[0]:x}).")
        if wids:
            self.embed_timer.stop()
            self._embed(wids[0])
        elif self._embed_attempts == self._max_embed_attempts:  # ~40 s
            self._set_status("running (own window)")
            if wsl:        # its windows are never its own processes'
                self.embed_timer.stop()
                self._end_wsl_turn()
                self._log(f"No embeddable window found after 40 s — panel "
                          "mode. Use the Embed button to retry once the "
                          "window is up.")
                return
            # A slow build (dotnet run compiling first) can outlast 40 s: keep
            # watching the module's own processes, slowly, and embed the
            # window when it turns up.
            self.embed_timer.setInterval(2000)
            self._log(f"No embeddable window found after 40 s (searched "
                      f"{len(pids)} process(es)) — still watching; it is "
                      "embedded when it appears (or use the Embed button).")

    def _embed(self, wid: int):
        self._end_wsl_turn()             # its window is chosen: next one's turn
        _CLAIMED_WINDOWS.add(wid)
        self._claimed_wid = wid
        try:
            host = EmbedHost(wid, self.embed_page, log=self._log)
        except Exception as e:
            # Reparenting unavailable (Wayland, or a window Windows won't let
            # us adopt); try Qt's own container instead.
            logger.debug(f"Reparent failed: {e}")
            if getattr(e, "winerror", None) in (87, 1400) \
                    and self._vanished < 5:      # (winerror: Windows only)
                # The window went away under us (Edge's short-lived first
                # window): 87/1400, not a refusal. Look again — this used to
                # leave the module in its own window for good.
                self._vanished += 1
                _CLAIMED_WINDOWS.discard(wid)
                self._claimed_wid = None
                self.embed_timer.start()
                return
            if IS_WINDOWS:
                # Qt's container would only SetParent again and fail the same.
                why = (" WSLg windows belong to msrdc.exe, which Windows won't "
                       "let another program adopt. To embed Linux windows, "
                       "run an X server (VcXsrv: -multiwindow -listen tcp) with "
                       "WSL's networkingMode=mirrored, then Restart."
                       if self.bridge == "wsl" else "")
                self._log(f"Can't embed this window: "
                          f"{getattr(e, 'strerror', None) or e}{why} It runs "
                          "in its own window.")
                self._set_status("running (own window)")
                return
            if IS_WAYLAND:
                self._log(f"X reparent unavailable on Wayland ({e}); "
                          "trying Qt container fallback…")
            else:
                self._log(f"X reparent failed ({e}); trying Qt fallback…")
            self._embed_qt(wid)
            return
        host.clicked.connect(self.pane_clicked)
        self.container = host
        self.embed_layout.addWidget(host)
        # Logs were force-closed on embed because they took the whole pane.
        # Docked and undocked logs can stay up beside the module instead.
        if self.cfg.log_mode == "embedded":
            self.chk_logs.setChecked(False)
        self._apply_log_mode()
        self._set_status("running (embedded)")
        self._log(f"Embedded window 0x{wid:x} via "
                  + ("SetParent." if IS_WINDOWS else "X reparent."))

        def check(stable=0, tries=0):
            if self.container is not host:
                return
            if not host.child_alive():
                # Window genuinely destroyed and recreated (common with
                # SDL/OpenGL apps during init) — the id is stale, so re-scan
                # for the module's current window and reparent that.
                self._teardown_embed()
                self._reembed_rounds += 1
                if self._reembed_rounds <= self._max_reembed_rounds:
                    self._log("Window was recreated — re-scanning "
                              f"({self._reembed_rounds}/"
                              f"{self._max_reembed_rounds})…")
                    self._embed_attempts = 0
                    self.embed_timer.start()
                    self._set_status("waiting for window")
                else:
                    self._log("Module keeps recreating its window — panel "
                              "mode. Use the Embed button to retry.")
                    self._set_status("running (own window)")
                return
            if host.verify():
                # Need two consecutive good checks ~0.5 s apart: some apps /
                # the WM nudge the window once more just after we grab it.
                if stable + 1 >= 2:
                    self._reembed_rounds = 0
                    host._resize_child()
                    return
                QTimer.singleShot(500, lambda: check(stable + 1, tries))
                return
            # Child drifted (Qt recreated our native window, or the WM grabbed
            # it back). Put it back rather than giving up — the host's heal
            # timer is doing the same; we just keep watching.
            host.reattach_if_needed()
            if tries + 1 <= 12:  # ~6 s of nudging
                QTimer.singleShot(500, lambda: check(0, tries + 1))
                return
            self._log("Couldn't keep the window docked — panel mode. "
                      "Use the Embed button to retry.")
            self._teardown_embed()
            self._set_status("running (own window)")
        QTimer.singleShot(700, lambda: check())

    def _embed_qt(self, wid: int):
        try:
            self.foreign_win = QWindow.fromWinId(wid)
            if self.foreign_win is None:
                raise RuntimeError("platform cannot wrap foreign windows")
            self.container = QWidget.createWindowContainer(
                self.foreign_win, self.embed_page)
            self.container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.embed_layout.addWidget(self.container)
            if self.cfg.log_mode == "embedded":
                self.chk_logs.setChecked(False)
            self._apply_log_mode()
            self._set_status("running (embedded)")
            self._log(f"Embedded window 0x{wid:x} via Qt container.")
        except Exception as e:
            logger.debug(f"Qt container embedding failed: {e}")
            self._log(f"Embedding unavailable: {e} — module running in own window.")
            self._set_status("running (own window)")

    def retry_embed(self):
        if self.embed_proc is None or self.container is not None:
            return
        self._embed_attempts = 0
        self.embed_timer.start()
        self._set_status("waiting for window")

    def _teardown_embed(self):
        if self._claimed_wid is not None:
            _CLAIMED_WINDOWS.discard(self._claimed_wid)
            self._claimed_wid = None
        if self.container is not None:
            if hasattr(self.container, "detach"):     # either EmbedHost
                self.container.detach()
            self.container.setParent(None)
            self.container.deleteLater()
            self.container = None
        self.foreign_win = None
        self._apply_log_mode()

    def _on_app_finished(self, code, _status):
        self.embed_timer.stop()
        self._end_wsl_turn()
        self._teardown_embed()
        self._kill_browser()
        self._log("Module stopped." if self._stopping
                  else f"Module exited (code {code}).")
        if code == 127 and self.bridge == "wsl" and not self._stopping:
            # `env` words it as "No such file" plus a shebang tip: noise.
            pkgs = TOOLCHAIN_PKGS.get(TOOLCHAIN_CMD.get(self.cfg.runtime, ""),
                                      {}).get("apt")
            self._log("Exit 127 is \"command not found\" inside WSL: the "
                      "program isn't installed in the distro (or wasn't "
                      "built) — see any setup note above." + (
                          "\n    This module's toolchain:  wsl -u root "
                          f"apt-get install -y {pkgs}" if pkgs else ""))
        # A launcher stub (a .bat that `start`s its app, a setup.exe that
        # hands off) can exit while what it started runs on, detached by Wine.
        left = set() if self._stopping else self._wine_family()
        if left:
            self._log(f"It left {len(left)} Windows process(es) running "
                      f"(pid {', '.join(map(str, sorted(left)))}) that this "
                      "tab can't embed or stop. Point the entry at the "
                      "program's .exe rather than a launcher that exits.")
        self._wine_tag = None
        self.app_proc = None
        self.embed_proc = None
        self._await_url = False
        self._set_status("stopped")

    def _on_browser_finished(self, code, _status):
        # Web runtime: the embedded browser closed but the server may still
        # be up. Drop the embed; leave the server running.
        self.embed_timer.stop()
        self._teardown_embed()
        self._log(f"Browser window closed (code {code}).")
        self._reap_web_profile()
        self.browser_proc = None
        self.embed_proc = self.app_proc
        if self.app_proc is not None and \
                self.app_proc.state() != QProcess.ProcessState.NotRunning:
            self._set_status("running (server only)")

    def _reap_web_profile(self):
        """Kill whatever is still running against our throwaway browser
        profile, then delete it.

        The QProcess we started is only a snap shim; the real Chromium lands
        in its own systemd scope, outside our process tree. Left alone it
        keeps running after the tab stops — one orphaned browser per web-module
        run, each holding an X connection.
        """
        prof = self._web_profile
        if not prof:
            return
        self._web_profile = None
        # "denied" is e.g. an AppArmor-confined snap browser.
        stuck = [pid for pid in pids_with_arg(prof)
                 if kill_pid(pid, SIGKILL) == "denied"]
        if stuck and x_close_clients(set(stuck)):
            self._log("The browser refused signals (a confined snap); closed "
                      "it through its X connection instead.")
        elif stuck:
            self._log(f"Could not close {len(stuck)} browser process(es) "
                      f"{stuck} — not permitted to signal them. Close that "
                      "browser window by hand so it stops holding the port.")
        shutil.rmtree(prof, ignore_errors=True)

    def _reap_container(self):
        """Remove the container this tab started, if any."""
        name = self._docker_name
        if not name:
            return
        self._docker_name = None
        # Through the bridge: a module under WSL ran WSL's docker, and a
        # Windows-side `docker rm` addressed another engine (or none) — the
        # container ran on after Stop.
        prog, args, _ = self._wrap("docker", ["rm", "-f", name], None)
        QProcess.startDetached(resolve_program(prog), args)

    def _kill_browser(self):
        if self.browser_proc is not None:
            if self.browser_proc.state() != QProcess.ProcessState.NotRunning:
                for sig in (self.browser_proc.finished,
                            self.browser_proc.readyReadStandardOutput,
                            self.browser_proc.errorOccurred):
                    try:
                        sig.disconnect()
                    except (RuntimeError, TypeError):
                        # Signal not connected or already disconnected
                        pass
                self._signal_tree(self.browser_proc, SIGKILL)
                self.browser_proc.kill()
            self.browser_proc = None
        self._reap_web_profile()

    def _kill_wine_family(self, sig: int):
        for wpid in self._wine_family():     # detached by Wine, see wine_family
            kill_pid(wpid, sig)

    def stop(self):
        if self._wsl_queued():            # waiting its turn: nothing runs yet
            self._end_wsl_turn()
            self._set_status("stopped")
            return
        s = self.setup_proc
        if s is not None and s.state() != QProcess.ProcessState.NotRunning:
            # Mid-setup (an image pull, npm install, a build): Stop cancels
            # it, and the chain ends in _run_setup's done() before launching.
            # Under WSL this ends wsl.exe; the distro's side may run on.
            self._cancel_setup = True
            self._set_status("stopping")
            if s.processId() > 0:
                kill_process_tree(int(s.processId()), SIGKILL)
            else:
                s.kill()
            return
        if self.app_proc is None and self.browser_proc is None:
            return
        self._set_status("stopping")
        self._stopping = True
        self._await_url = False
        self._kill_browser()          # snap chromium needs the profile sweep
        self._reap_container()        # docker run's client is not the container
        self._signal_tree(self.app_proc, SIGTERM)
        self._doomed = self.app_proc
        QTimer.singleShot(3000, self._force_kill)

    def _signal_tree(self, proc, sig: int):
        """Signal a module process and its whole tree, not just the wrapper."""
        if proc is None or \
                proc.state() == QProcess.ProcessState.NotRunning:
            return
        if proc is self.app_proc:
            self._kill_wine_family(sig)
        if proc is self.app_proc and self._wsl_pid:
            # The Windows-side tree is only wsl.exe; the app is in the distro.
            QProcess.startDetached("wsl.exe", [
                "--exec", "sh", "-c", wsl_kill_script(self._wsl_pid, sig)])
        pid = int(proc.processId())
        if pid > 0:
            kill_process_tree(pid, sig)
        elif sig == SIGKILL:
            proc.kill()          # starting up, no pid yet
        else:
            proc.terminate()

    def _force_kill(self):
        # Only what stop() was stopping. By now Restart (or Start right after
        # Stop) may have put a new process in app_proc, and SIGKILLing that
        # killed every restarted module 3 s after it came up. stop() already
        # reaped the browser and its profile.
        doomed, self._doomed = self._doomed, None
        self._signal_tree(doomed, SIGKILL)

    def restart(self):
        if self.app_proc is None:
            self.start()
            return
        self.app_proc.finished.connect(
            lambda *_: QTimer.singleShot(200, self.start))
        self.stop()

    def shutdown(self):
        # Stop embedding FIRST: the embed poll timer and the XEmbedHost heal
        # timer keep firing (Qt widget access + Xlib calls) after the tab is
        # deleteLater()'d on close — use-after-free that hard-crashes the app.
        self._stopping = True
        self._end_wsl_turn()
        self._close_log_window()      # or the log widget dies with the window
        if self.sampler is not None:
            self.sampler.set_roots(id(self), [])
        self.embed_timer.stop()
        self._teardown_embed()
        if self.terminal is not None:
            self.terminal.shutdown()   # stops its heal timer + kills xterm
        # _install_proc runs as root via pkexec; killing apt/dnf mid-transaction
        # corrupts the package DB. It's parented to the QApplication (not this
        # tab) so tab teardown won't destroy it — here we just sever its signals
        # so its stream/finished slots can't fire into the destroyed tab. It
        # keeps running to completion, orphaned.
        if self._install_proc is not None and \
                self._install_proc.state() != QProcess.ProcessState.NotRunning:
            for sig in (self._install_proc.readyReadStandardOutput,
                        self._install_proc.finished,
                        self._install_proc.errorOccurred):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
        self._kill_browser()
        self._reap_container()
        for p in (self.setup_proc, self.browser_proc, self.app_proc,
                  self._term_proc):
            if p is not None and \
                    p.state() != QProcess.ProcessState.NotRunning:
                # All three, not just finished: a tree kill makes the process
                # emit output and exit while the tab is being deleted, and a
                # surviving readyRead slot then touches a dead QProcess.
                for sig in (p.finished, p.readyReadStandardOutput,
                            p.errorOccurred):
                    try:
                        sig.disconnect()
                    except (RuntimeError, TypeError):
                        # Signal not connected or already disconnected
                        pass
                # Whole tree: `npm start`'s electron/vite grandchild outlives
                # a plain kill() and keeps its port and X window forever.
                self._signal_tree(p, SIGKILL)
                p.kill()
                p.waitForFinished(2000)
        if self._logfile is not None:
            try:
                self._logfile.close()
            except OSError:
                pass
            self._logfile = None


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class UnifiedBase(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Unified Base")
        self.resize(1100, 750)
        self.configs = load_configs()
        prefs = load_prefs()
        self._restore_geometry(prefs.get("geometry"))
        self.tab_color_mode = prefs.get("tab_color_mode", "chips")
        # One sampler for the whole base: per-pane sampling would walk /proc
        # once per module. See ResourceSampler.
        self.meters_on = bool(prefs.get("meters", True))
        self.sampler = ResourceSampler(self)
        self.sampler.sampled.connect(self._on_sampled)
        self._tab_color_sig = None

        # Central area: a tab bar that selects/manages modules, plus a
        # splitter content area that can show several module panes at once.
        # Each module's ModuleTab lives permanently in the splitter; which
        # ones are visible is driven by the current tab and its display mode.
        self.module_tabs: list[ModuleTab] = []
        self._prev_visible: tuple[int, ...] = ()
        self._highlighted: "ModuleTab | None" = None

        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        topbar = QHBoxLayout()
        topbar.setContentsMargins(2, 2, 2, 0)
        self.tabbar = LangTabBar()
        self.tabbar.color_mode = self.tab_color_mode
        self.tabbar.setTabsClosable(True)
        self.tabbar.setMovable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        self.tabbar.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabbar.currentChanged.connect(self._on_tab_selected)
        # i < 0 is the empty strip past the last tab: leave it to the
        # event filter, which drops the outline like any other click.
        self.tabbar.tabBarClicked.connect(
            lambda i: self._pick_tab(i) if i >= 0 else None)
        self.tabbar.tabCloseRequested.connect(self._close_tab)
        self.tabbar.tabBarDoubleClicked.connect(self._rename_tab)
        self.tabbar.tabMoved.connect(self._on_tab_moved)
        self.tabbar.customContextMenuRequested.connect(self._tab_context_menu)
        add_btn = QToolButton()
        add_btn.setText("＋ Add Module")
        add_btn.clicked.connect(self.add_module)
        self.agg_meter = ResourceMeter(AGG_COLORS)
        self.agg_meter.setMaximumWidth(210)
        self.agg_meter.setToolTip("CPU and resident memory across every "
                                  "running module")
        topbar.addWidget(self.tabbar, 1)
        topbar.addWidget(self.agg_meter)
        topbar.addWidget(add_btn)
        cv.addLayout(topbar)

        # Merge content lives in a scroll area: panes keep a minimum size so
        # loading several modules scrolls the view instead of squishing the
        # window. Two arrangements: a resizable single row (scroll →) and a
        # wrapping grid of rows (scroll ↓).
        pw, ph = prefs.get("pane_min", [520, 380])[:2]
        self.pane_min = QSize(int(pw), int(ph))
        self.merge_mode = prefs.get("merge_mode", "row")   # "row" | "grid"
        # grid: 0 = auto-fit to width, else a fixed column count
        self.merge_cols = int(prefs.get("merge_cols", 0))

        self.row_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.row_splitter.setChildrenCollapsible(False)
        # Grid mode is a splitter of splitters, not a QGridLayout: a layout
        # has no drag handles, so column widths were fixed at pane_min.
        # Rows resize independently — nothing keeps column 2 of row 1 lined
        # up with column 2 of row 2.
        self.grid_splitter = QSplitter(Qt.Orientation.Vertical)
        self.grid_splitter.setChildrenCollapsible(False)
        self._grid_rows: list[QSplitter] = []
        self.pane_stash = QWidget()      # parking lot for hidden panes
        self.pane_stash.hide()

        self.merge_root = QWidget()
        self._merge_root_layout = QVBoxLayout(self.merge_root)
        self._merge_root_layout.setContentsMargins(0, 0, 0, 0)
        self._merge_root_layout.addWidget(self.row_splitter)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.merge_root)
        # Native viewport so embedded X11 windows are clipped to the scroll
        # view rather than overflowing across the rest of the UI.
        self.scroll.viewport().setAttribute(
            Qt.WidgetAttribute.WA_NativeWindow, True)
        self.scroll.viewport().installEventFilter(self)
        if IS_WINDOWS:
            self._owner_watch = QTimer(self)
            self._owner_watch.timeout.connect(self._free_owner)
            self._owner_watch.start(1000)

        self.content = QStackedWidget()
        self.empty_page = QWidget()
        ev = QVBoxLayout(self.empty_page)
        hint = QLabel("No modules yet — use ＋ Add Module or the File menu.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(hint)
        self.content.addWidget(self.empty_page)   # index 0
        self.content.addWidget(self.scroll)       # index 1
        cv.addWidget(self.content, 1)
        self.setCentralWidget(central)

        m_file = self.menuBar().addMenu("&File")
        act_add = QAction("Add Module…", self)
        act_add.triggered.connect(self.add_module)
        m_file.addAction(act_add)
        act_scan = QAction("Scan Folder for Modules…", self)
        act_scan.triggered.connect(self.scan_folder_for_modules)
        m_file.addAction(act_scan)
        self.menu_recent = m_file.addMenu("Recent Folders")
        self.menu_demos = m_file.addMenu("Load Demo Modules")
        self.menu_demos.setToolTipsVisible(True)
        self.menu_demos.aboutToShow.connect(self._rebuild_demo_menu)
        self._rebuild_demo_menu()
        act_blank = QAction("New Blank Tab", self)
        act_blank.setToolTip("Empty scratch project — build it in the terminal, "
                             "then Re-detect runtime")
        act_blank.triggered.connect(self.new_blank_tab)
        m_file.addAction(act_blank)
        m_file.addSeparator()
        act_save_layout = QAction("Save Layout As…", self)
        act_save_layout.triggered.connect(self._save_layout)
        m_file.addAction(act_save_layout)
        self.menu_load_layout = m_file.addMenu("Load Layout")
        self.menu_del_layout = m_file.addMenu("Delete Layout")
        m_file.addSeparator()
        act_quit = QAction("Exit", self)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)
        for act, seq in ((act_add, "Ctrl+N"), (act_scan, "Ctrl+Shift+N"),
                         (act_blank, "Ctrl+T"), (act_save_layout, "Ctrl+S"),
                         (act_quit, "Ctrl+Q")):
            act.setShortcut(seq)

        # Every entry acts on the picked tab, so the keys work the same whether
        # focus is in the tab bar, a log pane or an embedded module's window.
        m_run = self.menuBar().addMenu("&Run")
        for label, seq, slot in (
                ("Start", "F5", lambda: self._on_current(ModuleTab.start)),
                ("Stop", "Shift+F5", lambda: self._on_current(ModuleTab.stop)),
                ("Restart", "Ctrl+R",
                 lambda: self._on_current(ModuleTab.restart)),
                ("Rebuild Environment", "Ctrl+Shift+R",
                 lambda: self._on_current(ModuleTab.rebuild_env)),
                (None, None, None),
                ("Next Module", "Ctrl+PgDown", lambda: self._cycle_tab(1)),
                ("Previous Module", "Ctrl+PgUp", lambda: self._cycle_tab(-1)),
                (None, None, None),
                ("Close Module", "Ctrl+W",
                 lambda: self._close_tab(self.tabbar.currentIndex())),
        ):
            if label is None:
                m_run.addSeparator()
                continue
            act = QAction(label, self)
            act.setShortcut(seq)
            act.triggered.connect(slot)
            m_run.addAction(act)
        # Ctrl+1..9 jump straight to a module. No menu entries: nine of them
        # would bury the four that matter.
        for i in range(9):
            act = QAction(self)
            act.setShortcut(f"Ctrl+{i + 1}")
            act.triggered.connect(lambda _=False, n=i: self._select_tab(n))
            self.addAction(act)

        self.menu_modules = self.menuBar().addMenu("&Modules")

        m_view = self.menuBar().addMenu("&View")
        mode_grp = QActionGroup(self)
        mode_grp.setExclusive(True)
        self.act_mode_row = QAction("Single row (scroll →)", self)
        self.act_mode_row.setCheckable(True)
        self.act_mode_row.setChecked(self.merge_mode == "row")
        self.act_mode_grid = QAction("Grid / rows (scroll ↓)", self)
        self.act_mode_grid.setToolTip("Wrapping rows of panes. Drag the "
                                      "handles to resize — each row's widths "
                                      "and each row's height, independently.")
        self.act_mode_grid.setCheckable(True)
        self.act_mode_grid.setChecked(self.merge_mode == "grid")
        for a in (self.act_mode_row, self.act_mode_grid):
            mode_grp.addAction(a)
            m_view.addAction(a)
        self.act_mode_row.triggered.connect(lambda: self._set_merge_mode("row"))
        self.act_mode_grid.triggered.connect(
            lambda: self._set_merge_mode("grid"))

        self.menu_cols = m_view.addMenu("Grid columns")
        cols_grp = QActionGroup(self)
        for label, n in (("Auto-fit", 0), ("1", 1), ("2", 2), ("3", 3),
                         ("4", 4)):
            a = self.menu_cols.addAction(label)
            a.setCheckable(True)
            a.setChecked(n == self.merge_cols)
            cols_grp.addAction(a)
            a.triggered.connect(lambda _=False, k=n: self._set_merge_cols(k))
        self.menu_cols.setEnabled(self.merge_mode == "grid")

        self.menu_tabcolor = m_view.addMenu("Tab colors")
        tc_grp = QActionGroup(self)
        tc_grp.setExclusive(True)
        for label, mode in (("None (plain)", "none"),
                            ("Language chips", "chips"),
                            ("Full color tabs", "full")):
            a = self.menu_tabcolor.addAction(label)
            a.setCheckable(True)
            a.setChecked(mode == self.tab_color_mode)
            tc_grp.addAction(a)
            a.triggered.connect(
                lambda _=False, m=mode: self._set_tab_color_mode(m))

        menu_size = m_view.addMenu("Pane minimum size")
        size_grp = QActionGroup(self)
        for label, w, h in (("Small (400×300)", 400, 300),
                            ("Medium (520×380)", 520, 380),
                            ("Large (760×560)", 760, 560)):
            a = menu_size.addAction(label)
            a.setCheckable(True)
            a.setChecked(w == self.pane_min.width())
            size_grp.addAction(a)
            a.triggered.connect(
                lambda _=False, ww=w, hh=h: self._set_pane_min(ww, hh))

        m_view.addSeparator()
        act_even = QAction("Even out panes", self)
        act_even.triggered.connect(lambda: self._even_split(force=True))
        m_view.addAction(act_even)
        m_view.addSeparator()
        self.act_meters = QAction("Resource meters", self)
        self.act_meters.setCheckable(True)
        self.act_meters.setChecked(self.meters_on)
        self.act_meters.setToolTip(
            "CPU and memory strip in every module's header, plus the "
            "cumulative one beside the tabs. Off stops all sampling.")
        self.act_meters.toggled.connect(self._set_meters)
        m_view.addAction(self.act_meters)

        self._rebuild_layout_menus()
        self._rebuild_modules_menu()
        self._rebuild_recent_menu()

        if not EMBEDDING_OK:
            self.statusBar().showMessage(
                "No X server found — embedding disabled, modules open "
                "their own windows.")

        for cfg in self.configs:
            self._add_tab(cfg)
        if self.module_tabs:
            self.tabbar.setCurrentIndex(0)
        self._set_meters(self.meters_on, persist=False)
        self._refresh_view()
        # Last: any click that isn't inside the highlighted pane drops the
        # outline. Installed here because eventFilter touches widgets that
        # only exist once __init__ has finished.
        QApplication.instance().installEventFilter(self)

    # -- resource meters ----------------------------------------------------
    def _set_meters(self, on: bool, persist: bool = True):
        """Master switch. Off stops the timer outright — no /proc reads, no
        repaints, nothing left running in the background."""
        self.meters_on = bool(on)
        self.agg_meter.setVisible(self.meters_on)
        for tab in self.module_tabs:
            tab.set_meter_enabled(self.meters_on)
        if self.meters_on:
            self.sampler.timer.start()
        else:
            self.sampler.timer.stop()
            self.agg_meter.clear()
        if persist:
            prefs = load_prefs()
            prefs["meters"] = self.meters_on
            save_prefs(prefs)

    def _on_sampled(self):
        for tab in self.module_tabs:
            if tab.meter_on:
                tab.meter.push(*self.sampler.usage.get(id(tab), (0.0, 0)))
        self.agg_meter.push(*self.sampler.total)

    # -- window geometry ----------------------------------------------------
    def _restore_geometry(self, blob: "str | None"):
        """Reopen where we closed, unless that spot is off every screen now
        (monitor unplugged), which would restore an invisible window."""
        if not blob:
            return
        try:
            ok = self.restoreGeometry(QByteArray.fromBase64(blob.encode()))
        except Exception as e:               # corrupt/foreign prefs blob
            logger.debug(f"Geometry restore failed: {e}")
            return
        if ok and not any(scr.availableGeometry().intersects(
                self.frameGeometry()) for scr in QGuiApplication.screens()):
            self.resize(1100, 750)
            self.move(80, 60)

    # -- keyboard targets ---------------------------------------------------
    def _on_current(self, fn):
        """Call an unbound ModuleTab method on the picked tab, if there is one."""
        tab = self._current_tab()
        if tab is not None:
            fn(tab)

    def _select_tab(self, index: int):
        if 0 <= index < len(self.module_tabs):
            self.tabbar.setCurrentIndex(index)

    def _cycle_tab(self, delta: int):
        n = len(self.module_tabs)
        if n:
            self.tabbar.setCurrentIndex(
                (self.tabbar.currentIndex() + delta) % n)

    # -- tab helpers --------------------------------------------------------
    def _current_tab(self) -> "ModuleTab | None":
        i = self.tabbar.currentIndex()
        if 0 <= i < len(self.module_tabs):
            return self.module_tabs[i]
        return None

    def _set_current_tab(self, tab: "ModuleTab"):
        if tab in self.module_tabs:
            self.tabbar.setCurrentIndex(self.module_tabs.index(tab))

    def _on_tab_selected(self, _index: int):
        self._refresh_view()
        self._highlight_current()
        self._reveal_current()

    def _reveal_current(self):
        """Scroll the picked module's pane into view.

        Several panes in a row (or a tall grid) overflow the viewport, so the
        module you just selected is often off-screen — and an outline you
        can't see is no help. Deferred a tick: _refresh_view may still have an
        even-out queued, and the final geometry is what we scroll to.
        """
        tab = self._current_tab()
        if tab is None:
            return

        def go():
            if tab is self._current_tab() and tab.parent() is not \
                    self.pane_stash and tab.isVisible():
                self.scroll.ensureWidgetVisible(tab, 0, 0)
        QTimer.singleShot(0, go)

    def _pick_tab(self, _index: int):
        """Tab bar clicked: outline that module and scroll to it. Fires even
        when the tab was already current, which is how you get back to a pane
        you have scrolled away from."""
        self._highlight_current()
        self._reveal_current()

    def _highlight_current(self):
        """Outline the pane of the tab just picked, if more than one shows."""
        tab = self._current_tab()
        n = visible_pane_count([t.cfg.independent for t in self.module_tabs],
                               self.tabbar.currentIndex())
        self._highlight_tab(tab if n > 1 else None)

    def _highlight_tab(self, tab: "ModuleTab | None"):
        for t in self.module_tabs:
            t.set_highlight(t is tab)
        # Same outline on the tab itself: with several panes on screen the
        # pane border alone doesn't say which tab it belongs to.
        self.tabbar.set_highlight(
            self.module_tabs.index(tab) if tab in self.module_tabs else None,
            border_colors(tab.cfg.runtime) if tab is not None else None)
        self._highlighted = tab

    def _pane_of(self, w) -> "ModuleTab | None":
        """The module pane a clicked widget sits in, if any."""
        while w is not None:
            if isinstance(w, ModuleTab):
                return w if w in self.module_tabs else None
            w = w.parentWidget()
        return None

    def _activate_pane(self, tab: "ModuleTab"):
        """A click landed in this module: select its tab, outline both.

        Deferred a tick: this runs while a mouse press is being delivered and
        selecting a tab can re-lay-out the panes, which would eat the click.
        """
        def go():
            if tab not in self.module_tabs:
                return
            if tab is self._current_tab():
                self._highlight_current()
            else:
                self._set_current_tab(tab)   # _on_tab_selected highlights
        QTimer.singleShot(0, go)

    def _add_tab(self, cfg: ModuleConfig) -> ModuleTab:
        tab = ModuleTab(cfg)
        tab.sampler = self.sampler
        tab.set_meter_enabled(self.meters_on)
        tab.setParent(self.pane_stash)   # _refresh_view will place it
        tab.hide()
        self.module_tabs.append(tab)
        self.tabbar.addTab(cfg.name)
        # Update tab title when status changes (running indicator)
        tab.state_changed.connect(lambda: self._update_tab_display(tab))
        tab.config_changed.connect(lambda: save_configs(self.configs))
        tab.pane_clicked.connect(lambda t=tab: self._activate_pane(t))
        self._refresh_view()
        self._refresh_tab_colors()   # applies chip/full/none per current mode
        self._update_tab_display(tab)   # OS badge before the first state change
        return tab

    def _update_tab_display(self, tab: ModuleTab):
        """Update tab title with running status indicator."""
        tab.meter.set_colors(border_colors(tab.cfg.runtime))
        idx = self.module_tabs.index(tab) if tab in self.module_tabs else -1
        if idx >= 0:
            running = tab.app_proc is not None and \
                tab.app_proc.state() != QProcess.ProcessState.NotRunning
            indicator = "◆ " if running else ""
            self.tabbar.setTabText(idx, indicator + tab.cfg.name)
            self._set_os_badge(idx, tab)

    def _set_os_badge(self, idx: int, tab: ModuleTab):
        """Windows / Linux mark beside the tab's name, on the side the close
        button isn't. Modules that run anywhere get none."""
        tb = self.tabbar
        close_side = tb.style().styleHint(
            QStyle.StyleHint.SH_TabBar_CloseButtonPosition, None, tb)
        side = QTabBar.ButtonPosition.RightSide if close_side == 0 \
            else QTabBar.ButtonPosition.LeftSide
        need = tab.cfg.platform
        cur = tb.tabButton(idx, side)
        if cur is not None and cur.property("os_need") == need:
            return
        pm = os_badge(need, tb.devicePixelRatioF())
        badge = None
        if pm is not None:
            badge = QLabel()
            badge.setPixmap(pm)
            badge.setFixedSize(14, 12)
            badge.setProperty("os_need", need)
            badge.setToolTip(OS_BADGE_TIPS.get((need, tab.bridge), need))
        tb.setTabButton(idx, side, badge)
        if cur is not None:
            cur.deleteLater()    # setTabButton only hides the one it replaces

    def _on_tab_moved(self, frm: int, to: int):
        tab = self.module_tabs.pop(frm)
        self.module_tabs.insert(to, tab)
        self.configs = [t.cfg for t in self.module_tabs]
        save_configs(self.configs)
        self._refresh_view()
        self._refresh_tab_colors()
        self._highlight_tab(self._highlighted)   # indexes just shifted

    def _refresh_tab_colors(self):
        """Sync the tab bar's per-language colors/icons to the current mode."""
        sig = (self.tab_color_mode,
               tuple(t.cfg.runtime for t in self.module_tabs))
        if self._tab_color_sig == sig:
            self.tabbar.update()
            return
        self._tab_color_sig = sig
        tb = self.tabbar
        tb.color_mode = self.tab_color_mode
        tb.tab_colors = {}
        for i, tab in enumerate(self.module_tabs):
            tb.tab_colors[i] = LANG_COLORS.get(
                tab.cfg.runtime, ("#9AA0A6", "#9AA0A6"))
            tb.setTabIcon(i, lang_icon(tab.cfg.runtime)
                          if self.tab_color_mode == "chips" else QIcon())
        tb.update()

    def _set_tab_color_mode(self, mode: str):
        self.tab_color_mode = mode
        prefs = load_prefs()
        prefs["tab_color_mode"] = mode
        save_prefs(prefs)
        self._tab_color_sig = None      # force reapply
        self._refresh_tab_colors()

    def new_blank_tab(self):
        """Create an empty project + tab under apps/, and open its terminal to
        build in (write scripts, install deps), then Re-detect runtime."""
        base = BLANK_DIR
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "New Blank Tab",
                                f"Could not create apps folder:\n{e}")
            return
        n = 1
        while (base / f"blank-{n}").exists():
            n += 1
        d = base / f"blank-{n}"
        d.mkdir()
        cfg = ModuleConfig(name=f"Blank {n}", project_dir=str(d), entry="",
                           runtime="")
        self.configs.append(cfg)
        save_configs(self.configs)
        tab = self._add_tab(cfg)
        self.tabbar.setCurrentIndex(self.module_tabs.index(tab))
        tab._log(f"Blank tab at {d}\nUse the terminal to create files "
                 "and install deps, then right-click the tab ▸ Re-detect "
                 "runtime once it's a real project.")
        if TERMINAL_OK:
            tab.chk_term.setChecked(True)   # open the terminal in the new folder
        self._rebuild_modules_menu()

    def _redetect_runtime(self, index: int):
        tab = self.module_tabs[index]
        found = detect_runtimes(Path(tab.cfg.project_dir))
        if not found:
            tab._log("Re-detect: nothing runnable found yet.")
            self.statusBar().showMessage(
                "No runtime detected yet — add project files first.", 4000)
            return
        if tab.cfg.runtime == "custom":
            tab._log("Re-detect: your custom commands stay stored — set a run "
                     "command again to switch back to custom.")
        tab.cfg.runtime = found[0]
        entries = RUNTIMES[found[0]].entries(Path(tab.cfg.project_dir))
        tab.cfg.platform = detect_platform(
            Path(tab.cfg.project_dir), found[0],
            tab.cfg.entry if tab.cfg.entry in entries else
            (entries[0] if entries else ""))
        save_configs(self.configs)
        tab._set_status("idle")
        self._tab_color_sig = None
        self._refresh_tab_colors()
        tab._log(f"Runtime detected: {found[0]}. Press ▶ Start to run.")
        self.statusBar().showMessage(f"Runtime detected: {found[0]}", 4000)

    # -- view composition ---------------------------------------------------
    def _refresh_view(self):
        """Show the right set of module panes for the current selection.

        Independent module selected -> only that pane fills the window.
        Merge module selected       -> all merge-mode panes are arranged in
        the scroll area (single resizable row, or a wrapping grid of rows).
        """
        if not self.module_tabs:
            self.content.setCurrentWidget(self.empty_page)
            self._prev_visible = ()
            return
        self.content.setCurrentWidget(self.scroll)
        cur = self._current_tab()
        independent = cur is not None and cur.cfg.independent
        visible = [cur] if independent else \
            [t for t in self.module_tabs if not t.cfg.independent]
        visset = set(visible)
        # Park panes that shouldn't show, so arrangements only hold visible.
        for t in self.module_tabs:
            if t not in visset and t.parent() is not self.pane_stash:
                t.setParent(self.pane_stash)
                t.hide()
        if not visible:
            return
        if independent:
            self._arrange_row(visible, enforce_min=False)
        elif self.merge_mode == "grid":
            self._arrange_grid(visible)
        else:
            self._arrange_row(visible, enforce_min=True)

    def _activate_arrangement(self, widget: QWidget):
        lay = self._merge_root_layout
        if lay.count() == 1 and lay.itemAt(0).widget() is widget:
            return
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None and w is not widget:
                w.setParent(None)   # detach (kept as attribute, not deleted)
        lay.addWidget(widget)
        widget.show()

    def _arrange_row(self, panes, enforce_min: bool):
        self._activate_arrangement(self.row_splitter)
        for i, t in enumerate(panes):
            if self.row_splitter.indexOf(t) != i:
                self.row_splitter.insertWidget(i, t)  # reparents into splitter
            t.setMinimumSize(QSize(PANE_MIN_W, self.pane_min.height())
                             if enforce_min else QSize(1, 1))
            t.show()
        # The pane_min width floor belongs on the splitter, not on the panes.
        # A splitter can only give one pane what it takes from another, so
        # panes each pinned at pane_min leave zero slack and every handle is
        # frozen — which is why a row that overflowed the viewport couldn't be
        # resized at all. Same fix as GRID_MIN_H vertically: the row still
        # spans n x pane_min (so it scrolls exactly as before), but the widths
        # inside it are now free to move.
        self.row_splitter.setMinimumWidth(
            (len(panes) * self.pane_min.width()
             + max(0, len(panes) - 1) * self.row_splitter.handleWidth())
            if enforce_min else 0)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if enforce_min
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Even the panes only when the visible set changed (preserve drags).
        vis = tuple(id(t) for t in panes)
        if vis != self._prev_visible:
            self._prev_visible = vis
            QTimer.singleShot(0, lambda: self._even_split())

    def _arrange_grid(self, panes):
        self._activate_arrangement(self.grid_splitter)
        cols = self.merge_cols
        if cols <= 0:   # auto-fit to the viewport width
            vw = self.scroll.viewport().width()
            cols = max(1, vw // max(1, self.pane_min.width() + 4))
        chunks = [panes[i:i + cols] for i in range(0, len(panes), cols)]
        while len(self._grid_rows) < len(chunks):
            sp = QSplitter(Qt.Orientation.Horizontal)
            sp.setChildrenCollapsible(False)
            self._grid_rows.append(sp)
        for i, sp in enumerate(self._grid_rows):
            if i >= len(chunks):
                sp.setParent(self.pane_stash)   # park the unused rows
                sp.hide()
                continue
            if self.grid_splitter.indexOf(sp) != i:
                self.grid_splitter.insertWidget(i, sp)
            for j, t in enumerate(chunks[i]):
                if sp.indexOf(t) != j:
                    sp.insertWidget(j, t)   # reparents out of its old row
                # Height floor well under pane_min: a splitter can only give
                # a row what it takes from another, so if every row sits at
                # its minimum the whole column is frozen.
                t.setMinimumSize(PANE_MIN_W, GRID_MIN_H)
                t.show()
            # Same story sideways: without this the row is exactly the sum of
            # its panes' minimums whenever the column count overflows the
            # viewport, and the handles seize up.
            sp.setMinimumWidth(len(chunks[i]) * self.pane_min.width()
                               + max(0, len(chunks[i]) - 1) * sp.handleWidth())
            sp.show()
        # The splitter itself keeps the full-size total (rows x pane_min
        # height), so the slack above is redistribution, not shrinkage.
        self.grid_splitter.setMinimumHeight(
            len(chunks) * self.pane_min.height()
            + max(0, len(chunks) - 1) * self.grid_splitter.handleWidth())
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Re-even only when the shape changed, so a drag survives a refresh.
        vis = tuple(id(t) for t in panes) + (cols,)
        if vis != self._prev_visible:
            self._prev_visible = vis
            QTimer.singleShot(0, self._even_grid)

    def _even_split(self, force: bool = False):
        n = self.row_splitter.count()
        if n <= 1:
            return
        total = max(self.row_splitter.width(), n * self.pane_min.width())
        self.row_splitter.setSizes([total // n] * n)

    def _even_grid(self):
        rows = [sp for sp in self._grid_rows
                if sp.parent() is not self.pane_stash and sp.count()]
        if not rows:
            return
        total_h = max(self.grid_splitter.height(),
                      len(rows) * self.pane_min.height())
        self.grid_splitter.setSizes([total_h // len(rows)] * len(rows))
        for sp in rows:
            n = sp.count()
            total_w = max(sp.width(), n * self.pane_min.width())
            sp.setSizes([total_w // n] * n)

    def _save_view_prefs(self):
        """Persist the View menu's choices. Read-modify-write so this doesn't
        clobber tab_color_mode, which lives in the same file."""
        prefs = load_prefs()
        prefs["merge_mode"] = self.merge_mode
        prefs["merge_cols"] = self.merge_cols
        prefs["pane_min"] = [self.pane_min.width(), self.pane_min.height()]
        save_prefs(prefs)

    def _set_merge_mode(self, mode: str):
        self.merge_mode = mode
        # Update menu action checked state
        self.act_mode_row.setChecked(mode == "row")
        self.act_mode_grid.setChecked(mode == "grid")
        self.menu_cols.setEnabled(mode == "grid")
        self._prev_visible = ()   # force a re-even when relevant
        self._save_view_prefs()
        self._refresh_view()

    def _set_merge_cols(self, n: int):
        self.merge_cols = n
        self._save_view_prefs()
        if self.merge_mode == "grid":
            self._refresh_view()

    def _set_pane_min(self, w: int, h: int):
        self.pane_min = QSize(w, h)
        self._prev_visible = ()
        self._save_view_prefs()
        self._refresh_view()

    def _free_owner(self):
        """Windows: an embedded app's dialog must not lock the launcher."""
        if QApplication.activeModalWidget() is None:
            winplat.free_owner(int(self.winId()))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            # Clicks inside an embedded child go to X, not Qt — those arrive
            # as ModuleTab.pane_clicked instead. This covers the launcher's
            # own widgets: a pane's chrome selects that module, the tab bar
            # re-highlights right after (filters run before handlers), and
            # anything else drops the outline.
            w = obj if isinstance(obj, QWidget) else None
            if IS_WINDOWS and w is not None and not isinstance(w, EmbedHost):
                winplat.take_keyboard(int(self.winId()))
            pane = self._pane_of(w)
            if pane is not None:
                self._activate_pane(pane)
            elif self._highlighted is not None:
                self._highlight_tab(None)
        # Recompute auto-fit grid columns when the viewport is resized.
        if obj is self.scroll.viewport() \
                and event.type() == QEvent.Type.Resize \
                and self.merge_mode == "grid" and self.merge_cols <= 0 \
                and self.module_tabs:
            cur = self._current_tab()
            if not (cur is not None and cur.cfg.independent):
                vis = [t for t in self.module_tabs if not t.cfg.independent]
                if vis:
                    self._arrange_grid(vis)
        return super().eventFilter(obj, event)

    def _set_tab_mode(self, tab: "ModuleTab", independent: bool):
        if tab.cfg.independent != independent:
            tab.cfg.independent = independent
            save_configs(self.configs)
        if independent:
            self._set_current_tab(tab)  # take over the window now
        self._refresh_view()
        self._rebuild_modules_menu()

    def _choose_runtime_and_entry(self, proj: Path):
        """Detect the runtime (asking if ambiguous) and the launch entry.
        Returns (runtime_id, entry) or None if cancelled/unsupported."""
        rids = detect_runtimes(proj)
        if not rids:
            # No detection is not a dead end: the custom runtime mounts any
            # language, the user just has to say how to build and run it.
            if QMessageBox.question(
                    self, "Unsupported project",
                    "Couldn't detect a known runtime in that folder.\n"
                    "Looked for: Python, Node.js/Electron, native binaries "
                    "(Rust/Go/C/C++/make/cmake), Java, C#, Ruby, PHP, Docker "
                    "and web apps.\n\n"
                    "Add it as a custom module instead? You give the build and "
                    "run commands — any language works that way.") \
                    != QMessageBox.StandardButton.Yes:
                return None
            return "custom", ""
        if len(rids) == 1:
            rid = rids[0]
        else:
            labels = [RUNTIMES[r].label for r in rids]
            label, ok = QInputDialog.getItem(
                self, "Runtime",
                "This project matches more than one runtime — pick one:",
                labels, 0, False)
            if not ok:
                return None
            rid = rids[labels.index(label)]
        entries = RUNTIMES[rid].entries(proj)
        if not entries:
            return rid, ""
        if len(entries) == 1:
            return rid, entries[0]
        entry, ok = QInputDialog.getItem(
            self, "Entry",
            f"How should this {RUNTIMES[rid].label} module launch?",
            entries, 0, False)
        return (rid, entry) if ok else None

    def add_module(self, start=None):
        folder = QFileDialog.getExistingDirectory(
            self, "Select module project folder", start or self._start_dir())
        if not folder:
            return
        proj = Path(folder)
        self._remember_dir(str(proj.parent))   # siblings are the likely next
        choice = self._choose_runtime_and_entry(proj)
        if choice is None:
            return
        rid, entry = choice
        cfg = ModuleConfig(name=proj.name, project_dir=str(proj),
                           entry=entry, runtime=rid,
                           platform=detect_platform(proj, rid, entry))
        self.configs.append(cfg)
        save_configs(self.configs)
        tab = self._add_tab(cfg)
        self._set_current_tab(tab)
        self._rebuild_modules_menu()
        if rid == "custom":
            self._edit_custom_cmds(self.module_tabs.index(tab))
        tab.start()

    def _start_dir(self) -> str:
        """Where a folder picker opens: the last place used, else home."""
        last = load_prefs().get("last_dir", "")
        return last if last and Path(last).is_dir() else str(Path.home())

    def _remember_dir(self, folder: str):
        """Record a browse location for next time, and for Recent Folders."""
        prefs = load_prefs()
        prefs["last_dir"] = folder
        prefs["recent_dirs"] = push_recent(prefs.get("recent_dirs", []), folder)
        save_prefs(prefs)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        """File ▸ Recent Folders — reopen the picker straight into a tree."""
        self.menu_recent.clear()
        dirs = [d for d in load_prefs().get("recent_dirs", [])
                if Path(d).is_dir()]
        if not dirs and DEMO_DIR.is_dir():
            dirs = [str(DEMO_DIR)]      # somewhere useful before first use
        if not dirs:
            self.menu_recent.addAction("(none yet)").setEnabled(False)
            return
        home = str(Path.home())
        for d in dirs:
            act = self.menu_recent.addAction(
                d.replace(home, "~", 1) if d.startswith(home) else d)
            act.setToolTip(d)
            act.triggered.connect(lambda _c=False, p=d: self.add_module(p))

    def _register_projects_in(self, base: Path) -> int:
        """Register each subdir of `base` that has a detectable runtime and
        isn't already open. Paths are taken fresh from `base`, so wherever the
        repo lives the entries point at the current location. Returns count added."""
        open_dirs = {c.project_dir for c in self.configs}
        added = 0
        for sub in project_dirs_in(base):
            if str(sub) in open_dirs:
                continue
            rids = detect_runtimes(sub)
            if not rids:
                continue
            rid = rids[0]
            entries = RUNTIMES[rid].entries(sub)
            entry = entries[0] if entries else ""
            cfg = ModuleConfig(name=sub.name, project_dir=str(sub),
                               entry=entry, runtime=rid,
                               platform=detect_platform(sub, rid, entry))
            self.configs.append(cfg)
            self._add_tab(cfg)
            added += 1
        if added:
            save_configs(self.configs)
            self._rebuild_modules_menu()
        return added

    def scan_folder_for_modules(self, start=None):
        folder = QFileDialog.getExistingDirectory(
            self, "Scan folder for module projects",
            start or self._start_dir())
        if not folder:
            return
        self._remember_dir(folder)     # it holds projects — browse it again
        added = self._register_projects_in(Path(folder))
        self.statusBar().showMessage(
            f"Added {added} module(s) from {folder}." if added else
            f"No new module projects found in {folder}.", 6000)

    def load_bundled_demos(self, group: str = ""):
        """Register the showcase apps of one OS group (or all of them) that
        aren't already open."""
        where = DEMO_DIR / group if group else DEMO_DIR
        if not where.is_dir():
            QMessageBox.warning(self, "Load Demo Modules",
                                f"No demo folder found at:\n{where}")
            return
        added = self._register_projects_in(where)
        label = f"{group} demo" if group else "demo"
        self.statusBar().showMessage(
            f"Loaded {added} {label} module(s)." if added else
            f"All {label} modules already loaded.", 6000)

    def _rebuild_demo_menu(self):
        """One entry per OS group under demo_module/, plus All. Rebuilt on
        open, so a group folder added while the app runs shows up."""
        m = self.menu_demos
        m.clear()
        groups = sorted(d.name for d in DEMO_DIR.iterdir()
                        if d.is_dir() and not d.name.startswith((".", "__"))) \
            if DEMO_DIR.is_dir() else []
        for g in groups:
            n = len(project_dirs_in(DEMO_DIR / g))
            act = m.addAction(f"{g} ({n})")
            act.setEnabled(n > 0)
            act.triggered.connect(lambda _c=False, g=g: self.load_bundled_demos(g))
        if not groups:
            m.addAction("(no demo folder)").setEnabled(False)
            return
        m.addSeparator()
        m.addAction("All").triggered.connect(
            lambda _c=False: self.load_bundled_demos())

    def _close_tab(self, index: int):
        if not (0 <= index < len(self.module_tabs)):
            return
        tab = self.module_tabs[index]
        if QMessageBox.question(
                self, "Remove module",
                f"Remove '{tab.cfg.name}' from the base?\n"
                "(Project folder and venv stay on disk.)") \
                != QMessageBox.StandardButton.Yes:
            return
        tab.shutdown()
        self.configs.remove(tab.cfg)
        save_configs(self.configs)
        if self._highlighted is tab:
            self._highlighted = None
        self.module_tabs.pop(index)
        self.tabbar.removeTab(index)
        tab.setParent(None)
        tab.deleteLater()
        self._refresh_view()
        self._tab_color_sig = None       # indices shifted — force reapply
        self._refresh_tab_colors()
        self._rebuild_modules_menu()

    # -- tab context menu -----------------------------------------------------
    def _tab_context_menu(self, pos):
        index = self.tabbar.tabAt(pos)
        if index < 0:
            return
        tab = self.module_tabs[index]
        menu = QMenu(self)
        act_rename = menu.addAction("Rename…")
        act_save = menu.addAction("Save to Modules")
        act_scan_sub = menu.addAction("Scan for Sub-modules…")
        act_redetect = menu.addAction("Re-detect runtime")
        act_redetect.setToolTip("Re-scan this folder and set its runtime "
                                "(for blank tabs once files exist)")
        menu.addSeparator()
        act_indep = menu.addAction("Independent (fills window)")
        act_indep.setCheckable(True)
        act_indep.setChecked(tab.cfg.independent)
        act_indep.setToolTip("On = take over the whole window. "
                             "Off = merge/tile with other modules.")
        menu.addSeparator()
        act_embed = menu.addAction("Embed window")
        act_embed.setCheckable(True)
        act_embed.setChecked(tab.cfg.embed)
        act_shared = menu.addAction("Use shared environment")
        act_shared.setCheckable(True)
        act_shared.setChecked(tab.cfg.use_shared)
        menu.addSeparator()
        act_meter = menu.addAction("Resource meter")
        act_meter.setCheckable(True)
        act_meter.setChecked(tab.cfg.show_meter)
        act_meter.setEnabled(self.meters_on)
        act_meter.setToolTip(
            "CPU and memory for this module's process tree"
            if self.meters_on else
            "Turn View ▸ Resource meters on first")
        menu.addMenu(tab._build_logmode_menu(menu))
        menu.addSeparator()
        act_args = menu.addAction("Startup args…")
        act_args.setToolTip("Extra arguments appended on start — e.g. "
                            "--no-sandbox for an Electron module")
        act_env = menu.addAction("Environment variables…")
        act_env.setToolTip("NAME=value pairs added to this module's "
                           "environment for its setup and launch commands")
        m_plat = menu.addMenu("Runs on")
        m_plat.setToolTipsVisible(True)
        plat_acts = {}
        for need, label in PLATFORM_NEEDS.items():
            via = bridge_for(need)
            act = m_plat.addAction(label + {"wine": "  (via Wine here)",
                                            "wsl": "  (via WSL here)"}.get(via, ""))
            act.setCheckable(True)
            act.setChecked(tab.cfg.platform == need)
            plat_acts[act] = need
        act_custom = menu.addAction("Custom commands…")
        act_custom.setToolTip("Build and run this module with your own shell "
                              "commands — any language, detected or not")
        menu.addSeparator()
        act_close = menu.addAction("Close (remove from base)")
        chosen = menu.exec(self.tabbar.mapToGlobal(pos))
        if chosen == act_rename:
            self._rename_tab(index)
        elif chosen == act_save:
            self._save_module_to_library(index)
        elif chosen == act_scan_sub:
            self._scan_submodules(index)
        elif chosen == act_redetect:
            self._redetect_runtime(index)
        elif chosen == act_indep:
            self._set_tab_mode(tab, act_indep.isChecked())
        elif chosen == act_embed:
            tab.cfg.embed = act_embed.isChecked()
            save_configs(self.configs)
            if tab.cfg.embed and tab.app_proc is not None \
                    and tab.container is None:
                tab.retry_embed()
            elif not tab.cfg.embed and tab.container is not None:
                tab._log("Embed disabled — takes effect on restart.")
        elif chosen == act_meter:
            tab.cfg.show_meter = act_meter.isChecked()
            save_configs(self.configs)
            tab.set_meter_enabled(self.meters_on)
        elif chosen == act_shared:
            tab.cfg.use_shared = act_shared.isChecked()
            save_configs(self.configs)
            tab._log(("Shared" if tab.cfg.use_shared else "Private")
                     + " environment selected — takes effect on next start.")
        elif chosen == act_args:
            self._edit_startup_args(index)
        elif chosen == act_env:
            self._edit_env_vars(index)
        elif chosen == act_custom:
            self._edit_custom_cmds(index)
        elif chosen in plat_acts:
            tab.cfg.platform = plat_acts[chosen]
            save_configs(self.configs)
            tab._set_status(tab.status)
            tab._log("Runs on: " + PLATFORM_NEEDS[tab.cfg.platform]
                     + {"wine": " — through Wine on this machine.",
                        "wsl": " — through WSL on this machine."}.get(
                            tab.bridge, ".") + " Takes effect on next start.")
        elif chosen == act_close:
            self._close_tab(index)

    def _edit_startup_args(self, index: int):
        """Edit a module's extra argv. The sandbox hint tells people to add
        --no-sandbox here, so there has to be a here."""
        tab = self.module_tabs[index]
        text, ok = QInputDialog.getText(
            self, "Startup args",
            f"Arguments appended when '{tab.cfg.name}' starts\n"
            "(shell quoting applies; blank for none):",
            text=" ".join(shlex.quote(a) for a in tab.cfg.startup_args))
        if not ok:
            return
        try:
            args = shlex.split(text)
        except ValueError as e:
            QMessageBox.warning(self, "Startup args",
                                f"Could not parse: {e}")
            return
        tab.cfg.startup_args = args
        save_configs(self.configs)
        tab._log(f"Startup args: {args if args else '(none)'} "
                 "— takes effect on next start.")

    def _edit_env_vars(self, index: int):
        """Edit a module's launch environment.

        cfg.extra_env has always been honored at launch; this is the way to
        reach it without hand-editing modules.json.
        """
        tab = self.module_tabs[index]
        cfg = tab.cfg
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Environment variables — {cfg.name}")
        v = QVBoxLayout(dlg)
        intro = QLabel("One NAME=value per line, added to the environment of "
                       "this module's setup and launch commands.\n"
                       "Blank lines and lines starting with # are ignored.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        box = QPlainTextEdit("\n".join(f"{k}={val}"
                                       for k, val in cfg.extra_env.items()))
        box.setPlaceholderText("DEBUG=1\nAPI_URL=http://localhost:8000\n"
                               "EXTRA_PIP_PACKAGES=rich pandas")
        v.addWidget(box, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.resize(520, 320)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        env, bad = {}, []
        for line in box.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, val = line.partition("=")
            key = key.strip()
            if not sep or not key:
                bad.append(line)
                continue
            env[key] = val.strip()
        if bad:
            QMessageBox.warning(self, "Environment variables",
                                "Ignored — each line needs NAME=value:\n  "
                                + "\n  ".join(bad[:8]))
        cfg.extra_env = env
        save_configs(self.configs)
        tab._log(f"Environment: {', '.join(sorted(env)) or '(none)'} "
                 "— takes effect on next start.")

    def _edit_custom_cmds(self, index: int) -> bool:
        """Set a module's own build/run commands.

        The escape hatch for every language without a runtime class: filling in
        a run command switches the module to the custom runtime.
        """
        tab = self.module_tabs[index]
        cfg = tab.cfg
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Custom commands — {cfg.name}")
        v = QVBoxLayout(dlg)
        intro = QLabel(f"Run in  {cfg.project_dir}\n"
                       "through your login shell, so &&, pipes and the PATH "
                       "from your profile all work.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        v.addWidget(QLabel("Setup (optional) — fetch deps / build, runs first:"))
        e_setup = QLineEdit(cfg.custom_setup)
        e_setup.setPlaceholderText("cpanm --installdeps .   ·   luarocks install …"
                                   "   ·   mix deps.get && mix compile")
        v.addWidget(e_setup)
        v.addWidget(QLabel("Run — starts the app (startup args are appended):"))
        e_run = QLineEdit(cfg.custom_run)
        e_run.setPlaceholderText("wish gui.tcl   ·   perl app.pl   ·   "
                                 "lua main.lua   ·   ./run.sh")
        v.addWidget(e_run)
        chk = QCheckBox("It serves a URL — embed a browser instead of a window")
        chk.setToolTip("For a custom web server: the launcher watches its "
                       "output for a URL and opens a browser pane on it.")
        chk.setChecked(cfg.custom_serves)
        v.addWidget(chk)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        cfg.custom_setup = e_setup.text().strip()
        cfg.custom_run = e_run.text().strip()
        cfg.custom_serves = chk.isChecked()
        if cfg.custom_run and cfg.runtime != "custom":
            tab._log(f"Runtime switched from {cfg.runtime!r} to 'custom'.")
            cfg.runtime = "custom"
            self._tab_color_sig = None
            self._refresh_tab_colors()
        save_configs(self.configs)
        tab._log(f"Custom run: {cfg.custom_run or '(none)'}"
                 + (f"\nCustom setup: {cfg.custom_setup}"
                    if cfg.custom_setup else "")
                 + "\nTakes effect on next start.")
        self._update_tab_display(tab)
        return True

    # -- sub-module scan --------------------------------------------------------
    def _scan_submodules(self, index: int):
        parent = self.module_tabs[index]
        proj = Path(parent.cfg.project_dir)
        rt = RUNTIMES.get(parent.cfg.runtime, PythonRuntime)
        candidates = rt.submodules(proj, parent.cfg.entry)
        if not candidates:
            QMessageBox.information(
                self, "Scan for Sub-modules",
                f"No additional runnable entries found for this "
                f"{rt.label} module besides the current one.\n\n"
                "(Python: .py files with a __main__ guard; "
                "Node/web: extra package.json scripts.)")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Sub-modules in {parent.cfg.name}")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Check the scripts to open as new tabs "
                             "(they share this module's environment):"))
        lst = QListWidget()
        for rel in candidates:
            item = QListWidgetItem(rel)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            lst.addItem(item)
        lay.addWidget(lst, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        dlg.resize(520, 420)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        open_keys = {(c.project_dir, c.entry) for c in self.configs}
        last = None
        for i in range(lst.count()):
            item = lst.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            rel = item.text()
            if (parent.cfg.project_dir, rel) in open_keys:
                continue
            name = rel.split(":")[-1] if ":" in rel else Path(rel).stem
            cfg = ModuleConfig(name=name,
                               project_dir=parent.cfg.project_dir,
                               entry=rel,
                               runtime=parent.cfg.runtime,
                               embed=parent.cfg.embed,
                               use_shared=parent.cfg.use_shared,
                               independent=parent.cfg.independent)
            self.configs.append(cfg)
            last = self._add_tab(cfg)
            last.start()
        save_configs(self.configs)
        self._rebuild_modules_menu()
        if last is not None:
            self._set_current_tab(last)

    # -- module library -------------------------------------------------------
    def _save_module_to_library(self, index: int):
        cfg = self.module_tabs[index].cfg
        entries = load_library()
        entries = [e for e in entries
                   if not (e["project_dir"] == cfg.project_dir
                           and e["entry"] == cfg.entry)]
        entries.append(asdict(cfg))
        save_library(entries)
        self._rebuild_modules_menu()
        self.statusBar().showMessage(
            f"Saved '{cfg.name}' to Modules.", 4000)

    def _rebuild_modules_menu(self):
        self.menu_modules.clear()

        # Per-open-tab display-mode toggle (mirrors the tab right-click menu).
        disp = self.menu_modules.addMenu("Tab Display Mode")
        if self.module_tabs:
            for tab in self.module_tabs:
                act = disp.addAction(f"{tab.cfg.name} — Independent")
                act.setCheckable(True)
                act.setChecked(tab.cfg.independent)
                act.toggled.connect(
                    lambda checked, t=tab: self._set_tab_mode(t, checked))
        else:
            disp.addAction("(no open tabs)").setEnabled(False)
        self.menu_modules.addSeparator()

        entries = load_library()
        if not entries:
            self.menu_modules.addAction("(no saved modules)").setEnabled(
                False)
            return
        for e in entries:
            act = self.menu_modules.addAction(e["name"])
            act.setStatusTip(e["project_dir"])
            act.triggered.connect(
                lambda _=False, d=dict(e): self._open_saved_module(d))
        self.menu_modules.addSeparator()
        m_rm = self.menu_modules.addMenu("Remove Saved Module")
        for e in entries:
            act = m_rm.addAction(e["name"])
            act.triggered.connect(
                lambda _=False, d=dict(e): self._remove_saved_module(d))

    def _open_saved_module(self, d: dict):
        for i, tab in enumerate(self.module_tabs):
            cfg = tab.cfg
            if cfg.project_dir == d["project_dir"] \
                    and cfg.entry == d["entry"]:
                self.tabbar.setCurrentIndex(i)
                return
        cfg = _config_from_dict(d)
        self.configs.append(cfg)
        save_configs(self.configs)
        tab = self._add_tab(cfg)
        self._set_current_tab(tab)
        self._rebuild_modules_menu()
        tab.start()

    def _remove_saved_module(self, d: dict):
        entries = [e for e in load_library()
                   if not (e["project_dir"] == d["project_dir"]
                           and e["entry"] == d["entry"])]
        save_library(entries)
        self._rebuild_modules_menu()

    # -- layouts ----------------------------------------------------------------
    def _current_layout(self) -> list[dict]:
        return [{**asdict(tab.cfg),
                 "project_dir": portable_path(tab.cfg.project_dir)}
                for tab in self.module_tabs]

    def _save_layout(self):
        layouts = load_layouts()
        name, ok = QInputDialog.getText(
            self, "Save Layout", "Layout name:",
            text=f"Layout {len(layouts) + 1}")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in layouts and QMessageBox.question(
                self, "Overwrite layout",
                f"Layout '{name}' exists. Overwrite?") \
                != QMessageBox.StandardButton.Yes:
            return
        layouts[name] = self._current_layout()
        save_layouts(layouts)
        self._rebuild_layout_menus()
        self.statusBar().showMessage(f"Layout '{name}' saved.", 4000)

    def _rebuild_layout_menus(self):
        for menu, handler in ((self.menu_load_layout, self._load_layout),
                              (self.menu_del_layout, self._delete_layout)):
            menu.clear()
            layouts = load_layouts()
            if not layouts:
                menu.addAction("(no layouts)").setEnabled(False)
                continue
            for name in sorted(layouts):
                act = menu.addAction(name)
                act.triggered.connect(
                    lambda _=False, n=name, h=handler: h(n))

    def _load_layout(self, name: str):
        layout = load_layouts().get(name)
        if layout is None:
            return
        if self.module_tabs and QMessageBox.question(
                self, "Load layout",
                f"Load '{name}'? Current tabs will be closed "
                "(running modules stopped).") \
                != QMessageBox.StandardButton.Yes:
            return
        while self.module_tabs:
            tab = self.module_tabs.pop(0)
            tab.shutdown()
            self.tabbar.removeTab(0)
            tab.setParent(None)
            tab.deleteLater()
        self.configs = [_config_from_dict(d) for d in layout]
        save_configs(self.configs)
        for cfg in self.configs:
            self._add_tab(cfg).start()
        if self.module_tabs:
            self.tabbar.setCurrentIndex(0)
        self._refresh_view()
        self._rebuild_modules_menu()
        self.statusBar().showMessage(f"Layout '{name}' loaded.", 4000)

    def _delete_layout(self, name: str):
        if QMessageBox.question(self, "Delete layout",
                                f"Delete layout '{name}'?") \
                != QMessageBox.StandardButton.Yes:
            return
        layouts = load_layouts()
        layouts.pop(name, None)
        save_layouts(layouts)
        self._rebuild_layout_menus()

    def _rename_tab(self, index: int):
        if not (0 <= index < len(self.module_tabs)):
            return
        tab = self.module_tabs[index]
        name, ok = QInputDialog.getText(self, "Rename tab", "New name:",
                                        text=tab.cfg.name)
        if ok and name.strip():
            tab.cfg.name = name.strip()
            self.tabbar.setTabText(index, tab.cfg.name)
            tab.name_label.setText(f"<b>{tab.cfg.name}</b>")  # in-window label too
            save_configs(self.configs)
            self._rebuild_modules_menu()

    def closeEvent(self, event):
        # __init__ filtered the whole application; leaving that in place means
        # Qt keeps calling into this window after Python has collected it.
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        for tab in self.module_tabs:
            tab.shutdown()
        save_configs(self.configs)
        prefs = load_prefs()
        prefs["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        save_prefs(prefs)
        super().closeEvent(event)


SELFTEST_PROBE = (
    "import tkinter as tk\n"
    "r = tk.Tk(); r.title('ub-selftest'); r.geometry('320x200')\n"
    "tk.Label(r, text='Unified Base self-test').pack(expand=True)\n"
    "r.after(30000, r.destroy); r.mainloop()\n")


def selftest() -> int:
    """`main.py --selftest`: what works on this machine, checked for real.

    Mostly for Windows, where none of this could be tried while it was being
    written: it launches a small Tk window, finds it by pid, embeds it, and
    probes WSL / Wine / winget / the browser. Paste the output back.
    """
    from PyQt6.QtCore import QT_VERSION_STR
    app = QApplication.instance() or QApplication(sys.argv[:1])
    fails = 0

    def row(name, ok, detail=""):
        nonlocal fails
        tag = "INFO" if ok is None else ("PASS" if ok else "FAIL")
        fails += ok is False
        print(f"  {tag}  {name:30} {detail}", flush=True)

    def run(cmd, timeout=30):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout)
            out = (r.stdout or b"").replace(b"\0", b"").decode(errors="replace")
            return r.returncode, out.strip()
        except (OSError, subprocess.SubprocessError) as e:
            return -1, str(e)

    print(f"Unified Base self-test — {platform.system()} {platform.release()}, "
          f"Python {platform.python_version()}, Qt {QT_VERSION_STR}, "
          f"platform plugin {QGuiApplication.platformName()}")
    row("embedding available", EMBEDDING_OK)
    row("window lookup", None, embed_diagnostics())
    row("browser for web modules", find_browser() is not None,
        find_browser() or "none found")
    row("full terminal", TERMINAL_OK)
    if IS_WINDOWS:
        row("winget (Install button)", bool(shutil.which("winget")))
        if wsl_ready():
            code, out = run(["wsl.exe", "--exec", "echo", "ub-wsl-ok"], 60)
            row("WSL runs commands", "ub-wsl-ok" in out, out[-60:])
            code, out = run(["wsl.exe", "--exec", "sh", "-c",
                             "echo DISPLAY=$DISPLAY WAYLAND=$WAYLAND_DISPLAY"])
            row("WSLg (Linux GUI apps)", "DISPLAY=:" in out, out)
            # One name per `command -v`: dash's checks only its first, so this
            # said "python3" whatever else was there. Linux PATH only, login
            # shell — as the modules see it.
            code, out = run(["wsl.exe", "--exec", "bash", "-lc",
                             WSL_LINUX_PATH + "for t in python3 node java "
                             "dotnet cargo ruby php docker; do command -v $t "
                             ">/dev/null && echo $t; done"])
            row("toolchains inside WSL", None, " ".join(out.split()) or "none")
            row("Linux windows embed", None,
                f"yes, X server on {wsl_x_display()}" if wsl_x_display()
                else "no — WSLg (run VcXsrv + mirrored networking to embed)")
        else:
            row("WSL (Linux modules)", False,
                "not set up — admin PowerShell: wsl --install, then restart")
    else:
        w = wine_program()
        if w:
            code, out = run([w, "--version"])
            row("Wine (Windows modules)", code == 0, out)
        else:
            row("Wine (Windows modules)", False,
                toolchain_install_cmd("wine") or "not installed")
    if not EMBEDDING_OK:
        print("  (no display — skipping the embed round trip)")
        return 1 if fails else 0

    probe = subprocess.Popen([sys.executable, "-c", SELFTEST_PROBE])
    t0, wid = time.monotonic(), None
    while time.monotonic() - t0 < 20 and wid is None:
        app.processEvents()
        time.sleep(0.2)
        hits = windows_for_pids(descendant_pids(probe.pid))
        wid = hits[0] if hits else None
    row("find a window by pid", wid is not None,
        f"{time.monotonic() - t0:.1f} s" if wid else "timed out (20 s)")
    if wid is not None:
        holder = QWidget()
        holder.setWindowTitle("Unified Base self-test host")
        holder.resize(420, 300)
        lay = QVBoxLayout(holder)
        try:
            host = EmbedHost(wid, holder)
            lay.addWidget(host)
            holder.show()
            end = time.monotonic() + 1.5
            while time.monotonic() < end:
                app.processEvents()
                time.sleep(0.05)
            row("embed the window", host.verify(),
                f"0x{wid:x} parented under the host")
            if IS_WINDOWS:
                # Parented isn't drawing: Tk once hid all its content here.
                kids = winplat.child_windows(wid)
                row("embedded content shown",
                    any(winplat.IsWindowVisible(k) for k in kids),
                    f"{len(kids)} child window(s)")
            host._resize_child()
            row("child still alive after resize", host.child_alive())
            host.detach()
        except Exception as e:
            row("embed the window", False, f"{type(e).__name__}: {e}")
        holder.close()
    stopped = kill_process_tree(probe.pid, SIGKILL)
    try:
        probe.wait(5)
    except subprocess.TimeoutExpired:
        pass
    row("stop the process tree", probe.poll() is not None,
        f"{stopped} process(es) signalled")
    print("FAILURES:", fails)
    return 1 if fails else 0


def install_crash_guard(log_file: Path, report=None) -> logging.Handler | None:
    """An exception in a Qt callback must not take the launcher down. PyQt6's
    default aborts the process: every embedded module loses its window while
    its processes run on untracked, and on Windows (console hidden) the
    launcher just vanished. Log it — to `log_file` too, since stderr is
    invisible there — tell `report`, and carry on. Returns the file handler."""
    handler = None
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=1 << 20, backupCount=1, encoding="utf-8")
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except OSError:
        pass

    def hook(etype, value, tb):
        logger.error("Unhandled error:\n" + "".join(
            traceback.format_exception(etype, value, tb)))
        if report is not None:
            try:
                report(f"Internal error ({etype.__name__}: {value}) — "
                       f"details in {log_file}")
            except RuntimeError:          # window already gone
                pass
    sys.excepthook = hook
    return handler


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if IS_WINDOWS:
        # Launched by run.bat in a console of its own: hide it. Module
        # processes inherit this hidden console instead of each opening one.
        winplat.hide_own_console()
    # Never start silently: name the Qt platform so a window that fails to
    # appear (e.g. a wedged XWayland after a crash) isn't a blank terminal.
    plat = os.environ.get("QT_QPA_PLATFORM") or "(Qt default)"
    print(f"Unified Base: starting on Qt platform '{plat}', "
          f"embedding={'on' if EMBEDDING_OK else 'off'}.",
          file=sys.stderr, flush=True)
    if IS_WAYLAND_SESSION and plat == "xcb":
        print("  Wayland session detected; using XWayland for window "
              "embedding. If no window appears, XWayland may be wedged — "
              "reboot, or run with UNIFIED_BASE_NATIVE=1 to use native "
              "Wayland (embedding disabled).", file=sys.stderr, flush=True)
    app = QApplication(sys.argv)
    app.setApplicationName("Unified Base")
    win = UnifiedBase()
    install_crash_guard(APP_DIR / "unified_base.log",
                        lambda m: win.statusBar().showMessage(m, 20000))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
