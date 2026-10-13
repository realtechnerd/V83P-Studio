// V83P Studio: Electron shell around the Python backend (mykeys/studio).
// Installed: runs the bundled backend (resources/backend/v83p-backend.exe) and keeps user data in %APPDATA%\V83P Studio.
// From source (npm start): runs `python -m mykeys.studio` from the project folder, which also holds the data.
"use strict";
const { app, BrowserWindow, Tray, Menu, Notification, nativeImage, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");          // the project folder (Python package lives here)
const ASSETS = path.join(__dirname, "assets");
const PYTHON = process.env.MYKEYS_PYTHON || "python";
const START_HIDDEN = process.argv.includes("--hidden");
const DEV = !app.isPackaged;

let win = null, tray = null, backend = null, server = null;
let quitting = false, restarts = 0, hideNoticeShown = false, last = {};

if (!app.requestSingleInstanceLock()) app.quit();
app.setAppUserModelId("com.v83p.studio");

/* ---------------- backend ---------------- */
function log(line) {
  fs.appendFile(path.join(app.getPath("userData"), "backend.log"), `[${new Date().toISOString()}] ${line}\n`, () => {});
}

function startBackend() {
  return new Promise((resolve, reject) => {
    server = null;
    const args = ["--no-window", "--json-ready", "--parent-pid", String(process.pid)];
    const env = { ...process.env, PYTHONUNBUFFERED: "1" };
    if (DEV) {
      backend = spawn(PYTHON, ["-m", "mykeys.studio", ...args], { cwd: ROOT, windowsHide: true, env });
    } else {
      const dir = path.join(process.resourcesPath, "backend");
      backend = spawn(path.join(dir, "v83p-backend.exe"), args,
        { cwd: dir, windowsHide: true, env: { ...env, MYKEYS_DATA: app.getPath("userData") } });
    }
    let buf = "";
    backend.stdout.on("data", d => {
      buf += d;
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!server && line.startsWith("{")) {
          try { server = JSON.parse(line); restarts = 0; resolve(server); } catch { log("bad handshake: " + line); }
        } else if (line) log(line);
      }
    });
    backend.stderr.on("data", d => log(String(d).trimEnd()));
    backend.on("error", e => { log("spawn failed: " + e.message); reject(e); });
    backend.on("exit", code => {
      log(`backend exited (${code})`);
      backend = null;
      if (!server) reject(new Error(`backend exited with code ${code}`));
      if (!quitting) onBackendLost();
    });
  });
}

async function onBackendLost() {
  server = null;
  if (restarts++ < 3) {
    showStatusPage("Reconnecting to the keyboard service…");
    setTimeout(() => boot().catch(() => {}), 1000);
  } else {
    showStatusPage(DEV ? "The keyboard service stopped. Check that Python is installed, then restart V83P Studio."
      : "The keyboard service stopped. Restart V83P Studio. If it keeps happening, reinstall it.", true);
  }
}

function api(p, body) {
  return new Promise((resolve, reject) => {
    if (!server) return reject(new Error("backend not ready"));
    const data = body === undefined ? null : JSON.stringify(body);
    const req = http.request({ host: "127.0.0.1", port: server.port, path: p, method: data ? "POST" : "GET",
      headers: { "X-MyKeys-Token": server.token, "Content-Type": "application/json" }, timeout: 8000 }, res => {
      let out = "";
      res.on("data", c => out += c);
      res.on("end", () => { try { const j = JSON.parse(out); j.ok === false ? reject(new Error(j.error)) : resolve(j.data); } catch (e) { reject(e); } });
    });
    req.on("error", reject);
    req.on("timeout", () => req.destroy(new Error("timeout")));
    if (data) req.write(data);
    req.end();
  });
}

/* ---------------- window ---------------- */
function statusHtml(msg, error) {
  return "data:text/html;charset=utf-8," + encodeURIComponent(`<!doctype html><html><body style="margin:0;height:100vh;display:flex;
    align-items:center;justify-content:center;flex-direction:column;gap:18px;background:#090b0f;color:#e9edf3;
    font:15px 'Segoe UI',sans-serif;-webkit-app-region:drag"><img src="data:image/png;base64,${fs.readFileSync(path.join(ASSETS, "icon.png")).toString("base64")}"
    width="84" style="filter:drop-shadow(0 0 18px #a6e57f66)"><div style="color:${error ? "#ff8a8a" : "#8a93a3"};max-width:460px;text-align:center">${msg}</div></body></html>`);
}
function showStatusPage(msg, error) { if (win) win.loadURL(statusHtml(msg, error)); }

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1100, minHeight: 700, show: false, backgroundColor: "#090b0f",
    title: "V83P Studio", icon: path.join(ASSETS, "icon.ico"),
    titleBarStyle: "hidden", titleBarOverlay: { color: "#0b0d11", symbolColor: "#c9d1dc", height: 36 },
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true },
  });
  win.loadURL(statusHtml("Starting…"));
  win.once("ready-to-show", () => { if (!START_HIDDEN) win.show(); });
  win.on("close", e => {
    if (quitting) return;
    e.preventDefault();
    win.hide();
    if (!hideNoticeShown) {
      hideNoticeShown = true;
      notify("V83P Studio is still running", "Reactions and auto profiles keep working. Open it again from the tray icon.");
    }
  });
  // Only our backend page may load inside the window; anything else opens in the browser.
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  win.webContents.on("will-navigate", (e, url) => {
    if (!server || !url.startsWith(`http://127.0.0.1:${server.port}/`)) e.preventDefault();
  });
}
function showWindow() {
  if (!win) createWindow();
  win.show();
  if (win.isMinimized()) win.restore();
  win.focus();
}

