// Electron — Unified Base Windows demo #2: the Electron APIs that reach into
// Windows.
//
// The Linux Electron demos are about the renderer and IPC. This one is about
// what Electron's main process can ask *Windows* for, much of it with no
// equivalent elsewhere:
//
//   desktopCapturer        live thumbnails of every window and screen
//   safeStorage            encryption keyed to your Windows logon (DPAPI)
//   systemPreferences      the accent colour and the Win32 system colours, live
//   nativeTheme            dark mode and contrast themes, live
//   powerMonitor           AC/battery, idle time, lock/unlock, sleep/wake
//   powerSaveBlocker       keep the display awake
//   screen                 every display: scale, refresh rate, colour depth
//   app.getFileIcon        the icon Explorer shows for a file
//   createThumbnailFromPath  the thumbnail Explorer shows for a file
//   shell.readShortcutLink   what a .lnk shortcut really points at
//
// Same boundary rules as the other Electron demos: nodeIntegration off,
// contextIsolation on, and preload.js lists the renderer's every capability.

const { app, BrowserWindow, desktopCapturer, dialog, ipcMain, nativeImage,
        nativeTheme, powerMonitor, powerSaveBlocker, safeStorage, screen,
        shell, systemPreferences } = require('electron');
const path = require('path');

let win = null;
let blocker = null;            // powerSaveBlocker id while keeping awake

const send = (channel, data) => win && !win.isDestroyed() &&
  win.webContents.send(channel, data);

function createWindow() {
  win = new BrowserWindow({
    width: 1000,
    height: 720,
    minWidth: 600,
    minHeight: 420,
    title: 'Electron × Windows — Unified Base Windows demo',
    backgroundColor: '#0d1117',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'index.html'));
}

// -- windows and screens -----------------------------------------------------
ipcMain.handle('capture:windows', async () => {
  const sources = await desktopCapturer.getSources({
    types: ['window', 'screen'],
    thumbnailSize: { width: 320, height: 200 },
    fetchWindowIcons: true,
  });
  return sources.map((s) => ({
    name: s.name,
    kind: s.id.split(':')[0],
    thumb: s.thumbnail.isEmpty() ? null : s.thumbnail.toDataURL(),
    icon: s.appIcon && !s.appIcon.isEmpty() ? s.appIcon.resize({ width: 16 }).toDataURL() : null,
  }));
});

// -- DPAPI ---------------------------------------------------------------------
// On Windows safeStorage encrypts with AES-256-GCM under a key that DPAPI locks
// to your Windows logon: the ciphertext decrypts for you, on this PC, and for
// nobody else — and GCM's tag refuses it if a single bit changes.
ipcMain.handle('dpapi:encrypt', (_e, text) => {
  if (!safeStorage.isEncryptionAvailable()) return { ok: false };
  const buf = safeStorage.encryptString(String(text));
  return { ok: true, b64: buf.toString('base64'), bytes: buf.length };
});

ipcMain.handle('dpapi:decrypt', (_e, b64) => {
  try {
    return { ok: true, text: safeStorage.decryptString(Buffer.from(String(b64), 'base64')) };
  } catch (err) {
    return { ok: false, error: err.message };   // tampered or someone else's
  }
});

// -- colours and theme -------------------------------------------------------
const SYSTEM_COLORS = ['window', 'window-text', 'highlight', 'highlight-text',
  'hotlight', 'button-text', 'active-caption', 'inactive-caption', 'menu',
  'menu-highlight', 'desktop', 'info-background', '3d-face', 'disabled-text'];

function colors() {
  const acc = systemPreferences.getAccentColor();       // "RRGGBBAA"
  return {
    accent: `#${acc.slice(0, 6)}`,
    system: SYSTEM_COLORS.map((name) => [name, systemPreferences.getColor(name)]),
    dark: nativeTheme.shouldUseDarkColors,
    highContrast: nativeTheme.shouldUseHighContrastColors,
    inverted: nativeTheme.shouldUseInvertedColorScheme,
  };
}
ipcMain.handle('theme:colors', colors);

