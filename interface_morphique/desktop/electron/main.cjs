const { app, BrowserWindow, dialog, shell } = require('electron');
const isDevelopment = !app.isPackaged;
// Packaged releases always use the operator-provisioned TLS endpoint. This
// avoids inheriting a stale Machine environment in an already-open Explorer.
const { resolveApiScheme } = require('./api-config.cjs');
const apiScheme = resolveApiScheme({ packaged: app.isPackaged, configuredScheme: process.env.GREATOS_API_SCHEME });
process.env.GREATOS_API_SCHEME = apiScheme;
const { ensureBackendAvailable } = require('./backend.cjs');
const desktopUrl = process.env.GREATOS_DESKTOP_URL || `${apiScheme}://localhost:8000/desktop/`;

function isAllowedNavigation(url) {
  try {
    const target = new URL(url);
    const targetOrigin = target.origin;
    const desktopOrigin = new URL(desktopUrl).origin;
    if (targetOrigin === desktopOrigin) return true;
    if (isDevelopment && targetOrigin === 'http://localhost:5173') return true;
    return false;
  } catch {
    return false;
  }
}

async function resolveInitialUrl() {
  if (isDevelopment) {
    try {
      const res = await fetch('http://localhost:5173', { signal: AbortSignal.timeout(600) });
      if (res.ok) return 'http://localhost:5173';
    } catch {
      // Dev server Vite non actif, repli vers l'endpoint desktop du serveur local
    }
  }
  return desktopUrl;
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
  void window.loadURL(startupPage).catch((error) => {
    console.error('Impossible d’afficher la page locale de démarrage GreatOS.', error);
    if (!window.isDestroyed()) window.show();
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (isAllowedNavigation(url)) return;
    event.preventDefault();
    if (url.startsWith('https://')) shell.openExternal(url);
  });
  return window;
}

async function ensureBackendWithRecovery(window) {
  while (!window.isDestroyed()) {
    try {
      await ensureBackendAvailable();
      return;
    } catch (error) {
      if (window.isDestroyed()) return;
      const result = await dialog.showMessageBox(window, {
        type: 'warning',
        title: 'Démarrage de GreatOS impossible',
        message: 'Le service local GreatOS n’est pas prêt.',
        detail: `${error.message}\n\nAprès l’installation du service, relance GreatOS ou réessaie maintenant.`,
        buttons: ['Réessayer', 'Fermer'],
        defaultId: 0,
        cancelId: 1,
        noLink: true,
      });
      if (result.response !== 0) {
        window.close();
        return;
      }
    }
  }
}

async function loadDesktopWithRecovery(window, url) {
  while (!window.isDestroyed()) {
    try {
      await window.loadURL(url);
      return;
    } catch (error) {
      if (window.isDestroyed()) return;
      const result = await dialog.showMessageBox(window, {
        type: 'warning',
        title: 'Interface GreatOS indisponible',
        message: 'La fenêtre GreatOS est ouverte, mais son interface ne peut pas être chargée.',
        detail: `${error.message}\n\nVérifie que le serveur GreatOS est démarré, puis réessaie.`,
        buttons: ['Réessayer', 'Fermer'],
        defaultId: 0,
        cancelId: 1,
        noLink: true,
      });
      if (result.response !== 0) {
        window.close();
        return;
      }
    }
  }
}

app.whenReady().then(async () => {
  const window = createWindow();
  const configuredUrl = new URL(desktopUrl);
  const usesLocalBackend = ['localhost', '127.0.0.1', '::1'].includes(configuredUrl.hostname)
    && configuredUrl.port === '8000';

  const targetUrl = await resolveInitialUrl();
  if (targetUrl === desktopUrl && usesLocalBackend) {
    await ensureBackendWithRecovery(window);
  }

  if (window.isDestroyed()) return;
  await loadDesktopWithRecovery(window, targetUrl);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}).catch((error) => {
  console.error('Échec inattendu du démarrage de GreatOS.', error);
  dialog.showErrorBox('Démarrage de GreatOS impossible', error.message);
  app.quit();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
