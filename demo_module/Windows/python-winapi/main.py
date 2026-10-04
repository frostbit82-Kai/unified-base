#!/usr/bin/env python3
"""Python — Unified Base Windows demo #2: the Win32 API from the stdlib alone.

No pywin32, no psutil, no pip at all: ctypes, winreg and winsound ship with
every Python for Windows, and between them they reach most of the OS.

  System     live CPU (GetSystemTimes deltas), memory, power, uptime, build
  Displays   every monitor to scale, its DPI, the accent colour and theme
  Windows    the desktop's top-level windows, live — select one to flash it
  Sounds     your sound scheme straight from the registry, and a Beep piano
  Registry   a read-only, lazily expanded browser of HKEY_CURRENT_USER

`python main.py --selftest` runs every query once and checks the answers.
"""
import ctypes
import queue
import sys
import threading
import time
import tkinter as tk
import winreg
import winsound
from ctypes import wintypes as w
from tkinter import ttk


def api(dll, name, res, *args):
    """Declare a Win32 function: without argtypes/restype ctypes assumes int,
    and 64-bit handles get truncated."""
    f = getattr(dll, name)
    f.restype, f.argtypes = res, list(args)
    return f


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
adv = ctypes.WinDLL("advapi32")
shc = ctypes.WinDLL("shcore")
dwm = ctypes.WinDLL("dwmapi")


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", w.DWORD), ("dwMemoryLoad", w.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", w.BYTE), ("BatteryFlag", w.BYTE),
                ("BatteryLifePercent", w.BYTE), ("SystemStatusFlag", w.BYTE),
                ("BatteryLifeTime", w.DWORD),
                ("BatteryFullLifeTime", w.DWORD)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT),
                ("rcWork", w.RECT), ("dwFlags", w.DWORD),
                ("szDevice", w.WCHAR * 32)]


class FLASHWINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.UINT), ("hwnd", w.HWND), ("dwFlags", w.DWORD),
                ("uCount", w.UINT), ("dwTimeout", w.DWORD)]


WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC,
                                     ctypes.POINTER(w.RECT), w.LPARAM)

GlobalMemoryStatusEx = api(k32, "GlobalMemoryStatusEx", w.BOOL,
                           ctypes.POINTER(MEMORYSTATUSEX))
GetSystemPowerStatus = api(k32, "GetSystemPowerStatus", w.BOOL,
                           ctypes.POINTER(SYSTEM_POWER_STATUS))
GetSystemTimes = api(k32, "GetSystemTimes", w.BOOL,
                     ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME),
                     ctypes.POINTER(w.FILETIME))
GetTickCount64 = api(k32, "GetTickCount64", ctypes.c_ulonglong)
GetComputerNameW = api(k32, "GetComputerNameW", w.BOOL, w.LPWSTR,
                       ctypes.POINTER(w.DWORD))
GetUserNameW = api(adv, "GetUserNameW", w.BOOL, w.LPWSTR,
                   ctypes.POINTER(w.DWORD))
