#!/usr/bin/env python3
"""Smallest runnable check for Unified Base's non-GUI logic.

Run:  python3 test_core.py   (inside the .venv — needs PyQt6 importable)
No framework — plain asserts. Fails loudly if core logic breaks.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import main  # noqa: E402


_APP = None
ON_WINDOWS = main.IS_WINDOWS     # the real host; _as_windows() only pretends
LINUX_HOST = set()


def linux_host(fn):
    """A check of Linux-only machinery (/proc, sh, the Wine bridge). Skipped
    on Windows, whose side of the same logic runs under _as_windows()."""
    LINUX_HOST.add(fn)
    return fn


def _app():
    """One QApplication for the whole run, held at module scope.

    A local reference dies when the check returns and PyQt then destroys the
    C++ object, so the next check that builds a widget crashes with
    "Must construct a QApplication before a QWidget".
    """
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def check_dep_name():
    for spec, want in [("requests>=2.0", "requests"),
                       ("PyQt6[all]==6", "PyQt6"),
                       ("x ; python_version<'3'", "x"),
                       ("plain", "plain")]:
        got = main._dep_name(spec)
        assert got == want, f"_dep_name({spec!r}) = {got!r}, want {want!r}"


def check_declared_deps():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "pyproject.toml").write_text(
            '[project]\nname = "x"\n'
            'dependencies = ["requests>=2.0", "rich"]\n'
            '[tool.poetry.dependencies]\npython = "^3.11"\nflask = "^2.0"\n')
        (p / "requirements.in").write_text("boto3\n# comment\n-c c.txt\n")
        deps = main.declared_python_deps(p)
        assert deps == ["boto3", "flask", "requests", "rich"], deps


def check_atomic_write():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "x.json"
        main.atomic_write(f, '{"a": 1}')
        assert f.read_text() == '{"a": 1}'
        main.atomic_write(f, '{"a": 2}')          # overwrite
        assert f.read_text() == '{"a": 2}'
        assert list(Path(d).iterdir()) == [f]     # no temp litter


def check_config_compat():
    # Old config (no extra_env/startup_args) must load with defaults.
    cfg = main._config_from_dict(
        {"name": "n", "project_dir": "/x", "entry": "m.py",
         "unknown_future_key": True})
    assert cfg.extra_env == {} and cfg.startup_args == []


def check_portable_paths():
    # In-repo paths round-trip through the <base>/ marker; a moved checkout
    # would resolve them against its own BASE_DIR.
    inside = str(main.DEMO_DIR / "Linux" / "python")
    stored = main.portable_path(inside)
    assert stored == "<base>/demo_module/Linux/python", stored
    assert main.resolve_path(stored) == inside
    # Paths outside the repo stay absolute and untouched.
    outside = "/home/someone/Projects/other"
    assert main.portable_path(outside) == outside
    assert main.resolve_path(outside) == outside
    # Loading a config stored either way yields a usable absolute path.
    assert main._config_from_dict(
        {"name": "n", "project_dir": stored, "entry": ""}).project_dir == inside


def check_moved_demo_paths():
    """Demos moved to demo_module/<OS>/; configs saved before still resolve."""
    old = "<base>/demo_module/python"            # the pre-move spelling
    got = main.resolve_path(old)
    assert got == str(main.DEMO_DIR / "Linux" / "python"), got
    # Re-saving writes the new spelling, so the migration is one-way.
    assert main.portable_path(got) == "<base>/demo_module/Linux/python"
    # A name that exists in no group is left alone — not invented.
    gone = main.resolve_path("<base>/demo_module/no-such-demo")
    assert gone == str(main.DEMO_DIR / "no-such-demo"), gone
    # Only *direct* children of demo_module are migrated.
    deep = "<base>/apps/python"
    assert main.resolve_path(deep) == str(main.BASE_DIR / "apps" / "python")
    # Group folders are looked through, so every demo is still found.
    found = main.project_dirs_in(main.DEMO_DIR)
    assert len(found) >= 18, len(found)
    assert all(f.parent.parent == main.DEMO_DIR for f in found), found[:3]


def check_frame_window_ranking():
    # Real shape of the csharp/rust bug: GNOME wraps the client in a larger
    # `mutter-x11-frames` window that also has a WM_CLASS, so it used to outrank
    # the client — embedding an empty frame, and freezing the session on remove.
    frame = (0x800385, 812 * 639, ("mutter-x11-frames", "mutter-x11-frames"))
    client = (0x800387, 800 * 600, ("demo", "Demo"))
    ranked = main.rank_new_windows([frame, client])
    assert ranked == [client[0]], ranked          # frame dropped entirely
    assert main.is_wm_frame(frame[2]) and not main.is_wm_frame(client[2])
    # Ranking still holds otherwise: WM_CLASS beats unnamed, then larger wins.
    unnamed_big = (0x1, 4000 * 4000, None)
    small_client = (0x2, 100 * 100, ("x", "X"))
    big_client = (0x3, 900 * 900, ("y", "Y"))
    assert main.rank_new_windows(
        [unnamed_big, small_client, big_client]) == [0x3, 0x2, 0x1]
    assert main.rank_new_windows([]) == []


def check_compose_args():
    # npm eats unknown flags; they must go after a `--` separator to reach the
    # script (this is what makes --no-sandbox work on an Electron module).
    assert main.compose_args("npm", ["start"], ["--no-sandbox"]) == \
        ["start", "--", "--no-sandbox"]
    assert main.compose_args("/usr/bin/npm", ["run", "dev"], ["--host"]) == \
        ["run", "dev", "--", "--host"]
    # Don't add a second separator if the caller already passed one.
    assert main.compose_args("npm", ["start", "--"], ["-x"]) == ["start", "--", "-x"]
    # Everything else takes args verbatim.
    assert main.compose_args("npx", ["electron", "main.js"], ["--no-sandbox"]) == \
        ["electron", "main.js", "--no-sandbox"]
    assert main.compose_args("python3", ["app.py"], []) == ["app.py"]
    assert main.compose_args("java", ["-jar", "x.jar"], None) == ["-jar", "x.jar"]


def check_chrome_sandbox_hint():
    # Exact abort text Chromium prints when unprivileged user namespaces are
    # blocked and chrome-sandbox isn't SUID root (Ubuntu apparmor default).
    err = ("[47965:0825/232257.203488:FATAL:setuid_sandbox_host.cc(158)] The "
           "SUID sandbox helper binary was found, but is not configured "
           "correctly. Rather than run without sandboxing I'm aborting now. "
           "You need to make sure that /home/u/app/node_modules/electron/dist/"
           "chrome-sandbox is owned by root and has mode 4755.")
    hint = main.chrome_sandbox_hint(err)
    assert hint and "chmod 4755" in hint, hint
    # The real path is echoed back, quoted, not a placeholder.
    assert "'/home/u/app/node_modules/electron/dist/chrome-sandbox'" in hint, hint

    # Same abort, but the project path has a space (verbatim from the user's
    # node-desktop run). A `\\S+` match truncated this to "Base/demo_module/..."
    # and printed a chown command that silently does nothing.
    spaced = err.replace("/home/u/app",
                         "/home/fr0st/Projects/Unified Base/demo_module/node-desktop")
    hint = main.chrome_sandbox_hint(spaced)
    assert "/home/fr0st/Projects/Unified Base/demo_module/node-desktop" in hint, hint
    # chown/chmod is the WRONG advice here: the SUID helper would then die on
    # the space, so this branch must send them to --no-sandbox instead.
    assert "--no-sandbox" in hint and "chmod" not in hint, hint
    # Second failure mode: helper configured, but the path has a space, so the
    # zygote re-exec is truncated at it.
    zyg = ("LaunchProcess: failed to execvp:\n/home/fr0st/Projects/Unified\n"
           "[51824:0825/232825.041224:FATAL:zygote_host_impl_linux.cc(201)] "
           "Check failed: . : Invalid argument (22)")
    hint = main.chrome_sandbox_hint(zyg)
    assert hint and "--no-sandbox" in hint and "spaces" in hint, hint
    # Windows: a portable Chromium whose folder app containers can't read
    # (verbatim, D:\chrome-win on an SD card). The fix names that folder.
    win = (r"[2164:12540:1003/192948.747:ERROR:sandbox\policy\win\sandbox_win"
           r".cc:805] Sandbox cannot access executable D:\Apps\chrome win\chro"
           r"me.EXE. Check filesystem permissions are valid. See https://bit.l"
           r"y/31yqMJR.: Access is denied. (0x5)")
    hint = main.chrome_sandbox_hint(win)
    assert hint and r'icacls "D:\Apps\chrome win" /grant' in hint, hint
    assert "S-1-15-2-1" in hint and "S-1-15-2-2" in hint, hint
    # Ordinary output must not trigger either branch.
    assert main.chrome_sandbox_hint("Debugger listening on ws://...") is None


@linux_host
def check_kill_process_tree():
    # QProcess.kill() only reaps the wrapper: `npm start` dies while the
    # electron/vite it forked keeps its port and its X window. Same shape
    # here — a shell whose grandchild must not survive the kill.
    import signal
    import subprocess
    import time
    parent = subprocess.Popen(["bash", "-c", "sleep 60 & sleep 60"])
    time.sleep(0.3)
    tree = main.descendant_pids(parent.pid)
    assert len(tree) >= 2, tree           # parent + at least one sleep
    assert main.kill_process_tree(parent.pid, signal.SIGKILL) >= 2
    parent.wait(timeout=5)
    time.sleep(0.3)
    alive = [p for p in tree if Path(f"/proc/{p}").exists()]
    # A dead-but-unreaped child still has a /proc entry; state Z is fine.
    for p in alive:
        state = Path(f"/proc/{p}/stat").read_text().rsplit(")", 1)[1].split()[0]
        assert state == "Z", (p, state)
    # A pid that no longer exists is not an error.
    assert main.kill_process_tree(parent.pid, signal.SIGKILL) >= 0


@linux_host
def check_pids_with_arg():
    # Snap-packaged Chromium re-execs into its own systemd scope, so it is not
    # in our process tree at all; the unique --user-data-dir we passed is the
    # only handle left on it. Same shape here: find a process by an argument.
    import signal
    import subprocess
    import time
    tag = "/tmp/ub_web_selftest_marker"
    proc = subprocess.Popen(["bash", "-c", f"exec -a 'sleep {tag}' sleep 60"])
    time.sleep(0.3)
    found = main.pids_with_arg(tag)
    assert proc.pid in found, (proc.pid, found)
    # Never returns our own pid, and refuses needles too generic to be safe.
    assert os.getpid() not in main.pids_with_arg("python")
    assert main.pids_with_arg("sh") == set()
    for pid in found:
        os.kill(pid, signal.SIGKILL)
    proc.wait(timeout=5)
    time.sleep(0.3)
    assert not main.pids_with_arg(tag)


def check_border_colors():
    # Every language's highlight border must clear the dark-theme floor,
    # otherwise ruby (#701516) and java (#B07219) paint a near-black outline.
    for rid in main.LANG_COLORS:
        for c in main.border_colors(rid):
            assert c.lightness() >= 120, (rid, c.name(), c.lightness())
    # Bright tones pass through untouched.
    assert main.border_colors("node")[0].name() == "#f7df1e"
    # Unknown runtime falls back to the same grey the tab chip uses.
    grey = main.border_colors("nope")
    assert grey[0] == grey[1] and grey[0].name() == "#9aa0a6", grey


def check_visible_pane_count():
    # Merge-mode panes all show at once -> highlight is worth drawing.
    assert main.visible_pane_count([False, False, False], 1) == 3
    # An independent module takes the window alone -> nothing to locate.
    assert main.visible_pane_count([False, True, False], 1) == 1
    # Independents don't count toward the merged set.
    assert main.visible_pane_count([False, True, False], 0) == 2
    # Single module, and no modules at all.
    assert main.visible_pane_count([False], 0) == 1
    assert main.visible_pane_count([], 0) == 0
    assert main.visible_pane_count([False, False], -1) == 0


def check_missing_setup_msg():
    # A program that is present is not worth a word.
    assert main.missing_setup_msg(sys.executable) is None
    # Ubuntu ships bundler as a default gem but no `bundle` binstub, so the
    # ruby demo died on `bundle install` even though its one gem was already
    # installed. A missing setup program must not read as a hard failure.
    msg = main.missing_setup_msg("definitely-not-a-real-binary-xyz")
    assert msg and "starting anyway" in msg, msg
    assert "definitely-not-a-real-binary-xyz" in msg, msg
    # Setup-only programs carry their own package names.
    for cmd in ("bundle", "npm", "mvn", "cargo"):
        assert cmd in main.TOOLCHAIN_PKGS, cmd
    hint = main.toolchain_install_cmd("bundle")
    assert hint is None or "bundler" in hint or "ruby" in hint, hint


def check_runtime_launch_specs():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        # C#: detect via .sln glob; launch uses --project with filename
        (p / "App.sln").touch()
        assert main.CsharpRuntime.detect(p)
        (p / "App.csproj").touch()
        assert main.CsharpRuntime.entries(p) == ["App.csproj"]
        spec = main.CsharpRuntime.launch(
            main.ModuleConfig("n", str(p), "App.csproj", runtime="csharp"))
        assert spec.args == ["run", "--project", "App.csproj"], spec.args

        # Ruby: entries keep .rb extension; (default) resolves to a real file
        (p / "app.rb").touch()
        assert "app.rb" in main.RubyRuntime.entries(p)
        spec = main.RubyRuntime.launch(
            main.ModuleConfig("n", str(p), "(default)", runtime="ruby"))
        assert spec.args == ["app.rb"], spec.args

        # Node: an Electron app's declared main must launch under electron,
        # not node (plain `node main.js` leaves `app` undefined).
        (p / "package.json").write_text(
            '{"main": "main.js", "devDependencies": {"electron": "^31"}}')
        spec = main.NodeRuntime.launch(
            main.ModuleConfig("n", str(p), "main.js", runtime="node"))
        assert (spec.program, spec.args) == ("npx", ["electron", "main.js"]), spec
        # A non-main script in the same project still runs under node.
        spec = main.NodeRuntime.launch(
            main.ModuleConfig("n", str(p), "build.js", runtime="node"))
        assert (spec.program, spec.args) == ("node", ["build.js"]), spec

        # A runtime that serves a URL must say so: the launcher watches its
        # stdout and embeds a browser instead of hunting for a window. PHP's
        # dev server is the case that was missing — the tab stayed blank.
        spec = main.PhpRuntime.launch(
            main.ModuleConfig("n", str(p), "composer (dev server)",
                              runtime="php"))
        assert spec.serves and spec.args[0] == "-S", spec
        assert spec.args[1].startswith("localhost:"), spec
        # The port is picked, not hardcoded: two PHP modules used to both
        # grab :8000 and the second died with "Address already in use".
        # (Binding 8000 here for real would be flaky — TIME_WAIT from an
        # earlier run makes the bind fail and the check lie.)
        real = main.free_port
        main.free_port = lambda pref: 54321
        try:
            busy = main.PhpRuntime.launch(
                main.ModuleConfig("n", str(p), "composer (dev server)",
                                  runtime="php"))
        finally:
            main.free_port = real
        assert busy.args == ["-S", "localhost:54321"], busy.args
        # A plain PHP script is not a server.
        assert not main.PhpRuntime.launch(
            main.ModuleConfig("n", str(p), "index.php", runtime="php")).serves
        assert main.WebRuntime.launch(
            main.ModuleConfig("n", str(p), "npm:dev", runtime="web")).serves
        assert not main.RubyRuntime.launch(
            main.ModuleConfig("n", str(p), "app.rb", runtime="ruby")).serves

        # Docker: no TTY flags, --rm present
        spec = main.DockerRuntime.launch(
            main.ModuleConfig("n", str(p), "docker build & run",
                              runtime="docker"))
        assert "-it" not in spec.args and "--rm" in spec.args, spec.args
        # Named, so stop() can remove the container: killing `docker run`
        # only detaches the client and leaves it running.
        assert "--name" in spec.args, spec.args
        # Tag is namespaced, never a bare folder name that could shadow a
        # real image (a folder called `nginx` used to build `nginx:latest`).
        tag = spec.args[-1]
        assert tag.startswith("ub-"), tag
        # Two runs of one image get distinct container names.
        spec2 = main.DockerRuntime.launch(
            main.ModuleConfig("n", str(p), "docker build & run",
                              runtime="docker"))
        assert spec2.args[spec2.args.index("--name") + 1] != \
            spec.args[spec.args.index("--name") + 1], spec2.args
        assert spec2.args[-1] == tag, spec2.args

        # Compose: v2 ships as a `docker compose` plugin with no binary on
        # PATH; only an actual v1 install should be called `docker-compose`.
        (p / "docker-compose.yml").write_text("services: {}\n")
        cfg = main.ModuleConfig("n", str(p), "docker-compose up",
                                runtime="docker")
        real_which = main.shutil.which
        main.shutil.which = lambda c: "/usr/bin/docker-compose" \
            if c == "docker-compose" else real_which(c)
        try:
            v1 = main.DockerRuntime.launch(cfg)
        finally:
            main.shutil.which = real_which
        assert (v1.program, v1.args) == ("docker-compose", ["up"]), v1
        main.shutil.which = lambda c: None if c == "docker-compose" \
            else real_which(c)
        try:
            v2 = main.DockerRuntime.launch(cfg)
        finally:
            main.shutil.which = real_which
        assert (v2.program, v2.args) == ("docker", ["compose", "up"]), v2
        (p / "docker-compose.yml").unlink()


def check_binary_build_entries():
    """Makefile/CMake projects must be launchable before anything is built."""
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        (proj / "Makefile").write_text("app:\n\ttrue\n")
        ents = main.BinaryRuntime.entries(proj)
        assert main.BinaryRuntime.MAKE in ents, ents
        cfg = main.ModuleConfig("n", str(proj), main.BinaryRuntime.MAKE,
                                runtime="binary")
        steps = main.BinaryRuntime.setup_steps(cfg)
        assert steps and steps[0][1] == "make", steps
        # Nothing built yet: the spec names the folder searched, and never
        # the project dir as a program to execute (that raised
        # PermissionError: the launcher tried to run the directory).
        (proj / "CMakeLists.txt").write_text("project(x)\n")
        ccfg = main.ModuleConfig("n", str(proj), main.BinaryRuntime.CMAKE,
                                 runtime="binary")
        csteps = main.BinaryRuntime.setup_steps(ccfg)
        assert csteps and "cmake" in csteps[0][2][-1], csteps
        assert main.BinaryRuntime.launch(ccfg).program == str(proj / "build")
        # Built output is what gets launched, newest first.
        if ON_WINDOWS:
            exe = proj / "app.exe"
            exe.write_bytes(b"MZ")
        else:
            exe = proj / "app"
            exe.write_text("#!/bin/sh\ntrue\n")
            exe.chmod(0o755)
        assert main.BinaryRuntime.launch(cfg).program == str(exe)


def check_free_port():
    import socket as _s
    # Preferred port free -> we get it back.
    probe = _s.socket(); probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]; probe.close()
    assert main.free_port(port) == port
    # Preferred port held -> a different, usable port.
    held = _s.socket(); held.bind(("127.0.0.1", 0))
    busy = held.getsockname()[1]
    try:
        got = main.free_port(busy)
        assert got != busy and got > 0, got
    finally:
        held.close()


def check_toolchain_preflight():
    # Present toolchain -> no message; python is never gated.
    assert main.missing_toolchain_msg("python") is None
    # A runtime whose command is guaranteed absent -> actionable message.
    main.TOOLCHAIN_CMD["_fake"] = "definitely-not-a-real-binary-xyz"
    msg = main.missing_toolchain_msg("_fake")
    del main.TOOLCHAIN_CMD["_fake"]
    assert msg and "definitely-not-a-real-binary-xyz" in msg, msg
    # Install command uses the detected package manager syntax when known.
    cmd = main.toolchain_install_cmd("node")
    assert cmd is None or "node" in cmd.lower(), cmd


def _row_window(app, d, n):
    """A shown UnifiedBase with `n` merge panes, its state in temp dir `d`,
    sized narrower than the panes need — the case both row checks care about."""
    sandbox = Path(d)
    for attr, name in [("APP_DIR", ""), ("CONFIG_FILE", "modules.json"),
                       ("PREFS_FILE", "prefs.json"),
                       ("LIBRARY_FILE", "library.json"),
                       ("LAYOUTS_FILE", "layouts.json"),
                       ("ENVS_DIR", "envs"), ("LOG_DIR", "logs")]:
        setattr(main, attr, sandbox / name if name else sandbox)
    main.save_configs([main.ModuleConfig(name=f"m{i}", project_dir=str(d),
                                        entry="main.py", runtime="python")
                       for i in range(n)])
    win = main.UnifiedBase()
    win.resize(1200, 700)
    win.show()
    win._set_merge_mode("row")
    for _ in range(6):
        app.processEvents()
    return win


def check_row_drag_slack():
    """Single-row panes must be draggable, not pinned at pane_min.

    A splitter can only give one pane what it takes from another, so if every
    pane sits at its minimum width the handles freeze — which is what happened
    once the row overflowed the viewport.
    """
    from PyQt6.QtWidgets import QApplication
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        n = 3
        win = _row_window(app, d, n)
        sp = win.row_splitter
        mins = sum(sp.widget(i).minimumWidth() for i in range(sp.count()))
        handles = sp.handleWidth() * (sp.count() - 1)
        assert sp.count() == n, sp.count()
        assert sp.width() - (mins + handles) > 0, \
            f"no slack: width={sp.width()} mins={mins} handles={handles}"
        # Total is still n panes wide, so the row scrolls exactly as before.
        assert sp.width() >= n * win.pane_min.width(), sp.width()
        win.close()


def check_tab_reveals_pane():
    """Picking a tab scrolls that module's pane into view."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        win = _row_window(app, d, 5)
        last = win.module_tabs[-1]
        assert last.visibleRegion().boundingRect().width() < last.width(), \
            "pane already fully visible — test proves nothing"
        QTest.mouseClick(win.tabbar, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         win.tabbar.tabRect(4).center())
        for _ in range(6):
            app.processEvents()
        vis = last.visibleRegion().boundingRect()
        assert vis.width() == last.width(), \
            f"pane not revealed: {vis.width()} of {last.width()}"
        # Clicking the tab that is already current jumps back to it.
        win.scroll.horizontalScrollBar().setValue(0)
        for _ in range(4):
            app.processEvents()
        QTest.mouseClick(win.tabbar, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         win.tabbar.tabRect(4).center())
        for _ in range(6):
            app.processEvents()
        assert last.visibleRegion().boundingRect().width() == last.width(), \
            "already-current tab did not scroll back"
        win.close()


