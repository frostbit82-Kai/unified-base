# Unified Base - set up Linux programs on Windows (WSL).
#
# Linux modules run inside WSL, and their windows embed in Unified Base
# through VcXsrv, an X server Unified Base starts when a Linux module needs
# one. This checks each piece and sets up what is missing, asking first.
# Safe to run again: whatever is already done just says "ok".
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File setup-wsl.ps1 [-NoPause]
#
# The installer puts it on the Start menu as "Set Up Linux Programs (WSL)",
# and a Linux module's "Set up WSL" button opens it. Keep this file ASCII:
# Windows PowerShell 5.1 reads a script without a BOM as the ANSI code page.
param([switch]$NoPause)    # no "Press Enter" at the end (for scripts)

$ErrorActionPreference = 'Stop'
try { $Host.UI.RawUI.WindowTitle = 'Unified Base - set up Linux programs (WSL)' } catch {}

function Ok($m)   { Write-Host "  [ok]  $m" -ForegroundColor Green }
function Todo($m) { Write-Host "  [..]  $m" -ForegroundColor Yellow }
function Bad($m)  { Write-Host "  [!!]  $m" -ForegroundColor Red }
function Note($m) { Write-Host "        $m" }
function Ask($q)  { (Read-Host "        $q [Y/n]") -notmatch '^\s*n' }
function Finish($code) {
    Write-Host ''
    if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
    exit $code
}

$Lxss = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
# Registered distros, without Docker Desktop's own: no place for modules.
function Distros {
    if (-not (Test-Path $Lxss)) { return @() }
    @(Get-ChildItem $Lxss | ForEach-Object { (Get-ItemProperty $_.PSPath).DistributionName } |
      Where-Object { $_ -and $_ -notlike 'docker-desktop*' })
}
# Modules run in the default distro (wsl.exe with no -d).
function DefaultDistro {
    try {
        $id = (Get-ItemProperty $Lxss -ErrorAction Stop).DefaultDistribution
        (Get-ItemProperty (Join-Path $Lxss $id) -ErrorAction Stop).DistributionName
    } catch { $null }
}

