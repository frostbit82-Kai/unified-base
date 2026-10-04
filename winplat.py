"""Windows backend for Unified Base.

Everything main.py does with X11 and /proc on Linux, done here with user32 and
psutil. main.py imports this module only when running on Windows and rebinds
its platform functions to the ones below, so every call site stays the same:

    window discovery   EnumWindows + GetWindowThreadProcessId
    embedding          SetParent, with the style changes Windows requires
    process trees      psutil (one Toolhelp snapshot per walk)
    polite stop        WM_CLOSE to the tree's windows; forced = TerminateProcess
    terminal           a real conhost console window, embedded like any app

Nothing here can be exercised on Linux; test_core's Windows checks run the
pure parts, and `main.py --selftest` reports on the rest on a real machine.
"""
import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys
from ctypes import wintypes

import psutil
from PyQt6.QtCore import QEvent, QProcess, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPlatformSurfaceEvent
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

logger = logging.getLogger("unified_base")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Must match main.py's values on Windows (it has no os.sysconf, so it falls
# back to these): the sampler turns ticks into percent with them.
CLK_TCK = 100
PAGE_SIZE = 4096

# --- constants ---------------------------------------------------------------
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_MAXIMIZE = 0x01000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_WINDOWEDGE = 0x00000100
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_NOPARENTNOTIFY = 0x00000004
WS_EX_TOPMOST = 0x00000008
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0010, 0x0020, 0x0040
SW_HIDE, SW_SHOW, SW_RESTORE = 0, 5, 9
GW_OWNER = 4
GA_PARENT = 1
WM_CLOSE = 0x0010
WM_PARENTNOTIFY = 0x0210
CLICKS = {0x0201, 0x0204, 0x0207, 0x020B, 0x0246}   # L/R/M/X button, pointer down

# --- prototypes ----------------------------------------------------------------
# Declared explicitly: ctypes' default int return truncates 64-bit HWNDs.
HWND = wintypes.HWND
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", HWND), ("hwndFocus", HWND),
                ("hwndCapture", HWND), ("hwndMenuOwner", HWND),
                ("hwndMoveSize", HWND), ("hwndCaret", HWND),
                ("rcCaret", wintypes.RECT)]


