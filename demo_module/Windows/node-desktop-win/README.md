# Node.js / Electron — Unified Base Windows demo: IPC & desktop integration

The Windows twin of `demo_module/Linux/node-desktop`: the same control panel
wired to the main process — runtime info, a polled live sample, a native
file dialog with a bounded preview, notifications, an application menu with
accelerators, window controls. `nodeIntegration` off, `contextIsolation` on.

## What differs on Windows
- **CPU % instead of load average.** Load average does not exist on Windows:
  Node's `os.loadavg()` returns `[0, 0, 0]` there. The live sample computes
  CPU % from `os.cpus()` time deltas instead (`main.js`, `cpuTimes`).
- **Electron 44, not 31.** Two things changed under Electron 31 on a current
  Windows toolchain:
  - npm 11.19+ blocks dependency install scripts by default, and Electron
    31 downloads its binary in one (`postinstall`).
  - Even when approved, that script's unzip step stops silently under
    Node 26.

  Electron 44 has no install script at all: it fetches its binary on the
  first `electron .` (the tab log says "Downloading Electron binary…"), so
  the first start takes a minute and later ones are instant.
- Everything the native menu, dialog and notification do is Windows' own:
  the menu bar is a real Win32 menu, the dialog is the common file dialog,
  the notification is a Windows toast.

## Dependencies
- Node.js + npm (`winget install -e --id OpenJS.NodeJS`; the tab's Install
  button offers it). `npm install` pulls Electron's loader; the binary
  (~110 MB) downloads on first start.

## Run
Unified Base runs this automatically (`npm start`).

Manual equivalent:

```
npm install && npm start
```

## Files
- `main.js` — window, IPC handlers, native menu
- `preload.js` — the whole renderer capability surface
- `index.html` — UI and renderer logic (inline, CSP-restricted)
- `package.json` — `main` + `start`, Electron dev dependency