try {
    Write-Host ''
    Write-Host 'Unified Base - Linux programs (WSL)' -ForegroundColor Cyan
    Write-Host ''

    # -- Windows ----------------------------------------------------------
    $build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
    if ($build -lt 19041) {
        Bad "Windows build $build is too old for WSL 2 (needs Windows 10 version 2004 or later)."
        Note 'Update Windows (Settings > Windows Update), then run this again.'
        Finish 1
    }
    # Embedding needs WSL's mirrored networking: Windows 11 22H2 and later.
    $embed = $build -ge 22621
    if ($embed) { Ok "Windows build $build" }
    else {
        Todo "Windows build ${build}: Linux programs will run, but in windows of their own."
        Note 'Embedding them in Unified Base needs Windows 11 22H2 or later.'
    }

    # -- Virtualization ---------------------------------------------------
    # With Hyper-V running, the CPU reports its virtualization as taken (off),
    # so a running hypervisor counts as yes.
    $cs = Get-CimInstance Win32_ComputerSystem
    $cpu = @(Get-CimInstance Win32_Processor)[0]
    if ($cs.HypervisorPresent -or $cpu.VirtualizationFirmwareEnabled) { Ok 'Virtualization is on' }
    else {
        Bad "Virtualization is off in this PC's firmware (BIOS/UEFI), and WSL 2 needs it."
        Note 'Turn on "Intel Virtualization Technology" (VT-x) or "SVM Mode" (AMD-V) there:'
        Note 'Settings > System > Recovery > Advanced startup > Restart now, then'
        Note 'Troubleshoot > Advanced options > UEFI Firmware Settings. Then run this again.'
        Finish 1
    }

    # -- WSL and a Linux distribution -------------------------------------
    $distros = Distros
    if (-not $distros) {
        Todo 'No Linux distribution yet.'
        Note 'This installs WSL and Ubuntu; Windows asks for administrator approval.'
        Note 'Ubuntu then asks for a new Linux user name and password (any you like - the'
        Note 'password is for sudo inside Linux). When it shows a Linux prompt ending in $,'
        Note 'type  exit  to come back here.'
        if (-not (Ask 'Install WSL and Ubuntu now?')) { Finish 1 }
        & wsl.exe --install -d Ubuntu
        $distros = Distros
        if (-not $distros) {
            Write-Host ''
            Todo 'Not finished yet. If Windows asked to restart, restart; Ubuntu opens by itself'
            Note 'to ask for a user name. Then run this setup again to finish.'
            Finish 1
        }
    }
    $default = DefaultDistro
    if (-not $default -or $default -like 'docker-desktop*') {
        $pick = if ($distros -contains 'Ubuntu') { 'Ubuntu' } else { $distros[0] }
        Note "Making $pick the default distribution (Linux modules run in the default one)."
        & wsl.exe --set-default $pick
        $default = DefaultDistro
    }
    Ok "WSL, running $default"

    # -- Python, a C compiler and GUI libraries inside the distro ---------
    # venv and Tk for the Python demos; gcc because Rust links with the
    # system's cc on Linux; GTK, NSS, gbm and ALSA for Electron, which also
    # cover what Java's Swing and Avalonia load. The languages themselves
    # (Node, .NET, Java, Rust) download on a module's first start.
    # Ubuntu 24.04 renamed ALSA's library (t64), and libasound2 then names
    # two packages. No double quotes below: PowerShell 5.1 mangles them in
    # arguments to wsl.exe.
    $pkgs = 'python3-venv python3-tk gcc libgtk-3-0 libnss3 libgbm1 libxtst6 libxi6'
    $alsa = 'a=libasound2; apt-cache show libasound2t64 >/dev/null 2>&1 && a=libasound2t64; '
    & wsl.exe -d $default -u root --cd / -- sh -c ($alsa + 'command -v apt-get >/dev/null && { apt-get install -s -q ' + $pkgs + ' $a >/tmp/ub-apt 2>&1 || exit 0; grep -q ^Inst /tmp/ub-apt; }')
    if ($LASTEXITCODE -eq 0) {
        Todo "Linux modules need Python's venv and Tk, a C compiler (gcc) and the libraries"
        Note "GUI programs load (GTK and others) inside $default - about 250 MB."
        if (Ask "Install them now (apt-get, as root inside $default)?") {
            & wsl.exe -d $default -u root --cd / -- sh -c ('apt-get update -q || exit 1; ' + $alsa + 'apt-get install -y -q ' + $pkgs + ' $a')
            if ($LASTEXITCODE -eq 0) { Ok 'Python, gcc and GUI libraries for Linux modules' }
            else { Bad "apt-get failed (exit $LASTEXITCODE) - the output above says why." }
        }
    } else { Ok 'Python, gcc and GUI libraries for Linux modules' }

    if ($embed) {
        # -- VcXsrv: the X server Linux windows embed through --------------
        $vcxsrv = Join-Path $env:ProgramFiles 'VcXsrv\vcxsrv.exe'
        if (Test-Path $vcxsrv) { Ok 'VcXsrv (draws Linux windows so they can embed)' }
        else {
            Todo 'VcXsrv is not installed. Unified Base draws Linux windows through it.'
            if (Ask 'Install VcXsrv now? Windows asks for administrator approval.') {
                if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
                    & winget.exe install -e --id marha.VcXsrv
                } else {
                    Note 'winget is missing (it is "App Installer" in the Microsoft Store).'
                    Note 'Opening the VcXsrv download page: install it, then run this again.'
                    Start-Process 'https://sourceforge.net/projects/vcxsrv/'
                }
            }
            if (Test-Path $vcxsrv) { Ok 'VcXsrv installed' }
            else { Bad 'No VcXsrv: Linux programs will run in windows of their own.' }
        }

        # -- Mirrored networking: WSL reaches VcXsrv on this PC's localhost --
        $cfg = Join-Path $env:USERPROFILE '.wslconfig'
        $lines = @(if (Test-Path $cfg) { Get-Content $cfg })
        $restart = $false
        if ($lines -match '^\s*networkingMode\s*=\s*mirrored\s*$') { Ok 'WSL mirrored networking' }
        elseif ($lines -match '^\s*networkingMode\s*=') {
            Bad "$cfg sets another networkingMode. Embedding needs networkingMode=mirrored;"
            Note 'change it yourself if nothing else on this PC depends on the current one.'
        } else {
            Todo 'WSL mirrored networking is off. Linux programs reach VcXsrv through it.'
            if (Ask "Turn it on (adds networkingMode=mirrored to $cfg)?") {
                $at = [array]::FindIndex([string[]]$lines, [Predicate[string]]{ $args[0] -match '^\s*\[wsl2\]\s*$' })
                if ($at -ge 0) {
                    $lines = @($lines[0..$at]) + 'networkingMode=mirrored' + @($lines | Select-Object -Skip ($at + 1))
                } else {
                    if ($lines) { $lines += '' }
                    $lines += '[wsl2]', 'networkingMode=mirrored'
                }
                if (Test-Path $cfg) { Copy-Item $cfg "$cfg.bak" -Force; Note "Old file kept as $cfg.bak" }
                [IO.File]::WriteAllLines($cfg, [string[]]$lines)
                Ok 'WSL mirrored networking'
                $restart = $true
            }
        }
        if ($restart) {
            Note 'WSL restarts to apply it; Linux programs running now will close.'
            if (Ask 'Restart WSL now?') { & wsl.exe --shutdown; Ok 'WSL restarted' }
            else { Note 'It applies the next time WSL starts (or after restarting Windows).' }
        }
    }

    Write-Host ''
    Write-Host 'Done.' -ForegroundColor Cyan
    Note 'In Unified Base: File > Load Demo Modules, then start a module in the Linux group.'
    Note "Node, .NET, Java and Rust download into $default the first time a Linux module"
    Note 'needs one. For Ruby or PHP, the module''s log gives the one apt-get line to run.'
    if ($embed) {
        Note 'The first Linux window starts VcXsrv. If Windows Firewall asks about'
        Note '"VcXsrv windows xserver", choose Allow: WSL reaches it on this PC.'
    }
    Finish 0
} catch {
    Bad "$_"
    Finish 1
}