def check_custom_runtime():
    """The any-language escape hatch: user-supplied shell commands."""
    rt = main.CustomRuntime
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / "main.py").write_text("print(1)\n")     # would detect python
        assert rt.detect(proj) is False                 # never auto-picked
        assert "custom" not in main.detect_runtimes(proj)

        cfg = main.ModuleConfig(name="x", project_dir=str(proj), entry="",
                                runtime="custom")
        assert rt.setup_steps(cfg) == []                # nothing set yet
        assert rt.launch(cfg).serves is False

        cfg.custom_setup = "make deps && echo ok"
        cfg.custom_run = "wish gui.tcl"
        cfg.custom_serves = True
        label, prog, args, cwd = rt.setup_steps(cfg)[0]
        assert cwd == str(proj), cwd
        assert args[-1] == cfg.custom_setup, args      # whole line, unsplit
        spec = rt.launch(cfg)
        assert spec.serves is True
        assert spec.workdir == str(proj), spec.workdir
        # "$@" tail + a $0 placeholder, so startup args land in the command
        # instead of becoming inert positional parameters. (cmd.exe needs
        # neither: start_qprocess appends them to the line.)
        if not ON_WINDOWS:
            assert spec.args[-2].endswith('"$@"'), spec.args
            assert spec.args[-1] == "ub-custom", spec.args
        composed = main.compose_args(spec.program, spec.args, ["--flag"])
        assert composed == spec.args + ["--flag"], composed

        # Config round-trip, and an old config without the fields still loads.
        keep = (main.APP_DIR, main.CONFIG_FILE)
        main.CONFIG_FILE = proj / "modules.json"
        main.APP_DIR = proj
        main.save_configs([cfg])
        back = main.load_configs()[0]
        assert (back.custom_run, back.custom_serves) == ("wish gui.tcl", True)
        (proj / "modules.json").write_text(
            '[{"name": "old", "project_dir": "/tmp", "entry": "main.py"}]')
        old = main.load_configs()[0]
        assert (old.custom_run, old.custom_serves) == ("", False)
        main.APP_DIR, main.CONFIG_FILE = keep    # don't strand later checks