OpenProcess = api(k32, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
CloseHandle = api(k32, "CloseHandle", w.BOOL, w.HANDLE)
QueryFullProcessImageNameW = api(k32, "QueryFullProcessImageNameW", w.BOOL,
                                 w.HANDLE, w.DWORD, w.LPWSTR,
                                 ctypes.POINTER(w.DWORD))
EnumDisplayMonitors = api(u32, "EnumDisplayMonitors", w.BOOL, w.HDC,
                          ctypes.POINTER(w.RECT), MONITORENUMPROC, w.LPARAM)
GetMonitorInfoW = api(u32, "GetMonitorInfoW", w.BOOL, w.HMONITOR,
                      ctypes.POINTER(MONITORINFOEXW))
GetDpiForMonitor = api(shc, "GetDpiForMonitor", ctypes.c_long, w.HMONITOR,
                       ctypes.c_int, ctypes.POINTER(w.UINT),
                       ctypes.POINTER(w.UINT))
EnumWindows = api(u32, "EnumWindows", w.BOOL, WNDENUMPROC, w.LPARAM)
IsWindowVisible = api(u32, "IsWindowVisible", w.BOOL, w.HWND)
GetWindow = api(u32, "GetWindow", w.HWND, w.HWND, w.UINT)
GetWindowTextW = api(u32, "GetWindowTextW", ctypes.c_int, w.HWND, w.LPWSTR,
                     ctypes.c_int)
GetClassNameW = api(u32, "GetClassNameW", ctypes.c_int, w.HWND, w.LPWSTR,
                    ctypes.c_int)
GetWindowThreadProcessId = api(u32, "GetWindowThreadProcessId", w.DWORD,
                               w.HWND, ctypes.POINTER(w.DWORD))
FlashWindowEx = api(u32, "FlashWindowEx", w.BOOL, ctypes.POINTER(FLASHWINFO))
DwmGetWindowAttribute = api(dwm, "DwmGetWindowAttribute", ctypes.c_long,
                            w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD)

SCALE = 1.0        # display DPI / 96, set once Tk is up


def px(n: float) -> int:
    """Canvas sizes are in pixels; this keeps them the same size on screen
    at any display scale (Tk already scales fonts by itself)."""
    return int(n * SCALE)


GW_OWNER = 4
DWMWA_CLOAKED = 14
MONITORINFOF_PRIMARY = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
FLASHW_ALL = 3


# --- queries -----------------------------------------------------------------
def memory() -> MEMORYSTATUSEX:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)       # Win32's versioning: say which struct
    GlobalMemoryStatusEx(ctypes.byref(m))
    return m


def power() -> SYSTEM_POWER_STATUS:
    p = SYSTEM_POWER_STATUS()
    GetSystemPowerStatus(ctypes.byref(p))
    return p


def _ft(f: w.FILETIME) -> int:
    return (f.dwHighDateTime << 32) | f.dwLowDateTime


def cpu_times() -> tuple[int, int]:
    """(idle, total) in 100 ns ticks since boot. Kernel time *includes*
    idle time, which is the classic trap in turning these into a percent."""
    idle, kern, user = w.FILETIME(), w.FILETIME(), w.FILETIME()
    GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    return _ft(idle), _ft(kern) + _ft(user)


def cpu_percent(a: tuple[int, int], b: tuple[int, int]) -> float:
    idle, total = b[0] - a[0], b[1] - a[1]
    return 0.0 if total <= 0 else max(0.0, min(100.0, 100 * (1 - idle / total)))


def _name(fn) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = w.DWORD(256)
    return buf.value if fn(buf, ctypes.byref(n)) else "?"


def windows_build() -> tuple[str, str]:
    """(edition, version) as Settings ▸ About shows them. The registry's
    ProductName still says "Windows 10" on Windows 11 — Microsoft never
    changed it — so 11 is told apart by build number, as Microsoft does."""
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
        def get(name, default=""):
            try:
                return winreg.QueryValueEx(k, name)[0]
            except OSError:
                return default
        build = int(get("CurrentBuildNumber", "0"))
        name = get("ProductName", "Windows")
        if build >= 22000:
            name = name.replace("Windows 10", "Windows 11")
        return name, f"{get('DisplayVersion', '?')} (build {build}.{get('UBR', 0)})"


def monitors() -> list[dict]:
    out = []

    @MONITORENUMPROC
    def cb(hmon, _hdc, _rect, _lp):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        GetMonitorInfoW(hmon, ctypes.byref(mi))
        dx, dy = w.UINT(), w.UINT()
        GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy))
        r, wk = mi.rcMonitor, mi.rcWork
        out.append({"device": mi.szDevice, "dpi": dx.value,
                    "primary": bool(mi.dwFlags & MONITORINFOF_PRIMARY),
                    "rect": (r.left, r.top, r.right, r.bottom),
                    "work": (wk.left, wk.top, wk.right, wk.bottom)})
        return True
    EnumDisplayMonitors(None, None, cb, 0)
    return out


