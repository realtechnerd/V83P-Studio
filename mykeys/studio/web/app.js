"use strict";
/* V83P Studio front end. Talks to the local Python server (mykeys/studio/server.py). */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};
let LAYERS = ["Windows", "Windows Fn", "Mac", "Mac Fn"];  // replaced by the board definition at boot

/* ---------------- API ---------------- */
async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-MyKeys-Token": window.MYKEYS_TOKEN },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok || j.ok === false) {
    const err = new Error(j.error || `HTTP ${res.status}`);
    err.code = j.code;
    throw err;
  }
  return j.data;
}
function toast(msg, err = false) {
  const t = el("div", { class: "toast" + (err ? " err" : "") }, msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), err ? 6000 : 2600);
}
async function safe(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(okMsg);
    return r;
  } catch (e) {
    toast(e.message, true);
    if (e.code === "not_wired") onNotWired();
    throw e;
  }
}
// The keyboard left USB in the middle of a change: grey out now and drop the optimistic on-screen change.
let notWiredBusy = false;
async function onNotWired() {
  if (notWiredBusy) return;
  notWiredBusy = true;
  try {
    S.connection = "disconnected";
    setStatus();
    const s = await api("/api/state").catch(() => null);
    if (s) {
      Object.assign(S.state, s);
      S.connection = s.connection;
      setStatus();
      LT.busy = false;
      if (S.page === "lighting") { LT.view.update(); refreshPanel(true); }
    }
  } finally {
    notWiredBusy = false;
  }
}
function throttle(fn, ms) {
  let last = 0, timer = null, pending = null;
  return (...args) => {
    pending = args;
    const run = () => { last = Date.now(); timer = null; fn(...pending); };
    const wait = ms - (Date.now() - last);
    if (wait <= 0) run(); else if (!timer) timer = setTimeout(run, wait);
  };
}

