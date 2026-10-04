# Node.js / Electron — Unified Base Windows demo #2: Electron × Windows

Six cards of what Electron's main process can ask Windows for — several of
them Windows-only APIs.

| Card | API | What you see |
|---|---|---|
| Every window and screen | `desktopCapturer` | live thumbnails of each window and screen, with app icons |
| Secrets | `safeStorage` | encrypt / decrypt / flip one bit and watch decryption refuse |
| Colours & theme | `systemPreferences.getAccentColor`, `getColor` (Windows-only), `nativeTheme` | the accent colour and Win32 system colours, live; the buttons take the accent |
| Power | `powerMonitor`, `powerSaveBlocker` | AC/battery, idle time, a log of lock/unlock and sleep/wake; keep the display awake |
| Displays | `screen` | DIP size, pixels, scale, refresh rate, colour depth; live on changes |
| Explorer's view of a file | `app.getFileIcon`, `nativeImage.createThumbnailFromPath`, `shell.readShortcutLink` (Windows-only) | a file's shell icon and thumbnail; for a `.lnk`, its real target, arguments and start-in folder |

## Demonstrates
- **Main-process power, renderer-safe.** The page has no Node: every card
  is an `ipcMain.handle` named in `preload.js`, and events Windows raises
  (accent change, contrast theme, lock screen, display added) are pushed
  to the page on their own channels.
- **What safeStorage really is on Windows:** AES-256-GCM under a key that
  DPAPI locks to your Windows logon. The ciphertext decrypts only for you
  on this PC, and GCM's tag rejects it if one bit changes.
- **Honest numbers.** Electron rounds display sizes *up* to whole DIPs
  (768 px ÷ 1.25 = 614.4 → 615), so pixels are recovered by rounding down;
  rounding to nearest — and `screen.dipToScreenRect` — report 769 rows on a
  768-row panel.
- **Embedding, seen from inside:** the window gallery is captured when the
  page loads. Press Refresh once Unified Base has adopted the window and it
  drops out of the list — it is a child window now, not a top-level one.

## Dependencies
- Node.js + npm. Electron 44 downloads its binary (~110 MB) on the first
  start; see `node-desktop-win`'s README for why that is not an npm install
  script any more.

## Run
Unified Base runs this automatically (`npm start`).

Manual equivalent:

```
npm install && npm start
```

## Files
- `main.js` — the IPC handlers and the Windows events they forward
- `preload.js` — the renderer's whole capability surface
- `index.html` — the six cards (inline, CSP-restricted; images are data: URLs)