def check_custom_start_routing():
    """A custom module that serves a URL takes the web path, not the window
    path; one with no run command refuses instead of launching the shell."""
    from PyQt6.QtWidgets import QApplication
    app = _app()   # noqa: F841
    with tempfile.TemporaryDirectory() as d:
        cfg = main.ModuleConfig(name="x", project_dir=d, entry="",
                                runtime="custom", custom_run="./serve.sh",
                                custom_serves=True)
        tab = main.ModuleTab(cfg)
        went = []
        tab._start_server = lambda rt: went.append("server")
        tab._start_generic = lambda proj: went.append("generic")
        tab.start()
        assert went == ["server"], went

        cfg.custom_serves = False
        went.clear()
        tab.start()
        assert went == ["generic"], went

        cfg.custom_run = "   "          # nothing to run: refuse, don't guess
        went.clear()
        tab.start()
        assert went == [], went
        assert "no run command" in tab.log.toPlainText().lower(), \
            tab.log.toPlainText()[-200:]
        tab.deleteLater()


def check_shell_command():
    prog, args = main.shell_command("echo hi")
    if ON_WINDOWS:
        assert args == ["/d", "/s", "/c", "echo hi"], args
        return
    assert args == ["-lc", "echo hi"], args
    prog, args = main.shell_command("run me", forward_args=True)
    assert args == ["-lc", 'run me "$@"', "ub-custom"], args


