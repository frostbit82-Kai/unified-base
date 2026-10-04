# Python — Unified Base Windows demo #2: Win32 from the standard library

Five tabs of live Windows internals, from a Python that has had nothing
installed into it — no pywin32, no psutil, no `pip install` at all.

| Tab | What it shows | How |
|---|---|---|
| System | CPU graph, memory, commit, battery, uptime, edition + build | `GetSystemTimes`, `GlobalMemoryStatusEx`, `GetSystemPowerStatus`, `GetTickCount64`, the registry |
| Displays | every monitor to scale, its DPI and scale %, accent colour, light/dark | `EnumDisplayMonitors` + `GetDpiForMonitor`, `HKCU\…\DWM\AccentColor` |
| Windows | the desktop's top-level windows, live; double-click flashes one | `EnumWindows`, `DwmGetWindowAttribute`, `QueryFullProcessImageNameW`, `FlashWindowEx` |
| Sounds | your sound scheme, playable; a one-octave Beep piano (keys A–K) | `HKCU\AppEvents`, `winsound.PlaySound(SND_ALIAS)`, `winsound.Beep` |
| Registry | HKEY_CURRENT_USER, read-only, expanded on demand | `winreg` |

## Demonstrates
The Linux Python demos are about Tk; this one is about **ctypes** — calling
any DLL export with nothing but a declaration:

- **Declare, then call.** Every function gets `argtypes`/`restype`. Without
  them ctypes assumes `int`, and 64-bit handles are silently truncated.
- **Structs with a size field** (`dwLength`, `cbSize`): Win32's way of
  versioning a struct, so the caller says which one it passed.
- **Callbacks** — `EnumWindows` and `EnumDisplayMonitors` call back into
  Python through `WINFUNCTYPE`.
- **Windows trivia, handled:** kernel time *includes* idle time (CPU % is
  `1 - idle/(kernel+user)`); the registry's `ProductName` still says
  "Windows 10" on Windows 11 (build ≥ 22000 tells them apart); Store apps
  leave *cloaked* windows that `IsWindowVisible` calls visible; the accent
  colour is stored ABGR.
- **Responsive while blocking:** `winsound.Beep` blocks for the length of the
  note, so notes play from a worker thread fed by a queue.
- **DPI awareness** — the window is per-monitor aware and sizes its canvases
  by the real DPI.

Something to notice while it is embedded: it is missing from its own
Windows tab. Unified Base adopted its window, which makes it a child window
— no longer top-level.

## Dependencies
Python 3.9+ for Windows (python.org's includes Tk). Nothing else.

## Run
Unified Base runs this automatically. Manual equivalent:

```
py main.py
```

Logic check, no window: `py main.py --selftest`

## Files
- `main.py` — declarations, queries, the five tabs, and `--selftest`
