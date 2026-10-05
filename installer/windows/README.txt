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
350 MB of disk, plus the languages your modules download (see below; all
of them together take about 1.5 GB).


FIRST STEPS
-----------

Start menu > Unified Base.

File > Load Demo Modules loads small programs in every supported language, so
you can see it work before adding your own. Start one with the > button at the
top of its pane. Modules > Close All Modules clears every tab at once.

File > Add Module... adds your own: pick a project folder and Unified Base
works out the language, installs its dependencies the way a developer would,
and runs it.

Nothing else needs installing first. When a module needs a language this PC
does not have (or has in a version too old for it), its first start
downloads that language for your user - no administrator rights - and every
module uses it from then on. The module's log shows the progress; the first
start of each language takes a few minutes. Downloads are checked against
the publisher's checksum before anything runs.

    Python ............. nothing - Unified Base brings its own
    Node / Electron .... Node.js 24        (36 MB)
    Web ................ Node.js for the dev server; the page itself
                         shows in Edge, which Windows has
    C# / WinForms ...... .NET SDK 10       (287 MB)
    Java ............... Temurin JDK 25 and Maven (135 + 9 MB)
    Rust ............... Rust, GNU toolchain (rustup: ~120 MB)
    Ruby ............... Ruby 3.4          (RubyInstaller, 20 MB)
    PHP ................ PHP 8.4           (34 MB)
    C .................. nothing for the demos (they come built); to
                         rebuild, the module's log names the compiler
    Docker ............. Docker Desktop    (see DOCKER below)

They go in %USERPROFILE%\.unified_base\toolchains (Rust in %USERPROFILE%\.cargo,
where rustup puts it). Go, CMake and make still come from winget, Windows'
own package manager, through an Install button in the module's pane.


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
  3. Inside Ubuntu: Python for Linux modules, a C compiler (Rust links
     with it) and the libraries Linux GUI programs load - about 250 MB.
     Node, .NET, Java and Rust for Linux modules download into Ubuntu by
     themselves, the first time a Linux module needs one, as on Windows.
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
                                           blank-tab projects, the languages
                                           it downloaded and every module's
                                           environment. Kept on upgrade;
                                           uninstalling asks.

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