// -- power -------------------------------------------------------------------
ipcMain.handle('power:state', () => ({
  onBattery: powerMonitor.isOnBatteryPower(),
  idle: powerMonitor.getSystemIdleState(60),
  idleSeconds: powerMonitor.getSystemIdleTime(),
  keepingAwake: blocker !== null && powerSaveBlocker.isStarted(blocker),
}));

ipcMain.handle('power:keep-awake', (_e, on) => {
  if (on && blocker === null) blocker = powerSaveBlocker.start('prevent-display-sleep');
  if (!on && blocker !== null) {
    powerSaveBlocker.stop(blocker);
    blocker = null;
  }
  return blocker !== null;
});

// -- displays ----------------------------------------------------------------
// Electron rounds DIP sizes *up* (768 px / 1.25 = 614.4 -> 615 dip), so
// scaling back and rounding down recovers the panel's pixels; rounding to
// nearest (or dipToScreenRect) says 769 rows on a 768-row panel.
const displays = () => screen.getAllDisplays().map((d) => ({
  label: d.label || (d.internal ? 'built-in display' : `display ${d.id}`),
  primary: d.id === screen.getPrimaryDisplay().id,
  size: `${d.size.width}×${d.size.height}`,
  pixels: `${Math.floor(d.size.width * d.scaleFactor)}×${Math.floor(d.size.height * d.scaleFactor)}`,
  scale: Math.round(d.scaleFactor * 100),
  hz: d.displayFrequency,
  depth: d.colorDepth,
  rotation: d.rotation,
  internal: d.internal,
  touch: d.touchSupport,
}));
ipcMain.handle('screen:displays', displays);

// -- shell -------------------------------------------------------------------
ipcMain.handle('shell:inspect', async () => {
  const startMenu = path.join(app.getPath('appData'),
    'Microsoft', 'Windows', 'Start Menu', 'Programs');
  const res = await dialog.showOpenDialog(win, {
    title: 'Pick any file — a .lnk shortcut, an image, a PDF, an .exe',
    defaultPath: startMenu,
    properties: ['openFile'],
  });
  if (res.canceled || !res.filePaths.length) return { canceled: true };
  const file = res.filePaths[0];
  const out = { canceled: false, path: file, name: path.basename(file) };
  out.icon = (await app.getFileIcon(file, { size: 'large' })).toDataURL();
  try {
    // Explorer's own thumbnail handler: images, videos, PDFs, documents.
    const t = await nativeImage.createThumbnailFromPath(file, { width: 256, height: 256 });
    out.thumb = t.isEmpty() ? null : t.toDataURL();
  } catch {
    out.thumb = null;                   // no thumbnail handler for this type
  }
  if (file.toLowerCase().endsWith('.lnk')) {
    try {
      out.link = shell.readShortcutLink(file);
    } catch (err) {
      out.link = { error: err.message };
    }
  }
  return out;
});

ipcMain.handle('shell:reveal', (_e, file) => {
  shell.showItemInFolder(String(file));
});

// -- pushed events -------------------------------------------------------------
function watch() {
  const themeChanged = () => send('theme:changed', colors());
  nativeTheme.on('updated', themeChanged);
  systemPreferences.on('accent-color-changed', themeChanged);
  systemPreferences.on('color-changed', themeChanged);
  for (const ev of ['suspend', 'resume', 'on-ac', 'on-battery', 'lock-screen',
                    'unlock-screen', 'speed-limit-change']) {
    powerMonitor.on(ev, () => send('power:event', { ev, at: new Date().toLocaleTimeString() }));
  }
  for (const ev of ['display-added', 'display-removed', 'display-metrics-changed']) {
    screen.on(ev, () => send('screen:changed', displays()));
  }
}

app.whenReady().then(() => {
  watch();
  createWindow();
});

app.on('window-all-closed', () => app.quit());