def _proto(dll, name, res, *args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = res, list(args)
    return fn


EnumWindows = _proto(user32, "EnumWindows", wintypes.BOOL, WNDENUMPROC,
                     wintypes.LPARAM)
EnumChildWindows = _proto(user32, "EnumChildWindows", wintypes.BOOL, HWND,
                          WNDENUMPROC, wintypes.LPARAM)
GetWindowThreadProcessId = _proto(user32, "GetWindowThreadProcessId",
                                  wintypes.DWORD, HWND,
                                  ctypes.POINTER(wintypes.DWORD))
IsWindow = _proto(user32, "IsWindow", wintypes.BOOL, HWND)
IsWindowVisible = _proto(user32, "IsWindowVisible", wintypes.BOOL, HWND)
IsIconic = _proto(user32, "IsIconic", wintypes.BOOL, HWND)
IsChild = _proto(user32, "IsChild", wintypes.BOOL, HWND, HWND)
GetWindowRect = _proto(user32, "GetWindowRect", wintypes.BOOL, HWND,
                       ctypes.POINTER(wintypes.RECT))
GetClassNameW = _proto(user32, "GetClassNameW", ctypes.c_int, HWND,
                       wintypes.LPWSTR, ctypes.c_int)
GetWindowTextW = _proto(user32, "GetWindowTextW", ctypes.c_int, HWND,
                        wintypes.LPWSTR, ctypes.c_int)
GetWindow = _proto(user32, "GetWindow", HWND, HWND, wintypes.UINT)
GetAncestor = _proto(user32, "GetAncestor", HWND, HWND, wintypes.UINT)
SetParent = _proto(user32, "SetParent", HWND, HWND, HWND)
SetWindowPos = _proto(user32, "SetWindowPos", wintypes.BOOL, HWND, HWND,
                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                      wintypes.UINT)
MoveWindow = _proto(user32, "MoveWindow", wintypes.BOOL, HWND, ctypes.c_int,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL)
ShowWindow = _proto(user32, "ShowWindow", wintypes.BOOL, HWND, ctypes.c_int)
PostMessageW = _proto(user32, "PostMessageW", wintypes.BOOL, HWND,
                      wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
SetFocus = _proto(user32, "SetFocus", HWND, HWND)
GetGUIThreadInfo = _proto(user32, "GetGUIThreadInfo", wintypes.BOOL,
                          wintypes.DWORD, ctypes.POINTER(GUITHREADINFO))
# 64-bit Windows has the Ptr variants; 32-bit exports only the plain ones.
_GetLong = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_GetLong.restype, _GetLong.argtypes = ctypes.c_ssize_t, [HWND, ctypes.c_int]
_SetLong = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_SetLong.restype = ctypes.c_ssize_t
_SetLong.argtypes = [HWND, ctypes.c_int, ctypes.c_ssize_t]
GetConsoleWindow = _proto(kernel32, "GetConsoleWindow", HWND)
GetConsoleProcessList = _proto(kernel32, "GetConsoleProcessList",
                               wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.DWORD)


def _signed(v: int) -> int:
    """Style words come back as signed pointers; WS_POPUP is the sign bit."""
    return v & 0xFFFFFFFF


# --- window queries --------------------------------------------------------------
def _h(hwnd) -> int:
    return int(hwnd or 0)


def top_windows() -> list[int]:
    out: list[int] = []

    @WNDENUMPROC
    def cb(hwnd, _lp):
        out.append(_h(hwnd))
        return True
    EnumWindows(cb, 0)
    return out


def child_windows(parent: int) -> list[int]:
    out: list[int] = []

    @WNDENUMPROC
    def cb(hwnd, _lp):
        out.append(_h(hwnd))
        return True
    EnumChildWindows(parent, cb, 0)
    return out


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_thread(hwnd: int) -> int:
    return int(GetWindowThreadProcessId(hwnd, None))


def window_size(hwnd: int) -> tuple[int, int]:
    r = wintypes.RECT()
    if not GetWindowRect(hwnd, ctypes.byref(r)):
        return 0, 0
    return r.right - r.left, r.bottom - r.top


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    GetWindowTextW(hwnd, buf, 512)
    return buf.value


def is_app_window(hwnd: int) -> bool:
    """A real application window: visible, top-level in its own right (no
    owner — owned windows are dialogs and popups), not a tool palette, and
    bigger than a tray stub."""
    if not IsWindowVisible(hwnd) or _h(GetWindow(hwnd, GW_OWNER)):
        return False
    if _signed(_GetLong(hwnd, GWL_EXSTYLE)) & WS_EX_TOOLWINDOW:
        return False
    w, h = window_size(hwnd)
    return w > 32 and h > 32


def windows_for_pids(pids: set[int]) -> list[int]:
    """App windows owned by any of `pids`, largest first."""
    cands = []
    for h in top_windows():
        if window_pid(h) in pids and is_app_window(h):
            w, hh = window_size(h)
            cands.append((h, w * hh))
    return [h for h, _ in sorted(cands, key=lambda t: -t[1])]


def all_window_ids(max_depth: int = 6) -> set[int]:
    return set(top_windows())


def _exe_name(pid: int, cache: dict) -> str:
    if pid not in cache:
        try:
            cache[pid] = psutil.Process(pid).name().lower()
        except psutil.Error:
            cache[pid] = ""
    return cache[pid]


def new_windows_since(baseline: set[int], own_pid: int, max_depth: int = 6,
                      owners=None) -> list[int]:
    """App windows that appeared since `baseline`, largest first.

    `owners` narrows it to windows of those executables — msrdc.exe for WSLg —
    which is what keeps a Linux app's window from being confused with
    whatever a neighbouring module opened at the same moment.
    """
    names: dict = {}
    cands = []
    for h in top_windows():
        if h in baseline or not is_app_window(h):
            continue
        pid = window_pid(h)
        if pid == own_pid:
            continue
        if owners and _exe_name(pid, names) not in owners:
            continue
        w, hh = window_size(h)
        cands.append((h, w * hh))
    return [h for h, _ in sorted(cands, key=lambda t: -t[1])]


LXSS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Lxss"


def wsl_ready() -> bool:
    """WSL is installed *and* has a distro to run Linux modules in.

    wsl.exe on PATH proves nothing: Windows 11 ships it in System32 as a stub
    that only prints "not installed" (in UTF-16, on stderr). Every registered
    distro has a key under Lxss with its name, read here without starting the
    WSL VM."""
    import winreg
    if not shutil.which("wsl.exe"):
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LXSS_KEY) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                with winreg.OpenKey(k, winreg.EnumKey(k, i)) as d:
                    try:
                        if winreg.QueryValueEx(d, "DistributionName")[0]:
                            return True
                    except OSError:
                        continue
    except OSError:
        pass
    return False


X_SERVERS = ("vcxsrv.exe", "x410.exe", "xming.exe")


def wsl_x_display() -> str | None:
    """DISPLAY that puts a Linux module's windows on a Windows X server.

    WSLg's windows belong to msrdc.exe, which refuses SetParent; an X server
    on Windows draws ordinary Win32 windows that embed. Only when one is
    running, and WSL's mirrored networking makes 127.0.0.1 this machine
    (VcXsrv admits localhost only, via X0.hosts — no -ac)."""
    try:
        with open(os.path.join(os.path.expanduser("~"), ".wslconfig"),
                  encoding="utf-8", errors="replace") as f:
            mirrored = re.search(r"(?im)^\s*networkingMode\s*=\s*mirrored",
                                 f.read())
    except OSError:
        return None
    if mirrored and any((p.info["name"] or "").lower() in X_SERVERS
                        for p in psutil.process_iter(["name"])):
        return "127.0.0.1:0"
    return None


def embed_diagnostics() -> str:
    return (f"window lookup: user32 OK, psutil {psutil.__version__}, "
            f"WSL {'ready' if wsl_ready() else 'not set up'}")


# --- processes -----------------------------------------------------------------------
def _ppid_map() -> dict[int, int]:
    try:
        return psutil._psplatform.ppid_map()      # one Toolhelp32 snapshot
    except Exception:
        out = {}
        for p in psutil.process_iter(["ppid"]):
            out[p.pid] = p.info.get("ppid") or 0
        return out


def tree_from_children(roots) -> set[int]:
    """Every pid at or under `roots`, from a single process snapshot."""
    kids: dict[int, list[int]] = {}
    for pid, ppid in _ppid_map().items():
        if pid != ppid:                       # pid 0 lists itself as parent
            kids.setdefault(ppid, []).append(pid)
    out, stack = set(roots), list(roots)
    while stack:
        for c in kids.get(stack.pop(), ()):
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


def descendant_pids(root_pid: int) -> set[int]:
    return tree_from_children([root_pid])


def _own_child_windows() -> list[int]:
    """Windows parented inside this launcher — i.e. the embedded apps, which
    are no longer top-level and so invisible to EnumWindows."""
    me = os.getpid()
    out = []
    for h in top_windows():
        if window_pid(h) == me:
            out += child_windows(h)
    return out


def kill_pid(pid: int, sig: int) -> str:
    """main.kill_pid, Windows: 'ok', 'gone' or 'denied'. os.kill can't tell a
    process that already exited — still listed while anyone (our QProcess)
    holds a handle — from one we may not touch: TerminateProcess says access
    denied to both. psutil checks which, so a browser that closed on its own
    no longer reads as stuck."""
    try:
        psutil.Process(pid).kill()
        return "ok"
    except psutil.NoSuchProcess:
        return "gone"
    except psutil.AccessDenied:
        return "denied"


def kill_process_tree(pid: int, sig: int = 15) -> int:
    """Stop a process tree. sig 9 forces (TerminateProcess); anything else is
    the polite path: WM_CLOSE to every window the tree owns — what clicking X
    does — and a forced stop only for a tree with no window to ask.

    Windowless members of a windowed tree are left alone on the polite pass:
    they are usually the app's own helpers (Electron renderers, a language
    server), and killing them first crashes the app instead of closing it.
    main.py follows up with a forced pass three seconds later anyway.
    """
    pids = descendant_pids(pid)
    if sig != 9:
        asked = 0
        for h in top_windows() + _own_child_windows():
            if window_pid(h) in pids and IsWindowVisible(h) \
                    and not _h(GetWindow(h, GW_OWNER)):
                PostMessageW(h, WM_CLOSE, 0, 0)
                asked += 1
        if asked:
            return asked
    hit = 0
    for p in sorted(pids, reverse=True):
        try:
            psutil.Process(p).kill()
            hit += 1
        except psutil.Error:
            continue
    return hit


def pids_with_arg(needle: str) -> set[int]:
    out: set[int] = set()
    if len(needle) < 8:
        return out
    mine = os.getpid()
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.info["pid"] != mine and \
                    needle in " ".join(p.info["cmdline"] or ()):
                out.add(p.info["pid"])
        except (psutil.Error, TypeError):
            continue
    return out


def proc_table(pids=None) -> dict:
    """pid -> (ppid, cpu_ticks, rss_pages), the shape main's sampler expects."""
    ppids = _ppid_map()
    out = {}
    for pid in (pids if pids is not None else list(ppids)):
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                t = p.cpu_times()
                rss = p.memory_info().rss
        except psutil.Error:
            continue
        out[pid] = (ppids.get(pid, 0), int((t.user + t.system) * CLK_TCK),
                    rss // PAGE_SIZE)
    return out


# --- environment ---------------------------------------------------------------------
def refresh_path() -> list[str]:
    """Pull PATH entries added since launch (by a winget install) from the
    registry. A running process never sees installer PATH changes otherwise,
    so a freshly installed `node` would still read as missing. Returns the
    entries it added."""
    import winreg
    keys = ((winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, "Environment"))
    have = os.environ.get("PATH", "").split(os.pathsep)
    seen = {p.lower().rstrip("\\") for p in have if p}
    added = []
    for root, sub in keys:
        try:
            with winreg.OpenKey(root, sub) as k:
                val, _t = winreg.QueryValueEx(k, "Path")
        except OSError:
            continue
        for part in os.path.expandvars(val).split(os.pathsep):
            norm = part.lower().rstrip("\\")
            if part and norm not in seen:
                seen.add(norm)
                added.append(part)
    if added:
        os.environ["PATH"] = os.pathsep.join(have + added)
    return added


def hide_own_console() -> bool:
    """Hide the console window if it was made for the launcher alone.

    run.bat starts the launcher with python.exe in a console of its own, so
    module processes inherit that (hidden) console instead of each popping a
    new one. Started from a terminal you're using, that console is yours, so
    it stays."""
    hwnd = _h(GetConsoleWindow())
    if not hwnd:
        return False
    arr = (wintypes.DWORD * 8)()
    n = GetConsoleProcessList(arr, 8)
    # A venv's python.exe is a redirector that runs the real interpreter as
    # its child on the same console, so run.bat's console holds two processes
    # even though it was made for the launcher alone. Count that one as ours.
    mine = {os.getpid()}
    try:
        parent = psutil.Process().parent()
        if parent is not None and os.path.normcase(parent.exe()) == \
                os.path.normcase(sys.executable):
            mine.add(parent.pid)
    except psutil.Error:
        pass
    if not 0 < n <= len(arr) or any(arr[i] not in mine for i in range(n)):
        return False
    ShowWindow(hwnd, SW_HIDE)
    return True


def find_browser() -> str | None:
    """A Chromium-family browser. Edge ships with every Windows 10/11, so this
    practically never comes back empty — but it isn't on PATH."""
    for name in ("msedge", "chrome", "brave", "chromium"):
        hit = shutil.which(name)
        if hit:
            return hit
    rels = (r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Chromium\Application\chrome.exe")
    for base in (os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        for rel in rels if base else ():
            path = os.path.join(base, rel)
            if os.path.isfile(path):
                return path
    return None


# --- embedding -----------------------------------------------------------------------
class Win32EmbedHost(QWidget):
    """Hosts another process's top-level window as a child of this widget.

    Same contract as main.XEmbedHost: clicked, child_alive, verify,
    reattach_if_needed, focus_child, _resize_child, detach.

    One hazard has no X11 equivalent. Destroying a window destroys its
    children, so if Qt ever recreates this widget's HWND (re-parenting a
    native widget across top-levels does) the embedded app's window would be
    destroyed with it. The platform-surface event fires *before* that
    happens; the child is parked on the desktop then, and re-attached on
    WinIdChange.
    """
    clicked = pyqtSignal()

    def __init__(self, child_wid: int, parent=None, log=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.child_wid = int(child_wid)
        self._log = log or (lambda _m: None)
        self._style = _signed(_GetLong(self.child_wid, GWL_STYLE))
        self._exstyle = _signed(_GetLong(self.child_wid, GWL_EXSTYLE))
        self._last_focus = 0
        self._watched = None
        err = self._attach()
        if err:
            # SetParent refused, e.g. access denied: WSLg's msrdc.exe windows
            # can't be adopted. Fail now, not after ~6 s of healing attempts.
            self.deleteLater()
            raise ctypes.WinError(err)
        self._watch_surface()
        self._heal_timer = QTimer(self)
        self._heal_timer.setInterval(400)
        self._heal_timer.timeout.connect(self._heal_tick)
        self._heal_ticks = 0
        self._heal_timer.start()
        # WM_PARENTNOTIFY is the primary click signal (nativeEvent); this
        # catches the apps that set WS_EX_NOPARENTNOTIFY on their own controls.
        self._focus_poll = QTimer(self)
        self._focus_poll.setInterval(250)
        self._focus_poll.timeout.connect(self._poll_focus)
        self._focus_poll.start()

    def _host_wid(self) -> int:
        return int(self.winId())

    def _attach(self) -> int:
        """Adopt the child. Returns SetParent's error code, 0 on success."""
        child = self.child_wid
        if not IsWindow(child):
            return 0
        if IsIconic(child) or self._style & WS_MAXIMIZE:
            ShowWindow(child, SW_RESTORE)
        # Order matters: SetParent's documentation says to clear WS_POPUP and
        # set WS_CHILD *before* reparenting a former desktop window.
        self._strip()
        if not SetParent(child, self._host_wid()):
            err = ctypes.get_last_error() or 5
            _SetLong(child, GWL_STYLE, self._style)     # not a parentless child
            _SetLong(child, GWL_EXSTYLE, self._exstyle)
            return err
        w, h = self._pixel_size()
        # Not laid out yet (still Qt's default 100x30): keep the child's own
        # size until the first show/resize. A console squeezed to one row
        # scrolls its view down to the cursor and never scrolls back up, so
        # the start of the prompt stayed hidden above the top edge.
        keep = 0 if self.isVisible() else SWP_NOSIZE
        SetWindowPos(child, None, 0, 0, w, h,
                     SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW
                     | SWP_NOACTIVATE | keep)
        return 0

    def _strip(self):
        """Child styles, frame off."""
        _SetLong(self.child_wid, GWL_STYLE,
                 (self._style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME
                                  | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
                                  | WS_SYSMENU | WS_MAXIMIZE)) | WS_CHILD)
        _SetLong(self.child_wid, GWL_EXSTYLE,
                 self._exstyle & ~(WS_EX_APPWINDOW | WS_EX_WINDOWEDGE
                                   | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME
                                   | WS_EX_NOPARENTNOTIFY | WS_EX_TOPMOST))

    def _framed(self) -> bool:
        s = _signed(_GetLong(self.child_wid, GWL_STYLE))
        return not s & WS_CHILD or bool(s & (WS_CAPTION | WS_THICKFRAME))

    def _pixel_size(self) -> tuple[int, int]:
        r = self.devicePixelRatioF()
        return max(1, int(self.width() * r)), max(1, int(self.height() * r))

    # -- surviving a recreated host HWND --
    def _watch_surface(self):
        wh = self.windowHandle()
        if wh is not None and wh is not self._watched:
            wh.installEventFilter(self)
            self._watched = wh

    def eventFilter(self, obj, event):
        if obj is self._watched and \
                event.type() == QEvent.Type.PlatformSurface and \
                event.surfaceEventType() == \
                QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed:
            self._park()
        return False

    def _park(self):
        """Lift the child onto the desktop (hidden) before our HWND dies."""
        if IsWindow(self.child_wid):
            ShowWindow(self.child_wid, SW_HIDE)
            SetParent(self.child_wid, None)

    def event(self, ev):
        if ev.type() == QEvent.Type.WinIdChange:
            QTimer.singleShot(0, self._after_recreate)
        return super().event(ev)

    def _after_recreate(self):
        self._watch_surface()
        self.reattach_if_needed()

    # -- contract shared with XEmbedHost --
    def child_alive(self) -> bool:
        return bool(IsWindow(self.child_wid))

    def verify(self) -> bool:
        return _h(GetAncestor(self.child_wid, GA_PARENT)) == self._host_wid()

    def reattach_if_needed(self) -> bool:
        if not self.child_alive():
            return False
        if not self.verify():
            self._attach()
        elif self._framed():
            # The app put its frame back: VcXsrv does, just after its window
            # maps — a Linux app embedded with its own title bar inside.
            self._strip()
            SetWindowPos(self.child_wid, None, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                         | SWP_FRAMECHANGED | SWP_NOACTIVATE)
        return True

    def _heal_tick(self):
        self._heal_ticks += 1
        if not self.child_alive() or self._heal_ticks > 15:     # ~6 s
            self._heal_timer.stop()
            return
        self.reattach_if_needed()

    def _resize_child(self):
        if self.child_alive():
            w, h = self._pixel_size()
            MoveWindow(self.child_wid, 0, 0, w, h, True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reattach_if_needed()
        self._resize_child()

    def showEvent(self, event):
        super().showEvent(event)
        self._watch_surface()
        self.reattach_if_needed()
        self._resize_child()

    def nativeEvent(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_PARENTNOTIFY and \
                    (msg.wParam & 0xFFFF) in CLICKS:
                self.clicked.emit()
                QTimer.singleShot(0, self._focus_if_outside)
        except Exception as e:                      # never break the pump
            logger.debug(f"nativeEvent inspect failed: {e}")
        # QWidget's own nativeEvent just returns false. Calling it through
        # super() spins forever in PyQt6 6.9 (seen under Wine), so don't.
        return False, 0

    def _poll_focus(self):
        if not self.child_alive():
            return
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not GetGUIThreadInfo(window_thread(self.child_wid),
                                ctypes.byref(info)):
            return
        f = _h(info.hwndFocus) or _h(info.hwndActive)
        if f and f != self._last_focus:
            first = self._last_focus == 0
            self._last_focus = f
            if not first and (f == self.child_wid or IsChild(self.child_wid, f)):
                self.clicked.emit()

    def mousePressEvent(self, event):
        self.focus_child()
        super().mousePressEvent(event)

    def focus_child(self):
        if self.child_alive():
            SetFocus(self.child_wid)

    def _focus_if_outside(self):
        """After a click inside the child, make sure it has the keyboard.

        A top-level app gets focus when the click activates it; an embedded
        one is never activated, so a window that doesn't SetFocus itself on a
        click — conhost — kept none and every key went to the launcher. A
        click on one of the child's own controls moves focus there by
        itself, so focus already inside the child is left alone."""
        if not self.child_alive():
            return
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        GetGUIThreadInfo(window_thread(self.child_wid), ctypes.byref(info))
        f = _h(info.hwndFocus)
        if f != self.child_wid and not IsChild(self.child_wid, f):
            self.focus_child()

    def detach(self):
        """Hand the window back to the desktop as it was, if it still exists —
        a module that drops to panel mode keeps running in its own window."""
        for t in (self._heal_timer, self._focus_poll):
            t.stop()
        if self._watched is not None:
            self._watched.removeEventFilter(self)
            self._watched = None
        child = self.child_wid
        if not IsWindow(child):
            return
        SetParent(child, None)
        _SetLong(child, GWL_STYLE, self._style)
        _SetLong(child, GWL_EXSTYLE, self._exstyle)
        SetWindowPos(child, None, 80, 80, 0, 0,
                     SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
                     | SWP_SHOWWINDOW)


class ConsoleTerminal(QWidget):
    """The Windows twin of main.TerminalHost: a real console, embedded.

    `conhost.exe cmd.exe` is started explicitly — naming conhost bypasses the
    Windows 11 "default terminal" hand-off to Windows Terminal, whose window
    would belong to WindowsTerminal.exe instead of anything we started. Its
    console window is then hosted with Win32EmbedHost like any module, so
    vim, ssh and interactive prompts all work.
    """

    def __init__(self, cwd: str, parent=None, log=None):
        super().__init__(parent)
        self._log = log or (lambda _m: None)
        self.setMinimumHeight(140)
        self.cwd = cwd
        self.pid = 0
        self.host: Win32EmbedHost | None = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._wait = QLabel("starting console…")
        self._lay.addWidget(self._wait)
        self._tries = 0
        self._plain = False        # conhost refused a command line
        self._find = QTimer(self)
        self._find.setInterval(250)
        self._find.timeout.connect(self._find_console)

    def showEvent(self, event):
        super().showEvent(event)
        if self.host is not None and not self.host.child_alive():
            # `exit` closed the console; showing the terminal again starts
            # a fresh one.
            self.host.deleteLater()
            self.host = None
            self.pid = 0
        if self.pid == 0:
            self._start()

    def _start(self):
        shell = os.environ.get("COMSPEC", "cmd.exe")
        self._tries = 0
        self._wait.setText("starting console…")
        self._wait.show()
        if self._plain:
            # A console of cmd's own. Windows 11 may hand that one to Windows
            # Terminal, out of our reach — which is why conhost goes first.
            try:
                self.pid = subprocess.Popen(
                    [shell], cwd=self.cwd,
                    creationflags=subprocess.CREATE_NEW_CONSOLE).pid
            except OSError as e:
                self._wait.setText(f"Could not start {shell}: {e}")
                return
        else:
            root = os.environ.get("SystemRoot", r"C:\Windows")
            conhost = os.path.join(root, "System32", "conhost.exe")
            ok, pid = QProcess.startDetached(conhost, [shell], self.cwd)
            if not ok:
                self._wait.setText("Could not start conhost.exe")
                return
            self.pid = int(pid)
        self._find.start()

    def _find_console(self):
        self._tries += 1
        if not self._plain and not psutil.pid_exists(self.pid):
            # conhost quit without a window (Wine's takes no command line).
            self._find.stop()
            self._plain = True
            self._start()
            return
        pids = descendant_pids(self.pid)
        for h in top_windows():
            if window_pid(h) in pids and IsWindowVisible(h):
                self._find.stop()
                self._wait.hide()
                self.host = Win32EmbedHost(h, self, log=self._log)
                self._lay.addWidget(self.host)
                return
        if self._tries > 60:                      # ~15 s
            self._find.stop()
            kill_process_tree(self.pid, 9)
            self.pid = 0            # so toggling the terminal starts a new one
            self._wait.setText("Console window never appeared — toggle the "
                               "terminal off and on to retry.")

    def shutdown(self):
        self._find.stop()
        if self.pid:
            kill_process_tree(self.pid, 9)
            self.pid = 0
