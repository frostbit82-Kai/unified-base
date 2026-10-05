# Installers

Release packaging for Unified Base.

    installer/
      build_linux.sh     build the Linux tarball  (run on Linux)
      build_windows.py   build the Windows setup.exe  (run on Windows)
      linux/             what goes inside the tarball for the end user
      windows/           the Inno Setup script, the end-user README, selftest.bat
      licenses/          third-party licence texts, shipped in app/licenses
      build/  dist/      output, gitignored

## Releases

`.github/workflows/release.yml` builds both installers on GitHub's runners
(free for a public repo) with the two scripts below, `test_core.py` gating
each. Bump `VERSION`, commit, then

    git tag v0.9.1 && git push origin v0.9.1

and it makes a **draft** release with both files, renamed without the
version (`UnifiedBase-windows-x64-setup.exe`, `UnifiedBase-linux-x86_64.tar.gz`,
so `/releases/latest/download/<name>` — what the README and the website link
— always reaches the newest) and `SHA256SUMS.txt`. Download them, try them on
a real machine, then Publish. The tag must match `VERSION` or it stops.
*Run workflow* on the Actions tab builds them as artifacts without a release.
The release text is `.github/release-notes.md`; edit the draft for what
changed.

## Linux

    bash installer/build_linux.sh

Produces `installer/dist/UnifiedBase-<version>-linux-x86_64.tar.gz` (~75 MB).
The user extracts it and double-clicks *Install Unified Base* (or runs
`./install.sh`): it installs to `~/.local/share/UnifiedBase` with no root,
adds a menu entry (Development) and a `unified-base` command, and opens Qt
once to check it starts before claiming success. `./uninstall.sh` reverses
it and leaves `~/.unified_base` alone. Needs `uv` on the build machine.

### Why not PyInstaller

The package is a standalone CPython (python-build-standalone, fetched by
`uv python install`) with PySide6 pip-installed into it, running `main.py`
from source. Both reasons were measured:

- **The app runs its own helpers through `sys.executable`** — the Wine
  toolchain downloads, the run-once lock, the self-test's Tk probe. In a
  frozen build `sys.executable` is the app.
- **A frozen build inherits the build machine's glibc.** This box is Ubuntu
  26.04 (glibc 2.43); the Mint test machine is 21.3 (2.35). The standalone
  CPython needs 2.17, so the floor is PySide6's wheels: **2.34** — Mint 21+,
  Ubuntu 22.04+, Debian 12+. The build fails if anything raises it past
  `GLIBC_MAX` (2.35).

### What the build does, and the traps

- **The bundled Python runs with `-E -s`** — in the launcher, the install
  check and every build step. Without them it reads the build user's
  `~/.local/lib/python3.14` packages: pip counted `six` (python-xlib's
  dependency) as installed and left it out, the tests passed on the user's
  copy, and on a clean machine window lookup silently found nothing. On a
  user's machine their own packages would load ahead of the bundled Qt.
- **Qt is trimmed** from 233 MB to Widgets: a blunt list of unused modules,
  then an `ldd` loop deleting anything that links a missing Qt library,
  until nothing changes, then a check that the essentials survived. QtTest
  stays because the next step needs it.
- **`test_core.py` runs on the packaged runtime** and must say
  `ALL CHECKS PASS`; `import main` must work from the staged `app/`.
- **PyQt6 must not be in the runtime** (GPL, and a second Qt) — checked.
- `app/` is tracked files only (`git ls-files`), so demo build output stays
  behind. `app/BUILD` records the commit, `app/PACKAGES` the pip freeze.
- `uv python install` links `python3.x` into `~/.local/bin` unless given
  `--no-bin` — it did, pointing at a deleted build folder.

### Testing on Mint without booting it

