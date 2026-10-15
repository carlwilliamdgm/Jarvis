const { app, BrowserWindow, dialog } = require('electron');

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    width: 900,
    height: 700,
    title: 'GreatOS — sonde PRF Electron',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  try {
    await window.loadURL('http://localhost:8765/electron');
  } catch (error) {
    dialog.showErrorBox('Sonde PRF Electron', `Impossible de charger la sonde locale : ${error.message}`);
    window.close();
    app.quit();
  }
});

app.on('window-all-closed', () => app.quit());
