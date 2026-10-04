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
private): `~/Projects/Unified Base` on Linux, `D:\Projects\Unified Base` (the
"Storage" SD card, NTFS) on Windows. Commit, push, pull. A copy made any other
way is how work gets stranded.

**No build output in git.** Each demo rebuilds `node_modules`, `target`,
`bin`/`obj` for the OS it runs on (see `.gitignore`). The prebuilt
`Windows/win32-native/app.exe`, `Windows/c-paint/paint.exe`,
`Windows/c-sysmon/sysmon.exe` and `Linux/x11-native/x11-native` are the
deliberate exceptions: C needs a compiler most machines lack.

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
  `demo_module/Windows/*` (22): `win32-native`, `winforms-dotnet`, and two
  per Linux language — a twin of the Linux demo #2 (`*-win`, same code
  where the toolkit allows, for side-by-side comparison; the suffix because
  a cross-platform module gets no OS badge) and one showing Windows itself
  (`python-winapi`, `web-edge`, `node-windows`, `csharp-winrt`, `java-ffm`,
  `rust-synth`, `c-paint` + `c-sysmon`, `ruby-com`, `php-com`,
  `docker-windows`). Most have `--selftest`; each README says what differs.

## Run and test

- Linux: `./run.sh`. Windows: double-click `run.bat` (makes `.venv`, pip
  installs `requirements.txt`, starts in a minimised console the app hides).
- `run.bat --selftest` / `./run.sh --selftest`: finds, embeds and stops a Tk
  window, probes WSL / Wine / winget / the browser. Run it first on any new
  machine.
- `python test_core.py` (inside `.venv`). Linux: 72 pass. Real Windows: 59
  pass, 9 skipped as of 2026-10-04 morning; the Linux pass after it added 3
  portable checks and 1 Linux-host one, so expect 62 pass, 10 skipped. Under Wine `check_proc_table` and `check_sampler` fail
  only because Wine reports no CPU time / parent for other processes.
- Linux GUI tests run on a nested Xvfb display, never the user's desktop;
  never `pkill -f` (it matches Claude's own shell).

## Port status (2026-10-03)

Verified live on Linux: Windows apps through Wine (both Windows demos, a `.bat`
launcher, restart/stop) embed and resize.

Verified live on real Windows 11 26H2 (Python 3.13, Qt 6.11): `--selftest` 0
failures; test_core all pass. win32-native and winforms-dotnet: start, embed,
resize, click highlight, Restart, Stop. The conhost terminal: embedded, takes
the keyboard on click, `exit` + toggle gives a fresh one. Install buttons
(winget .NET SDK, Node) incl. UAC and the live PATH refresh. Web demo in Edge
`--app`: embeds, renders, Stop cleans up. WSL bridge with Ubuntu: x11-native
and the python demo (venv in the distro) run, embed, animate, take clicks,
stop (Stop and quit); a removable drive is mounted on demand. Tk apps embed
natively too.

**Linux windows on Windows embed through VcXsrv, not WSLg.** WSLg's windows
(msrdc.exe RAIL) refuse SetParent — access denied, UIPI. Setup on this machine:
VcXsrv (`winget install marha.VcXsrv`), started at login by a Startup shortcut
(`vcxsrv.exe :0 -multiwindow -clipboard -wgl -listen tcp`, no `-ac`: its
X0.hosts admits localhost only), and `networkingMode=mirrored` in
`%USERPROFILE%\.wslconfig` so 127.0.0.1 in WSL is Windows. With both,
`wsl_display_env()` gives WSL launches `DISPLAY=127.0.0.1:0`; without, WSLg.
In WSL: `apt install python3-venv python3-tk` (Ubuntu ships neither).

**Known limits on Windows:**
- A portable Chromium needs its folder ACL'd for app containers (the log
  hint gives the icacls line); installed Chrome/Edge are fine.
- VcXsrv renders in software: ~1 core for a 60 fps full-window animation,
  embedded or not.

DPI: verified at 125% (live switch and fresh start). The launcher and every
embedded type are per-monitor aware; each child fits its pane to the pixel,
clicks land, VcXsrv's geometry matches. X11 apps don't scale their content.
Nothing on the original Windows list is untested.