def check_push_recent():
    d = []
    for x in ("/a", "/b", "/a"):
        d = main.push_recent(d, x)
    assert d == ["/a", "/b"], d           # no duplicate, newest first
    d = main.push_recent(list("abcdefgh"), "z", limit=3)
    assert d == ["z", "a", "b"], d        # capped, oldest dropped


def check_tab_highlight():
    """The clicked tab gets the same outline colors as its pane."""
    from PyQt6.QtWidgets import QApplication
    app = _app()   # noqa: F841
    bar = main.LangTabBar()
    bar.addTab("one")
    assert bar.hl_index is None
    colors = main.border_colors("python")
    bar.set_highlight(0, colors)
    assert (bar.hl_index, bar.hl_colors) == (0, colors)
    for mode in ("chips", "full"):   # both paint paths draw the outline
        bar.color_mode = mode
        assert not bar.grab().isNull()
    bar.set_highlight(None, None)
    assert bar.hl_index is None
    assert not bar.grab().isNull()


def check_compact_header():
    """A pane dragged narrow folds its button row into the ☰ menu.

    The header needs ~640px but a tiled pane can be dragged to PANE_MIN_W
    (160), where the buttons survived as unreadable ~13px slivers.
    """
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import QPoint, Qt
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        win = _row_window(app, d, 3)
        panes = win.module_tabs
        # Nothing in the pane may set a minimum wider than a dragged pane, or
        # the drag below silently does nothing.
        assert panes[0].layout().minimumSize().width() <= main.PANE_MIN_W, \
            panes[0].layout().minimumSize().width()
        assert all(t._compact == 0 for t in panes), [t._compact for t in panes]

        sp = win.row_splitter
        h = sp.handle(1)
        mid = QPoint(h.width() // 2, h.height() // 2)
        origin = h.mapToGlobal(mid)
        QTest.mousePress(h, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, mid)
        for step in range(0, 700, 25):
            QTest.mouseMove(h, h.mapFromGlobal(origin) + QPoint(-step, 0))
            app.processEvents()
        QTest.mouseRelease(h, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)
        for _ in range(6):
            app.processEvents()

        narrow, wide = panes[0], panes[2]
        assert narrow.width() < 430, narrow.width()
        assert narrow._compact > 0, narrow._compact
        assert not narrow.btn_start.isVisible()
        assert narrow.btn_more.isVisible()
        # Every action still reachable, and the menu mirrors button state.
        narrow._fill_more_menu()
        labels = [a.text() for a in narrow.menu_more.actions() if a.text()]
        for want in ("Start", "Stop", "Restart", "Logs"):
            assert any(want in x for x in labels), (want, labels)
        # Its neighbour kept the full header.
        assert wide._compact == 0 and wide.btn_start.isVisible(), wide.width()
        for t in panes:
            t.shutdown()
        win.close()


def check_compact_button_intent():
    """Collapsing must not resurrect a button that was deliberately hidden."""
    from PyQt6.QtWidgets import QApplication
    app = _app()   # noqa: F841
    cfg = main.ModuleConfig(name="m", project_dir="/tmp", entry="main.py")
    tab = main.ModuleTab(cfg)
    # isVisibleTo, not isVisible: the tab is never shown, so isVisible() is
    # False for every child no matter what the compact tier did.
    assert not tab.btn_install.isVisibleTo(tab)   # hidden by _build_ui
    tab._show_btn(tab.btn_install, True)
    tab._compact = 2                             # as if dragged narrow
    tab._show_btn(tab.btn_nosandbox, True)
    assert not tab.btn_nosandbox.isVisibleTo(tab), "compact pane showed one"
    tab._compact = None                          # force _apply_compact to run
    tab.resize(900, 400)
    tab._apply_compact()
    assert tab._compact == 0, tab._compact
    assert tab.btn_install.isVisibleTo(tab), "wanted button lost on expand"
    assert tab.btn_nosandbox.isVisibleTo(tab)
    assert tab.cmd_row.isVisibleTo(tab)
    tab.shutdown()


def check_module_log_file():
    """Pane output is teed to disk — the widget's 5000 blocks die with the tab."""
    from PyQt6.QtWidgets import QApplication
    app = _app()   # noqa: F841
    with tempfile.TemporaryDirectory() as d:
        keep = (main.LOG_DIR, main.ENVS_DIR)
        main.LOG_DIR = Path(d) / "logs"
        main.ENVS_DIR = Path(d) / "envs"
        try:
            cfg = main.ModuleConfig(name="m", project_dir=d, entry="main.py")
            tab = main.ModuleTab(cfg)
            tab._log("first")
            tab._log("second")
            files = sorted(main.LOG_DIR.glob("*.log"))
            assert len(files) == 1, files
            # Name carries the project-path hash, so same-named modules split.
            assert files[0].stem == cfg.env_dir.name, files[0]
            body = files[0].read_text()
            assert "first" in body and "second" in body, body
            assert "[log file:" in tab.log.toPlainText()
            tab.shutdown()
            assert tab._logfile is None
        finally:
            main.LOG_DIR, main.ENVS_DIR = keep


def check_env_var_editor():
    """extra_env has always been honored at launch; this is the way in."""
    from PyQt6.QtWidgets import (QApplication, QDialogButtonBox,
                                 QPlainTextEdit)
    from PyQt6.QtCore import QTimer
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        win = _row_window(app, d, 1)

        def fill():
            dlg = QApplication.activeModalWidget()
            if dlg is None:
                return
            dlg.findChild(QPlainTextEdit).setPlainText(
                "DEBUG=1\n# comment\n\n"
                "API_URL=http://localhost:8000\n  SPACED = yes  \nJUNK")
            dlg.findChild(QDialogButtonBox).button(
                QDialogButtonBox.StandardButton.Ok).click()

        # The "JUNK was ignored" warning opens only after the editor closes,
        # so poll for it: a single fixed-delay timer could fire before the
        # warning exists and leave that modal waiting forever (a hung run).
        from PyQt6.QtWidgets import QMessageBox
        poll = QTimer()
        poll.setInterval(20)
        deadline = time.monotonic() + 5

        def dismiss():
            w = QApplication.activeModalWidget()
            if isinstance(w, QMessageBox):
                w.accept()
                poll.stop()
            elif time.monotonic() > deadline:
                poll.stop()

        poll.timeout.connect(dismiss)
        QTimer.singleShot(0, fill)
        poll.start()
        win._edit_env_vars(0)
        poll.stop()
        env = win.module_tabs[0].cfg.extra_env
        assert env == {"DEBUG": "1", "API_URL": "http://localhost:8000",
                       "SPACED": "yes"}, env      # comment + JUNK dropped
        saved = main.load_configs()
        assert saved[0].extra_env == env, saved[0].extra_env
        for t in win.module_tabs:
            t.shutdown()
        win.close()


def check_shortcuts():
    """Keys act on the picked tab, wherever the focus happens to be."""
    from PyQt6.QtWidgets import QApplication, QMenu
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        win = _row_window(app, d, 3)
        m_run = next(m for m in win.menuBar().findChildren(QMenu)
                     if m.title() == "&Run")
        keys = {a.text(): a.shortcut().toString() for a in m_run.actions()
                if a.text()}
        for label, seq in (("Start", "F5"), ("Stop", "Shift+F5"),
                           ("Restart", "Ctrl+R"), ("Close Module", "Ctrl+W"),
                           ("Next Module", "Ctrl+PgDown")):
            assert keys.get(label) == seq, (label, keys.get(label))
        seqs = {a.shortcut().toString() for a in win.actions()}
        assert all(f"Ctrl+{n}" in seqs for n in range(1, 10)), sorted(seqs)

        win.tabbar.setCurrentIndex(0)
        win._cycle_tab(1)
        assert win.tabbar.currentIndex() == 1
        win._cycle_tab(-1)
        assert win.tabbar.currentIndex() == 0
        win._cycle_tab(-1)
        assert win.tabbar.currentIndex() == 2, "cycle must wrap"
        win._select_tab(1)
        assert win.tabbar.currentIndex() == 1
        win._select_tab(99)                     # out of range = no-op
        assert win.tabbar.currentIndex() == 1
        hit = []
        win._on_current(lambda t: hit.append(t.cfg.name))
        assert hit == ["m1"], hit
        for t in win.module_tabs:
            t.shutdown()
        win.close()


def check_geometry_roundtrip():
    """Reopen where we closed — but never off every screen."""
    from PyQt6.QtWidgets import QApplication
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        win = _row_window(app, d, 0)
        avail = app.primaryScreen().availableGeometry()
        size = (min(1234, avail.width() - 80), min(567, avail.height() - 80))
        win.resize(*size)
        win.move(140, 90)
        # The offscreen platform settles a top-level resize asynchronously,
        # so wait for it and compare against the size actually closed at.
        for _ in range(30):
            app.processEvents()
            if (win.width(), win.height()) == size:
                break
        want = (win.width(), win.height())
        assert want == size, want
        win.close()
        blob = main.load_prefs().get("geometry")
        assert blob, "geometry not saved on close"

        again = main.UnifiedBase()
        again.show()
        for _ in range(30):
            app.processEvents()
            if (again.width(), again.height()) == want:
                break
        assert (again.width(), again.height()) == want, \
            (again.width(), again.height(), want)
        again.close()

        # A blob from a monitor that is gone must not restore an invisible
        # window.
        far = main.UnifiedBase()
        far.resize(400, 300)
        far.move(60000, 60000)
        prefs = main.load_prefs()
        prefs["geometry"] = bytes(far.saveGeometry().toBase64()).decode()
        far.close()
        main.save_prefs(prefs)
        back = main.UnifiedBase()
        back.show()
        app.processEvents()
        assert back.x() < 10000 and back.y() < 10000, (back.x(), back.y())
        back.close()

        prefs["geometry"] = "not-base64-!!!"    # corrupt prefs must not crash
        main.save_prefs(prefs)
        ok = main.UnifiedBase()
        ok.show()
        app.processEvents()
        ok.close()
        # Keep every window alive to the end of the check: a collected
        # QMainWindow that is still an application event filter crashes Qt.
        del win, again, far, back, ok


def check_proc_table():
    """The meters' only data source. A dead pid is normal, not an error."""
    me = os.getpid()
    full = main._proc_table()
    assert me in full, "own process missing from a full sweep"
    ppid, ticks, rss = full[me]
    assert ppid > 0 and ticks >= 0 and rss > 0, full[me]
    few = main._proc_table([me])
    assert set(few) == {me}, list(few)
    assert main._proc_table([999999]) == {}, "a dead pid must be skipped"
    assert main._proc_table([]) == {}


@linux_host
def check_children_walk():
    """Tree membership comes from /proc/<pid>/task/*/children — one small read
    per process instead of a ~15 ms walk of every process on the box."""
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess, sys, time\n"
         "subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(4)'])\n"
         "time.sleep(4)"])
    try:
        for _ in range(40):                  # wait for the grandchild to exist
            time.sleep(0.05)
            kids = main._children_of(holder.pid)
            if kids:
                break
        assert kids, "no child found under the holder"
        tree = main._tree_from_children([holder.pid])
        assert holder.pid in tree and len(tree) >= 2, sorted(tree)
        # A kernel with no children files must say so, not report an empty tree.
        real = main._children_of
        main._children_of = lambda pid: None
        try:
            assert main._tree_from_children([holder.pid]) is None
        finally:
            main._children_of = real
        # A pid that is gone reads as "no children", not as a reason to fall back.
        assert main._children_of(999999) == []
    finally:
        holder.kill()
        holder.wait()


