# Installers

Release packaging for Unified Base.

    installer/
      build_linux.sh   build the Linux tarball  (run on Linux)
      linux/           what goes inside the tarball for the end user
      licenses/        third-party licence texts, shipped in app/licenses
      build/  dist/    output, gitignored

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
          --bind <scratch-home> /home/tim --bind <extracted-dir> /home/tim/Downloads \
          --clearenv --setenv HOME /home/tim --setenv DISPLAY :77 \
          --setenv PATH /home/tim/.local/bin:/usr/bin:/bin --setenv XDG_RUNTIME_DIR /tmp \
          bash -c 'cd ~/Downloads/UnifiedBase-*/ && ./install.sh && unified-base --selftest'

with `Xvfb :77` on the host. Do not unshare the PID namespace: the X server
reports host PIDs, and window lookup matches on them. There is no DNS inside
(Mint's resolver is not running), so anything that downloads fails there.

## Windows (next)

Same shape, built on Windows: a python-build-standalone (or python.org)
CPython with `requirements.txt` installed into it, `main.py` from source,
Inno Setup installing **per user** (`PrivilegesRequired=lowest`,
`{localappdata}\Programs\Unified Base`) so the demos can still build in the
install folder. The shortcut should run `python.exe main.py` in a minimised
console, as `run.bat` does — the app hides that console and every module
process shares it. Ship `installer/licenses/` and the `.ico` from
`unified-base.svg`.
