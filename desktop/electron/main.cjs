const { app, BrowserWindow, shell } = require('electron');

const isDevelopment = !app.isPackaged;
const desktopUrl = process.env.GREATOS_DESKTOP_URL || 'http://127.0.0.1:8000/desktop/';
const allowedOrigin = new URL(isDevelopment ? 'http://127.0.0.1:5173/' : desktopUrl).origin;
const allowedPath = new URL(isDevelopment ? 'http://127.0.0.1:5173/' : desktopUrl).pathname.replace(/\/+$/, '');

function isAllowedNavigation(url) {
  try {
    const target = new URL(url);
    return target.origin === allowedOrigin
      && (target.pathname === allowedPath || target.pathname.startsWith(`${allowedPath}/`));
  } catch {
    return false;
  }
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 760,
    minHeight: 620,
    title: 'GreatOS — J.A.R.V.I.S',
    backgroundColor: '#080d16',
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.once('ready-to-show', () => window.show());
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (isAllowedNavigation(url)) return;
    event.preventDefault();
    if (url.startsWith('https://')) shell.openExternal(url);
  });
  if (isDevelopment) window.loadURL('http://127.0.0.1:5173');
  else window.loadURL(desktopUrl);
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