def check_sampler():
    """CPU and RSS per owner, summed over each owner's whole process tree."""
    from PyQt6.QtWidgets import QApplication
    _app()
    busy = subprocess.Popen(
        [sys.executable, "-c",
         "import time\nt=time.time()\nwhile time.time()-t<6: pass"])
    # Baseline only once it's up: interpreter startup is CPU too, and from a
    # slow drive (an SD card) it read 12.6% inside the measured window.
    idle = subprocess.Popen(
        [sys.executable, "-c", "import time;print(flush=True);time.sleep(6)"],
        stdout=subprocess.PIPE)
    idle.stdout.readline()
    try:
        sam = main.ResourceSampler()
        sam.set_roots("busy", [busy.pid])
        sam.set_roots("idle", [idle.pid])
        sam.tick()                    # first tick is only a baseline
        assert sam.usage["busy"][0] == 0.0, "no delta yet on the first tick"
        time.sleep(1.2)
        sam.tick()
        cpu_b, rss_b = sam.usage["busy"]
        cpu_i, rss_i = sam.usage["idle"]
        assert cpu_b > 40, f"a spinning process read {cpu_b:.1f}%"
        assert cpu_i < 10, f"a sleeping process read {cpu_i:.1f}%"
        assert rss_b > (1 << 20) and rss_i > (1 << 20), (rss_b, rss_i)
        assert abs(sam.total[0] - (cpu_b + cpu_i)) < 0.01, sam.total
        assert sam.total[1] == rss_b + rss_i, sam.total

        # With children files present the expensive full sweep never runs.
        sweeps = []
        real = main._proc_table
        main._proc_table = lambda pids=None: (sweeps.append(pids is None)
                                              or real(pids))
        try:
            for _ in range(5):
                sam.tick()
        finally:
            main._proc_table = real
        assert not any(sweeps), f"{sweeps.count(True)} full /proc sweeps"

        sam.set_roots("busy", [])
        sam.set_roots("idle", [])
        sam.tick()
        assert sam.usage == {} and sam.total == (0.0, 0), (sam.usage, sam.total)
    finally:
        for pr in (busy, idle):
            pr.kill()
            pr.wait()


def check_meter_widget():
    from PyQt6.QtWidgets import QApplication
    _app()
    m = main.ResourceMeter(main.border_colors("python"))
    m.resize(150, 20)
    assert not m.grab().isNull(), "empty meter must still paint"
    for v in (0, 5, 240, 60):          # 240% exercises the one-core marker
        m.push(v, 96 << 20)
    assert not m.grab().isNull()
    for _ in range(main.METER_HISTORY * 3):
        m.push(7, 1 << 20)
    assert len(m.history) == main.METER_HISTORY, len(m.history)
    m.clear()
    assert m.history == [] and m.cpu == 0.0 and m.rss == 0
    assert (main.human_bytes(2 << 30), main.human_bytes(96 << 20),
            main.human_bytes(4096)) == ("2.0G", "96M", "4K")


def check_log_modes():
    """The log shows in the pane, docked beside the module, or its own window —
    and survives every move, since it is one widget being reparented."""
    from PyQt6.QtWidgets import QApplication
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        win = _row_window(app, d, 1)
        tab = win.module_tabs[0]
        log = tab.log
        log.appendPlainText("marker line")

        def where():
            if log.parent() is tab.io_split:
                return "panel"
            if log.parent() is tab.log_dock:
                return "dock"
            if tab.log_window is not None and log.parent() is tab.log_window.host:
                return "window"
            return "?"

        assert where() == "panel", where()
        tab.container = object()          # pretend a module window is embedded
        tab._apply_log_mode()
        assert tab.stack.currentWidget() is tab.embed_page

        tab._set_log_mode("docked")
        assert where() == "dock", where()
        assert tab.log_dock.isVisible()
        assert tab.stack.currentWidget() is tab.embed_page, "module lost its pane"
        assert min(tab.body.sizes()) > 40, tab.body.sizes()
        assert tab.chk_logs.isChecked(), "picking a mode must switch logs on"

        tab._set_log_mode("undocked")
        app.processEvents()
        assert where() == "window", where()
        assert not tab.log_dock.isVisible()
        assert tab.log_window.isWindow()
        assert tab.log_window.colors == main.border_colors(tab.cfg.runtime)
        assert not tab.log_window.grab().isNull()

        tab.log_window.redock.emit()       # the ⧉ button
        app.processEvents()
        assert where() == "dock" and tab.log_window is None, where()

        tab._set_log_mode("undocked")
        app.processEvents()
        tab.log_window.close()             # the ✕ button
        app.processEvents()
        assert not tab.chk_logs.isChecked(), "✕ must switch the log off"
        assert where() == "panel" and tab.log_window is None, where()

        tab._set_log_mode("embedded")
        assert where() == "panel"
        assert tab.stack.currentWidget() is tab.panel, "log should take the pane"
        tab.chk_logs.setChecked(False)
        assert tab.stack.currentWidget() is tab.embed_page

        assert "marker line" in log.toPlainText(), "log content lost in a move"
        assert main.load_configs()[0].log_mode == "embedded"
        tab.container = None
        for t in win.module_tabs:
            t.shutdown()
        win.close()


def check_meter_toggles():
    """Master switch, per-module switch, and the narrow-pane tier."""
    from PyQt6.QtWidgets import QApplication
    app = _app()
    with tempfile.TemporaryDirectory() as d:
        win = _row_window(app, d, 1)
        tab = win.module_tabs[0]
        assert tab.sampler is win.sampler, "pane not wired to the shared sampler"
        assert win.sampler.timer.isActive()
        assert win.agg_meter.isVisible()

        win.act_meters.setChecked(False)
        assert not win.sampler.timer.isActive(), "master off must stop sampling"
        assert not win.agg_meter.isVisible()
        assert not tab.meter.isVisibleTo(tab)
        assert main.load_prefs().get("meters") is False
        win.act_meters.setChecked(True)
        assert win.sampler.timer.isActive()
        assert tab.meter.isVisibleTo(tab)

        tab.cfg.show_meter = False
        tab.set_meter_enabled(win.meters_on)
        assert not tab.meter.isVisibleTo(tab)
        assert id(tab) not in win.sampler.roots, "an off meter must not sample"
        assert win.agg_meter.isVisible(), "aggregate is not per module"
        tab.cfg.show_meter = True
        tab.set_meter_enabled(win.meters_on)
        assert tab.meter.isVisibleTo(tab)

        tab.resize(200, 400)          # below the 300px tier
        tab._apply_compact()
        assert not tab.meter.isVisibleTo(tab), tab._compact
        tab.resize(900, 400)
        tab._apply_compact()
        assert tab.meter.isVisibleTo(tab)
        for t in win.module_tabs:
            t.shutdown()
        win.close()