2026-10-04: the header folds by real widths (full → glyph buttons → ☰);
browser panes crop Chromium's own caption strip; `exit` folds the terminal
away; toolchains installed outside the launcher are found (`which_fresh`);
child output loses terminal escapes. Toolchains on this machine: Rust (GNU
host, no Visual Studio), Temurin 25 + Maven (user zips), Ruby 3.4, PHP 8.4
(winget, its `php.ini` made from `php.ini-development` + `com_dotnet`),
zig + make, Docker Engine *inside WSL*, and Docker Desktop (installed
without `--accept-license`/`--no-windows-containers`, winget's defaults;
its Ubuntu integration is off, so WSL keeps its own engine).
`docker-multistage-win` runs on either; `docker-windows` runs on Docker
Desktop's Windows engine (Containers feature on, Hyper-V isolation; ~150 s
first build incl. the Nano Server pulls). A failed build names the fix
(`docker_hint`: engine stopped, wrong container mode, docker group). Both
Linux Electron demos are on ^44 and run through WSL (Ubuntu 26.04's
`nodejs` is 22.22; Electron 40+ needs ≥ 22.12). Final pass the same day:
all 22 Windows demos start, embed (or finish, for the Docker two) and stop.

**Handoff to the Linux clone (2026-10-04).** Pull, then: `python
test_core.py`; `node -v` (≥ 22.12 for Electron 44, else NodeSource/nvm);
start `Linux/node` and `Linux/node-desktop` — their old Electron 31
`node_modules` reinstall on the first start (the pulled package.json is
newer than npm's hidden lockfile), then Electron 44 downloads as a setup
step. Shared code changed on Windows that Linux runs too: `npm_setup`
(every Node/web module's setup), `docker_hint` (failed setup steps), the
header compaction, `proc_text`'s escape stripping, `which_fresh`. The
Linux demos weren't re-run on Linux after these.

**Linux pass, 2026-10-04 (after the Windows session).** All 19 Linux demos
re-run on Linux after the shared-code changes: start, embed, Restart, Stop.
The Windows demos on Linux: the cross-platform twins run natively
(python-fractal-win, php-forms-win, java-table-win, rust-raytracer-win,
node-desktop-win, web-worker-win, docker-multistage-win) as do the ones that
degrade gracefully off Windows (web-edge, node-windows, php-com). Compiled
Windows-only demos run through Wine and embed: c-paint, c-sysmon,
win32-native, winforms-dotnet, csharp-winrt, and rust-synth (cross-compiled
for `x86_64-pc-windows-gnu`, the C# pattern). csharp-binding-win: WPF
FailFasts in font fallback under Wine (Wine limit). The interpreted
Windows-only ones (python-winapi, java-ffm, ruby-com, ruby-lsystem-win) and
docker-windows are now *detected* as Windows (they get the four-pane mark
on both OSes) and Linux says why it can't run them. Not built yet, but
proven: a Windows Python 3.12 inside the Wine prefix runs python-winapi's
`--selftest` — Windows toolchains in the prefix would be the mirror of WSL's.
Existing configs keep the platform they were added with: on Windows,
re-add those demos (or right-click ▸ Runs on ▸ Windows) to see the mark.

## Traps (each cost real time)

- Electron 38+ ignores `ELECTRON_OZONE_PLATFORM_HINT`. With
  `XDG_SESSION_TYPE=wayland` it opens on the real Wayland desktop even with
  `WAYLAND_DISPLAY` removed (it finds the default socket): the embed never
  happens. `X11_BACKEND_HINTS` sets `XDG_SESSION_TYPE=x11` (also for WSL's
  VcXsrv env).
- Snap Chromium's AppArmor profile takes signals only from senders labelled
  `unconfined`. A confined launcher — or one started from Claude Desktop
  (`claude-desktop-unofficial`) — gets EPERM and leaks every web module's
  browser. `x_close_clients` then closes it through its X connection
  (XRes client → XKillClient), which needs no signal permission.
- A module's launch spec is asked for *after* its setup steps: a build
  entry's output (the jar mvn makes, make's newest program) doesn't exist on
  a fresh clone before then — it ran `java -jar (build)`.
- Not every `*-win` twin is cross-platform: ruby-lsystem-win (Win32 through
  Fiddle) and csharp-binding-win (WPF) are Windows-only. `detect_platform`'s
  per-language rules decide (module-level Windows imports, `unless
  Gem.win_platform?`, FFM on user32, Windows crates outside a cfg table,
  Windows base images), never the folder name.
- Hand-copying demo folders into a clone blocks `git pull` (untracked files)
  and an exFAT copy flips exec bits; compare blob hashes, `git clean`, pull.
  Windows-built node_modules/target/bin copied along are wrong on Linux.

- Edge signs the Windows account into every throwaway `--user-data-dir` and
  says so in a modal dialog. The dialog's owner is the embedded window, so
  it disabled the *launcher* — and came up minimized, nothing to click.
  Web launches pass `--disable-sync --disable-features=msImplicitSignin`;
  `winplat.free_owner` restores a minimized dialog of an embedded app and
  re-enables a launcher whose dialog's process died.
- Chromium `--app` windows draw caption + frame inside the client area;
  the host hangs the window past its edges by the page's insets
  (`Chrome_RenderWidgetHostHWND`). At 125% the bottom inset flips 7/8 with
  every resize — `settle_crop` only grows on 1-2 px changes.
- Win32 *child* windows can't have menus (the HMENU slot is the control
  ID): an embedded app loses a Win32 menu bar. Electron's survives (it is
  drawn in the client area). The C demos use buttons + accelerators.
