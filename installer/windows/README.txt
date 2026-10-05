Unified Base  (beta) - Windows
==============================

Runs programs written in any language side by side in one window, each
embedded as a tab or a pane: Python, Node and Electron, Rust, C and C++, Java,
C#, Ruby, PHP, web apps, Docker - and Linux programs too, through WSL.

Free while in beta. Guide: https://bomsaisoftware.com/software/unified-base-guide


INSTALL
-------

Double-click UnifiedBase-<version>-windows-x64-setup.exe.

Windows may say "Windows protected your PC": the beta installer is not
code-signed yet. Click "More info", then "Run anyway".

It installs for your user only, so it needs no administrator rights, and it
brings its own Python and Qt: nothing else on your PC changes. Setup checks
that Unified Base starts before it finishes.

Needs Windows 10 version 1809 or later, or Windows 11, 64-bit, and about
350 MB of disk.


FIRST STEPS
-----------

Start menu > Unified Base.

File > Load Demo Modules loads small programs in every supported language, so
you can see it work before adding your own. Start one with the > button at the
top of its pane. These need nothing else installed: python-fractal-win,
c-paint, win32-native.

File > Add Module... adds your own: pick a project folder and Unified Base
works out the language, installs its dependencies the way a developer would,
and runs it.

A module whose language is not installed yet gets an Install button in its
pane. It uses winget, Windows' own package manager; the installer of that
language may ask for administrator approval. What the demos need:

    Python ............. nothing - Unified Base brings its own
    Web ................ Node.js for the dev server (Install button);
                         the page itself shows in Edge, which Windows has
    Node / Electron .... Node.js            (Install button)
    C# / WinForms ...... .NET SDK           (Install button)
    Java ............... a JDK (Temurin)    (Install button)
    Rust ............... Rust               (Install button)
    Ruby ............... Ruby               (Install button)
    PHP ................ PHP                (Install button)
    C .................. nothing for the demos (they come built); to
                         rebuild, the module's log names the compiler
    Docker ............. Docker Desktop     (see DOCKER below)


LINUX PROGRAMS (optional)
-------------------------

Unified Base runs Linux programs through WSL (Windows Subsystem for Linux)
and embeds their windows like any other. To set it up, run

    Start menu > Unified Base > Set Up Linux Programs (WSL)

or click "Set up WSL" in a Linux module's pane. It checks each piece, asks
before changing anything, and is safe to run again:

  1. Virtualization must be on in your PC's firmware (BIOS/UEFI). It checks,
     and tells you where the switch is if it is off.
  2. WSL and Ubuntu (Windows asks for administrator approval, and may ask
     to restart - run the setup again afterwards). Ubuntu asks you to pick a
     Linux user name and password.
  3. Python for Linux modules inside Ubuntu.
  4. VcXsrv, a free X server, which lets Linux windows embed. Unified Base
     starts it when a Linux module first needs it (two terminal windows
     flash for a moment as it reads your keyboard layout). If Windows
     Firewall asks about "VcXsrv windows xserver", choose Allow.
  5. WSL's mirrored networking, so Linux programs reach VcXsrv on this PC.

Embedding Linux windows needs Windows 11 22H2 or later. On older Windows,
Linux programs still run, in windows of their own.


DOCKER (optional)
-----------------

The docker demos need Docker Desktop: https://www.docker.com/products/docker-desktop/
(its own installer, and its own licence to accept). docker-windows builds
Windows containers: switch Docker Desktop to Windows containers for it (it
turns on the Windows features that need, Hyper-V and Containers).


WHERE THINGS ARE
----------------

    %LOCALAPPDATA%\Programs\Unified Base   the program. Replaced on upgrade.
    %USERPROFILE%\.unified_base            your modules, layouts, settings,
                                           blank-tab projects and every
                                           module's environment. Kept on
                                           upgrade; uninstalling asks.

The demo programs build inside the program folder, so after an upgrade each
demo rebuilds the first time you start it.

To upgrade:  run the new setup the same way (quit Unified Base first).
To remove:   Settings > Apps > Installed apps > Unified Base > Uninstall.
             It then asks whether to delete your data too (No by default,
             so a reinstall picks up where you left off). Yes also removes
             Linux modules' environments inside WSL. Unattended:
             unins000.exe /VERYSILENT /DELETEDATA=yes
Third-party licences: the program folder, app\licenses


IF IT WILL NOT START
--------------------

Run "Unified Base Self-Test" from the Start menu: it opens a small window,
embeds it, stops it, and says what this PC has for each kind of module.
The app's own log is %USERPROFILE%\.unified_base\unified_base.log, and each
module's output is in %USERPROFILE%\.unified_base\logs.