class _as_windows:
    """Run a block as if the launcher were on Windows (pure logic only)."""
    def __enter__(self):
        self.keep = main.IS_WINDOWS
        main.IS_WINDOWS = True

    def __exit__(self, *exc):
        main.IS_WINDOWS = self.keep


@linux_host
def check_bridge_selection():
    """A module says what it needs; the machine picks the bridge."""
    assert main.bridge_for("") == "native"
    assert main.bridge_for("linux") == "native"
    assert main.bridge_for("windows") == "wine"
    with _as_windows():
        assert main.bridge_for("") == "native"
        assert main.bridge_for("windows") == "native"
        assert main.bridge_for("linux") == "wsl"
    cfg = main.ModuleConfig(name="x", project_dir="/p", entry="", platform="")
    assert not main.builds_on_windows(cfg)
    with _as_windows():
        assert main.builds_on_windows(cfg)
        cfg.platform = "linux"          # built inside WSL: Linux names
        assert not main.builds_on_windows(cfg)
    # An old config without the field loads as "runs anywhere".
    old = main._config_from_dict({"name": "o", "project_dir": "/p", "entry": ""})
    assert old.platform == ""


def check_wsl_paths():
    t = main.to_wsl_path
    assert t(r"C:\Users\me\proj") == "/mnt/c/Users/me/proj"
    assert t(r"D:\a b\c.jar") == "/mnt/d/a b/c.jar"
    assert t("C:/mixed/slashes") == "/mnt/c/mixed/slashes"
    assert t(r"\\wsl$\Ubuntu\home\me\app") == "/home/me/app"
    assert t(r"\\wsl.localhost\Debian\srv") == "/srv"
    assert t(r"\\wsl$\Ubuntu") == "/"
    for same in ("/home/me", "relative/path", "--flag", "main.py", "x=C:y"):
        assert t(same) == same, same


def check_wsl_wrap():
    prog, args = main.wsl_wrap("npm", ["run", "dev"], r"C:\proj",
                               env={"NODE_ENV": "dev", "ROOT": r"C:\proj"},
                               track_pid=True)
    assert prog == "wsl.exe"
    assert args[:2] == ["--cd", "/mnt/c/proj"], args
    i = args.index("--exec")
    assert args[i + 1:i + 3] == ["bash", "-lc"]
    assert "UBPID:$$" in args[i + 3] and 'exec "$@"' in args[i + 3]
    tail = args[i + 5:]
    # env rides in front of the program, Windows paths translated
    assert tail == ["env", "NODE_ENV=dev", "ROOT=/mnt/c/proj",
                    "npm", "run", "dev"], tail
    # setup steps don't announce a pid, and skip a tool the distro lacks
    _, plain = main.wsl_wrap("make", [], "/x", setup=True)
    assert not any("UBPID" in a for a in plain)
    guard = plain[plain.index("-lc") + 1]
    assert 'command -v "$1"' in guard and "exit 0" in guard, guard
    assert plain[-1] == "make"
    # a shell line keeps its pipes and gets the startup args as "$@"
    prog, args = main.wsl_shell("ls | wc -l", r"C:\p", ["--x"])
    assert prog == "wsl.exe" and args[-1] == "--x"
    assert args[args.index("-lc") + 1] == 'ls | wc -l "$@"', args


def check_wsl_mount_args():
    """A module on a removable drive (D: is an SD card here) gets its drive
    mounted in WSL first; already-mounted drives make it a no-op."""
    a = main.wsl_mount_args(r"D:\Projects\Unified Base\demo")
    assert a[:4] == ["--cd", "~", "-u", "root"], a
    line = a[-1]
    assert line.startswith("mountpoint -q /mnt/d || ") and \
        "mount -t drvfs D: /mnt/d" in line, line
    assert main.wsl_mount_args("/home/me/proj") is None
    assert main.wsl_mount_args(r"\\wsl$\Ubuntu\home\me") is None


def check_wsl_display_env():
    """With a Windows X server, a Linux module's launch draws there (its
    windows embed); without one it stays on WSLg, untouched."""
    keep = main.wsl_x_display
    try:
        main.wsl_x_display = lambda: "127.0.0.1:0"
        env = main.wsl_display_env()
        assert env["DISPLAY"] == "127.0.0.1:0" and env["WAYLAND_DISPLAY"] == ""
        assert env["GDK_BACKEND"] == "x11" and env["QT_QPA_PLATFORM"] == "xcb"
        main.wsl_x_display = lambda: None
        assert main.wsl_display_env() == {}
    finally:
        main.wsl_x_display = keep


def _win32_window(style):
    """A real top-level HWND (offscreen Qt widgets have none)."""
    import ctypes
    import winplat
    cw = winplat.user32.CreateWindowExW
    cw.restype = winplat.HWND
    cw.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
                   ctypes.c_uint32] + [ctypes.c_int] * 4 + [ctypes.c_void_p] * 4
    return int(cw(0, "STATIC", "ub probe", style, 0, 0, 80, 80,
                  None, None, None, None))


def check_frame_restrip():
    """VcXsrv puts its frame back just after its window maps; the host sees
    it and strips it again, instead of a title bar inside the pane."""
    if not ON_WINDOWS:
        return
    from types import SimpleNamespace
    import winplat as w
    style = w.WS_POPUP | w.WS_CAPTION | w.WS_THICKFRAME
    wid = _win32_window(style)
    stub = SimpleNamespace(child_wid=wid, _style=style, _exstyle=0)
    assert w.Win32EmbedHost._framed(stub)
    w.Win32EmbedHost._strip(stub)
    assert not w.Win32EmbedHost._framed(stub)
    w.user32.DestroyWindow(w.HWND(wid))


def check_embed_refused():
    """A window Windows won't let us adopt (WSLg's msrdc.exe: access denied)
    fails the embed at once with its styles restored, instead of logging
    success and then 6 s of failed healing."""
    if not ON_WINDOWS:
        return
    import ctypes
    import winplat
    from PyQt6.QtWidgets import QWidget
    _app()
    wid = _win32_window(winplat.WS_POPUP)
    before = winplat._GetLong(wid, winplat.GWL_STYLE)
    keep = winplat.SetParent

    def refuse(_child, _parent):
        ctypes.set_last_error(5)
        return None
    winplat.SetParent = refuse
    try:
        main.EmbedHost(wid, QWidget())
        raise AssertionError("embedding a refused window succeeded")
    except PermissionError:
        pass
    finally:
        winplat.SetParent = keep
    assert winplat._GetLong(wid, winplat.GWL_STYLE) == before
    winplat.user32.DestroyWindow(winplat.HWND(wid))


