# Node.js / Electron — Unified Base demo #2: IPC & desktop integration

A control panel wired to the main process: live runtime info, a polled memory
sample, a native file dialog with a bounded preview, desktop notifications, an
application menu with accelerators, and window controls.

## Demonstrates
Demo #1 is a pretty window. This one is the part a web page *cannot* do:

- **contextBridge** — the renderer's entire capability surface is the handful of
  functions in `preload.js`. No `require`, no `process`, no filesystem.
- **ipcMain.handle / ipcRenderer.invoke** — request/response IPC with real
  return values, one handler per capability.
- **Native OS integration** — application menu with `CmdOrCtrl` accelerators,
  `dialog.showOpenDialog`, `Notification`, fullscreen/minimize, and
  `shell.openExternal` so links open in the real browser instead of hijacking
  the app window.
- **Privileged work stays privileged** — the main process reads the file and
  returns a bounded 4 KB slice; the renderer only formats and displays it, via
  `textContent` (no HTML injection) under a restrictive CSP.
- **Pull, not push** — samples are fetched when the renderer asks, so nothing
  runs while the UI is idle.

`nodeIntegration` is off and `contextIsolation` is on throughout.

## Dependencies
- Node.js + npm. `npm install` pulls Electron (~100 MB) on first run.

## Run
Unified Base runs this automatically (`npx electron main.js`).

Manual equivalent:

```
npm install && npm start
```

### Passing flags to Electron
This module's default entry is `(default)`, which runs `npm start`. Unified Base
inserts `--` before a module's startup args for npm (`npm start -- --no-sandbox`)
because npm silently swallows unknown flags otherwise. Choosing `main.js` as the
entry instead runs `npx electron main.js` and passes flags straight through.

### If it exits immediately with a `chrome-sandbox` or zygote error
Chromium's SUID sandbox can't cope when the project path contains a space, and
npm installs `chrome-sandbox` unprivileged. Add `--no-sandbox` to the tab's
startup args, or move the checkout to a path without spaces. Unified Base
prints the same advice in the tab log when it sees that crash.

## Files
- `main.js` — window, IPC handlers, native menu
- `preload.js` — the whole renderer capability surface
- `index.html` — UI and renderer logic (inline, CSP-restricted)
- `package.json` — `main` + `start`, Electron dev dependency