- A failed setup step stops the launch even when a prebuilt exe exists:
  the C demos' recipes are prefixed `-` only while the exe exists.
- npm 11.19 blocks dependency install scripts by default; Electron ≤ 41
  downloads its binary in one (31's unzip also stops silently under
  Node 26). Electron 42+ has none and fetches on first start — which ate
  the 40 s embed wait. `npm_setup` runs `node_modules/electron/install.js`
  as a setup step for either. "Installed" means
  `node_modules/.package-lock.json` (npm writes it last) newer than
  `package.json`/`package-lock.json` — not the folder, so a failed install
  retries and a pulled dependency bump reinstalls.
- A drive mounted in WSL as root is root-owned: every chmod fails (npm's
  bin links: EPERM). `wsl_mount_args` copies /mnt/c's uid/gid.
- `windows-sys` ≥ 0.60 links via raw-dylib, which on the GNU toolchain needs
  `dlltool` on PATH (Rust ships one, privately): `rust-synth` pins 0.59.
- Fiddle runs a `bind` block with its own `self`; a Ruby exception must
  not unwind into user32. ruby.exe has no Common Controls 6 manifest: the
  Ruby demos activate one at run time (`CreateActCtxW`) before comctl32 loads.
- Testing: PrintWindow on an embedded child needs the *parent's* thread
  pumping — a harness that blocks on its capture subprocess deadlocks.

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
- `C:\Windows\System32\wsl.exe` exists even without WSL (installer stub):
  readiness is `winplat.wsl_ready()` (distros under HKCU Lxss), never
  `which("wsl.exe")`. WSL mounts fixed drives only — a module on a removable
  drive gets `wsl_mount_args` first.
- On Windows `os.kill` calls an already-exited process "access denied" while
  a handle is open; `kill_pid` there is psutil's.
- Embedded children are never activated: a click must hand them focus
  (`_focus_if_outside`), or conhost never gets a key — and the reverse: a
  click on our own widgets must take it back (`take_keyboard`), or every
  shortcut goes to the embedded app.
- An embed search that times out keeps watching the module's own pids
  (slow builds: `dotnet run` compiles first); only the "new window since
  launch" guess stops at 40 s.
- Test scripts on a scaled display must be per-monitor DPI aware, or every
  coordinate they read or click is the scaled one.
- Tk withdraws its content when parented into a still-hidden window; the
  host shows it again once, a turn after its first showEvent.
- VcXsrv, once its window is our child: repaints only top-level windows
  (host invalidates at 30 Hz); maps clicks through its own copy of the
  window's screen position, refreshed only on that window's WM_MOVE (host
  posts one when the parent moves it); re-applies its frame and taskbar
  button right after mapping (host strips both again); steals the
  foreground for every new X window. Count frames on real screen pixels
  (BitBlt of the desktop), never PrintWindow — that renders fresh and hid
  the freeze.