def reg_value(root, path: str, name: str, default=None):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def theme() -> dict:
    p = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    abgr = reg_value(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM",
                     "AccentColor")
    accent = None
    if abgr is not None:          # stored ABGR: the bytes are back to front
        accent = "#%02x%02x%02x" % (abgr & 0xFF, (abgr >> 8) & 0xFF,
                                    (abgr >> 16) & 0xFF)
    hkcu = winreg.HKEY_CURRENT_USER
    return {"apps_light": reg_value(hkcu, p, "AppsUseLightTheme", 1) == 1,
            "system_light": reg_value(hkcu, p, "SystemUsesLightTheme", 1) == 1,
            "transparency": reg_value(hkcu, p, "EnableTransparency", 1) == 1,
            "accent": accent}


def exe_of(pid: int) -> str:
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "?"          # elevated or protected: limited access refused
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = w.DWORD(1024)
        if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value.rsplit("\\", 1)[-1]
        return "?"
    finally:
        CloseHandle(h)


def top_windows() -> list[dict]:
    """What a taskbar would show: visible, titled, unowned — and not
    *cloaked*. Store apps park windows that are 'visible' to IsWindowVisible
    but hidden by DWM; without that check the list fills with ghosts."""
    out = []

    @WNDENUMPROC
    def cb(h, _lp):
        if not IsWindowVisible(h) or GetWindow(h, GW_OWNER):
            return True
        cloaked = w.DWORD()
        DwmGetWindowAttribute(h, DWMWA_CLOAKED, ctypes.byref(cloaked), 4)
        if cloaked.value:
            return True
        title = ctypes.create_unicode_buffer(256)
        if not GetWindowTextW(h, title, 256):
            return True
        cls = ctypes.create_unicode_buffer(128)
        GetClassNameW(h, cls, 128)
        pid = w.DWORD()
        GetWindowThreadProcessId(h, ctypes.byref(pid))
        out.append({"hwnd": int(h), "title": title.value, "class": cls.value,
                    "pid": pid.value})
        return True
    EnumWindows(cb, 0)
    return out


def flash(hwnd: int) -> None:
    fi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_ALL, 6, 0)
    FlashWindowEx(ctypes.byref(fi))


SCHEME = r"AppEvents\Schemes\Apps\.Default"


def sound_events() -> list[tuple[str, str]]:
    """(event, .wav) for every event in the current sound scheme that has a
    sound. The event key's name is exactly what PlaySound(SND_ALIAS) takes."""
    out = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SCHEME)
    except OSError:
        return out
    with root:
        i = 0
        while True:
            try:
                ev = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            wav = reg_value(winreg.HKEY_CURRENT_USER,
                            rf"{SCHEME}\{ev}\.Current", "", "")
            if wav:
                out.append((ev, wav))
    return sorted(out, key=lambda t: t[0].lower())


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n:.0f} B"
        n /= 1024
    return ""


def fmt_uptime(ms: int) -> str:
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    return (f"{d}d " if d else "") + f"{h}h {s // 60:02d}m {s % 60:02d}s"


