const { app, BrowserWindow } = require('electron');
const path = require('path');
const axios = require('axios');

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
    return path.join(__dirname, "..", "..", "app_main.py")
  }
  if (process.platform === 'win32') {
    return path.join(__dirname, "..", "dist", "perfi", "perfi.exe")
  }
  return path.join(__dirname, "..", "dist", "perfi", "perfi")
}

let pyProc
const createPyProc = () => {
  let script = getScriptPath()
  console.log('launching ' + script)

  if (guessPackaged()) {
    console.log('looks packaged')
    pyProc = require('child_process').execFile(script, [])
  } else {
    console.log('looks local')
    pyProc = require('child_process').spawn('poetry', ['run', 'python', 'app_main.py'], {
      cwd: path.join(__dirname, '..', '..')
    })
  }

  pyProc.stdout.pipe(process.stdout);
  pyProc.stderr.pipe(process.stderr);
}


// Handle creating/removing shortcuts on Windows when installing/uninstalling.
// eslint-disable-next-line global-require
if (require('electron-squirrel-startup')) {
  app.quit();
}

const sleep = ms => new Promise(r => setTimeout(r, ms));


const createWindow = async () => {
  // Create the browser window.
  const mainWindow = new BrowserWindow({
    width: 800,
    height: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  // and load the index.html of the app.
  mainWindow.loadFile(path.join(__dirname, 'index.html'));

  let tries = 0
  const url = "http://127.0.0.1:5002"
  let ready = false
  while (! ready && tries < 20) {
    await sleep(1000)
    try {
      console.log(`Trying to fetch ${url}`)
      let data = await axios.get(url)
      if (data) ready = true
    }
    catch (exception) {
      console.log(`Fetch failed for ${url}. Sleeping...`)
    }
    tries += 1
  }

  mainWindow.loadURL(url);

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

app.on('before-quit', () => {
  if (pyProc) {
    console.log('Killing python process...')
    pyProc.kill('SIGTERM')
    console.log('Killed.')
  }
})
