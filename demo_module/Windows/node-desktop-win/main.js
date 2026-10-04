// Electron — Unified Base Windows demo: twin of demo_module/Linux/node-desktop.
//
// The same main process as the Linux demo, with one change: load average does
// not exist on Windows (Node's os.loadavg() returns [0, 0, 0] there), so the
// live sample carries CPU % instead, from os.cpus() time deltas.
//
// Demo #1 is a pretty window. This one is about the part a web page cannot do:
// privileged work in the main process, exposed to a sandboxed renderer over a
// narrow, explicit IPC surface.
//
//   * contextBridge + preload — the renderer gets a handful of named functions,
//     never `require`, never Node globals
//   * ipcMain.handle / ipcRenderer.invoke — request/response with real return values
//   * native OS integration — application menu with accelerators, file dialog,
//     desktop notification, external links opened in the real browser
//
// nodeIntegration stays off and contextIsolation stays on; every capability the
// UI has is one of the functions listed in preload.js.

const { app, BrowserWindow, ipcMain, dialog, Menu, Notification, shell } =
  require('electron');
const fs = require('fs/promises');
const os = require('os');
const path = require('path');

let win = null;

function createWindow() {
  win = new BrowserWindow({
    width: 940,
    height: 660,
    minWidth: 560,
    minHeight: 420,
    title: 'Electron · IPC & desktop integration — Unified Base Windows demo',
    backgroundColor: '#0d1117',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  win.loadFile(path.join(__dirname, 'index.html'));
}

// ---------------------------------------------------------------------------
// IPC handlers. Each one is a capability the renderer would otherwise not have.
// ---------------------------------------------------------------------------
ipcMain.handle('system:info', () => ({
  electron: process.versions.electron,
  chrome: process.versions.chrome,
  node: process.versions.node,
  v8: process.versions.v8,
  platform: `${os.type()} ${os.release()}`,
  arch: process.arch,
  cpus: os.cpus().length,
  cpuModel: (os.cpus()[0] || {}).model || 'unknown',
  totalMem: os.totalmem(),
  freeMem: os.freemem(),
  uptime: os.uptime(),
  home: os.homedir(),
  pid: process.pid
}));

// CPU % between two samples: the busy share of every core's time since the
// last one. Windows has no load average to report instead.
function cpuTimes() {
  return os.cpus().reduce((a, { times: t }) => {
    a.idle += t.idle;
    a.total += t.user + t.nice + t.sys + t.irq + t.idle;
    return a;
  }, { idle: 0, total: 0 });
}
let lastCpu = cpuTimes();

// Sampled on demand rather than pushed on a timer: the renderer decides how
// often it wants numbers, and no work happens while it isn't asking.
ipcMain.handle('system:sample', () => {
  const now = cpuTimes();
  const total = now.total - lastCpu.total;
  const cpu = total > 0 ? 100 * (1 - (now.idle - lastCpu.idle) / total) : 0;
  lastCpu = now;
  return {
    freeMem: os.freemem(),
    totalMem: os.totalmem(),
    cpu,
    rss: process.memoryUsage().rss,
    uptime: os.uptime()
  };
});

ipcMain.handle('file:open', async () => {
  const res = await dialog.showOpenDialog(win, {
    title: 'Pick a file to inspect',
    properties: ['openFile'],
    filters: [{ name: 'Text-ish', extensions: ['txt', 'md', 'json', 'js', 'log'] },
              { name: 'All files', extensions: ['*'] }]
  });
  if (res.canceled || !res.filePaths.length) return { canceled: true };

  const file = res.filePaths[0];
  const stat = await fs.stat(file);
  // Read a bounded slice: a demo should not try to load a 2 GB file into a div.
  const handle = await fs.open(file, 'r');
  try {
    const buf = Buffer.alloc(Math.min(stat.size, 4096));
    await handle.read(buf, 0, buf.length, 0);
    const text = buf.toString('utf8');
    return {
      canceled: false,
      path: file,
      name: path.basename(file),
      size: stat.size,
      modified: stat.mtime.toISOString(),
      truncated: stat.size > buf.length,
      lines: text.split('\n').length,
      preview: text
    };
  } finally {
    await handle.close();
  }
});

ipcMain.handle('notify', (_e, text) => {
  if (!Notification.isSupported()) return { ok: false, reason: 'unsupported' };
  new Notification({ title: 'Unified Base demo', body: String(text) }).show();
  return { ok: true };
});

ipcMain.handle('window:state', (_e, action) => {
  if (!win) return null;
  if (action === 'minimize') win.minimize();
  if (action === 'devtools') win.webContents.toggleDevTools();
  if (action === 'fullscreen') win.setFullScreen(!win.isFullScreen());
  return { fullscreen: win.isFullScreen() };
});

// Never hand a URL to the renderer's own navigation — open it in the user's
// real browser instead, so a page can't turn the app window into a web view.
ipcMain.handle('open:external', (_e, url) => {
  const ok = /^https?:\/\//i.test(String(url));
  if (ok) shell.openExternal(url);
  return { ok };
});

// ---------------------------------------------------------------------------
// Native application menu. Menu items reach the page by sending on a channel;
// the renderer subscribes through preload's onMenuCommand.
// ---------------------------------------------------------------------------
function buildMenu() {
  const send = (cmd) => () => win && win.webContents.send('menu:command', cmd);
  const template = [
    {
      label: 'Demo',
      submenu: [
        { label: 'Refresh system info', accelerator: 'CmdOrCtrl+R', click: send('refresh') },
        { label: 'Open file…', accelerator: 'CmdOrCtrl+O', click: send('open') },
        { label: 'Send notification', accelerator: 'CmdOrCtrl+N', click: send('notify') },
        { type: 'separator' },
        { role: 'quit' }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' }
      ]
    }
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(() => {
  buildMenu();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
