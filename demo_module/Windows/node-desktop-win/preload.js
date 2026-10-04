// The entire capability surface of the renderer. Nothing else crosses the
// boundary: the page has no `require`, no `process`, no filesystem — only these
// functions, each of which lands on a matching ipcMain.handle in main.js.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  systemInfo: () => ipcRenderer.invoke('system:info'),
  sample: () => ipcRenderer.invoke('system:sample'),
  openFile: () => ipcRenderer.invoke('file:open'),
  notify: (text) => ipcRenderer.invoke('notify', text),
  windowState: (action) => ipcRenderer.invoke('window:state', action),
  openExternal: (url) => ipcRenderer.invoke('open:external', url),

  // Menu clicks arrive here. Only the command string is forwarded — the
  // renderer never sees the IpcRendererEvent, which would leak `sender`.
  onMenuCommand: (fn) =>
    ipcRenderer.on('menu:command', (_event, cmd) => fn(cmd))
});
