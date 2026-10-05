Free, MIT-licensed. Each download carries its own Python and Qt — nothing else to install first.

**Windows 10 1809+ / 11** — run `UnifiedBase-windows-x64-setup.exe`. Installs for your user only, no admin.
The installer is not code-signed yet, so Windows SmartScreen may say *Windows protected your PC*:
click **More info**, then **Run anyway**.

**Linux** (Mint 21+, Ubuntu 22.04+, Debian 12+, or another distro with glibc 2.34+) — extract
`UnifiedBase-linux-x86_64.tar.gz` and double-click **Install Unified Base** (or run `./install.sh`).
Installs to `~/.local`, no root. Your file manager may ask you to trust the launcher first.

The languages modules are written in (Node.js, .NET, Java, Rust, and on Windows Ruby and PHP too) download
themselves for your user, checksum-verified, the first time a module needs one.

Start with **File ▸ Load Demo Modules**. Setup guide: https://bomsaisoftware.com/software/unified-base-guide
Questions and feedback: [Discussions](https://github.com/frostbit82-Kai/unified-base/discussions). Bugs: [Issues](https://github.com/frostbit82-Kai/unified-base/issues) — paste the output of the self-test (`unified-base --selftest`, or *Unified Base Self-Test* in the Start menu).

SHA-256:
