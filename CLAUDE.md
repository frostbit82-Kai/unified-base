# Unified Base

A PyQt6 launcher (BomsAI Software) that runs other programs, in any language,
and embeds their windows as tabs and side-by-side panes. One code base for
Linux and Windows, and each OS also runs the other's apps: Windows apps
through **Wine** on Linux, Linux apps through **WSL** on Windows.

## Rules

**Both OSes, always.** A change must keep Linux and Windows working. OS code
sits behind `IS_WINDOWS` / `IS_LINUX`; Win32 code lives in `winplat.py`, and
`main.py` rebinds its process/window globals to winplat's when `IS_WINDOWS`
(the `if IS_WINDOWS:` block near the top). Never put Linux-only calls
(`/proc`, python-xlib, `pkexec`) on a path Windows reaches, or the reverse.

**One choke point each.** Every child process starts in `start_qprocess()`
(cmd.exe gets its command line verbatim via `setNativeArguments`). Every
launch, setup step and command-bar line goes through `ModuleTab._wrap()`,
which applies the module's bridge.

**One clone per machine**, and they meet on GitHub (`frostbit82-Kai/unified-base`,
private): `~/Projects/Unified Base` on Linux, `Projects\Windows\Unified Base`
on the Backup Plus drive for Windows. Commit, push, pull. A copy made any other
way is how work gets stranded.

**No build output in git.** Each demo rebuilds `node_modules`, `target`,
`bin`/`obj` for the OS it runs on (see `.gitignore`). The prebuilt
`Windows/win32-native/app.exe` and `Linux/x11-native/x11-native` are the
deliberate exceptions.

**Installers come later (Linux and Windows).** Keep that possible: no
personal paths in defaults, and nothing new that must write next to the code.
Today `apps/` (blank tabs) and the demos' build output live under the install
folder, which will be read-only in Program Files or `/opt` — both need a
user-writable home before an installer ships.

**User preferences.** The user is on a fixed plan: never warn about token cost
or scale work down to save it. Admin/root installs (apt, UAC prompts) are the
user's to run — hand them the command; never type a password.

## Layout

- `main.py` (~6,000 lines): runtimes (`PythonRuntime`, `NodeRuntime`,
  `BinaryRuntime`, `JavaRuntime`, `WebRuntime`, `CsharpRuntime`, `RubyRuntime`,
  `PhpRuntime`, `DockerRuntime`, `CustomRuntime`), `ModuleTab` (one module:
  setup chain, launch, embed, stop, log, meter), `UnifiedBase` (main window,
  tabs, merge panes, menus), `XEmbedHost` (X11 embedding), `TerminalHost`
  (xterm), `ResourceSampler`/`ResourceMeter`, `LogWindow`, `selftest()`.
- `winplat.py`: `Win32EmbedHost` (SetParent), `ConsoleTerminal` (conhost.exe,
  embedded), psutil process tree / kill, EnumWindows lookup, `refresh_path`
  (after winget), `hide_own_console`, `find_browser` (Edge).
- `test_core.py`: plain-assert checks. Windows branches of shared logic are
  tested on Linux under `_as_windows()`; `@linux_host` checks (/proc, sh,
  Wine) are skipped on Windows.
- `demo_module/Linux/*` (19 demos, one per runtime) and
  `demo_module/Windows/{win32-native, winforms-dotnet}`.

## Run and test

- Linux: `./run.sh`. Windows: double-click `run.bat` (makes `.venv`, pip
  installs `requirements.txt`, starts in a minimised console the app hides).
- `run.bat --selftest` / `./run.sh --selftest`: finds, embeds and stops a Tk
  window, probes WSL / Wine / winget / the browser. Run it first on any new
  machine.
- `python test_core.py` (inside `.venv`). Linux: 55 pass. Windows build under
  Wine: 44 pass, 9 skipped; `check_proc_table` and `check_sampler` failed there
  only because Wine reports no CPU time / parent for other processes — on real
  Windows they must pass, and a failure is a real bug.
- Linux GUI tests run on a nested Xvfb display, never the user's desktop;
  never `pkill -f` (it matches Claude's own shell).

## Port status (2026-10-03)

Verified live on Linux: Windows apps through Wine (both Windows demos, a `.bat`
launcher, restart/stop) embed and resize. Verified under Wine with Windows
Python 3.12 + PyQt6 6.9.1 (the Windows code paths): embedding, resize, click
detection (WM_PARENTNOTIFY), meters, stop, venvs, cmd.exe command bar and
quoting, the console terminal's fallback path, env vars, logs, geometry.

**Never tested anywhere — the Windows session's job:**
1. `run.bat --selftest` on real Windows.
2. Windows demos natively: win32-native (prebuilt; `make` optional via MSYS2),
   winforms-dotnet (`winget install -e --id Microsoft.DotNet.SDK.10`). Start,
   embed, resize, click (tab highlight), Restart, Stop.
3. Full terminal: real `conhost.exe cmd.exe` embedding (Wine's conhost refuses
   a command line, so only the plain-console fallback ran). Type `exit`,
   toggle off and on: a fresh console.
4. **WSL bridge** (Linux demos on Windows, Tux mark on their tabs): admin
   PowerShell `wsl --install`, reboot. x11-native needs only glibc 2.26;
   WSLg windows belong to msrdc.exe and are found by `new_windows_since`.
5. Web demos: Edge `--app` window embedded. Toolchain Install buttons
   (winget) and the PATH refresh afterwards. Windows 11's default-terminal
   hand-off. DPI scaling of embedded windows on a scaled monitor.

## Traps (each cost real time)

- Qt 6.11 (current PyQt6) needs Windows 10 1809+ (system ICU); Wine lacks it,
  so Wine tests pin `PyQt6==6.9.1`.
- Never call `super().nativeEvent()` from an override — it spun forever;
  return `(False, 0)`, which is all QWidget's does.
- Win32: set `WS_CHILD` / clear `WS_POPUP` *before* `SetParent`; ctypes needs
  explicit `argtypes`/`restype` (64-bit HWNDs truncate otherwise). Destroying a
  parent HWND destroys embedded children — `Win32EmbedHost` parks the child on
  `SurfaceAboutToBeDestroyed` and re-attaches on `WinIdChange`.
- QProcess quotes MSVC-style (`\"`), which cmd.exe misreads: cmd lines go
  through `setNativeArguments`; startup args with `& | < > ^` get quoted
  (`_cmd_arg`).
- Child output: `proc_text()` decodes UTF-8, else the ANSI code page, and
  folds CRLF; Python children get `PYTHONIOENCODING=utf-8`.
- `signal.SIGKILL` doesn't exist on Windows: use main's `SIGTERM`/`SIGKILL`.
- Stop's 3 s force-kill hits only the process `stop()` was stopping
  (`_doomed`) — it used to kill a Restart's new process.
- Wine detaches every process a Windows program starts: launches are tagged
  `UB_LAUNCH=…` and found through `/proc/*/environ` (`wine_family`). Wine only
  resizes an embedded window whose `WM_STATE` is Normal
  (`XEmbedHost._claim_state`).
- WSL: env vars don't cross into WSL (folded into argv / exported); the Linux
  pid is printed as `UBPID:` and is the only handle that can stop the app.
- `Linux/x11-native` is built with zig against glibc 2.31 plus `compat.c`;
  `compat.c` must never go into a native gcc build (infinite recursion).
- On an exFAT drive Git for Windows may refuse the repo with "dubious
  ownership": `git config --global --add safe.directory "<path>"`.
