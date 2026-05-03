const { app, BrowserWindow } = require('electron')

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: true,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  })

  const frontendPort = process.env.OPENAWA_E2E_FRONTEND_PORT || '15173'
  const frontendUrl = process.env.FRONTEND_URL || `http://127.0.0.1:${frontendPort}/plugins`
  win.loadURL(frontendUrl)
}

app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