# --- UI --------------------------------------------------------------------
class SystemTab(ttk.Frame):
    HISTORY = 60

    def __init__(self, master):
        super().__init__(master, padding=12)
        self.rows = {}
        grid = ttk.Frame(self)
        grid.pack(fill="x")
        for i, key in enumerate(("Computer", "User", "Windows", "Version",
                                 "Uptime", "CPU", "Memory", "Commit", "Power")):
            ttk.Label(grid, text=key, foreground="#6b7280").grid(
                row=i, column=0, sticky="w", padx=(0, 16), pady=2)
            v = ttk.Label(grid, text="…")
            v.grid(row=i, column=1, sticky="w", pady=2)
            self.rows[key] = v
        self.mem_bar = ttk.Progressbar(grid, length=220, maximum=100)
        self.mem_bar.grid(row=6, column=2, padx=12)
        self.bat_bar = ttk.Progressbar(grid, length=220, maximum=100)
        self.bat_bar.grid(row=8, column=2, padx=12)
        ttk.Label(self, text="CPU, last minute", foreground="#6b7280").pack(
            anchor="w", pady=(14, 2))
        self.graph = tk.Canvas(self, height=px(120), bg="#0f172a",
                               highlightthickness=0)
        self.graph.pack(fill="x")
        self.hist = [0.0] * self.HISTORY
        name, ver = windows_build()
        self.rows["Computer"].config(text=_name(GetComputerNameW))
        self.rows["User"].config(text=_name(GetUserNameW))
        self.rows["Windows"].config(text=name)
        self.rows["Version"].config(text=ver)
        self.last = cpu_times()
        self.tick()

    def tick(self):
        now = cpu_times()
        pct = cpu_percent(self.last, now)
        self.last = now
        self.hist = self.hist[1:] + [pct]
        m = memory()
        p = power()
        used = m.ullTotalPhys - m.ullAvailPhys
        commit = m.ullTotalPageFile - m.ullAvailPageFile
        self.rows["Uptime"].config(text=fmt_uptime(GetTickCount64()))
        self.rows["CPU"].config(text=f"{pct:5.1f} %   ({__import__('os').cpu_count()} logical processors)")
        self.rows["Memory"].config(
            text=f"{fmt_bytes(used)} of {fmt_bytes(m.ullTotalPhys)} "
                 f"({m.dwMemoryLoad} %)")
        self.rows["Commit"].config(
            text=f"{fmt_bytes(commit)} of {fmt_bytes(m.ullTotalPageFile)}")
        self.mem_bar["value"] = m.dwMemoryLoad
        if p.BatteryFlag == 128:            # 128 = no system battery
            self.rows["Power"].config(text="mains — no battery")
            self.bat_bar["value"] = 0
        else:
            src = {0: "on battery", 1: "plugged in"}.get(p.ACLineStatus, "?")
            left = ("" if p.BatteryLifeTime == 0xFFFFFFFF else
                    f", {p.BatteryLifeTime // 3600}h {p.BatteryLifeTime // 60 % 60:02d}m left")
            saver = ", battery saver on" if p.SystemStatusFlag else ""
            self.rows["Power"].config(
                text=f"{p.BatteryLifePercent} % {src}{left}{saver}")
            self.bat_bar["value"] = p.BatteryLifePercent
        self.draw_graph()
        self.after(1000, self.tick)

    def draw_graph(self):
        c = self.graph
        c.delete("all")
        gw, gh = c.winfo_width(), c.winfo_height()
        if gw < 10:
            return
        for y in (25, 50, 75):
            yy = gh - gh * y / 100
            c.create_line(0, yy, gw, yy, fill="#1e293b")
        step = gw / (self.HISTORY - 1)
        pts = []
        for i, v in enumerate(self.hist):
            pts += [i * step, gh - gh * v / 100]
        c.create_polygon(0, gh, *pts, gw, gh, fill="#1d4ed8", outline="")
        c.create_line(*pts, fill="#60a5fa", width=2)


class DisplaysTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)
        self.canvas = tk.Canvas(self, height=px(200), bg="#0f172a",
                                highlightthickness=0)
        self.canvas.pack(fill="x")
        self.text = ttk.Label(self, justify="left", font=("Consolas", 10))
        self.text.pack(anchor="w", pady=(10, 0))
        theme_row = ttk.Frame(self)
        theme_row.pack(anchor="w", pady=(10, 0))
        ttk.Label(theme_row, text="Accent colour").pack(side="left")
        self.swatch = tk.Label(theme_row, width=6, relief="flat")
        self.swatch.pack(side="left", padx=8)
        self.theme = ttk.Label(theme_row)
        self.theme.pack(side="left", padx=8)
        ttk.Label(self, foreground="#6b7280", text=(
            "Live: change Settings ▸ Personalization ▸ Colors, or the display "
            "scale, and watch this tab follow within two seconds.")).pack(
            anchor="w", pady=(10, 0))
        self.tick()

    def tick(self):
        mons = monitors()
        c = self.canvas
        c.delete("all")
        cw, ch = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        x0 = min(m["rect"][0] for m in mons)
        y0 = min(m["rect"][1] for m in mons)
        x1 = max(m["rect"][2] for m in mons)
        y1 = max(m["rect"][3] for m in mons)
        s = min((cw - 20) / (x1 - x0), (ch - 20) / (y1 - y0))
        ox = (cw - (x1 - x0) * s) / 2 - 10       # centre the layout
        lines = []
        th = theme()
        accent = th["accent"] or "#3b82f6"
        for m in mons:
            l, t, r, b = ((v - o) * s + 10 + d for v, o, d in
                          zip(m["rect"], (x0, y0, x0, y0), (ox, 0, ox, 0)))
            c.create_rectangle(l, t, r, b, outline=accent, width=2,
                               fill="#1e293b")
            wl, wt, wr, wb = ((v - o) * s + 10 + d for v, o, d in
                              zip(m["work"], (x0, y0, x0, y0), (ox, 0, ox, 0)))
            c.create_rectangle(wl, wt, wr, wb, outline="#334155", dash=(3, 3))
            c.create_text((l + r) / 2, (t + b) / 2, fill="#e2e8f0",
                          text=f"{m['device'].lstrip(chr(92) + '.')}\n"
                               f"{m['rect'][2] - m['rect'][0]}×"
                               f"{m['rect'][3] - m['rect'][1]}\n"
                               f"{m['dpi'] * 100 // 96} %",
                          justify="center")
            lines.append(
                f"{m['device']:<14} {m['rect'][2] - m['rect'][0]:>5}×"
                f"{m['rect'][3] - m['rect'][1]:<5} at {m['rect'][:2]}  "
                f"{m['dpi']} dpi = {m['dpi'] * 100 // 96} %"
                f"{'  primary' if m['primary'] else ''}")
        self.text.config(text="\n".join(lines))
        self.swatch.config(bg=accent)
        self.theme.config(text=(
            f"apps {'light' if th['apps_light'] else 'dark'} · taskbar "
            f"{'light' if th['system_light'] else 'dark'} · transparency "
            f"{'on' if th['transparency'] else 'off'}"))
        self.after(2000, self.tick)