def check_kill_pid_exited():
    """A process that already exited is 'gone', not 'denied' — on Windows it
    stays listed while a handle (Popen's here, QProcess's in the app) is open,
    and TerminateProcess calls that access denied. The web reaper then told
    the user to close a browser that had already closed."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert main.kill_pid(p.pid, main.SIGKILL) == "gone"


def check_wsl_ready():
    """wsl.exe on PATH isn't WSL: Windows 11 ships it as an installer stub.
    Ready must agree with whether `wsl --list` names a distro."""
    if not ON_WINDOWS:
        assert main.wsl_ready() is False
        return
    if not shutil.which("wsl.exe"):
        assert not main.wsl_ready()
        return
    r = subprocess.run(["wsl.exe", "--list", "--quiet"], capture_output=True,
                       timeout=60)
    listed = r.returncode == 0 and bool(r.stdout.replace(b"\0", b"").strip())
    assert main.wsl_ready() == listed, (r.returncode, r.stdout, r.stderr)


def check_wine_wrap():
    with tempfile.TemporaryDirectory() as d:
        pre = Path(d) / "prefix"
        prog, args, env = main.wine_wrap("/apps/tool.exe", ["-v"], pre)
        assert args == ["/apps/tool.exe", "-v"], args
        assert env == {"WINEPREFIX": str(pre), "WINEDEBUG": "-all"}
        _, args, _ = main.wine_wrap("/apps/run.BAT", [], pre)
        assert args == ["cmd", "/c", "/apps/run.BAT"], args
        _, args, _ = main.wine_wrap("/apps/setup.msi", [], pre)
        assert args[:2] == ["msiexec", "/i"], args
        # Not a Windows program: left alone, so builds still run natively.
        prog, args, env = main.wine_wrap("make", ["all"], pre)
        assert (prog, args) == ("make", ["all"]) and "WINEDEBUG" not in env
        # An extensionless PE is recognised by its header.
        pe = Path(d) / "noext"
        pe.write_bytes(b"MZ\x90\x00" + b"\0" * 60)
        prog, args, _ = main.wine_wrap(str(pe), [], pre)
        assert args == [str(pe)], args


def check_detect_platform():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / "app.exe").write_bytes(b"MZ" + b"\0" * 62)
        (proj / "tool").write_bytes(b"\x7fELF" + b"\0" * 60)
        (proj / "tool").chmod(0o755)
        assert main.detect_platform(proj, "binary", "app.exe") == "windows"
        assert main.detect_platform(proj, "binary", "tool") == "linux"
        # A build entry is judged by what's in the folder: mixed = portable...
        assert main.detect_platform(proj, "binary", "(make & run)") == ""
        (proj / "tool").unlink()
        # ...and a prebuilt .exe beside its Makefile = Windows.
        assert main.detect_platform(proj, "binary", "(make & run)") == "windows"
        (proj / "W.csproj").write_text(
            "<Project><PropertyGroup><TargetFramework>net10.0-windows"
            "</TargetFramework><UseWindowsForms>true</UseWindowsForms>"
            "</PropertyGroup></Project>")
        assert main.detect_platform(proj, "csharp", "W.csproj") == "windows"
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / "main.py").write_text("import gi\ngi.require_version('Gtk','3.0')\n")
        assert main.detect_platform(proj, "python", "main.py") == "linux"
        (proj / "main.py").write_text(
            "import sys\nif sys.platform == 'win32':\n    import winreg\n")
        # a guarded Windows import proves nothing — stays portable
        assert main.detect_platform(proj, "python", "main.py") == ""
        (proj / "x.csproj").write_text("<TargetFramework>net10.0</TargetFramework>")
        assert main.detect_platform(proj, "csharp", "x.csproj") == ""


class _FakeProc:
    def __init__(self, native=True):
        self.calls = []
        if not native:
            self.setNativeArguments = None
            del self.setNativeArguments

    def start(self, *a):
        self.calls.append(("start",) + a)

    def setProgram(self, prog):
        self.calls.append(("program", prog))

    def setArguments(self, args):
        self.calls.append(("arguments", args))

    def setNativeArguments(self, line):
        self.calls.append(("native", line))


def check_start_qprocess():
    """One start point; cmd.exe gets its line verbatim on Windows."""
    fp = _FakeProc()
    # Not on any PATH: on real Windows a bare name that is (node, once
    # installed) resolves to its full path, which is resolve_program's job.
    main.start_qprocess(fp, "ub-no-such-tool", ["a b", 3])
    assert fp.calls == [("start", "ub-no-such-tool", ["a b", "3"])], fp.calls
    with _as_windows():
        keep = main.shutil.which
        main.shutil.which = lambda name: {"npm": r"C:\nodejs\npm.CMD"}.get(name)
        try:
            assert main.resolve_program("npm") == r"C:\nodejs\npm.CMD"
            assert main.resolve_program(r"C:\x\app.exe") == r"C:\x\app.exe"
            assert main.resolve_program("nope") == "nope"
            prog, args = main.shell_command('echo "hi there" && dir')
            assert (prog, args[:3]) == ("cmd.exe", ["/d", "/s", "/c"])
            fp = _FakeProc()
            main.start_qprocess(fp, prog, args + ["--port", "8 0"])
            native = [c for c in fp.calls if c[0] == "native"]
            assert native == [("native",
                               '/d /s /c "echo "hi there" && dir --port "8 0""')], \
                fp.calls
            assert fp.calls[-1] == ("start",)
        finally:
            main.shutil.which = keep


@linux_host
def check_module_wrap():
    """ModuleTab._wrap routes launch, setup and shell lines per bridge."""
    _app()
    cfg = main.ModuleConfig(name="w", project_dir="/proj", entry="a.exe",
                            runtime="binary", platform="windows")
    tab = main.ModuleTab(cfg)
    assert tab.bridge == "wine"
    prog, args, env = tab._wrap("/proj/a.exe", ["--x"], "/proj", {"K": "1"},
                                launch=True)
    assert args == ["/proj/a.exe", "--x"] and "WINEPREFIX" in env, (prog, args)
    assert env["K"] == "1"
    env2 = tab._wrap("/proj/a.exe", [], "/proj", {"WINEPREFIX": "/mine"},
                     launch=True)[2]
    assert env2["WINEPREFIX"] == "/mine", "a module's own WINEPREFIX must win"
    prog, args, env = tab._wrap("make", [], "/proj")       # a build step
    assert (prog, args) == ("make", []) and "WINEPREFIX" in env
    tab.shutdown()

    with _as_windows():
        cfg = main.ModuleConfig(name="l", project_dir=r"C:\proj",
                                entry="", runtime="node", platform="linux")
        tab = main.ModuleTab(cfg)
        assert tab.bridge == "wsl"
        prog, args, env = tab._wrap("npm", ["start"], r"C:\proj", {"A": "1"},
                                    launch=True)
        assert prog == "wsl.exe" and env == {}, (prog, env)
        assert args[-4:] == ["env", "A=1", "npm", "start"], args
        assert any("UBPID" in a for a in args)
        prog, args, _ = tab._wrap(*main.shell_command("pip install rich"),
                                  r"C:\proj", {"B": "x y"})
        script = args[args.index("-lc") + 1]
        assert script.startswith("export B='x y'; pip install rich"), script
        again = tab._wrap(prog, args, r"C:\proj")
        assert again[:2] == (prog, args), "already-wrapped must pass through"
        tab.shutdown()


def check_wsl_pid_capture():
    """The Linux pid printed by the WSL wrapper is kept and kept out of the log."""
    _app()

    class Out:
        def __init__(self, text):
            self.text = text

        def readAllStandardOutput(self):
            return self.text.encode()

    with _as_windows():
        cfg = main.ModuleConfig(name="l", project_dir=r"C:\p", entry="",
                                runtime="node", platform="linux")
        tab = main.ModuleTab(cfg)
        tab._handle_stdout(Out("UBPID:4242\nserver up\n"))
        assert tab._wsl_pid == 4242
        log = tab.log.toPlainText()
        assert "UBPID" not in log and "server up" in log, log
        tab._handle_stdout(Out("UBPID:9\n"))       # only the first one counts
        assert tab._wsl_pid == 4242
        tab.shutdown()


def check_python_under_wsl():
    """Python in WSL: venv in the distro's home, $HOME expanded there."""
    _app()
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / "main.py").write_text("import requests\n")
        (proj / "requirements.txt").write_text("rich\n")
        with _as_windows():
            cfg = main.ModuleConfig(name="py", project_dir=str(proj),
                                    entry="main.py", platform="linux")
            tab = main.ModuleTab(cfg)
            seen = {}
            tab._run_command_chain = lambda steps, on_ok: (
                seen.update(steps=steps), on_ok())
            tab._launch_process = lambda prog, args, wd, env=None, **k: \
                seen.update(launch=(prog, args, env))
            tab._start_python_wsl(proj)
            *mount, (label, prog, args, cwd) = seen["steps"]
            # A Windows path (real host) has its drive mounted in WSL first.
            assert len(mount) == (1 if ON_WINDOWS else 0), mount
            script = args[args.index("-lc") + 1]
            assert prog == "wsl.exe" and "python3 -m venv" in script, script
            # a half-made venv (no ensurepip) has bin/python but no bin/pip
            assert "/bin/pip ||" in script and "--clear" in script, script
            assert "requests" in script and "-r " in script, script
            assert "$HOME/.unified_base/envs/" in script
            lprog, largs, lenv = seen["launch"]
            assert lprog == "sh" and largs[-1] == "main.py", largs
            assert "$HOME" in largs[1] and "PYTHONPATH" in lenv
            tab.shutdown()


def check_program_files():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        exe = root / "app.exe"
        exe.write_bytes(b"MZ")                     # no execute bit
        dll = root / "lib.dll"
        dll.write_bytes(b"MZ")
        dll.chmod(0o755)                           # mingw marks DLLs +x
        elf = root / "tool"
        elf.write_bytes(b"\x7fELF")
        elf.chmod(0o755)
        sh = root / "go.sh"
        sh.write_text("#!/bin/sh\n")
        sh.chmod(0o755)
        assert main.is_program_file(exe), ".exe runs here through Wine"
        assert not main.is_program_file(dll)
        assert main.is_program_file(elf)
        assert not main.is_program_file(sh)
        assert main._executable_files(root) == ["app.exe", "tool"]
        with _as_windows():
            assert main.is_program_file(exe)
            assert main.is_program_file(elf), "an ELF runs through WSL"
            assert not main.is_program_file(sh), "no execute bit to go by"
    assert main.venv_python(Path("/e"), windows=True) == \
        Path("/e") / "Scripts" / "python.exe"
    assert main.venv_python(Path("/e"), windows=False) == Path("/e/bin/python")


