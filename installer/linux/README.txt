Unified Base  (beta)
====================

Runs programs written in any language side by side in one window, each
embedded as a tab or a pane: Python, Node and Electron, Rust, C and C++, Java,
C#, Ruby, PHP, web apps, Docker — and Windows programs too, through Wine.

Free while in beta. Guide: https://bomsaisoftware.com/software/unified-base-guide


INSTALL
-------

Double-click "Install Unified Base". A terminal opens, it installs, and it
waits for you to press Enter before closing.

The first time, your desktop may ask whether to trust the launcher -- that is
the desktop protecting you from files that arrive pretending to be something
else, and it happens to every archive that ships one:

    Linux Mint (Nemo)  choose Launch Anyway, or Mark as Trusted
    GNOME Files        right-click the launcher -> Allow Launching, then double-click
    Thunar / KDE       double-click, then choose Trust and Launch / Execute

If you would rather not, or there is no desktop, the launcher only runs the
script sitting next to it:

    ./install.sh

Installs to ~/.local, no root needed. It adds an applications-menu entry
(under Development) and a `unified-base` command, then checks that it starts.
It brings its own Python and Qt, so nothing on your system changes.

To install somewhere else:   PREFIX=/opt ./install.sh    (may need sudo)
To upgrade:                  install the new version the same way
To remove:                   double-click "Uninstall Unified Base",
                             or run ./uninstall.sh

Keep this folder. The uninstaller lives in it, not in the installed copy.


FIRST STEPS
-----------

File > Load Demo Modules loads small programs in every supported language, so
you can see it work before adding your own. Start one with the ▶ button at the
top of its pane.

File > Add Module... adds your own: pick a project folder and Unified Base
works out the language, installs its dependencies the way a developer would,
and runs it.

A module whose language is not installed yet gets an Install button in its pane.
That runs your package manager, so the system asks for your password there.


WHAT IT NEEDS
-------------

An X11 session for embedding. Linux Mint's Cinnamon is X11 already. On a
Wayland desktop it runs through XWayland and most programs still embed; if one
will not, log in with a session ending in "on Xorg".

Wine, for Windows programs:   sudo apt install wine wine64
xterm, for the full terminal under each module (it offers to install it).


WHERE THINGS ARE
----------------

    ~/.local/share/UnifiedBase   the program. Replaced on upgrade.
    ~/.unified_base              your modules, layouts, settings, blank-tab
                                 projects, every module's environment and the
                                 Wine prefix. Kept on upgrade and uninstall.

The demo programs build inside the program folder, so after an upgrade each
demo rebuilds the first time you start it.


IF IT WILL NOT START
--------------------

Run `unified-base` in a terminal: it says what it is doing, and an error lands
there. Settings and logs are in ~/.unified_base (unified_base.log for the app,
logs/ for each module).