With the Mint disk mounted, `bwrap` runs the package against Mint's own
glibc and libraries, read-only, no root:

    bwrap --ro-bind <mint-root> / --dev /dev --proc /proc --ro-bind /sys /sys \
          --tmpfs /tmp --bind /tmp/.X11-unix/X77 /tmp/.X11-unix/X77 \
          --tmpfs /run --ro-bind /run/systemd/resolve /run/systemd/resolve \
          --bind <scratch-home> /home/tim --bind <extracted-dir> /home/tim/Downloads \
          --clearenv --setenv HOME /home/tim --setenv DISPLAY :77 \
          --setenv PATH /home/tim/.local/bin:/usr/bin:/bin --setenv XDG_RUNTIME_DIR /tmp \
          bash -c 'cd ~/Downloads/UnifiedBase-*/ && ./install.sh && unified-base --selftest'

with `Xvfb :77` on the host. Do not unshare the PID namespace: the X server
reports host PIDs, and window lookup matches on them. The `/run/systemd/resolve`
bind gives it the host's DNS (Mint's resolv.conf points there), so module
setup and the toolchain downloads work. New mount points need a writable
parent: bind extra folders under a `--tmpfs /mnt`.

## Windows

    py installer\build_windows.py

Produces `installer\dist\UnifiedBase-<version>-windows-x64-setup.exe` (~28 MB;
97 MB installed) and the end-user README beside it. Needs `git`, `uv` and
Inno Setup 6 on the build machine (`winget install -e --id astral-sh.uv`,
`winget install -e --id JRSoftware.InnoSetup --scope user`). Any Python runs
the script; the package gets its own.

Same shape as Linux: python-build-standalone CPython (via uv, with Tk and the
MSVC runtime DLLs) with `requirements.txt` installed into it, `main.py` from
source. Inno Setup installs it **per user** (`PrivilegesRequired=lowest`,
`%LOCALAPPDATA%\Programs\Unified Base`, no UAC), so the demos still build in
the install folder. Nothing else is needed on the target: it passed on a
clean Windows Sandbox (no Python, no VC++ redistributable, no winget, no
WSL) — installed, self-test, `python-fractal-win` built its venv from the
bundled Python and embedded, then uninstalled clean.

What the setup does:

- **Start menu folder** "Unified Base": the app, *Set Up Linux Programs
  (WSL)*, *Unified Base Self-Test* (`selftest.bat`, a console that waits for
  Enter) and the Read Me. Desktop shortcut optional. The Finish page offers
  to launch it, run the WSL setup, or open the Read Me.
- **The shortcut runs `runtime\pythonw.exe -E -s app\main.py`.** No console:
  Qt then starts every module with `CREATE_NO_WINDOW`, so console programs
  open no window (checked across a dozen demos, WSL ones included). Not
  `conhost --headless` (works, but is a known malware trick that security
  tools flag), and not `python.exe` in a minimised console as `run.bat`
  does: that console shows until the app hides it, and pythonw has none.
- **AppUserModelID `BomsAI.UnifiedBase`** on the shortcuts and in the process
  (`winplat.set_app_id`), so pinning the running window pins the shortcut,
  not a bare pythonw.exe.
- **Refuses while Unified Base runs** — anything whose executable is under
  the install folder (a WMI query filtered by path; walking every process
  took 10 s), on upgrade and on uninstall, like the Linux scripts.