class WindowsTab(ttk.Frame):
    COLS = ("title", "exe", "pid", "class")

    def __init__(self, master):
        super().__init__(master, padding=12)
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        self.count = ttk.Label(bar)
        self.count.pack(side="left")
        ttk.Button(bar, text="Flash it", command=self.flash).pack(side="right")
        self.tree = ttk.Treeview(self, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for col, width in zip(self.COLS, (320, 150, 70, 220)):
            self.tree.heading(col, text=col.title())
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        self.tree.bind("<Double-1>", lambda _e: self.flash())
        self.exes: dict[int, str] = {}
        ttk.Label(self, foreground="#6b7280", text=(
            "This program is missing from the list while it is embedded: a "
            "window adopted by Unified Base is a child window now, not a "
            "top-level one.")).pack(anchor="w", pady=(8, 0))
        self.tick()

    def tick(self):
        """Update in place — rebuilding the list would drop the selection."""
        wins = {str(x["hwnd"]): x for x in top_windows()}
        for iid in set(self.tree.get_children()) - set(wins):
            self.tree.delete(iid)
        for iid, x in wins.items():
            if x["pid"] not in self.exes:
                self.exes[x["pid"]] = exe_of(x["pid"])
            vals = (x["title"], self.exes[x["pid"]], x["pid"], x["class"])
            if self.tree.exists(iid):
                self.tree.item(iid, values=vals)
            else:
                self.tree.insert("", "end", iid=iid, values=vals)
        self.count.config(text=f"{len(wins)} top-level windows")
        self.after(1500, self.tick)

    def flash(self):
        sel = self.tree.selection()
        if sel:
            flash(int(sel[0]))


NOTES = [("A", "C", 261.63), ("W", "C#", 277.18), ("S", "D", 293.66),
         ("E", "D#", 311.13), ("D", "E", 329.63), ("F", "F", 349.23),
         ("T", "F#", 369.99), ("G", "G", 392.00), ("Y", "G#", 415.30),
         ("H", "A", 440.00), ("U", "A#", 466.16), ("J", "B", 493.88),
         ("K", "C", 523.25)]


class SoundsTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)
        ttk.Label(self, text="Your sound scheme (double-click to play)",
                  foreground="#6b7280").pack(anchor="w")
        self.list = ttk.Treeview(self, columns=("wav",), show="tree headings",
                                 height=8, selectmode="browse")
        self.list.heading("#0", text="Event")
        self.list.heading("wav", text="File")
        self.list.column("#0", width=230)
        self.list.column("wav", width=480)
        for ev, wav in sound_events():
            self.list.insert("", "end", iid=ev, text=ev, values=(wav,))
        self.list.pack(fill="x", pady=(4, 0))
        self.list.bind("<Double-1>", self.play)
        ttk.Label(self, foreground="#6b7280", text=(
            "winsound.Beep piano — click a key, or type A W S E D F T G Y H "
            "U J K")).pack(anchor="w", pady=(14, 4))
        self.keys = tk.Canvas(self, height=px(150), bg="#0f172a",
                              highlightthickness=0)
        self.keys.pack(fill="x")
        self.keys.bind("<Configure>", lambda _e: self.draw_keys())
        self.keys.bind("<Button-1>", self.click_key)
        # Beep blocks for the note's length; a worker keeps the UI live.
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self.player, daemon=True).start()
        self.rects = []

    def play(self, _e=None):
        sel = self.list.selection()
        if sel:
            winsound.PlaySound(sel[0], winsound.SND_ALIAS | winsound.SND_ASYNC)

    def player(self):
        while True:
            winsound.Beep(int(self.q.get()), 220)

    def draw_keys(self):
        c = self.keys
        c.delete("all")
        whites = [n for n in NOTES if "#" not in n[1]]
        kw = max(c.winfo_width(), 200) / len(whites)
        kh = c.winfo_height()
        self.rects = []
        for i, (key, name, f) in enumerate(whites):
            r = c.create_rectangle(i * kw + 1, 1, (i + 1) * kw - 1, kh - 1,
                                   fill="#f8fafc", outline="#94a3b8")
            c.create_text(i * kw + kw / 2, kh - px(8), anchor="s",
                          text=f"{name}\n{key}", fill="#334155",
                          justify="center")
            self.rects.append((r, f, False))
        wi = 0
        for key, name, f in NOTES:
            if "#" in name:
                x = wi * kw
                r = c.create_rectangle(x - kw * 0.3, 1, x + kw * 0.3, kh * 0.6,
                                       fill="#0f172a", outline="#475569")
                c.create_text(x, kh * 0.6 - px(6), anchor="s", text=key,
                              fill="#cbd5e1")
                self.rects.append((r, f, True))
            else:
                wi += 1

    def click_key(self, e):
        hits = self.keys.find_overlapping(e.x, e.y, e.x, e.y)
        for r, f, black in sorted(self.rects, key=lambda t: not t[2]):
            if r in hits:
                self.hit(r, f, black)
                return

    def hit(self, rect, freq, black):
        self.q.put(freq)
        self.keys.itemconfig(rect, fill="#60a5fa")
        self.after(180, lambda: self.keys.itemconfig(
            rect, fill="#0f172a" if black else "#f8fafc"))

    def key(self, ch: str):
        for (r, f, black), (k, _n, _f) in zip(
                sorted(self.rects, key=lambda t: t[1]),
                sorted(NOTES, key=lambda n: n[2])):
            if k == ch.upper():
                self.hit(r, f, black)


class RegistryTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)
        ttk.Label(self, foreground="#6b7280", text=(
            "HKEY_CURRENT_USER, read-only. Keys load as you expand them — "
            "the whole hive is tens of thousands of keys.")).pack(anchor="w")
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=(6, 0))
        self.keys = ttk.Treeview(pane, show="tree", selectmode="browse")
        self.vals = ttk.Treeview(pane, columns=("type", "data"),
                                 show="tree headings")
        self.vals.heading("#0", text="Name")
        self.vals.heading("type", text="Type")
        self.vals.heading("data", text="Data")
        self.vals.column("#0", width=160)
        self.vals.column("type", width=90)
        self.vals.column("data", width=320)
        pane.add(self.keys, weight=1)
        pane.add(self.vals, weight=2)
        self.add_children("", "")
        self.keys.bind("<<TreeviewOpen>>", self.opened)
        self.keys.bind("<<TreeviewSelect>>", self.selected)

    TYPES = {winreg.REG_SZ: "SZ", winreg.REG_EXPAND_SZ: "EXPAND_SZ",
             winreg.REG_DWORD: "DWORD", winreg.REG_QWORD: "QWORD",
             winreg.REG_BINARY: "BINARY", winreg.REG_MULTI_SZ: "MULTI_SZ"}

    def add_children(self, node: str, path: str):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                n = winreg.QueryInfoKey(k)[0]
                names = sorted((winreg.EnumKey(k, i) for i in range(n)),
                               key=str.lower)
        except OSError:
            return
        for name in names:
            full = f"{path}\\{name}" if path else name
            iid = self.keys.insert(node, "end", iid=full, text=name)
            self.keys.insert(iid, "end", text="…")    # expandable placeholder

    def opened(self, _e):
        node = self.keys.focus()
        kids = self.keys.get_children(node)
        if len(kids) == 1 and self.keys.item(kids[0], "text") == "…":
            self.keys.delete(kids[0])
            self.add_children(node, node)

    def selected(self, _e):
        self.vals.delete(*self.vals.get_children())
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                self.keys.focus()) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, data, typ = winreg.EnumValue(k, i)
                    if typ == winreg.REG_BINARY:
                        data = data[:24].hex(" ") + (" …" if len(data) > 24
                                                     else "")
                    elif typ == winreg.REG_DWORD:
                        data = f"0x{data:08x} ({data})"
                    self.vals.insert("", "end", text=name or "(Default)",
                                     values=(self.TYPES.get(typ, typ),
                                             str(data)[:300]))
        except OSError as e:
            self.vals.insert("", "end", text="(cannot open)",
                             values=("", e.strerror))


def main():
    # Before Tk exists: awareness is fixed once the first window opens.
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    root = tk.Tk()
    global SCALE
    SCALE = root.winfo_fpixels("1i") / 96.0
    root.title("Python · Win32 from the standard library — Unified Base")
    root.geometry(f"{px(860)}x{px(600)}")
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")         # the real Windows controls
    head = ttk.Frame(root, padding=(12, 10, 12, 0))
    head.pack(fill="x")
    ttk.Label(head, text="Win32 from the standard library",
              font=("Segoe UI Semibold", 15)).pack(anchor="w")
    ttk.Label(head, foreground="#6b7280", text=(
        "ctypes · winreg · winsound — no pip install, no pywin32")).pack(
        anchor="w")
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=12, pady=12)
    sounds = SoundsTab(nb)
    for tab, label in ((SystemTab(nb), "System"), (DisplaysTab(nb), "Displays"),
                       (WindowsTab(nb), "Windows"), (sounds, "Sounds"),
                       (RegistryTab(nb), "Registry")):
        nb.add(tab, text=label)
    root.bind("<Key>", lambda e: e.char and nb.select() == str(sounds)
              and sounds.key(e.char))
    root.mainloop()


def selftest():
    a = cpu_times()
    time.sleep(0.25)
    pct = cpu_percent(a, cpu_times())
    assert 0 <= pct <= 100, pct
    assert cpu_percent((10, 100), (15, 110)) == 50.0    # idle 5 of 10
    m = memory()
    assert m.ullTotalPhys > 256 * 2 ** 20 and 0 <= m.dwMemoryLoad <= 100
    mons = monitors()
    assert mons and any(x["primary"] for x in mons), mons
    assert all(x["dpi"] >= 96 for x in mons), mons
    name, ver = windows_build()
    assert name.startswith("Windows") and "build" in ver, (name, ver)
    wins = top_windows()
    assert all(x["title"] and x["pid"] for x in wins), wins[:3]
    assert theme()["accent"] is None or theme()["accent"].startswith("#")
    assert fmt_uptime(90061000) == "1d 1h 01m 01s"
    assert fmt_bytes(1536) == "1.5 KB"
    print(f"selftest ok: {name} {ver}, cpu {pct:.0f} %, "
          f"{len(mons)} monitor(s), {len(wins)} windows, "
          f"{len(sound_events())} sound events")


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("This demo calls the Win32 API — run it on Windows.")
    selftest() if "--selftest" in sys.argv else main()