/* ---------------- tray ---------------- */
async function buildTrayMenu() {
  let profiles = [], st = last;
  try { profiles = await api("/api/profiles"); } catch {}
  const autoStart = getAutoStart();
  return Menu.buildFromTemplate([
    { label: "Open V83P Studio", click: showWindow },
    { type: "separator" },
    { label: "Profiles", enabled: profiles.length > 0 && st.connection === "wired",
      submenu: profiles.map(n => ({ label: n, type: "radio", checked: st.active_profile === n,
        click: () => api("/api/profiles/apply", { name: n, lighting_only: true })
          .then(() => notify("Profile applied", n)).catch(e => notify("Couldn't apply profile", e.message)) })) },
    { label: "Music mode (Spotify)", type: "checkbox", checked: !!st.music?.enabled,
      enabled: !!st.firmware?.mykeys || !!st.music?.enabled || st.connection !== "wired",   // stock firmware can't
      click: m => api("/api/music", { enabled: m.checked }).catch(e => notify("Music mode", e.message)) },
    { label: "Pause reactions & auto profiles", type: "checkbox", checked: !!st.paused,
      click: m => api("/api/pause", { paused: m.checked }).catch(() => {}) },
    { label: "Start with Windows", type: "checkbox", checked: autoStart, click: m => setAutoStart(m.checked) },
    { type: "separator" },
    { label: "Quit", click: () => { quitting = true; app.quit(); } },
  ]);
}
function createTray() {
  tray = new Tray(nativeImage.createFromPath(path.join(ASSETS, "tray.png")));
  tray.setToolTip("V83P Studio");
  tray.on("click", showWindow);
  tray.on("right-click", async () => tray.popUpContextMenu(await buildTrayMenu()));
}

/* ---------------- notifications + state watch ---------------- */
function notify(title, body) {
  if (Notification.isSupported()) new Notification({ title, body, icon: path.join(ASSETS, "icon.png"), silent: true }).show();
}
const CONN = { wired: "Keyboard connected (wired)", wireless: "Keyboard is on wireless", disconnected: "Keyboard disconnected",
  flashing: "Updating firmware" };
async function watchState() {
  let st;
  try { st = await api("/api/state?lite=1"); } catch { return; }
  if (last.connection && st.connection !== last.connection && st.connection !== "flashing" && last.connection !== "flashing")
    notify(CONN[st.connection], st.connection === "wired" ? "You can edit settings now." :
      st.connection === "wireless" ? "Saved settings keep working. Plug in the cable to edit." : "");
  if (st.active_profile && st.active_profile !== last.active_profile && st.auto_reason)
    notify(`Profile: ${st.active_profile}`, `Switched because ${st.auto_reason} is active`);
  if (st.music?.active && !last.music?.active)
    notify("Music mode on", [st.music.artist, st.music.title].filter(Boolean).join(" — ") || "Listening to Spotify");
  tray?.setToolTip(`V83P Studio — ${CONN[st.connection]}${st.active_profile ? " · " + st.active_profile : ""}`);
  last = st;
}

/* ---------------- start with Windows ---------------- */
const loginArgs = () => DEV ? [app.getAppPath(), "--hidden"] : ["--hidden"];
function getAutoStart() {
  return app.getLoginItemSettings({ path: process.execPath, args: loginArgs() }).openAtLogin;
}
function setAutoStart(on) {
  app.setLoginItemSettings({ openAtLogin: !!on, path: process.execPath, args: loginArgs() });
  return getAutoStart();
}
ipcMain.handle("autostart:get", () => getAutoStart());
// Title-bar buttons + window background follow the app's dark/light appearance.
const TITLEBAR = { dark: { color: "#09090a", symbolColor: "#c9d1dc" }, light: { color: "#f4f4f1", symbolColor: "#3c3c43" } };
ipcMain.handle("appearance:set", (_e, mode) => {
  const t = TITLEBAR[mode] || TITLEBAR.dark;
  if (win) { win.setTitleBarOverlay({ ...t, height: 36 }); win.setBackgroundColor(t.color); }
});
ipcMain.handle("autostart:set", (_e, on) => setAutoStart(on));

/* ---------------- lifecycle ---------------- */
async function boot() {
  await startBackend();
  if (win) await win.loadURL(`http://127.0.0.1:${server.port}/`);
}

app.on("second-instance", showWindow);
app.on("before-quit", () => { quitting = true; if (backend) backend.kill(); });
app.on("window-all-closed", e => e.preventDefault?.()); // stay in the tray

app.whenReady().then(async () => {
  createWindow();
  createTray();
  try {
    await boot();
  } catch (e) {
    showStatusPage(DEV ? `Couldn't start the keyboard service: ${e.message}.<br>Is Python installed and on PATH?`
      : `Couldn't start the keyboard service: ${e.message}.<br>Try reinstalling V83P Studio.`, true);
  }
  setInterval(watchState, 2000);
});