/* ---------------- color helpers ---------------- */
const hex2rgb = h => { h = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
const rgb2hex = rgb => "#" + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
function hsv2rgb(h, s, v) {
  const f = n => { const k = (n + h * 6) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); };
  return [f(5) * 255, f(3) * 255, f(1) * 255];
}
function rgb2hsv([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [((h / 6) + 1) % 1, mx ? d / mx : 0, mx];
}
const validHex = h => /^#?[0-9a-f]{6}$/i.test(h.trim());
const normHex = h => "#" + h.trim().replace("#", "").toLowerCase();

/* ---------------- global state ---------------- */
const S = {
  state: null, connection: "disconnected", keycodes: [], kcByValue: new Map(),
  page: "lighting", keymap: null, encoders: null, macros: null, loaded: {},
};
const wired = () => S.connection === "wired";
/* Per-key colors and music mode need our firmware; on the original (stock) firmware they're locked. */
const fwOurs = () => !!S.state?.firmware?.mykeys;
const stockFw = () => wired() && !!S.state?.firmware && !fwOurs();

/* ---------------- keyboard renderer ----------------
   Layered like real hardware: floor (underglow spill) → case → plate with an LED light canvas →
   keycaps (skirt + dished top + legend). LED light shows through the gaps between caps. */
// Keycap colors come from the board's colorways.json: each colorway lists its "mod" and "accent" keys.
const CW = { id: null, roles: { mod: new Set(), accent: new Set() } };
const ALL_VIEWS = [];
const capRole = name => CW.roles.accent.has(name) ? "accent" : CW.roles.mod.has(name) ? "mod" : "";
const mixWhite = (hex, k) => rgb2hex(hex2rgb(hex).map(c => c + (255 - c) * k));
const GLOW_SCALE = 0.25;          // glow canvases render at 1/4 size; the GPU upscales (it's a blur anyway)
const SPRITES = new Map();        // quantized color -> 32px radial-gradient sprite
function glowSprite(hex) {
  const [r, g, b] = hex2rgb(hex).map(c => c & 0xf8);  // 5 bits/channel keeps the cache small
  const key = (r << 16) | (g << 8) | b;
  let c = SPRITES.get(key);
  if (!c) {
    if (SPRITES.size > 2048) SPRITES.clear();
    c = document.createElement("canvas");
    c.width = c.height = 32;
    const x = c.getContext("2d"), gr = x.createRadialGradient(16, 16, 0, 16, 16, 16);
    gr.addColorStop(0, `rgba(${r},${g},${b},1)`);
    gr.addColorStop(0.45, `rgba(${r},${g},${b},.45)`);
    gr.addColorStop(1, `rgba(${r},${g},${b},0)`);
    x.fillStyle = gr;
    x.fillRect(0, 0, 32, 32);
    SPRITES.set(key, c);
  }
  return c;
}

class KeyboardView {
  constructor(host, opts) {
    this.host = host; this.o = opts; this.keys = new Map(); this.cache = new Map();
    this.render();
    new ResizeObserver(() => { this.layout(); this.update(); }).observe(host);
  }
  get caps() { return S.state.layout.caps; }
  render() {
    this.host.innerHTML = "";
    this.floor = el("canvas", { class: "kb-floor" });
    this.board = el("div", { class: "kb" });
    this.plate = el("div", { class: "plate" });
    this.glow = el("canvas");
    this.plate.append(this.glow);
    this.board.append(this.plate, el("div", { class: "badge-logo" }, "Inland · MK Pro V2"));
    for (const cap of this.caps) {
      const k = el("div", { class: "key" }, el("div", { class: "top" }, el("span", { class: "lbl" })));
      k.addEventListener("mousedown", e => { e.stopPropagation(); this.o.onClick?.(cap, e); });
      this.keys.set(cap, k);
      this.board.append(k);
    }
    if (this.o.edge) {
      const L = S.state.layout, pts = L.points;
      const side = x => L.edge_leds.filter(i => pts[i][0] === x).sort((a, b) => pts[a][1] - pts[b][1]);
      this.edges = [];
      for (const [cls, x] of [["l", 0], ["r", 224]]) {
        const bar = el("div", { class: "edge " + cls });
        for (const i of side(x)) {
          const seg = el("i", { title: "Underglow LED " + i });
          seg.addEventListener("mousedown", e => { e.stopPropagation(); this.o.onEdge?.(i, e); });
          this.edges.push([i, seg, cls]);
          bar.append(seg);
        }
        this.board.append(bar);
      }
    }
    if (this.o.boxSelect) this.enableBox();
    this.classify();
    if (!ALL_VIEWS.includes(this)) ALL_VIEWS.push(this);
    this.host.append(this.floor, this.board);
    this.layout();
    this.update();
  }
  classify() {  // keycap color roles for the current colorway
    for (const [cap, k] of this.keys) {
      k.classList.remove("mod", "accent");
      if (cap.name === "KNOB") k.classList.add("knob");
      else if (capRole(cap.name)) k.classList.add(capRole(cap.name));
    }
  }
  layout() {
    const W = Math.max(...this.caps.map(c => c.x + c.w)), H = Math.max(...this.caps.map(c => c.y + c.h));
    const avail = Math.max(420, this.host.clientWidth - 60);
    const u = Math.min(this.o.maxUnit || 64, avail / (W + 0.9));
    const pad = u * 0.42, gap = u * 0.07;
    this.unit = u;
    const bw = W * u + pad * 2, bh = H * u + pad * 2;
    Object.assign(this.board.style, { width: bw + "px", height: bh + "px" });
    const pi = pad - u * 0.1;
    Object.assign(this.plate.style, { left: pi + "px", top: pi + "px", width: bw - pi * 2 + "px", height: bh - pi * 2 + "px" });
    this.plateBox = { x: pi, y: pi, w: bw - pi * 2, h: bh - pi * 2 };
    const logo = this.board.querySelector(".badge-logo");
    Object.assign(logo.style, { right: pad + "px", bottom: Math.max(2, pad * 0.12) + "px", fontSize: Math.max(6.5, u * 0.11) + "px" });
    this.centers = new Map();
    const small = this.o.maxUnit && this.o.maxUnit < 50;
    for (const [cap, k] of this.keys) {
      const knob = cap.name === "KNOB";
      const size = knob ? Math.min(cap.w, cap.h) * u * 0.92 : null;
      const x = pad + cap.x * u + gap / 2 + (knob ? (cap.w * u - gap - size) / 2 : 0);
      const y = pad + cap.y * u + gap / 2 + (knob ? (cap.h * u - gap - size) / 2 : 0);
      const w = size ?? cap.w * u - gap, h = size ?? cap.h * u - gap;
      Object.assign(k.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
      k.querySelector(".lbl").style.fontSize = Math.max(7.5, u * (small ? 0.2 : 0.165)) + "px";
      this.centers.set(cap, [x + w / 2, y + h / 2, w, h]);
    }
    // the floor canvas extends around the case so underglow can spill onto the "desk"
    const m = u * 1.4;
    this.floorBox = { m, w: bw + m * 2, h: bh + m * 2 };
    for (const [c, w, h] of [[this.glow, this.plateBox.w, this.plateBox.h], [this.floor, this.floorBox.w, this.floorBox.h]]) {
      c.width = Math.max(1, Math.round(w * GLOW_SCALE)); c.height = Math.max(1, Math.round(h * GLOW_SCALE));
      c.style.width = w + "px"; c.style.height = h + "px";
    }
    const br = this.board.getBoundingClientRect(), hr = this.host.getBoundingClientRect();
    Object.assign(this.floor.style, { left: br.left - hr.left - m + "px", top: br.top - hr.top - m + "px" });
    // underglow segment positions in floor coordinates (measured once here, not every frame)
    const fr = { left: br.left - m, top: br.top - m };
    this.edgePos = new Map((this.edges || []).map(([i, seg, side]) => {
      const sr = seg.getBoundingClientRect();
      return [i, [(side === "l" ? sr.left : sr.right) - fr.left, sr.top + sr.height / 2 - fr.top]];
    }));
    this.lastSig = null;
  }
  update(force) {
    if (!this.centers) return;
    const caps = [...this.keys.keys()];
    const colors = caps.map(cap => cap.led != null ? this.o.color?.(cap) || null : null);
    const edgeColors = (this.edges || []).map(([i]) => this.o.edgeColor?.(i) || null);
    const sig = colors.join() + "|" + edgeColors.join();
    if (sig !== this.lastSig || force) { this.lastSig = sig; this.paint(caps, colors, edgeColors); }
    this.updateDom(caps, colors);
  }
  paint(caps, colors, edgeColors) {
    const k = GLOW_SCALE, u = this.unit, m = this.floorBox.m;
    const g = this.glow.getContext("2d"), f = this.floor.getContext("2d");
    g.setTransform(k, 0, 0, k, 0, 0); f.setTransform(k, 0, 0, k, 0, 0);
    g.globalCompositeOperation = f.globalCompositeOperation = "source-over";
    g.clearRect(0, 0, this.plateBox.w, this.plateBox.h);
    f.clearRect(0, 0, this.floorBox.w, this.floorBox.h);
    g.globalCompositeOperation = f.globalCompositeOperation = "lighter";
    const blit = (ctx, x, y, r, hex, a) => { ctx.globalAlpha = a; ctx.drawImage(glowSprite(hex), x - r, y - r, r * 2, r * 2); };
    caps.forEach((cap, n) => {
      const c = colors[n];
      if (!c) return;
      const [cx, cy, w, h] = this.centers.get(cap), r = Math.max(w, h);
      blit(g, cx - this.plateBox.x, cy - this.plateBox.y, r * 0.78, c, 0.95);
      blit(f, cx + m, cy + m, r * 1.6, c, 0.05);
    });
    (this.edges || []).forEach(([i], n) => {
      const c = edgeColors[n], pos = this.edgePos?.get(i);
      if (!c || !pos) return;
      blit(f, pos[0], pos[1], u * 1.5, c, 0.5);
      blit(f, pos[0], pos[1], u * 0.6, c, 0.5);
    });
    g.globalAlpha = f.globalAlpha = 1;
  }
  updateDom(caps, colors) {
    // Legend shine-through repaints every keycap, so while animating it updates at ~5 fps;
    // the light itself (canvas) still animates smoothly.
    const now = performance.now(), legends = !this.lastDom || now - this.lastDom > 200;
    if (legends) this.lastDom = now;
    caps.forEach((cap, n) => {
      const k = this.keys.get(cap), c = colors[n];
      const label = this.o.label ? this.o.label(cap) : prettyCap(cap.name);
      const sel = !!this.o.isSel?.(cap), changed = !!this.o.changed?.(cap);
      const state = `${legends ? c : this.cache.get(k)?.split("|")[0]}|${label}|${sel}|${changed}`;
      if (this.cache.get(k) === state) return;
      this.cache.set(k, state);
      const lit = state.split("|")[0];
      k.classList.toggle("lit", lit !== "null" && lit !== "undefined");
      if (c && legends) { k.style.setProperty("--lit", mixWhite(c, 0.45)); k.style.setProperty("--lit-glow", c + "aa"); k.style.setProperty("--lit-rim", c + "66"); }
      k.querySelector(".lbl").textContent = label;
      k.classList.toggle("sel", sel);
      k.classList.toggle("changed", changed);
      k.title = this.o.title?.(cap) || "";
    });
    (this.edges || []).forEach(([i, seg]) => {
      const c = this.o.edgeColor?.(i) || "";
      if (seg._c !== c) { seg._c = c; seg.style.background = c || "#0006"; seg.style.boxShadow = c ? `0 0 8px ${c}, 0 0 2px ${c}` : ""; }
      seg.classList.toggle("sel", !!this.o.isEdgeSel?.(i));
    });
  }
  enableBox() {
    let start = null, box = null;
    this.board.addEventListener("mousedown", e => {
      const r = this.board.getBoundingClientRect();
      start = { x: e.clientX - r.left, y: e.clientY - r.top, add: e.shiftKey || e.ctrlKey };
      box = el("div", { class: "selbox" });
      this.board.append(box);
    });
    window.addEventListener("mousemove", e => {
      if (!start) return;
      const r = this.board.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      Object.assign(box.style, { left: Math.min(x, start.x) + "px", top: Math.min(y, start.y) + "px",
        width: Math.abs(x - start.x) + "px", height: Math.abs(y - start.y) + "px" });
    });
    window.addEventListener("mouseup", () => {
      if (!start) return;
      const b = box.getBoundingClientRect(), hits = [];
      for (const [cap, k] of this.keys) {
        const kr = k.getBoundingClientRect();
        if (kr.right > b.left && kr.left < b.right && kr.bottom > b.top && kr.top < b.bottom) hits.push(cap);
      }
      box.remove();
      const add = start.add;
      start = null;
      if (b.width > 4 || b.height > 4) this.o.boxSelect(hits, add);
      else if (!add) this.o.boxSelect([], false);
    });
  }
}
const PRETTY = { BACKSPACE: "Bksp", LBRACKET: "[", RBRACKET: "]", BACKSLASH: "\\", SEMICOLON: ";", QUOTE: "'",
  GRAVE: "`", MINUS: "-", EQUAL: "=", COMMA: ",", DOT: ".", SLASH: "/", LSHIFT: "Shift", RSHIFT: "Shift",
  LCTRL: "Ctrl", RCTRL: "Ctrl", LALT: "Alt", RALT: "Alt", WIN: "Win", SPACE: "", ENTER: "Enter",
  CAPS: "Caps", PAGEUP: "PgUp", PAGEDOWN: "PgDn", UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→", KNOB: "", DEL: "Del",
  ESC: "Esc", TAB: "Tab", HOME: "Home", END: "End", FN: "Fn" };
const prettyCap = n => (n in PRETTY ? PRETTY[n] : n.length === 1 ? n : n[0] + n.slice(1).toLowerCase());

/* ---------------- keycode labels ---------------- */
const MOD_BITS = [["Ctrl", 1], ["Shift", 2], ["Alt", 4], ["Win", 8]];
const SHORT = { "Hold Windows Fn": "Fn", "Hold Mac Fn": "Fn", LControl: "Ctrl", RControl: "Ctrl", LGUI: "Win", RGUI: "Win",
  LAlt: "Alt", RAlt: "Alt", LShift: "Shift", RShift: "Shift", Spacebar: "", "Caps Lock": "Caps", "Page Up": "PgUp",
  "Page Down": "PgDn", Backspace: "Bksp", Delete: "Del", Escape: "Esc", "Volume Up": "Vol +", "Volume Down": "Vol −",
  "Play/Pause": "Play", "Win lock": "Win lock", "Brightness Up": "Bright +", "Brightness Down": "Bright −" };
function kcLabel(v, short = false) {
  const k = S.kcByValue.get(v);
  if (k) return short && k.label in SHORT ? SHORT[k.label] : k.label;
  if (v >= 0x0100 && v <= 0x1fff) {
    const mods = (v >> 8) & 0x1f, base = S.kcByValue.get(v & 0xff);
    const names = MOD_BITS.filter(([, b]) => mods & b).map(([n]) => n);
    if (mods & 0x10) names.unshift("R");
    return [...names, base ? base.label : "?"].join("+");
  }
  return "0x" + v.toString(16).toUpperCase().padStart(4, "0");
}

/* ---------------- key picker (shared) ---------------- */
function buildPicker(host, { onPick, current = () => null, allowMods = true, filter = () => true }) {
  host.innerHTML = "";
  const head = el("div", { class: "picker-head" });
  const search = el("input", { placeholder: "Search keys, e.g. volume, ctrl, macro…", spellcheck: "false" });
  head.append(search);
  const modsRow = el("div", { class: "mods-row" });
  const mods = new Set();
  if (allowMods) {
    modsRow.append(el("span", { class: "quick-label" }, "Hold with"));
    for (const [n, b] of MOD_BITS) {
      const btn = el("button", { onclick: () => { mods.has(b) ? mods.delete(b) : mods.add(b); btn.classList.toggle("on"); } }, n);
      modsRow.append(btn);
    }
  }
  const groupsRow = el("div", { class: "groups" });
  const grid = el("div", { class: "kc-grid" });
  const list = S.keycodes.filter(filter);
  const groups = [...new Set(list.map(k => k.group))];
  let group = groups.includes("Letters") ? "Letters" : groups[0];
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    grid.innerHTML = "";
    $$("button", groupsRow).forEach(b => b.classList.toggle("on", !q && b.textContent === group));
    const cur = current();
    for (const k of list) {
      if (q ? !(k.label + " " + k.name + " " + (k.desc || "") + " " + k.group).toLowerCase().includes(q) : k.group !== group) continue;
      grid.append(el("div", { class: "kc" + (k.value === cur ? " cur" : ""), title: k.desc || k.name,
        onclick: () => {
          let v = k.value;
          const m = [...mods].reduce((a, b) => a | b, 0);
          if (m && v <= 0xff) v = (m << 8) | v;
          onPick(v, k);
        } }, k.label));
    }
  };
  for (const g of groups) groupsRow.append(el("button", { onclick: () => { group = g; search.value = ""; draw(); } }, g));
  search.addEventListener("input", draw);
  host.append(head, modsRow, groupsRow, grid);
  draw();
  return { redraw: draw, focus: () => search.focus() };
}
function openModal(build) {
  const m = $("#modal"), card = $("#modal-card");
  card.innerHTML = "";
  const close = () => m.classList.add("hidden");
  build(card, close);
  m.classList.remove("hidden");
  m.onclick = e => { if (e.target === m) close(); };
  return close;
}
function pickKeyModal(title, current, onPick, opts = {}) {
  openModal((card, close) => {
    card.append(el("div", { class: "row between" }, el("h2", {}, title), el("button", { class: "btn ghost", onclick: close }, "Close")));
    const host = el("div");
    card.append(host);
    buildPicker(host, { ...opts, current: () => current, onPick: (v, k) => { close(); onPick(v, k); } }).focus();
  });
}

/* ================= LIGHTING ================= */
const LT = { sel: new Set(), color: "#ff0000", kbright: 100, view: null, busy: false, busyTimer: null, dirty: false };
function markBusy() { LT.busy = true; clearTimeout(LT.busyTimer); LT.busyTimer = setTimeout(() => LT.busy = false, 2500); }
const QUICK = {
  wasd: ["W", "A", "S", "D"], arrows: ["UP", "DOWN", "LEFT", "RIGHT"],
  frow: ["ESC", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"],
  numbers: ["GRAVE", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "MINUS", "EQUAL"],
  mods: ["LSHIFT", "RSHIFT", "LCTRL", "RCTRL", "LALT", "RALT", "WIN", "FN", "CAPS", "TAB"],
};
const SWATCHES = ["#ff0000", "#ff5a00", "#ffb000", "#ffee00", "#7dff00", "#00ff6a", "#00ffe1", "#00a2ff", "#2b3bff", "#8a00ff",
  "#ff00d4", "#ff2a6d", "#ffffff", "#ffd7a8", "#a6e57f", "#5cc9a7", "#7a8cff", "#ff8fd8", "#444444", "#000000"];

function ledColor(i) { return S.state.perkey_enabled ? S.state.perkey[i] : null; }

/* --- live preview: QMK rgb_matrix effects re-implemented (rgb_matrix/animations/*.h) --- */
const u8 = v => ((Math.round(v) % 256) + 256) % 256;
const sin8 = t => Math.round(128 + 127 * Math.sin(u8(t) / 256 * 2 * Math.PI));
const cos8 = t => sin8(t + 64);
const atan2_8 = (y, x) => u8((Math.atan2(y, x) / (2 * Math.PI)) * 256);
const RAND = Array.from({ length: 128 }, (_, i) => (Math.sin(i * 12.9898) * 43758.5453) % 1);
function effectLed(i, ms) {
  const l = S.state.lighting;
  if (!l) return null;
  const name = S.state.effects[l.effect];
  const [x, y] = S.state.layout.points[i], dx = x - 112, dy = y - 32;
  const time = u8((ms * (Math.floor(l.speed / 4) + 1)) / 256);
  let h = l.hue, s = l.sat, v = 255;
  switch (name) {
    case "off": case "solid_reactive_simple": case "solid_reactive_nexus": case "multisplash": case "typing_heatmap":
      return null; // dark until keys are pressed
    case "solid_color": case "solid_reactive": break;
    case "breathing": v = Math.min(255, Math.abs(sin8((ms * Math.max(1, l.speed / 8)) / 256) - 128) * 2); break;
    case "cycle_all": h = time; break;
    case "cycle_left_right": h = x - time; break;
    case "cycle_up_down": h = y - time; break;
    case "rainbow_moving_chevron": h = h + Math.abs(dy) + x - time; break;
    case "cycle_out_in": h = 3 * Math.hypot(dx, dy) - time; break;
    case "cycle_out_in_dual": h = 3 * Math.hypot(56 - Math.abs(dx), dy) + time; break;
    case "cycle_pinwheel": h = atan2_8(dy, dx) + time; break;
    case "cycle_spiral": h = Math.hypot(dx, dy) - time - atan2_8(dy, dx); break;
    case "dual_beacon": h = h + (dy * cos8(time) + dx * sin8(time)) / 128 / 2; break;
    case "rainbow_beacon": h = h + (dy * cos8(time) + dx * sin8(time)) / 128; break;
    case "raindrops": h = h + RAND[i] * 64 + Math.sin(ms / 1500 + i) * 20; break;
    default: h = time;
  }
  return hsv2rgb(u8(h) / 255, s / 255, v / 255);
}
// Screen brightness: the keyboard's 0-255 value, lifted a little so dim settings stay readable.
const shade = (rgb, val) => rgb2hex(rgb.map(c => c * (0.25 + 0.75 * Math.sqrt(val / 255))));
function liveColor(i, ms) {
  const l = S.state.lighting, val = l ? l.brightness : 255;
  const own = ledColor(i);
  if (own) return own === "#000000" ? null : shade(hex2rgb(own), val);
  const fx = effectLed(i, ms);
  return fx ? shade(fx, val) : null;
}
let previewMs = 0, stageVisible = true;
const STATIC_EFFECTS = new Set(["off", "solid_color", "solid_reactive", "solid_reactive_simple", "solid_reactive_nexus", "multisplash", "typing_heatmap"]);
function previewAnimates() {
  const l = S.state.lighting;
  if (!l || STATIC_EFFECTS.has(S.state.effects[l.effect])) return false;
  // every LED has a custom color -> the effect is fully covered, nothing moves
  return !(S.state.perkey_enabled && Object.keys(S.state.perkey).length >= S.state.layout.led_count);
}
function previewLoop(now) {
  const active = S.page === "lighting" && LT.view && !document.hidden && stageVisible;
  if (active && previewAnimates()) { previewMs = now; LT.view.update(); }
  // ~24 fps while you're using the app, ~8 fps when it's visible but another window has focus
  const interval = active && previewAnimates() ? (document.hasFocus() ? 40 : 125) : 250;
  setTimeout(() => requestAnimationFrame(previewLoop), interval);
}
// Friendly names + what each animation actually uses (the firmware ignores color/speed for some).
const EFFECT_INFO = {
  off: ["Off"], solid_color: ["Static color", "color"], breathing: ["Breathing", "color speed"],
  cycle_all: ["Color cycle", "speed"], cycle_left_right: ["Rainbow wave →", "speed"], cycle_up_down: ["Rainbow wave ↓", "speed"],
  rainbow_moving_chevron: ["Chevron", "speed"], cycle_out_in: ["Rainbow tunnel", "speed"], cycle_out_in_dual: ["Dual tunnel", "speed"],
  cycle_pinwheel: ["Pinwheel", "speed"], cycle_spiral: ["Spiral", "speed"], dual_beacon: ["Dual beacon", "color speed"],
  rainbow_beacon: ["Rainbow beacon", "speed"], raindrops: ["Raindrops", "color speed"],
  typing_heatmap: ["Typing heatmap", "speed reactive"], solid_reactive_simple: ["Reactive", "color speed reactive"],
  solid_reactive: ["Reactive shift", "color speed reactive"], solid_reactive_nexus: ["Reactive cross", "color speed reactive"],
  multisplash: ["Splash", "color speed reactive"],
};
const effectName = name => (EFFECT_INFO[name] || [name.replace(/_/g, " ")])[0];
const effectUses = (name, what) => ((EFFECT_INFO[name] || [, "color speed"])[1] || "").includes(what);
const currentEffect = () => S.state.lighting && S.state.effects[S.state.lighting.effect];
const effectId = name => +Object.keys(S.state.effects).find(id => S.state.effects[id] === name);
const isAnimation = name => name && name !== "off" && name !== "solid_color";
const effectColorHex = () => { const l = S.state.lighting; return rgb2hex(hsv2rgb(l.hue / 255, l.sat / 255, 1)); };

/* "Unsaved" marker: live changes vanish on replug until saved to the keyboard */
function setDirty(on = true) { LT.dirty = on; $("#lt-save").classList.toggle("dirty", on); }

/* ---- per-key modes ----
   The keyboard runs one animation (the base effect) and a per-key overlay on top:
   no overlay color = Animated, black = Off, any other color = Static. */
const allLeds = () => [...Array(S.state.layout.led_count).keys()];
const targets = () => LT.sel.size ? [...LT.sel] : allLeds();   // nothing selected = whole keyboard
function keyMode(i) {
  const c = S.state.perkey_enabled ? S.state.perkey[i] : null;
  if (c) return c === "#000000" ? ["off"] : ["static", c];
  const fx = currentEffect();                     // legacy states, before the app normalized them
  if (fx === "off") return ["off"];
  if (fx === "solid_color") return ["static", effectColorHex()];
  return ["animated"];
}
function analyze(leds) {
  const counts = { static: 0, animated: 0, off: 0 }, colors = new Set();
  for (const i of leds) { const [m, c] = keyMode(i); counts[m]++; if (c) colors.add(c); }
  const modes = Object.keys(counts).filter(m => counts[m]);
  return { counts, mode: modes.length === 1 ? modes[0] : "mixed", color: colors.size === 1 ? [...colors][0] : null };
}
/* Bring old states (keyboard set to Off / Solid color, or overlay hidden) into the per-key model, looking the same. */
async function normalize() {
  if (!fwOurs()) return;                     // stock: nothing to convert (no per-key overlay)
  const fx = currentEffect();
  if (S.state.perkey_enabled && isAnimation(fx)) return;
  const colors = {};
  if (!S.state.perkey_enabled) {             // hidden overlay colors were invisible: forget them
    Object.assign(S.state, await api("/api/perkey", { clear: true }));
  }
  if (!isAnimation(fx)) {
    const c = fx === "off" ? "#000000" : effectColorHex();
    for (const i of allLeds()) if (!S.state.perkey[i]) colors[i] = c;
    await api("/api/lighting", { fields: { effect: LT.lastAnim ?? effectId("cycle_left_right") } });
    S.state.lighting.effect = LT.lastAnim ?? effectId("cycle_left_right");
  }
  Object.assign(S.state, await api("/api/perkey", { colors, enabled: true }));
}
async function applyToTargets(value) {   // value: hex (static), "#000000" (off) or null (animated)
  if (!fwOurs()) return applyWholeStock(value);
  markBusy();
  const leds = targets(), colors = {};
  for (const i of leds) { colors[i] = value; if (value) S.state.perkey[i] = value; else delete S.state.perkey[i]; }
  S.state.perkey_enabled = true;
  LT.view.update();
  await safe(async () => { await normalize(); Object.assign(S.state, await api("/api/perkey", { colors, enabled: true })); });
  setDirty(); refreshPanel(); LT.view.update();
}

/* Stock firmware has no per-key overlay: Static = the "solid color" effect, Off = the "off" effect,
   Animated = the last animation. keyMode() already reads those effects back as static / off. */
async function applyWholeStock(value) {
  markBusy();
  const f = {};
  if (value === "#000000") f.effect = effectId("off");
  else if (value) {
    const [h, s] = rgb2hsv(hex2rgb(value));
    Object.assign(f, { effect: effectId("solid_color"), hue: Math.round(h * 255), sat: Math.round(s * 255) });
  } else f.effect = isAnimation(S.state.effects[LT.lastAnim]) ? LT.lastAnim : effectId("cycle_left_right");
  Object.assign(S.state.lighting, f);
  setDirty(); renderEffects(); updateEffectUI(); refreshPanel(); LT.view.update();
  await safe(() => api("/api/lighting", { fields: f }));
}
function initLighting() {
  const host = $("#lt-kb");
  LT.view = new KeyboardView(host, {
    edge: true,
    color: cap => cap.led == null ? null : liveColor(cap.led, previewMs),
    edgeColor: i => liveColor(i, previewMs),
    isSel: cap => LT.sel.has(cap.led), isEdgeSel: i => LT.sel.has(i),
    label: cap => prettyCap(cap.name),
    onClick: (cap, e) => { if (cap.led == null) return; toggleSel([cap.led], e.shiftKey || e.ctrlKey); },
    onEdge: (i, e) => toggleSel([i], e.shiftKey || e.ctrlKey),
    boxSelect: (caps, add) => toggleSel(caps.map(c => c.led).filter(x => x != null), add, true),
  });
  new IntersectionObserver(es => { stageVisible = es[0].isIntersecting; }).observe(host);
  $$("#page-lighting .quick button").forEach(b => b.onclick = () => quickSelect(b.dataset.q));
  document.addEventListener("keydown", e => { if (e.key === "Escape" && S.page === "lighting" && LT.sel.size) { LT.sel.clear(); refreshSel(); } });
  for (const c of SWATCHES) $("#lt-swatches").append(el("i", { style: `background:${c}`, title: c, onclick: () => setColor(c, true) }));
  drawWheel();
  setColor(LT.color, false);
  $("#lt-hex").addEventListener("change", e => validHex(e.target.value) && setColor(normHex(e.target.value), true));
  $("#lt-kbright").addEventListener("input", e => { LT.kbright = +e.target.value; $("#lt-kbv").textContent = LT.kbright + "%"; updatePreview(); liveApply(); });
  $("#lt-save").onclick = saveLighting;
  $$("#lt-style button").forEach(b => b.onclick = () => chooseMode(b.dataset.style));
  // Reset menu
  const menu = $("#lt-reset-menu");
  $("#lt-reset").onclick = e => { e.stopPropagation(); menu.classList.toggle("hidden"); };
  document.addEventListener("click", () => menu.classList.add("hidden"));
  $$("#lt-reset-menu button").forEach(b => b.onclick = async () => {
    menu.classList.add("hidden");
    if (b.dataset.reset === "selected") {
      if (!LT.sel.size) return toast("Select some keys first");
      return applyToTargets(null);
    }
    await safe(async () => { await normalize(); Object.assign(S.state, await api("/api/perkey", { clear: true, enabled: true })); }, "All keys are animated again");
    setDirty(); refreshPanel(); LT.view.update();
  });
  // overall brightness + animation speed
  const send = throttle(fields => safe(() => api("/api/lighting", { fields })).then(updateEffectUI), 80);
  for (const [id, key, lbl] of [["#lt-bright", "brightness", "#lt-bv"], ["#lt-speed", "speed", "#lt-sv"]]) {
    $(id).addEventListener("input", e => {
      markBusy(); setDirty();
      S.state.lighting[key] = +e.target.value;
      $(lbl).textContent = Math.round(e.target.value / 2.55) + "%";
      LT.view.update();
      send({ [key]: +e.target.value });
    });
  }
  LT.sendEffectColor = throttle((hue, sat) => safe(() => api("/api/lighting", { fields: { hue, sat } })), 80);
  updatePreview();
  refreshPanel();
}
function selectionLeds() { return [...LT.sel]; }
// click: select only this; Shift/Ctrl+click: toggle; box: select (Shift/Ctrl box adds)
function toggleSel(leds, add, box = false) {
  if (stockFw()) return;                     // per-key needs our firmware
  if (!add) LT.sel.clear();
  for (const i of leds) {
    if (add && !box && LT.sel.has(i)) LT.sel.delete(i);
    else LT.sel.add(i);
  }
  refreshSel();
}
function quickSelect(q) {
  if (stockFw()) return;
  const L = S.state.layout;
  LT.sel.clear();
  if (q === "all") { for (let i = 0; i < L.led_count; i++) LT.sel.add(i); }
  else if (q === "letters") { for (const [n, i] of Object.entries(L.keys)) if (/^[A-Z]$/.test(n)) LT.sel.add(i); }
  else if (q === "edge") L.edge_leds.forEach(i => LT.sel.add(i));
  else if (QUICK[q]) QUICK[q].forEach(n => L.keys[n] != null && LT.sel.add(L.keys[n]));
  refreshSel();
}
function redrawBoard() { if (LT.view) LT.view.update(); }
function refreshSel() {
  LT.pendingMode = null;   // a new selection starts from what those keys actually do
  refreshPanel(true);
  LT.view.update();
}
/* What the panel shows: the selection's current mode, or the mode the user just picked for a mixed selection. */
function panelMode() { return LT.pendingMode || analyze(targets()).mode; }
function refreshPanel(selectionChanged) {
  const leds = targets(), a = analyze(leds), mode = panelMode(), fx = currentEffect();
  // title: what the buttons will act on
  const edge = leds.filter(i => S.state.layout.edge_leds.includes(i)).length, keys = leds.length - edge;
  $("#lt-target").textContent = !LT.sel.size ? "Whole keyboard" : leds.length === S.state.layout.led_count ? "All keys"
    : [keys && `${keys} key${keys > 1 ? "s" : ""}`, edge && `${edge} underglow light${edge > 1 ? "s" : ""}`].filter(Boolean).join(" + ");
  const parts = ["static", "animated", "off"].filter(m => a.counts[m]).map(m => `${a.counts[m]} ${m}`);
  $("#lt-summary").textContent = a.mode === "mixed" ? `Mixed: ${parts.join(" · ")}. Choose what these keys should do.`
    : a.mode === "static" ? (a.color ? "Static color" : "Static, in different colors") : a.mode === "animated" ? `Animated: ${effectName(fx || "")}` : "Off";
  $$("#lt-style button").forEach(b => b.classList.toggle("on", b.dataset.style === mode));

  // detail area
  const showStatic = mode === "static", showAnim = mode === "animated";
  const animColor = showAnim && isAnimation(fx) && effectUses(fx, "color");
  $("#lt-color-block").classList.toggle("hidden", !(showStatic || animColor));
  $("#lt-anim-block").classList.toggle("hidden", !showAnim);
  $("#lt-kbright-field").classList.toggle("hidden", !showStatic);
  $("#lt-color-label").textContent = showStatic ? "Color" : "Animation color";
  $("#lt-panel").classList.toggle("anim-only", showAnim && !animColor);
  const note = mode === "off" ? "These keys are dark. Choose Static or Animated to light them again."
    : mode === "mixed" ? "These keys do different things. Pick Static, Animated or Off above to set them all at once." : "";
  $("#lt-note").textContent = note;
  $("#lt-note").classList.toggle("hidden", !note);
  // never show a stale color: load what the selection really has
  const wheelOff = $("#lt-wheel-off");
  if (showStatic) {
    if (a.mode === "static" && a.color && (selectionChanged || !LT.busy)) {
      const [h, s, v] = rgb2hsv(hex2rgb(a.color));
      setColor(rgb2hex(hsv2rgb(h, s, 1)), false, Math.max(1, Math.round(v * 100)));
    }
    const differ = a.mode === "static" && !a.color && !LT.pendingColorSet;
    wheelOff.textContent = "These keys have different colors. Pick a color to set them all.";
    wheelOff.classList.toggle("hidden", !differ);
    wheelOff.classList.toggle("soft", differ);
  } else if (animColor) {
    wheelOff.classList.add("hidden");
    if (selectionChanged || !LT.busy) setColor(effectColorHex(), false);
  }
  if (showAnim) { renderEffects(); updateEffectUI(); }
}
async function chooseMode(mode) {
  const a = analyze(targets());
  if (mode === "animated") { LT.pendingMode = null; return applyToTargets(null); }
  if (mode === "off") { LT.pendingMode = null; return applyToTargets("#000000"); }
  // Static: already static → just show the picker; otherwise paint with the current picker color right away
  LT.pendingMode = null;
  if (a.mode === "static") return refreshPanel();
  LT.pendingColorSet = true;
  await applyToTargets(finalColor());
  LT.pendingColorSet = false;
}
function drawWheel() {
  const cv = $("#lt-wheel"), ctx = cv.getContext("2d"), r = cv.width / 2;
  const img = ctx.createImageData(cv.width, cv.height);
  for (let y = 0; y < cv.height; y++) for (let x = 0; x < cv.width; x++) {
    const dx = x - r, dy = y - r, d = Math.hypot(dx, dy) / r, o = (y * cv.width + x) * 4;
    if (d > 1) { img.data[o + 3] = 0; continue; }
    const [R, G, B] = hsv2rgb(((Math.atan2(dy, dx) / (2 * Math.PI)) + 1) % 1, d, 1);
    img.data.set([R, G, B, d > 0.985 ? 255 * (1 - d) / 0.015 : 255], o);
  }
  ctx.putImageData(img, 0, 0);
  let drag = false;
  const pick = e => {
    const b = cv.getBoundingClientRect(), rr = b.width / 2, dx = e.clientX - b.left - rr, dy = e.clientY - b.top - rr;
    const d = Math.min(1, Math.hypot(dx, dy) / rr);
    setColor(rgb2hex(hsv2rgb(((Math.atan2(dy, dx) / (2 * Math.PI)) + 1) % 1, d, 1)), true);
  };
  cv.addEventListener("mousedown", e => { drag = true; markBusy(); pick(e); });
  window.addEventListener("mousemove", e => { if (drag) { markBusy(); pick(e); } });
  window.addEventListener("mouseup", () => drag = false);
}
function setColor(hex, live, brightness) {
  LT.color = hex;
  if (brightness != null) { LT.kbright = brightness; $("#lt-kbright").value = brightness; $("#lt-kbv").textContent = brightness + "%"; rangeFill($("#lt-kbright")); }
  $("#lt-hex").value = hex;
  const [h, s] = rgb2hsv(hex2rgb(hex)), r = 110;
  const dot = $("#lt-wheel-dot");
  dot.style.left = r + Math.cos(h * 2 * Math.PI) * s * r + "px";
  dot.style.top = r + Math.sin(h * 2 * Math.PI) * s * r + "px";
  dot.style.background = hex;
  updatePreview();
  if (live) { $("#lt-wheel-off").classList.add("hidden"); liveApply(); }
}
function finalColor() {
  const c = rgb2hex(hex2rgb(LT.color).map(v => v * (panelMode() === "static" ? LT.kbright / 100 : 1)));
  return c === "#000000" ? "#010101" : c;   // pure black means "Off" in the overlay
}
function updatePreview() {
  const c = finalColor();
  $("#lt-preview").style.background = c;
  $("#lt-preview").style.setProperty("--pv", c + "88");
}
// Live: Static → recolor the target keys; Animated → change the animation's color.
const liveApply = throttle(() => {
  if (!wired()) return;
  const mode = panelMode();
  if (mode === "static") return applyToTargets(finalColor());
  const fx = currentEffect();
  if (mode !== "animated" || !isAnimation(fx) || !effectUses(fx, "color")) return;
  const [h, s] = rgb2hsv(hex2rgb(LT.color)), l = S.state.lighting;
  l.hue = Math.round(h * 255); l.sat = Math.round(s * 255);
  markBusy(); setDirty(); LT.view.update(); renderEffects();
  LT.sendEffectColor(l.hue, l.sat);
}, 70);
async function saveLighting() {
  await safe(async () => {
    await api("/api/lighting", { fields: S.state.lighting, save: true });
    if (fwOurs()) await api("/api/perkey", { save: true });
  }, "Saved to the keyboard. It keeps this lighting after unplugging and on 2.4G / Bluetooth.");
  setDirty(false);
}
async function setEffect(id) {
  const l = S.state.lighting;
  l.effect = +id;
  LT.lastAnim = +id;
  setDirty(); renderEffects(); updateEffectUI(); refreshPanel(); LT.view.update();
  await safe(async () => { await api("/api/lighting", { fields: { effect: +id } }); await normalize(); });
}
const EFFECT_PV = {
  breathing: "background:var(--ec);animation:breathe 2.4s ease-in-out infinite",
  typing_heatmap: "background:linear-gradient(90deg,#001,#00f,#0f0,#ff0,#f00);background-size:200%;animation:slide 4s linear infinite alternate",
  raindrops: "background:radial-gradient(circle at 20% 30%,var(--ec) 8%,transparent 9%),radial-gradient(circle at 70% 60%,var(--ec) 8%,transparent 9%),#111;animation:breathe 1.6s infinite",
};
function effectPreview(name) {
  if (EFFECT_PV[name]) return EFFECT_PV[name];
  if (name.startsWith("solid_reactive") || name.includes("splash"))
    return "background:radial-gradient(circle at 50% 50%,var(--ec) 10%,transparent 60%),#111;animation:breathe 1.2s ease-out infinite";
  const dir = name.includes("up_down") ? "180deg" : name.includes("out_in") || name.includes("beacon") || name.includes("pinwheel") || name.includes("spiral") ? "45deg" : "90deg";
  return `background:linear-gradient(${dir},#f00,#ff0,#0f0,#0ff,#00f,#f0f,#f00);background-size:200% 200%;animation:slide 3s linear infinite`;
}
function renderEffects() {
  const host = $("#lt-effects"), l = S.state.lighting;
  host.innerHTML = "";
  if (!l) return;
  const ec = effectColorHex();
  const groups = [["Animations", n => !effectUses(n, "reactive")], ["React to typing", n => effectUses(n, "reactive")]];
  for (const [title, test] of groups) {
    const grid = el("div", { class: "effects" });
    for (const [id, name] of Object.entries(S.state.effects)) {
      if (!isAnimation(name) || !test(name)) continue;
      grid.append(el("div", { class: "effect" + (+id === l.effect ? " on" : ""), style: `--ec:${ec}`,
        title: effectUses(name, "reactive") ? "Lights up as you type" : "", onclick: () => setEffect(id) },
        el("div", { class: "pv", style: effectPreview(name) }), effectName(name)));
    }
    host.append(el("div", { class: "effect-group" }, el("div", { class: "label mono" }, title), grid));
  }
}
let shownEffect = null;
function renderEffectsIfChanged() {
  const l = S.state.lighting;
  const key = l && `${l.effect}/${l.hue}/${l.sat}/${JSON.stringify(S.state.perkey).length}`;
  if (key !== shownEffect) { shownEffect = key; refreshPanel(); }
}
function updateEffectUI() {
  const l = S.state.lighting;
  if (!l) return;
  const fx = currentEffect();
  $("#lt-bright").value = l.brightness; $("#lt-bv").textContent = Math.round(l.brightness / 2.55) + "%";
  $("#lt-speed").value = l.speed; $("#lt-sv").textContent = Math.round(l.speed / 2.55) + "%";
  $("#lt-speed-field").classList.toggle("hidden", !isAnimation(fx) || !effectUses(fx, "speed"));
  $("#lt-reactive-note").classList.toggle("hidden", !fx || !effectUses(fx, "reactive"));
  $$("input[type=range]").forEach(rangeFill);
}
function updateModes() { /* per-key modes replaced the old "Keyboard shows" switch */ }
function showLighting() {
  updateEffectUI(); refreshPanel(); LT.view.update();
}

/* ================= KEYS ================= */
const KM = { layer: 0, cap: null, view: null, picker: null };
function initKeys() {
  for (const [i, n] of LAYERS.entries())
    $("#km-layers").append(el("button", { class: i === 0 ? "on" : "", onclick: e => {
      KM.layer = i; $$("#km-layers button").forEach(b => b.classList.toggle("on", b === e.target)); KM.view.update(); KM.picker?.redraw();
    } }, n));
  KM.view = new KeyboardView($("#km-kb"), {
    label: cap => S.keymap ? kcLabel(S.keymap[KM.layer][cap.row][cap.col], true) : "",
    title: cap => S.keymap ? `${prettyCap(cap.name)} → ${kcLabel(S.keymap[KM.layer][cap.row][cap.col])}` : "",
    isSel: cap => KM.cap === cap,
    changed: cap => S.keymap && KM.layer % 2 === 1 && S.keymap[KM.layer][cap.row][cap.col] > 1,
    onClick: cap => { KM.cap = cap; KM.view.update(); $("#km-title").textContent = `${LAYERS[KM.layer]} · ${prettyCap(cap.name) || cap.name}`; KM.picker.redraw(); },
  });
  const host = $("#km-picker");
  const title = $("#km-title");
  host.innerHTML = "";
  host.append(el("div", { class: "picker-head" }, title));
  const inner = el("div");
  host.append(inner);
  KM.picker = buildPicker(inner, {
    current: () => KM.cap && S.keymap ? S.keymap[KM.layer][KM.cap.row][KM.cap.col] : null,
    onPick: async v => {
      if (!KM.cap) return toast("Click a key on the keyboard first");
      const { row, col } = KM.cap;
      await safe(() => api("/api/key", { layer: KM.layer, row, col, keycode: v }), `${prettyCap(KM.cap.name) || KM.cap.name} → ${kcLabel(v)}`);
      S.keymap[KM.layer][row][col] = v;
      KM.view.update(); KM.picker.redraw();
    },
  });
  $("#km-reload").onclick = () => loadKeymap(true);
}
async function loadKeymap(force) {
  if (!wired() || (S.keymap && !force)) return;
  const r = await safe(() => api("/api/keymap"));
  S.keymap = r.keymap; S.encoders = r.encoders;
  KM.view?.update(); renderKnob(); MC.view?.update();
}

/* ================= MACROS ================= */
const MC = { slot: 0, slots: [], names: [], size: 0, view: null, rec: null, assignLayer: 1 };
const CODE2HID = (() => {
  const m = {};
  "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").forEach((c, i) => m["Key" + c] = 0x04 + i);
  "1234567890".split("").forEach((c, i) => m["Digit" + c] = 0x1e + i);
  Object.assign(m, { Enter: 0x28, Escape: 0x29, Backspace: 0x2a, Tab: 0x2b, Space: 0x2c, Minus: 0x2d, Equal: 0x2e,
    BracketLeft: 0x2f, BracketRight: 0x30, Backslash: 0x31, Semicolon: 0x33, Quote: 0x34, Backquote: 0x35, Comma: 0x36,
    Period: 0x37, Slash: 0x38, CapsLock: 0x39, PrintScreen: 0x46, ScrollLock: 0x47, Pause: 0x48, Insert: 0x49, Home: 0x4a,
    PageUp: 0x4b, Delete: 0x4c, End: 0x4d, PageDown: 0x4e, ArrowRight: 0x4f, ArrowLeft: 0x50, ArrowDown: 0x51, ArrowUp: 0x52,
    NumLock: 0x53, NumpadDivide: 0x54, NumpadMultiply: 0x55, NumpadSubtract: 0x56, NumpadAdd: 0x57, NumpadEnter: 0x58,
    NumpadDecimal: 0x63, ContextMenu: 0x65, ControlLeft: 0xe0, ShiftLeft: 0xe1, AltLeft: 0xe2, MetaLeft: 0xe3,
    ControlRight: 0xe4, ShiftRight: 0xe5, AltRight: 0xe6, MetaRight: 0xe7 });
  for (let i = 1; i <= 12; i++) m["F" + i] = 0x39 + i;
  for (let i = 1; i <= 9; i++) m["Numpad" + i] = 0x58 + i;
  m.Numpad0 = 0x62;
  return m;
})();
const basicKeys = () => S.keycodes.filter(k => k.value >= 4 && k.value <= 0xe7);
function stepBytes(s) {
  if (s.type === "text") return new TextEncoder().encode(s.text.replace(/[^\x09\x0a\x20-\x7e]/g, "")).length;
  if (s.type === "delay") return 3 + String(Math.round(s.ms || 0)).length;
  return 3;
}
const macroBytes = slots => slots.reduce((a, s) => a + s.reduce((b, st) => b + stepBytes(st), 0), 0) + slots.length;
function initMacros() {
  for (const [i, n] of LAYERS.entries()) $("#mc-layer").append(el("option", { value: i, selected: i === 1 }, n));
  $("#mc-layer").onchange = e => { MC.assignLayer = +e.target.value; MC.view.update(); };
  MC.view = new KeyboardView($("#mc-kb"), {
    maxUnit: 40,
    label: cap => S.keymap ? kcLabel(S.keymap[MC.assignLayer][cap.row][cap.col], true) : prettyCap(cap.name),
    isSel: cap => S.keymap && S.keymap[MC.assignLayer][cap.row][cap.col] === 0x7700 + MC.slot,
    onClick: async cap => {
      if (!S.keymap) return toast("Plug in the keyboard (wired) to assign macros", true);
      await safe(() => api("/api/key", { layer: MC.assignLayer, row: cap.row, col: cap.col, keycode: 0x7700 + MC.slot }),
        `${LAYERS[MC.assignLayer]} · ${prettyCap(cap.name) || cap.name} now plays "${MC.names[MC.slot] || "Macro " + MC.slot}"`);
      S.keymap[MC.assignLayer][cap.row][cap.col] = 0x7700 + MC.slot;
      MC.view.update(); KM.view?.update();
    },
  });
  $("#mc-name").addEventListener("input", e => { MC.names[MC.slot] = e.target.value; renderSlots(); });
  $$("[data-add]").forEach(b => b.onclick = () => addStep(b.dataset.add));
  $("#mc-clear").onclick = () => { MC.slots[MC.slot] = []; renderSteps(); };
  $("#mc-save").onclick = saveMacros;
  $("#mc-record").onclick = toggleRecord;
}
async function loadMacros(force) {
  if (!wired() || (MC.loaded && !force)) return;
  const r = await safe(() => api("/api/macros"));
  Object.assign(MC, { slots: r.slots, names: r.names, size: r.size, loaded: true });
  renderSlots(); renderSteps();
}
function renderSlots() {
  const host = $("#mc-slots");
  host.innerHTML = "";
  MC.slots.forEach((s, i) => host.append(el("div", { class: "slot" + (i === MC.slot ? " on" : ""), onclick: () => { MC.slot = i; renderSlots(); renderSteps(); MC.view.update(); } },
    el("span", {}, MC.names[i] || `Macro ${i}`), el("small", {}, s.length ? `${s.length} step${s.length > 1 ? "s" : ""}` : "empty"))));
  const used = macroBytes(MC.slots);
  $("#mc-meter").style.width = Math.min(100, used / MC.size * 100) + "%";
  $("#mc-meter-label").textContent = `${used} / ${MC.size} bytes`;
}
function keySelect(value, onChange) {
  const s = el("select", { onchange: e => onChange(+e.target.value) });
  for (const k of basicKeys()) s.append(el("option", { value: k.value, selected: k.value === value }, `${k.label}  (${k.group})`));
  return s;
}
function renderSteps() {
  $("#mc-name").value = MC.names[MC.slot] || "";
  const host = $("#mc-steps"), steps = MC.slots[MC.slot] || [];
  host.innerHTML = "";
  if (!steps.length) host.append(el("div", { class: "empty" }, "No steps yet — record or add some below."));
  steps.forEach((st, i) => {
    const row = el("div", { class: "step" });
    const tagName = { text: "Type", tap: "Press", down: "Hold", up: "Release", delay: "Wait" }[st.type];
    row.append(el("span", { class: "tag" }, tagName));
    if (st.type === "text") row.append(el("input", { value: st.text, placeholder: "Text to type", oninput: e => { st.text = e.target.value; renderSlots(); } }));
    else if (st.type === "delay") row.append(el("input", { type: "number", min: 0, max: 60000, value: st.ms, oninput: e => { st.ms = +e.target.value; renderSlots(); } }), el("span", { class: "muted" }, "ms"));
    else {
      row.append(keySelect(st.key, v => st.key = v));
      const kind = el("select", { onchange: e => { st.type = e.target.value; renderSteps(); } },
        ...["tap", "down", "up"].map(t => el("option", { value: t, selected: st.type === t }, { tap: "press + release", down: "hold down", up: "release" }[t])));
      kind.style.flex = "0 0 150px";
      row.append(kind);
    }
    row.append(el("button", { class: "mv", title: "Move up", onclick: () => { if (i) { [steps[i - 1], steps[i]] = [steps[i], steps[i - 1]]; renderSteps(); } } }, "↑"),
      el("button", { class: "x", title: "Remove", onclick: () => { steps.splice(i, 1); renderSteps(); renderSlots(); } }, "×"));
    host.append(row);
  });
  renderSlots();
}
function addStep(type) {
  const steps = MC.slots[MC.slot] || (MC.slots[MC.slot] = []);
  if (type === "text") steps.push({ type: "text", text: "" });
  else if (type === "tap") steps.push({ type: "tap", key: 0x28 });
  else if (type === "delay") steps.push({ type: "delay", ms: 100 });
  else if (type === "combo") {
    pickKeyModal("Pick the shortcut (choose modifiers with “Hold with”)", null, v => {
      const mods = (v >> 8) & 0x1f, key = v & 0xff, hold = [];
      MOD_BITS.forEach(([, b], i) => { if (mods & b) hold.push((mods & 0x10 ? 0xe4 : 0xe0) + i); });
      hold.forEach(m => steps.push({ type: "down", key: m }));
      steps.push({ type: "tap", key });
      hold.reverse().forEach(m => steps.push({ type: "up", key: m }));
      renderSteps();
    }, { filter: k => k.value >= 4 && k.value <= 0xe7 });
    return;
  }
  renderSteps();
}
function toggleRecord() {
  const btn = $("#mc-record");
  if (MC.rec) {
    window.removeEventListener("keydown", MC.rec.down, true);
    window.removeEventListener("keyup", MC.rec.up, true);
    const ev = MC.rec.events;
    MC.rec = null;
    btn.classList.remove("on"); btn.textContent = "Record";
    // compress: down X immediately followed by up X -> tap X
    const steps = [];
    for (let i = 0; i < ev.length; i++) {
      const e = ev[i], n = ev[i + 1];
      if (e.delay > 40) steps.push({ type: "delay", ms: Math.min(5000, Math.round(e.delay / 10) * 10) });
      if (e.type === "down" && n && n.type === "up" && n.key === e.key && n.delay <= 400) { steps.push({ type: "tap", key: e.key }); i++; }
      else steps.push({ type: e.type, key: e.key });
    }
    MC.slots[MC.slot] = (MC.slots[MC.slot] || []).concat(steps);
    renderSteps();
    toast(`Recorded ${steps.length} steps — remember to Save`);
    return;
  }
  const rec = { events: [], last: 0, held: new Set() };
  const push = (type, e) => {
    const key = CODE2HID[e.code];
    if (!key) return;
    e.preventDefault(); e.stopPropagation();
    if (type === "down" && rec.held.has(key)) return; // auto-repeat
    type === "down" ? rec.held.add(key) : rec.held.delete(key);
    const now = performance.now();
    rec.events.push({ type, key, delay: rec.last ? now - rec.last : 0 });
    rec.last = now;
  };
  rec.down = e => push("down", e);
  rec.up = e => push("up", e);
  window.addEventListener("keydown", rec.down, true);
  window.addEventListener("keyup", rec.up, true);
  MC.rec = rec;
  btn.classList.add("on"); btn.textContent = "Stop recording";
  toast("Recording… type your macro, then press Stop");
}
async function saveMacros() {
  if (macroBytes(MC.slots) > MC.size) return toast("Macros are too long for the keyboard's memory", true);
  const r = await safe(() => api("/api/macros", { slots: MC.slots, names: MC.names }), "Macros saved to keyboard");
  if (r) renderSlots();
}

/* ================= KNOB ================= */
function renderKnob() {
  const host = $("#kn-grid");
  host.innerHTML = "";
  if (!S.encoders || !S.keymap) { host.append(el("div", { class: "card empty" }, "Plug in the keyboard (wired) to edit the knob.")); return; }
  const knob = S.state.layout.caps.find(c => c.name === "KNOB");
  LAYERS.forEach((name, l) => {
    const enc = S.encoders[l];
    const act = (label, value, set) => el("div", { class: "knob-act" }, el("span", { class: "muted" }, label),
      el("button", { class: "btn", onclick: () => pickKeyModal(`${name} · ${label}`, value, set) }, kcLabel(value)));
    host.append(el("div", { class: "card knob-card" }, el("h2", {}, name, el("span", { class: "muted" }, l % 2 ? "while holding Fn" : "")),
      act("Turn right ⟳", enc.cw, async v => { await safe(() => api("/api/encoder", { layer: l, clockwise: true, keycode: v }), "Knob updated"); enc.cw = v; renderKnob(); }),
      act("Turn left ⟲", enc.ccw, async v => { await safe(() => api("/api/encoder", { layer: l, clockwise: false, keycode: v }), "Knob updated"); enc.ccw = v; renderKnob(); }),
      act("Press", S.keymap[l][knob.row][knob.col], async v => {
        await safe(() => api("/api/key", { layer: l, row: knob.row, col: knob.col, keycode: v }), "Knob updated");
        S.keymap[l][knob.row][knob.col] = v; renderKnob(); KM.view?.update();
      })));
  });
}

/* ================= REACTIONS ================= */
const RX = { cfg: null };
/* App picker (Reactions + auto profiles): installed apps from the Start menu + apps with a window open,
   or Browse… to choose any .exe. Rules store the program name (e.g. Steam.exe), which is what Windows reports. */
const APPS = { list: [], byExe: {}, loaded: null };
function loadApps() {
  return APPS.loaded ||= api("/api/apps").catch(() => []).then(list => {
    APPS.list = list;
    APPS.byExe = Object.fromEntries(list.map(a => [a.exe.toLowerCase(), a]));
    let dl = $("#app-list");
    if (!dl) document.body.append(dl = el("datalist", { id: "app-list" }));
    dl.replaceChildren(...list.map(a => el("option", { value: a.exe, label: a.name + (a.running ? "  · open now" : "") })));
    setTimeout(() => APPS.loaded = null, 60000);   // refresh the list now and then
  });
}
function toExe(text) {
  const t = text.trim();
  if (!t) return null;
  const byName = APPS.list.find(a => a.name.toLowerCase() === t.toLowerCase());
  if (byName) return byName.exe;
  return /[.*?]/.test(t) ? t : t + ".exe";        // "steam" → "steam.exe"; wildcards kept as-is
}
function appChip(app, onRemove) {
  const known = APPS.byExe[app.toLowerCase()];
  return el("span", { class: "chip", title: app }, known ? known.name : app, el("button", { onclick: onRemove, title: "Remove" }, "×"));
}
function appPicker(onAdd, placeholder = "add an app") {
  const input = el("input", { list: "app-list", placeholder, style: "width:190px",
    onchange: e => { const exe = toExe(e.target.value); if (exe) onAdd(exe); } });
  const file = el("input", { type: "file", accept: ".exe", hidden: true,
    onchange: e => { const f = e.target.files[0]; if (f) onAdd(f.name); } });
  return el("span", { class: "row gap app-picker" }, input,
    el("button", { class: "btn ghost", title: "Choose a program (.exe) in File Explorer", onclick: () => file.click() }, "Browse…"), file);
}
const ANIMS = { firmware: "Built-in effect", pulse: "Pulse a color", flash: "Flash a color", hue_sweep: "Rainbow sweep", static: "Static scene" };
async function loadReactions() {
  RX.cfg = await safe(() => api("/api/rules"));
  await loadApps();
  renderReactions();
}
function effectSelect(value, onChange) {
  const s = el("select", { onchange: e => onChange(S.state.effects[e.target.value]) });
  for (const [id, n] of Object.entries(S.state.effects)) s.append(el("option", { value: id, selected: n === value || +id === value }, n.replace(/_/g, " ")));
  return s;
}
const colorInput = (value, onChange) => el("input", { type: "color", value: value || "#ff0000", oninput: e => onChange(e.target.value), style: "width:46px;padding:2px" });
const numInput = (value, min, max, onChange, w = 80) => el("input", { type: "number", min, max, value, style: `width:${w}px`, oninput: e => onChange(+e.target.value) });
function renderReactions() {
  const cfg = RX.cfg;
  cfg.rules ||= [];
  const list = $("#rx-list");
  list.innerHTML = "";
  if (!cfg.rules.length) list.append(el("div", { class: "card empty" }, "No reactions yet. Click New reaction to make one, or ? above for how it works."));
  cfg.rules.forEach((r, i) => {
    const a = r.animation || (r.animation = { type: "flash", color: "#ffffff" });
    const chips = el("div", { class: "chips" }, ...(r.apps || []).map((app, j) => appChip(app, () => { r.apps.splice(j, 1); renderReactions(); })));
    const add = appPicker(exe => { (r.apps ||= []).push(exe); renderReactions(); });
    const params = el("span", { class: "row gap" });
    if (a.type === "firmware") params.append(effectSelect(a.effect, v => a.effect = v), el("span", { class: "muted" }, "speed"), numInput(a.speed ?? 200, 0, 255, v => a.speed = v));
    if (["pulse", "flash"].includes(a.type)) params.append(colorInput(a.color, v => a.color = v));
    if (a.type === "static") { a.state ||= { effect: "solid_color", color: "#ff0030" }; params.append(effectSelect(a.state.effect, v => a.state.effect = v), colorInput(a.state.color, v => a.state.color = v)); }
    const typeSel = el("select", { onchange: e => { r.animation = { type: e.target.value, priority: a.priority ?? 60 }; if (e.target.value === "firmware") Object.assign(r.animation, { effect: "cycle_spiral", speed: 220 }); if (["pulse", "flash"].includes(e.target.value)) r.animation.color = "#00a2ff"; renderReactions(); } },
      ...Object.entries(ANIMS).map(([k, n]) => el("option", { value: k, selected: k === a.type }, n)));
    const when = el("select", { onchange: e => { r.when = e.target.value; renderReactions(); } },
      el("option", { value: "app_launch", selected: r.when === "app_launch" }, "launches"),
      el("option", { value: "foreground", selected: r.when === "foreground" }, "is the active window"));
    const ready = r.when === "app_launch" ? el("label", { class: "row gap muted" },
      el("input", { type: "checkbox", checked: !!r.on_ready, onchange: e => { r.on_ready = e.target.checked ? { type: "flash", color: "#00ff40", count: 2 } : undefined; } }), "flash green when loaded") : null;
    list.append(el("div", { class: "card rx" },
      el("div", {},
        el("input", { class: "title-input", value: r.name || "", placeholder: "Reaction name", oninput: e => r.name = e.target.value, style: "margin-bottom:10px" }),
        el("div", { class: "rx-body" }, el("span", { class: "word" }, "When"), chips, add, when),
        el("div", { class: "rx-body", style: "margin-top:10px" }, el("span", { class: "word" }, "play"), typeSel, params, ready)),
      el("div", {}, el("button", { class: "btn ghost danger", onclick: () => { cfg.rules.splice(i, 1); renderReactions(); } }, "Delete"))));
  });
}
function initReactions() {
  $("#rx-add").onclick = () => { RX.cfg.rules.push({ name: "New reaction", when: "app_launch", apps: [], min_seconds: 1, timeout: 45, animation: { type: "firmware", effect: "cycle_spiral", speed: 220, brightness: 200, priority: 60 } }); renderReactions(); };
  $("#rx-save").onclick = () => safe(() => api("/api/rules", RX.cfg), "Reactions saved");
}

/* ================= PROFILES ================= */
async function loadProfiles() {
  const names = await safe(() => api("/api/profiles"));
  const host = $("#pf-list");
  host.innerHTML = "";
  if (!names.length) host.append(el("div", { class: "card empty" }, "No profiles yet — set things up how you like, then “Save current”."));
  PF.names = names;
  for (const n of names) host.append(el("div", { class: "card profile" + (S.state.active_profile === n ? " active" : "") },
    el("h2", {}, n, S.state.active_profile === n ? el("span", { class: "badge" }, "active") : null),
    el("div", { class: "row gap" },
      el("button", { class: "btn primary needs-cable", onclick: () => safe(async () => { await api("/api/profiles/apply", { name: n }); await refreshAll(true); }, `“${n}” applied`) }, "Apply"),
      el("button", { class: "btn ghost needs-cable", onclick: () => safe(() => api("/api/profiles/save", { name: n }), `“${n}” updated`) }, "Overwrite"),
      el("button", { class: "btn ghost danger", onclick: async () => { if (confirm(`Delete profile “${n}”?`)) { await safe(() => api("/api/profiles/delete", { name: n })); loadProfiles(); } } }, "Delete"))));
}
const PF = { names: [], auto: null };
async function loadAutoProfiles() {
  PF.auto = await safe(() => api("/api/autoprofiles"));
  await loadApps();
  renderAutoProfiles();
}
function profileSelect(value, onChange, allowNone) {
  const s = el("select", { onchange: e => onChange(e.target.value || null) });
  if (allowNone) s.append(el("option", { value: "" }, "— keep current lighting —"));
  for (const n of PF.names) s.append(el("option", { value: n, selected: n === value }, n));
  return s;
}
function renderAutoProfiles() {
  const a = PF.auto;
  if (!a) return;
  $("#ap-enabled").checked = a.enabled;
  $("#ap-default").replaceWith(Object.assign(profileSelect(a.default, v => a.default = v, true), { id: "ap-default" }));
  const host = $("#ap-rules");
  host.innerHTML = "";
  if (!PF.names.length) host.append(el("p", { class: "hint" }, "Save at least one profile above first."));
  a.rules.forEach((r, i) => {
    host.append(el("div", { class: "auto-rule" },
      el("span", { class: "muted" }, "When"),
      el("div", { class: "chips" }, ...r.apps.map((app, j) => appChip(app, () => { r.apps.splice(j, 1); renderAutoProfiles(); }))),
      appPicker(exe => { r.apps.push(exe); renderAutoProfiles(); }, "add an app"),
      el("span", { class: "muted" }, "is focused, use"),
      profileSelect(r.profile, v => r.profile = v),
      el("button", { class: "btn ghost danger", onclick: () => { a.rules.splice(i, 1); renderAutoProfiles(); } }, "Remove")));
  });
}
function initProfiles() {
  $("#ap-enabled").onchange = e => PF.auto && (PF.auto.enabled = e.target.checked);
  $("#ap-add").onclick = () => {
    if (!PF.names.length) return toast("Save a profile first", true);
    PF.auto.rules.push({ apps: [], profile: PF.names[0] });
    renderAutoProfiles();
  };
  $("#ap-save").onclick = async () => {
    const empty = PF.auto.rules.find(r => !r.apps.length);
    if (empty) return toast("Each rule needs at least one app", true);
    PF.auto = await safe(() => api("/api/autoprofiles", PF.auto), PF.auto.enabled ? "Automatic switching is on" : "Saved (automatic switching is off)");
    renderAutoProfiles();
  };
  $("#pf-save").onclick = async () => {
    const n = $("#pf-name").value.trim();
    if (!n) return toast("Give the profile a name", true);
    await safe(() => api("/api/profiles/save", { name: n }), `Saved “${n}”`);
    $("#pf-name").value = "";
    loadProfiles();
  };
}

/* ================= DEVICE ================= */
function renderDevice() {
  const fw = S.state.firmware;
  const rows = [["Connection", { wired: "Wired (USB cable)", wireless: "Wireless (2.4G dongle) — plug in to edit", disconnected: "Not found" }[S.connection]],
    ["USB ID", "FFFE:001B (Inland V83P)"], ["Firmware", fw ? `release ${fw.release}` : "—"],
    ["Per-key RGB", fw ? (fw.mykeys ? `yes (protocol v${fw.protocol})` : "needs the V83P Studio firmware") : "—"],
    ["LEDs", `${S.state.layout.led_count} (82 keys + ${S.state.layout.edge_leds.length} edge)`], ["Layers", "4 (Windows, Windows Fn, Mac, Mac Fn)"]];
  $("#dv-info").replaceChildren(el("h2", {}, "Keyboard"), el("div", { class: "kv" }, ...rows.flatMap(([k, v]) => [el("div", {}, k), el("div", {}, v)])));
  renderFirmwareCard();
  if (window.mykeysApp) {
    $("#dv-app").classList.remove("hidden");
    window.mykeysApp.getAutoStart().then(on => $("#dv-autostart").checked = on);
  }
}
function initDevice() {
  const sel = $("#dv-colorway");
  if (sel) {
    sel.replaceChildren(...Object.entries(colorways()).map(([id, cw]) => el("option", { value: id }, cw.name)));
    sel.value = CW.id;
    sel.onchange = e => applyColorway(e.target.value);
  }
  $("#dv-autostart").onchange = async e => {
    const on = await window.mykeysApp.setAutoStart(e.target.checked);
    e.target.checked = on;
    toast(on ? "V83P Studio will start with Windows (in the tray)" : "Won't start with Windows");
  };
}

/* ================= FIRMWARE (Device page card + wizard) ================= */
const setKids = (node, ...a) => node.replaceChildren(...a.filter(x => x != null && x !== false));  // skips null (would print "null")
const FW = { info: null, open: false, update: null, loading: null };
const fwJobActive = () => ["starting", "driver", "bootloader", "backup", "flashing", "replug"].includes(S.state?.flash?.step);
const FW_STEPS = [["driver", "Driver"], ["bootloader", "Flash mode"], ["backup", "Backup"], ["flashing", "Write"], ["replug", "Replug"]];
function fwInfo(force) {
  if (force || !FW.loading) FW.loading = api("/api/firmware").then(i => (FW.info = i)).catch(() => FW.info);
  return FW.loading;
}
function fwVersion(release) {             // "0220" → "2.2.0"
  return release && /^\d{4}$/.test(release) ? `${+release[0] * 10 + +release[1]}.${release[2]}.${release[3]}` : release;
}
function renderFirmwareCard() {
  const host = $("#dv-fw");
  if (!host) return;
  if (!FW.info) { fwInfo().then(() => FW.info && renderFirmwareCard()); return; }
  const fw = S.state.firmware, b = FW.info.bundled || {}, wiredNow = S.connection === "wired";
  const ours = fw?.mykeys, current = ours && fw.release === b.release;
  let line, action, label;
  if (fwJobActive()) {
    line = "A firmware update is in progress."; label = "Show progress"; action = () => openFirmwareWizard(null, true);
  } else if (S.connection === "flashing") {
    line = "The keyboard is in flash mode (its lights are off). Unplug the cable and plug it back in to start it normally.";
  } else if (!fw) {
    line = "Plug the keyboard in with the cable (switch on wired) to check its firmware.";
  } else if (!ours) {
    line = "Your keyboard has its original (stock) firmware. Install the V83P Studio firmware for per-key colors, music mode and reactions.";
    label = `Install firmware ${b.version || ""}`; action = () => openFirmwareWizard("install");
  } else if (!current) {
    line = `V83P Studio firmware ${fwVersion(fw.release)} is installed. Version ${b.version} is available, and updating keeps your settings.`;
    label = `Update to ${b.version}`; action = () => openFirmwareWizard("install");
  } else {
    line = `V83P Studio firmware ${b.version} is installed and up to date.`;
  }
  const backups = FW.info.backups || [];
  setKids(host, 
    el("div", { class: "card-head" }, el("h2", {}, "Firmware")),
    el("p", { class: "hint fw-line" }, line),
    el("div", { class: "row gap wrap" },
      label ? el("button", { class: "btn primary", onclick: action }, label) : null,
      current && wiredNow ? el("button", { class: "btn ghost", onclick: () => openFirmwareWizard("install") }, "Reinstall") : null,
      el("button", { class: "btn ghost", onclick: openRestorePicker, disabled: !backups.length,
        title: backups.length ? "Put a saved firmware (e.g. the original) back on the keyboard" : "No backups yet. The first install makes one." }, "Restore a backup…")),
    !FW.info.tools ? el("p", { class: "hint warn-text" }, "The flash tool is missing from this install, so firmware can't be changed.") : null);
}
function openRestorePicker() {
  openModal((card, close) => {
    card.classList.add("fw-modal");
    card.append(el("div", { class: "row between" }, el("h2", {}, "Restore a backup"), el("button", { class: "btn ghost", onclick: close }, "Close")),
      el("p", { class: "hint" }, "Puts a saved firmware back on the keyboard, for example its original firmware. Settings may reset."),
      el("div", { class: "fw-backups" }, ...(FW.info.backups || []).map(bk => el("div", { class: "fw-backup" },
        el("div", {}, el("b", { class: "mono" }, bk.name), el("small", { class: "muted" }, bk.date)),
        el("button", { class: "btn", onclick: () => { close(); openFirmwareWizard("restore", false, bk.name); } }, "Restore")))),
      el("button", { class: "btn ghost small", style: "margin-top:12px", onclick: () => api("/api/firmware/open-backups", {}).catch(() => {}) }, "Open backups folder"));
  });
}
function openFirmwareWizard(action, resume, backup) {
  const fw = S.state.firmware, b = FW.info?.bundled || {}, stock = !fw?.mykeys;
  FW.open = true;
  openModal((card, close) => {
    card.classList.add("fw-modal");
    const done = () => { FW.open = false; FW.update = null; close(); fwInfo(true).then(renderFirmwareCard); };
    const body = el("div");
    card.append(body);
    const confirmView = () => {
      const restore = action === "restore";
      const same = !stock && fw?.release === b.release;
      const title = restore ? "Restore a backup" : stock ? `Install V83P Studio firmware ${b.version || ""}`
        : same ? `Reinstall firmware ${b.version || ""}` : `Update to firmware ${b.version || ""}`;
      const points = restore ? [
        `The keyboard gets the firmware saved in ${backup}.`,
        "If it's the original firmware, per-key colors, music mode and reactions stop working until you install again.",
        "The keyboard switches to flash mode by itself. If it can't, you'll be asked to hold Esc while plugging it in.",
      ] : stock ? [
        "First, the keyboard's original firmware is backed up to this PC, so you can go back any time.",
        "Your keyboard's settings (lighting, remapped keys, macros, knob) reset to defaults once.",
        "You'll unplug the cable, then hold Esc while plugging it back in. The app tells you when.",
        "Windows may ask once for permission to install the flash-mode driver.",
        "Takes about a minute. Use the cable, and keep it plugged in while the firmware is written.",
      ] : [
        "Your settings are kept.",
        "The keyboard switches to flash mode by itself, so you only replug the cable at the end.",
        "Takes under a minute.",
      ];
      const ok = el("input", { type: "checkbox", onchange: e => go.disabled = !e.target.checked });
      const go = el("button", { class: "btn primary", disabled: stock && !restore, onclick: start }, restore ? "Restore" : stock ? "Install" : same ? "Reinstall" : "Update");
      setKids(body, 
        el("div", { class: "eyebrow mono" }, "Firmware"), el("h2", { class: "fw-title" }, title),
        el("ul", { class: "fw-points" }, ...points.map(t => el("li", {}, t))),
        stock && !restore ? el("label", { class: "fw-ack" }, ok, "I understand that this changes my keyboard's firmware, and that I use it at my own risk.") : null,
        el("div", { class: "row gap fw-actions" }, el("button", { class: "btn ghost", onclick: done }, "Cancel"), go));
    };
    async function start() {
      try { S.state.flash = await api("/api/firmware/start", { action, backup }); }
      catch (e) { toast(e.message, true); return; }
      FW.update = progressView;                 // from now on, follow the job's progress
      progressView(S.state.flash);
    }
    const progressView = st => {
      st ||= { step: "starting", message: "Starting…" };
      const order = FW_STEPS.map(s => s[0]), idx = order.indexOf(st.step);
      const finished = st.step === "done", failed = st.step === "error", idle = st.step === "idle";
      const steps = el("ol", { class: "fw-steps" }, ...FW_STEPS.filter(([k]) => !(k === "backup" && st.action === "restore")).map(([k, n]) => {
        const i = order.indexOf(k);
        const cls = finished || (idx > i && idx >= 0) ? "done" : k === st.step ? (failed ? "fail" : "now") : "";
        return el("li", { class: cls }, el("i", {}), n);
      }));
      const manual = st.step === "bootloader" && st.manual
        ? el("div", { class: "fw-manual" }, el("div", { class: "fw-keycap" }, "Esc"),
            el("ol", {}, el("li", {}, "Unplug the keyboard's USB cable."), el("li", {}, "Hold down Esc."), el("li", {}, "Plug the cable back in while still holding Esc."), el("li", {}, "Let go after 2 seconds.")),
            el("p", { class: "hint" }, "The keys stay dark in flash mode. That's normal."))
        : st.step === "replug" ? el("div", { class: "fw-manual" }, el("div", { class: "fw-keycap plug" }, "USB"),
            el("p", {}, "Unplug the cable, wait a second, and plug it back in. (No need to hold anything.)")) : null;
      const canCancel = ["starting", "driver", "bootloader", "replug"].includes(st.step);
      setKids(body, 
        el("div", { class: "eyebrow mono" }, "Firmware"),
        el("h2", { class: "fw-title" }, finished ? "All done" : failed ? "That didn't work" : idle ? "Cancelled" : "Working on it…"),
        steps,
        el("p", { class: "fw-msg" + (failed ? " bad" : finished ? " good" : "") }, st.message || ""),
        manual,
        st.backup ? el("p", { class: "hint" }, `Original firmware saved as ${st.backup}. Restore it from the Firmware card at any time.`) : null,
        el("div", { class: "row gap fw-actions" },
          canCancel ? el("button", { class: "btn ghost", onclick: () => api("/api/firmware/cancel", {}).catch(() => {}) }, "Cancel") : null,
          finished || failed || idle ? el("button", { class: "btn primary", onclick: done }, "Close")
            : st.step === "flashing" ? el("span", { class: "muted" }, "Don't unplug the keyboard.")
            : el("button", { class: "btn ghost", onclick: () => { FW.open = false; FW.update = null; close(); } }, "Hide")));
    };
    if (resume) { FW.update = progressView; progressView(S.state.flash); } else confirmView();
  });
  $("#modal").onclick = null;                 // no closing by a stray click outside while flashing
}

/* ================= MUSIC ================= */
const MU = { cfg: null, view: null, frame: [], bands: [], timer: null, send: null };
const MU_STYLES = {
  spectrum: ["Spectrum", "Bars rise up each column with its frequency. Best on this board.",
    "background:linear-gradient(0deg,var(--a) 0 30%,transparent 30%) 0 0/12.5% 100%,linear-gradient(0deg,var(--b) 0 70%,transparent 70%) 6.25% 0/12.5% 100%,#111"],
  bass_pulse: ["Bass pulse", "The whole board breathes with the kick drum.", "background:radial-gradient(circle,var(--b),var(--a) 60%,#111)"],
  ripple: ["Beat ripple", "Each beat sends a ring of light out from the space bar.",
    "background:radial-gradient(circle at 50% 90%,transparent 20%,var(--b) 24%,transparent 30%,transparent 44%,var(--a) 48%,transparent 54%),#111"],
  wave: ["Wave", "Calm color wave that speeds up with the music.", "background:linear-gradient(90deg,var(--a),var(--b),var(--c),var(--b),var(--a))"],
  mirror: ["Mirror", "Spectrum from the center out: bass in the middle, treble at the edges.",
    "background:linear-gradient(0deg,var(--b) 0 75%,transparent 75%) 50% 0/14% 100% no-repeat,linear-gradient(0deg,var(--a) 0 45%,transparent 45%) 0 0/100% 100%,#111"],
  waterfall: ["Waterfall", "The spectrum scrolls down the rows: the last half-second of music.",
    "background:linear-gradient(180deg,var(--c),var(--b) 40%,var(--a) 80%,#111)"],
  fireworks: ["Fireworks", "Each beat launches a spark that bursts at the F-row.",
    "background:radial-gradient(circle at 30% 25%,var(--c) 6%,var(--b) 14%,transparent 30%),radial-gradient(circle at 72% 30%,var(--b) 8%,transparent 22%),#111"],
  sparkle: ["Sparkle rain", "Hi-hats and cymbals pop random keys over a bass glow.",
    "background:radial-gradient(circle at 20% 40%,var(--c) 5%,transparent 9%),radial-gradient(circle at 60% 70%,var(--b) 5%,transparent 9%),radial-gradient(circle at 85% 30%,var(--c) 4%,transparent 8%),var(--a)"],
  zones: ["Keycap zones", "Bass on the black keys, mids on the white, highs on the lime.",
    "background:linear-gradient(90deg,#222 0 25%,#e8e8e8 25% 75%,#a6d43e 75%)"],
  pitch: ["Pitch color", "The melody's note sets the color as the singer moves up and down.",
    "background:linear-gradient(90deg,#f33,#fd3,#3f6,#3cf,#a3f,#f3a)"],
};
const MU_ORDER = ["spectrum", "mirror", "waterfall", "bass_pulse", "ripple", "fireworks", "sparkle", "zones", "pitch", "wave"];
const MU_PALETTES = {
  matcha: ["#1e2a0c", "#7fbf2a", "#c8f06a", "#f4ffe4"], rainbow: ["#ff0000", "#ffee00", "#00ff6a", "#00a2ff", "#a100ff"],
  fire: ["#2a0000", "#d11a00", "#ff8a00", "#ffe9a8"], ice: ["#00142e", "#0068ff", "#3fd8ff", "#eafcff"],
  synthwave: ["#22003f", "#a100ff", "#ff2a9d", "#00e5ff"],
  album: null, // from the current song's cover art
};
const MU_STATUS = { idle: ["Off", ""], playing: ["Listening to Spotify", "playing"], waiting_for_spotify: ["Waiting for Spotify", "waiting"],
  elsewhere: ["Spotify is playing on another device (no sound on this PC)", "waiting"],
  not_wired: ["Plug in the cable", "not_wired"],
  needs_firmware: ["Needs the V83P Studio firmware", "not_wired"] };

function initMusic() {
  MU.view = new KeyboardView($("#mu-kb"), { edge: true, color: cap => cap.led == null ? null : MU.frame[cap.led] || null,
    edgeColor: i => MU.frame[i] || null, label: cap => prettyCap(cap.name) });
  MU.send = throttle(changes => safe(() => api("/api/music", changes)).then(c => { if (c) { MU.cfg = c; renderMusicStatus(); } }), 150);
  $("#mu-enabled").onchange = e => setMusic({ enabled: e.target.checked });
  $("#mu-vu").onchange = e => setMusic({ underglow_vu: e.target.checked });
  $("#mu-only").onchange = e => setMusic({ only_spotify: e.target.checked });
  for (const [id, key, div] of [["#mu-sens", "sensitivity", 100], ["#mu-smooth", "smoothing", 100], ["#mu-dyn", "dynamics", 100], ["#mu-bright", "brightness", 100]])
    $(id).addEventListener("input", e => { setMusic({ [key]: e.target.value / div }, true); renderMusicSliders(); });
  for (let i = 0; i < 16; i++) $("#mu-eq").append(el("i"));
}
function setMusic(changes, quiet) {
  Object.assign(MU.cfg, changes);
  if (!quiet) renderMusic();
  MU.send(changes);
}
async function loadMusic() {
  MU.cfg = await safe(() => api("/api/music"));
  renderMusic();
  musicLoop();
}
function renderMusicSliders() {
  const c = MU.cfg;
  $("#mu-sens").value = c.sensitivity * 100; $("#mu-sens-v").textContent = c.sensitivity.toFixed(2) + "×";
  $("#mu-smooth").value = c.smoothing * 100; $("#mu-smooth-v").textContent = Math.round(c.smoothing * 100) + "%";
  $("#mu-bright").value = c.brightness * 100; $("#mu-bright-v").textContent = Math.round(c.brightness * 100) + "%";
  $("#mu-dyn").value = (c.dynamics ?? 0.4) * 100; $("#mu-dyn-v").textContent = Math.round((c.dynamics ?? 0.4) * 100) + "%";
  $$("#page-music input[type=range]").forEach(rangeFill);
}
function renderMusic() {
  const c = MU.cfg;
  if (!c) return;
  $("#mu-enabled").checked = c.enabled; $("#mu-vu").checked = c.underglow_vu; $("#mu-only").checked = c.only_spotify;
  renderMusicSliders();
  const albumStops = c.album || ["#333", "#666", "#999", "#ccc"];
  const stops = c.palette === "album" ? albumStops : MU_PALETTES[c.palette];
  const vars = `--a:${stops[1]};--b:${stops[2]};--c:${stops[stops.length - 1]}`;
  $("#mu-styles").replaceChildren(...MU_ORDER.map(k => [k, MU_STYLES[k]]).map(([k, [name, desc, pv]]) =>
    el("div", { class: "mu-style" + (c.style === k ? " on" : ""), style: vars, onclick: () => setMusic({ style: k }) },
      el("div", { class: "pv", style: pv }), el("b", {}, name), el("small", {}, desc))));
  $("#mu-palettes").replaceChildren(...Object.entries(MU_PALETTES).map(([k, s]) =>
    el("div", { class: "mu-pal" + (c.palette === k ? " on" : ""), onclick: () => setMusic({ palette: k }) },
      el("i", { style: `background:linear-gradient(90deg,${(s || albumStops).join(",")})` }), k === "album" ? "Album art" : k)));
  renderMusicStatus();
}
function renderMusicStatus() {
  const c = MU.cfg;
  if (!c) return;
  const [text, cls] = MU_STATUS[c.status] || [c.status, ""];
  $("#mu-status").className = "pill " + cls;
  $("#mu-status span").textContent = c.enabled ? text : "Off";
  const sp = c.spotify || {};
  $(".np-title", $("#mu-now")).textContent = sp.title || (sp.running ? "Spotify is paused" : "Spotify isn't open");
  $(".np-artist", $("#mu-now")).textContent = sp.artist || "Spotify";
  $("#mu-device").textContent = c.error ? `Audio capture problem: ${c.error}` : c.device ? `Listening on: ${c.device}` : "";
}
async function musicLoop() {
  clearTimeout(MU.timer);
  if (S.page !== "music") return;
  const live = MU.cfg && MU.cfg.enabled && MU.cfg.status === "playing" && !document.hidden;
  try {
    if (live) {
      const f = await api("/api/music/frame");
      MU.frame = f.colors; MU.bands = f.bands;
      MU.view.update();
      $$("#mu-eq i").forEach((b, i) => b.style.height = Math.max(2, (f.bands[i] || 0) * 28) + "px");
    }
    if (!live || (MU.tick = (MU.tick || 0) + 1) % 20 === 0) { // status every ~1 s
      MU.cfg = { ...MU.cfg, ...(await api("/api/music")) };
      if (!live) { MU.frame = []; MU.view.update(); $$("#mu-eq i").forEach(b => b.style.height = "2px"); }
      renderMusicStatus();
    }
  } catch { /* backend busy or restarting */ }
  MU.timer = setTimeout(musicLoop, live ? (document.hasFocus() ? 50 : 150) : 1000);
}

/* ================= theme + small UI helpers ================= */
function rangeFill(r) {
  const p = ((r.value - r.min) / (r.max - r.min)) * 100;
  r.style.setProperty("--p", p + "%");
}
function colorways() { return S.state.board?.colorways || {}; }
function applyColorway(id) {
  const all = colorways(), cw = all[id] || all[S.state.board?.default_colorway] || Object.values(all)[0];
  if (!cw) return;
  CW.id = all[id] ? id : Object.keys(all).find(k => all[k] === cw);
  CW.roles = { mod: new Set(cw.roles?.mod || []), accent: new Set(cw.roles?.accent || []) };
  for (const [k, v] of Object.entries(cw.vars || {})) document.body.style.setProperty("--" + k, v);
  const accent = cw.accent?.[resolvedAppearance()] || cw.accent?.dark || {};  // the app's highlight color
  for (const [k, v] of Object.entries(accent)) document.body.style.setProperty("--" + k, v);
  document.body.classList.toggle("opaque-legends", !!cw.opaque_legends);
  ALL_VIEWS.forEach(v => { v.classify(); v.cache?.clear(); v.update(); });
  $$("#cap-theme button").forEach(b => b.classList.toggle("on", b.dataset.theme === CW.id));
  const sel = $("#dv-colorway");
  if (sel) sel.value = CW.id;
  savePref("colorway", CW.id);
}
/* Preferences are kept by the backend (studio_state.json): the window's address has a new port each launch,
   and browser storage is per address, so it would forget them. localStorage only migrates older choices. */
function loadPref(k) {
  let v = S.state?.ui?.[k];
  if (!v) try { v = localStorage.getItem("mykeys." + k) || (k === "colorway" ? localStorage.getItem("mykeys.capTheme2") : null); } catch {}
  return v || null;
}
function savePref(k, v) {
  if ((S.state.ui ||= {})[k] === v) return;
  S.state.ui[k] = v;
  api("/api/prefs", { [k]: v }).catch(() => {});
}
/* Appearance: dark / light / system (follows Windows). The keyboard stage stays dark in both. */
const APPEAR = { mode: "system", mq: window.matchMedia("(prefers-color-scheme: dark)") };
function resolvedAppearance() { return APPEAR.mode === "system" ? (APPEAR.mq.matches ? "dark" : "light") : APPEAR.mode; }
function applyAppearance(mode) {
  if (mode) APPEAR.mode = mode;
  const r = resolvedAppearance();
  document.documentElement.dataset.appearance = r;
  $$("#dv-appearance button").forEach(b => b.classList.toggle("on", b.dataset.mode === APPEAR.mode));
  savePref("appearance", APPEAR.mode);
  if (CW.id) applyColorway(CW.id);              // accent colors differ per appearance
  window.mykeysApp?.setAppearance?.(r);          // Electron: title-bar buttons match
}
function initAppearance() {
  APPEAR.mode = loadPref("appearance") || "system";
  APPEAR.mq.addEventListener("change", () => { if (APPEAR.mode === "system") applyAppearance(); });
  $$("#dv-appearance button").forEach(b => b.onclick = () => applyAppearance(b.dataset.mode));
  applyAppearance();
}
function initTheme() {
  const all = colorways();
  // switch under the board: every colorway in the board definition
  $("#cap-theme").replaceChildren(...Object.entries(all).map(([id, cw]) =>
    el("button", { "data-theme": id, onclick: () => applyColorway(id) }, cw.name)));
  let chosen = null;
  chosen = loadPref("colorway");
  applyColorway(chosen || S.state.board?.default_colorway);
  if (!chosen) pickColorway();   // first run: ask which keyboard they have
}
/* First run: "Which MK PRO V2 do you have?" with a little keycap sample of each colorway. */
function pickColorway() {
  const all = colorways(), board = S.state.board || {};
  const sample = ["ESC", "F1", "F5", "1", "Q", "W", "TAB", "CAPS", "ENTER", "LSHIFT", "SPACE", "UP"];
  const close = openModal((card, close) => {
    card.classList.add("cw-modal");
    card.append(el("div", { class: "eyebrow mono" }, "Welcome"), el("h2", { class: "cw-title" }, `Which ${board.name || "keyboard"} do you have?`),
      el("p", { class: "hint" }, "The app draws your keyboard in its real colors. You can change this later on the Device page."));
    const grid = el("div", { class: "cw-grid" });
    for (const [id, cw] of Object.entries(all)) {
      if (cw.selectable === false) continue;
      const roles = { mod: new Set(cw.roles?.mod || []), accent: new Set(cw.roles?.accent || []) };
      const v = cw.vars || {};
      const keys = sample.map(n => {
        const r = roles.accent.has(n) ? "acc" : roles.mod.has(n) ? "mod" : "cap";
        return el("i", { class: "cw-key" + (n === "SPACE" ? " wide" : ""), style:
          `background:linear-gradient(180deg,${v[r + "-top-a"]},${v[r + "-top-b"]});box-shadow:0 2px 0 ${v[r + "-side-b"]};color:${v[r === "cap" ? "legend" : r + "-legend"]}` },
          prettyCap(n) || "");
      });
      grid.append(el("button", { class: "cw-card", onclick: () => { applyColorway(id); close(); } },
        el("div", { class: "cw-board", style: `background:linear-gradient(180deg,${v["case-a"]},${v["case-b"]})` }, ...keys),
        el("b", {}, cw.name), el("small", {}, cw.description || "")));
    }
    card.append(grid);
  });
}

/* ================= shell ================= */
function setStatus() {
  const c = S.connection, st = $("#status");
  document.body.classList.toggle("offline", c !== "wired");  // greys out everything that needs the cable
  document.body.classList.toggle("stock-fw", stockFw());       // locks per-key + music (see .needs-fw)
  if (stockFw() && LT.sel?.size) { LT.sel.clear(); refreshSel?.(); }
  st.className = "status status-" + c;
  $(".status-text", st).textContent = { wired: "Connected · wired", wireless: "Wireless · plug in to edit", disconnected: "Keyboard not found",
    flashing: "Updating firmware" }[c];
  const fw = S.state?.firmware;
  $("#fw-label").textContent = fw ? `Firmware ${fw.release}${fw.mykeys ? "" : " · stock"}` : "";
  const b = $("#banner");
  if (c === "wired") b.classList.add("hidden");
  else {
    b.classList.remove("hidden");
    b.textContent = c === "flashing" ? (fwJobActive() ? "Firmware update in progress. Follow the steps in the firmware window."
        : "The keyboard is in flash mode. Unplug the cable and plug it back in to start it normally.")
      : c === "wireless"
      ? "The keyboard is on wireless, so greyed-out options are unavailable. Set the switch to wired and plug in the cable to change them. Saved settings keep working wirelessly."
      : `Keyboard not found, so greyed-out options are unavailable. Plug it in with the cable and set the switch to wired. V83P Studio supports the ${S.state?.board?.name || "Inland MK PRO V2"} (${Object.values(colorways()).filter(c => c.selectable !== false).map(c => c.name).join(" / ") || "Matcha / Mint"}).`;
  }
}
async function refreshAll(force) {
  S.state = await api("/api/state");
  S.connection = S.state.connection;
  setStatus();
  if (wired()) {
    if (force || !S.keymap) await loadKeymap(true);
    if (S.page === "macros") await loadMacros(force);
  }
  showPage(S.page, true);
}
function showPage(p, quiet) {
  S.page = p;
  $$(".nav button").forEach(b => b.classList.toggle("active", b.dataset.page === p));
  $$(".page").forEach(s => s.classList.toggle("hidden", s.id !== "page-" + p));
  if (p === "lighting") showLighting();
  if (p === "keys") { KM.view.layout(); KM.view.update(); }
  if (p === "macros") { MC.view.layout(); loadMacros(); MC.view.update(); }
  if (p === "knob") renderKnob();
  if (p === "music") { MU.view.layout(); loadMusic(); }
  if (p === "reactions" && !quiet) loadReactions();
  if (p === "profiles" && !quiet) loadProfiles().then(loadAutoProfiles);
  if (p === "device") renderDevice();
}
async function poll() {
  if (document.hidden) return;
  try {
    const s = await api("/api/state?lite=1");
    const was = S.connection;
    S.state.connection = S.connection = s.connection;
    S.state.firmware = s.firmware;
    S.state.flash = s.flash;
    if (FW.open) FW.update?.(s.flash);
    $("#nav-music-live").classList.toggle("on", !!(s.music && s.music.active));
    // mirror the keyboard (Fn-key changes, factory reset); skip while the user is dragging colors
    if (!LT.busy && JSON.stringify(s.perkey) !== JSON.stringify(S.state.perkey)) S.state.perkey = s.perkey;
    if (!LT.busy) S.state.perkey_enabled = s.perkey_enabled;
    if (S.page === "lighting" && !LT.busy) { updateEffectUI(); renderEffectsIfChanged(); updateModes(); redrawBoard(); }
    if (s.active_profile !== S.state.active_profile) {
      S.state.active_profile = s.active_profile;
      if (S.page === "profiles") loadProfiles();
    }
    if (s.lighting && !LT.busy) S.state.lighting = s.lighting;
    setStatus();
    if (was !== "wired" && s.connection === "wired") { toast("Keyboard connected"); await refreshAll(true); }
    if (S.page === "device") renderDevice();
  } catch { /* server restarting */ }
}
/* "?" next to each page title opens that page's help (content in help.js). */
function showHelp(page) {
  const h = HELP[page];
  if (!h) return;
  const close = openModal((card, close) => {
    card.classList.add("help-modal");
    card.append(
      el("div", { class: "row between" }, el("div", {}, el("div", { class: "eyebrow mono" }, "How to use"), el("h2", { class: "help-title" }, h.title)),
        el("button", { class: "btn ghost", onclick: close }, "Close")),
      el("p", { class: "hint help-intro" }, h.intro),
      ...h.sections.map(([head, lines]) => el("section", { class: "help-sec" }, el("h3", {}, head), el("ul", {}, ...lines.map(t => el("li", {}, t))))));
  });
  const esc = e => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc, true); } };
  document.addEventListener("keydown", esc, true);
}
function initHelp() {
  for (const page of $$("section.page")) {
    const id = page.id.replace("page-", ""), h1 = page.querySelector(".page-head h1");
    if (HELP[id] && h1) h1.append(el("button", { class: "help-btn", title: "How to use this page", "aria-label": "Help", onclick: () => showHelp(id) }, "?"));
  }
}
async function boot() {
  const style = document.createElement("style");
  style.textContent = "@keyframes slide{to{background-position:200% 0}}@keyframes breathe{50%{opacity:.25}}";
  document.head.append(style);
  S.keycodes = await api("/api/keycodes");
  for (const k of S.keycodes) if (!S.kcByValue.has(k.value)) S.kcByValue.set(k.value, k);
  S.state = await api("/api/state");
  S.connection = S.state.connection;
  if (window.mykeysApp) document.body.classList.add("electron");
  if (S.state.board?.layers) LAYERS = S.state.board.layers;
  initAppearance();
  initTheme();
  document.addEventListener("input", e => { if (e.target.type === "range") rangeFill(e.target); });
  initHelp();
  initLighting(); initKeys(); initMacros(); initReactions(); initProfiles(); initDevice(); initMusic();
  $$(".nav button").forEach(b => b.onclick = () => showPage(b.dataset.page));
  $$("[data-goto-fw]").forEach(b => b.onclick = () => { showPage("device"); setTimeout(() => $("#dv-fw")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50); });
  await refreshAll(true);
  setInterval(poll, 700);
  requestAnimationFrame(previewLoop);
}
boot().catch(e => { document.body.prepend(el("div", { class: "banner" }, "Failed to start: " + e.message)); console.error(e); });