- **Upgrade replaces `runtime\` and `app\` wholesale** (`[InstallDelete]`),
  so the demos rebuild once; module venvs (in `~\.unified_base\envs`) keep
  working while the bundled Python's minor version stays the same.
- **Checks it starts**: after copying, it imports `main` and opens a
  `QApplication` with the bundled Python; a failure shows the error. It also
  leaves `main.py`'s byte-code.
- **Uninstall** removes the folder, build output included, then asks
  whether to delete the user's data too — No by default, since it holds the
  New Blank Tab projects. Yes deletes `%USERPROFILE%\.unified_base`, the
  Linux modules' `~/.unified_base` inside WSL (when WSL has a default
  distro) and any `%TEMP%\ub_web_*` Edge profiles a crash left.
  `/DELETEDATA=yes` does it on a silent uninstall.

### What the build does, and the traps

- **`uv pip`, not pip**: PySide6 has paths past Windows' 260-character limit
  (`qml\Qt\labs\...`), which pip cannot write (WinError 206); uv can.
- **Qt is trimmed** to what the app imports (QtCore, QtGui, QtWidgets,
  QtTest) plus the plugins it loads by name (platforms `qwindows` and
  `qoffscreen`, styles, imageformats, iconengines): everything those import,
  transitively, stays — read from the PE import tables, `ldd`'s job on Linux —
  every other DLL, .pyd and .exe goes. A plugin for a module the wheel does
  not ship (`qpdf` needs Qt6Pdf, which is in Addons) is dropped first. Then
  every remaining Qt/PySide/MSVC import must resolve, or the build fails.
  Also gone: QML, translations, `.pyi`, the Qt tools, `opengl32sw.dll` (20 MB,
  software OpenGL, unused by Widgets) and `resources\icudtl.dat` (QtWebEngine's
  ICU; Qt Core uses Windows').
- **test_core.py runs on the packaged runtime** and must say `ALL CHECKS
  PASS` with no traceback; `import main` must work from the staged `app\`,
  and Tk must load.
- **The icon** (`unified-base.ico`, 16–256 px) and the wizard images are drawn
  from `unified-base.svg` by the staged Qt; nothing binary is committed.
- **Inno's preprocessor un-doubles `""` inside `"..."`**: defines holding
  quoted arguments use single quotes.

### Languages on demand

The package carries Python only. A module's first start downloads the
language it needs into `%USERPROFILE%\.unified_base\toolchains`, per user:
`WINDOWS_TOOLCHAINS` in `main.py` (Node, .NET SDK, Temurin + Maven, rustup's
GNU host, RubyInstaller, PHP), pinned and SHA-256-checked, the same
mechanism as Linux's `USER_TOOLCHAINS`. The uninstaller's delete-data
answer runs the fetched Ruby's own uninstaller first (it registers itself
under Installed Apps); rustup's `~\.cargo` and `~\.rustup` stay, as on
Linux.

### Testing on a clean Windows

Windows Sandbox (Windows Pro; the "Windows Sandbox" feature) is a throwaway
clean Windows. A `.wsb` file maps a host folder in and runs a script at
logon; the script can `shutdown /s /t 0` to close the sandbox when done.
Start it with `WindowsSandbox.exe <file>.wsb` — double-clicking a `.wsb`
may ask which app to open it with. The sandbox has no winget and no
virtualization, so the WSL and Install-button paths only print their
guidance there.

### Linux programs on Windows: `setup-wsl.ps1`

At the repo root (so a source checkout has it too), on the Start menu, and
behind a Linux module's **Set up WSL** button. It checks the Windows build
(WSL 2 needs 19041; embedding needs 22621 for mirrored networking),
virtualization (a running hypervisor counts: with Hyper-V on, the CPU reports
its virtualization as off), WSL and a default distro that is not
`docker-desktop` (`wsl --install -d Ubuntu`, which raises its own UAC prompt),
python3-venv, python3-tk, gcc (Rust's linker) and the GUI libraries Electron,
Swing and Avalonia load (GTK, NSS, gbm, ALSA — `libasound2t64` on 24.04+,
where the old name has two providers) in the distro, VcXsrv (`winget install
marha.VcXsrv`), and `networkingMode=mirrored` in `.wslconfig` (backed up,
then `wsl --shutdown` if the user agrees). It asks before each change.

VcXsrv gets no login item: `winplat.start_x_server` starts it when a Linux
module needs it. It runs `cmd /c xkbcomp` twice as it starts, and under
Windows Terminal each opens a window for ~200 ms; nothing in the flags it is
started with changes that (it never passes a console on).
