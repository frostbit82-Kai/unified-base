// The renderer's whole capability surface — one function per ipcMain.handle
// in main.js, plus subscriptions for the events main pushes.
const { contextBridge, ipcRenderer } = require('electron');

const on = (channel) => (fn) => ipcRenderer.on(channel, (_e, data) => fn(data));

contextBridge.exposeInMainWorld('win', {
  windows: () => ipcRenderer.invoke('capture:windows'),
  encrypt: (text) => ipcRenderer.invoke('dpapi:encrypt', text),
  decrypt: (b64) => ipcRenderer.invoke('dpapi:decrypt', b64),
  colors: () => ipcRenderer.invoke('theme:colors'),
  power: () => ipcRenderer.invoke('power:state'),
  keepAwake: (on) => ipcRenderer.invoke('power:keep-awake', on),
  displays: () => ipcRenderer.invoke('screen:displays'),
  inspectFile: () => ipcRenderer.invoke('shell:inspect'),
  reveal: (path) => ipcRenderer.invoke('shell:reveal', path),
  onColors: on('theme:changed'),
  onPower: on('power:event'),
  onDisplays: on('screen:changed'),
});
