# Node.js / Electron — Unified Base demo

A single dark, animated Electron desktop window: a gradient-title heading, an
animated aurora backdrop, a `requestAnimationFrame` canvas with bouncing
connected shapes, and a live clock.

## Demonstrates
An embedded Electron `BrowserWindow` (900x600) — a real, visible desktop window
that Unified Base reparents into a tab.

## Dependencies
- [Node.js](https://nodejs.org/) **22.12 or newer** (includes `npm`).
  Ubuntu 26.04's `nodejs` qualifies; Ubuntu 24.04 (18) and Debian 13 (20)
  are too old — use NodeSource or nvm there.
- Electron `^44.0.0` — a devDependency. `npm install` fetches the package;
  the Electron binary itself (~100 MB) downloads on the first start.

```bash
npm install
```

## Running
Unified Base runs this automatically: it detects `package.json` and executes
`npm start` (which runs `electron .`). No manual steps required.

## If it aborts with "The SUID sandbox helper binary was found, but is not configured correctly"

Not a bug in this demo. Electron's first start downloads
`node_modules/electron/dist/chrome-sandbox` owned by you with mode 0755. On distros that block unprivileged user namespaces
(Ubuntu ships `kernel.apparmor_restrict_unprivileged_userns=1`) Chromium can't
build a namespace sandbox, falls back to that SUID helper, and refuses to start
because it isn't root-owned. Fix once — keeps the sandbox on:

    sudo chown root:root node_modules/electron/dist/chrome-sandbox
    sudo chmod 4755 node_modules/electron/dist/chrome-sandbox

Any reinstall of electron resets it, so redo it then. The
alternative is running with `--no-sandbox`, which is only sensible because this
demo loads a local file with `nodeIntegration: false`.
