const { app, BrowserWindow } = require('electron');
const path = require('path');


const cp = require("child_process");
const util = require("util");
const execFile = util.promisify(cp.execFile);
const fs = require("fs");

const PY_DIST_FOLDER = 'dist'
const PY_FOLDER = '.'
const PY_MODULE = 'app_main' // without .py suffix

const guessPackaged = () => {
  const fullPath = path.join(__dirname, "..", PY_DIST_FOLDER)
  return require('fs').existsSync(fullPath)
}

const getScriptPath = () => {
  if (!guessPackaged()) {
    return path.join(__dirname, "..", "app_main.py")
  }
  if (process.platform === 'win32') {
    return path.join(__dirname, "..", "dist", "perfi", "perfi.exe")
  }
  return path.join(__dirname, "..", "dist", "perfi", "perfi")
}

const createPyProc = () => {
  let script = getScriptPath()
  console.log('launching ' + script)

  if (guessPackaged()) {
    pyProc = require('child_process').execFile(script, [])
  } else {
    pyProc = require('child_process').spawn('python', [script])
  }

  if (pyProc != null) {
    //console.log(pyProc)
    console.log('child process running')
  }
}


// Handle creating/removing shortcuts on Windows when installing/uninstalling.
// eslint-disable-next-line global-require
if (require('electron-squirrel-startup')) {
  app.quit();
}

const createWindow = () => {
  // Create the browser window.
  const mainWindow = new BrowserWindow({
    width: 800,
    height: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  // and load the index.html of the app.
  // mainWindow.loadFile(path.join(__dirname, 'index.html'));
  mainWindow.loadURL("http://127.0.0.1:5002");

  // Open the DevTools.
  mainWindow.webContents.openDevTools();
};

createPyProc()

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.on('ready', createWindow);

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  // On OS X it's common to re-create a window in the app when the
  // dock icon is clicked and there are no other windows open.
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// In this file you can include the rest of your app's specific main process
// code. You can also put them in separate files and import them here.
