// Exposes the few Windows features the page can use. Nothing else from Node reaches the page.
"use strict";
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("mykeysApp", {
  isElectron: true,
  getAutoStart: () => ipcRenderer.invoke("autostart:get"),
  getVersion: () => ipcRenderer.invoke("app:version"),
  setAutoStart: on => ipcRenderer.invoke("autostart:set", !!on),
  setAppearance: mode => ipcRenderer.invoke("appearance:set", mode === "light" ? "light" : "dark"),
});