def check_proc_text():
    """Child output: UTF-8, else the ANSI code page; CRLF folded to LF."""
    assert main.proc_text(b"a\r\nb\r\n") == "a\nb\n"
    assert main.proc_text("café\n".encode()) == "café\n"
    keep = main._OUTPUT_FALLBACK
    main._OUTPUT_FALLBACK = "cp1252"            # what Windows falls back to
    try:
        assert main.proc_text(b"caf\xe9 na\xefve\r\n") == "café naïve\n"
    finally:
        main._OUTPUT_FALLBACK = keep
    if not ON_WINDOWS:              # Windows reads it in its ANSI code page
        assert main.proc_text(b"caf\xe9") == "caf\ufffd"


def check_cmd_metachar_args():
    """A startup arg holding & or ^ stays one argument on a cmd.exe line."""
    with _as_windows():
        prog, args = main.shell_command("tool")
        fp = _FakeProc()
        main.start_qprocess(fp, prog, args + ["--q=a&b", "x^y", "plain",
                                              "two words"])
        native = [c[1] for c in fp.calls if c[0] == "native"]
        assert native == ['/d /s /c "tool "--q=a&b" "x^y" plain "two words""'], \
            native


@linux_host
def check_wsl_setup_env():
    """A WSL setup step with env vars: a missing tool still skips its step,
    and the vars still arrive. Runs the Linux half of the command here."""
    for prog, extra, want in (("ub-no-such-tool", [], "skipping it"),
                              ("sh", ["-c", 'echo "FOO=$FOO"'], "FOO=x y")):
        _, args = main.wsl_wrap(prog, extra, "/tmp",
                                {"FOO": "x y", "BAD-NAME": "1"}, setup=True)
        linux = args[args.index("--exec") + 1:]
        assert "BAD-NAME" not in " ".join(linux), linux
        r = subprocess.run(linux, capture_output=True, text=True, cwd="/tmp",
                           timeout=30)
        assert r.returncode == 0 and want in r.stdout, \
            (prog, r.returncode, r.stdout, r.stderr)


def _alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


@linux_host
def check_wsl_kill_tree():
    """The WSL stop line reaches grandchildren (npm -> sh -> electron)."""
    top = subprocess.Popen(["sh", "-c", 'sh -c "sleep 3001 & wait" & wait'])
    kids = set()
    try:
        end = time.monotonic() + 5
        while time.monotonic() < end and len(kids) < 2:
            kids = main.descendant_pids(top.pid) - {top.pid}
            time.sleep(0.05)
        assert len(kids) >= 2, kids
        subprocess.run(["sh", "-c", main.wsl_kill_script(top.pid, main.SIGTERM)],
                       timeout=10)
        top.wait(5)
        end = time.monotonic() + 3
        while time.monotonic() < end and any(_alive(k) for k in kids):
            time.sleep(0.05)
        assert not [k for k in kids if _alive(k)], kids
    finally:
        for pid in (top.pid, *kids):
            main.kill_pid(pid, main.SIGKILL)
        top.wait(5)


def check_force_kill_restart():
    """Stop's delayed force-kill hits the process it was stopping, never the
    one a Restart started in the meantime."""
    _app()
    tab = main.ModuleTab(main.ModuleConfig(name="r", project_dir="/tmp",
                                           entry="", runtime="custom"))
    hit = []
    tab._signal_tree = lambda proc, sig: hit.append((proc, sig))
    class Proc:                           # stand-in: _signal_tree is stubbed
        def state(self):
            return main.QProcess.ProcessState.Running

        def processId(self):
            return 0
    old, new = Proc(), Proc()
    tab.app_proc = old
    tab.stop()
    tab.app_proc = new                    # Restart's fresh process
    tab._force_kill()
    assert hit == [(old, main.SIGTERM), (old, main.SIGKILL)], hit
    tab._force_kill()                     # a second timer has nothing left
    assert hit[-1] == (None, main.SIGKILL), hit
    tab.app_proc = None
    tab.shutdown()


@linux_host
def check_wine_family():
    """Processes Wine detached are found by their launch tag; a Linux program
    and Wine's shared services that carry the tag are not."""
    tag = f"ub-test-{os.getpid()}"
    env = dict(os.environ, UB_LAUNCH=tag)
    procs = [subprocess.Popen(["bash", "-c", f"exec -a '{a}' sleep 30"], env=env)
             for a in ("C:\\x\\app.exe", "services.exe", "sleep")]
    try:
        found, end = set(), time.monotonic() + 5
        while time.monotonic() < end and procs[0].pid not in found:
            found = main.wine_family(f"UB_LAUNCH={tag}")
            time.sleep(0.05)
        assert found == {procs[0].pid}, (found, [p.pid for p in procs])
    finally:
        for p in procs:
            p.kill()
            p.wait()


@linux_host
def check_private_wineprefix_boot():
    """A module's own WINEPREFIX gets the first-run wineboot, not the shared one."""
    _app()
    with tempfile.TemporaryDirectory() as d:
        mine = Path(d) / "mine"
        cfg = main.ModuleConfig(name="w", project_dir=d, entry="a.exe",
                                runtime="binary", platform="windows",
                                extra_env={"WINEPREFIX": str(mine)})
        tab = main.ModuleTab(cfg)
        steps = tab._bridge_steps()
        assert steps and steps[0][4]["WINEPREFIX"] == str(mine), steps
        (mine / "system.reg").write_text("")
        assert tab._bridge_steps() == []
        tab.shutdown()


def check_os_badge():
    """OS-bound tabs carry a Windows/Linux mark beside the name; it follows
    Runs on, and modules that run anywhere get none."""
    from PyQt6.QtWidgets import QStyle, QTabBar
    app = _app()
    assert main.os_badge("") is None
    for need in ("windows", "linux"):
        pm = main.os_badge(need, 2.0)
        assert pm is not None and not pm.isNull()
        assert pm.deviceIndependentSize().toSize().width() == 12
    with tempfile.TemporaryDirectory() as d:
        win = _row_window(app, d, 2)
        tb = win.tabbar
        close = tb.style().styleHint(
            QStyle.StyleHint.SH_TabBar_CloseButtonPosition, None, tb)
        side = QTabBar.ButtonPosition.RightSide if close == 0 \
            else QTabBar.ButtonPosition.LeftSide
        t0 = win.module_tabs[0]
        assert tb.tabButton(0, side) is None, "runs anywhere: no mark"
        t0.cfg.platform = "windows"
        win._update_tab_display(t0)
        b = tb.tabButton(0, side)
        assert b is not None and "Windows" in b.toolTip(), b
        t0.cfg.platform = "linux"
        win._update_tab_display(t0)
        assert "Linux" in tb.tabButton(0, side).toolTip()
        t0.cfg.platform = ""
        win._update_tab_display(t0)
        assert tb.tabButton(0, side) is None
        assert tb.tabButton(1, side) is None
        for t in win.module_tabs:
            t.shutdown()
        win.close()


if __name__ == "__main__":
    for fn in (check_dep_name, check_declared_deps, check_atomic_write,
               check_config_compat, check_portable_paths,
               check_moved_demo_paths,
               check_frame_window_ranking, check_compose_args,
               check_chrome_sandbox_hint, check_kill_process_tree,
               check_pids_with_arg, check_missing_setup_msg,
               check_border_colors,
               check_visible_pane_count,
               check_runtime_launch_specs, check_free_port,
               check_binary_build_entries,
               check_push_recent, check_tab_highlight,
               check_custom_runtime, check_custom_start_routing,
               check_shell_command,
               check_row_drag_slack, check_tab_reveals_pane,
               check_compact_header, check_compact_button_intent,
               check_module_log_file, check_env_var_editor,
               check_shortcuts, check_geometry_roundtrip,
               check_proc_table, check_children_walk, check_sampler,
               check_meter_widget, check_log_modes, check_meter_toggles,
               check_bridge_selection, check_wsl_paths, check_wsl_wrap,
               check_wsl_ready, check_wsl_mount_args, check_wsl_display_env,
               check_frame_restrip, check_embed_refused,
               check_kill_pid_exited,
               check_wine_wrap, check_detect_platform, check_start_qprocess,
               check_module_wrap, check_wsl_pid_capture,
               check_python_under_wsl, check_program_files,
               check_toolchain_preflight, check_proc_text,
               check_cmd_metachar_args, check_wsl_setup_env,
               check_wsl_kill_tree, check_force_kill_restart,
               check_wine_family, check_private_wineprefix_boot,
               check_os_badge):
        if ON_WINDOWS and fn in LINUX_HOST:
            print(f"skip {fn.__name__} (Linux host only)")
            continue
        fn()
        print(f"ok  {fn.__name__}")
    print("ALL CHECKS PASS")
