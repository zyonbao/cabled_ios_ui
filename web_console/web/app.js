// app.js — device picker, continuous MJPEG screen mirror, mouse tap/swipe
// forwarding, and Mac-keyboard mirroring.
"use strict";

const els = {
  select: document.getElementById("device-select"),
  refresh: document.getElementById("refresh-btn"),
  fps: document.getElementById("fps-select"),
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  fpsReadout: document.getElementById("fps-readout"),
  phone: document.getElementById("phone"),
  screen: document.getElementById("screen"),
  touch: document.getElementById("touch"),
  overlay: document.getElementById("overlay"),
  overlayText: document.getElementById("overlay-text"),
  overlaySub: document.getElementById("overlay-sub"),
  spinner: document.getElementById("spinner"),
  infoName: document.getElementById("info-name"),
  infoModel: document.getElementById("info-model"),
  infoOs: document.getElementById("info-os"),
  infoUdid: document.getElementById("info-udid"),
  infoSize: document.getElementById("info-size"),
  infoOrient: document.getElementById("info-orient"),
  homeBtn: document.getElementById("home-btn"),
  switcherBtn: document.getElementById("switcher-btn"),
  reloadBtn: document.getElementById("reload-btn"),
  kbdBtn: document.getElementById("kbd-btn"),
  shotBtn: document.getElementById("shot-btn"),
  kbd: document.getElementById("kbd-capture"),
};

const state = {
  devices: {},          // udid -> device meta
  target: "",           // current selected udid
  winSize: null,        // { width, height } in WDA points (current orientation)
  orientation: { orientation: "PORTRAIT", degrees: 0 }, // clockwise degrees to upright
  streaming: false,
  generation: 0,        // bumped on every device switch to kill stale streams
  streamFps: 20,        // requested MJPEG framerate
  kbdOn: false,         // keyboard capture enabled
  composing: false,     // IME composition in progress
};

const TAP_THRESHOLD_PX = 8; // movement below this counts as a tap
// 600ms sits comfortably above iOS's ~0.5s system long-press threshold, so the
// on-device press reliably triggers a menu while staying clear of normal taps.
const LONG_PRESS_MIN_MS = 600; // in-place hold at/above this counts as a long press
const LONG_PRESS_MAX_MS = 3000; // clamp the reported long-press hold time

// ---------------------------------------------------------------------------
// Status / overlay helpers
// ---------------------------------------------------------------------------

function setStatus(text, kind) {
  els.statusText.textContent = text;
  els.statusDot.className = "status-dot" + (kind ? " " + kind : "");
}

function showOverlay(text, sub, spinning) {
  els.overlayText.textContent = text || "";
  els.overlaySub.textContent = sub || "";
  els.spinner.classList.toggle("hidden", !spinning);
  els.overlay.classList.remove("hidden");
}

function hideOverlay() {
  els.overlay.classList.add("hidden");
}

// ---------------------------------------------------------------------------
// Device list
// ---------------------------------------------------------------------------

async function loadDevices() {
  setStatus("正在扫描设备…", "busy");
  try {
    const res = await fetch("/api/devices");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const targets = data.targets || [];
    state.devices = {};
    const prev = state.target;

    els.select.innerHTML = '<option value="">— 选择设备 —</option>';
    for (const t of targets) {
      state.devices[t.id] = t;
      const opt = document.createElement("option");
      opt.value = t.id;
      const wda = t.state === "online" ? "" : "（未装 WDA）";
      const model = (t.metadata && t.metadata.model) || "";
      opt.textContent = `${t.name || t.id}  ${model} ${wda}`.trim();
      els.select.appendChild(opt);
    }

    if (prev && state.devices[prev]) {
      els.select.value = prev;
    }
    setStatus(`发现 ${targets.length} 台设备`, targets.length ? "online" : "");
    if (!targets.length) {
      showOverlay("未检测到 USB 设备", "请连接并信任 iOS 设备后点击“刷新”", false);
    }
  } catch (err) {
    setStatus("设备列表加载失败", "error");
    showOverlay("无法获取设备列表", String(err), false);
  }
}

// ---------------------------------------------------------------------------
// Device selection / stream lifecycle
// ---------------------------------------------------------------------------

function stopStream() {
  state.streaming = false;
  state.generation += 1; // invalidate any in-flight stream
  els.homeBtn.disabled = true;
  els.switcherBtn.disabled = true;
  setKeyboard(false);
  els.kbdBtn.disabled = true;
  els.shotBtn.disabled = true;
  els.reloadBtn.disabled = true;
  els.fpsReadout.textContent = "";
  // Clearing src closes the MJPEG connection held open by the browser.
  els.screen.removeAttribute("src");
}

function fillInfo(dev) {
  const meta = (dev && dev.metadata) || {};
  els.infoName.textContent = (dev && dev.name) || "—";
  els.infoModel.textContent = meta.model || "—";
  els.infoOs.textContent = meta.os_version || "—";
  els.infoUdid.textContent = (dev && dev.id) || "—";
  els.infoSize.textContent = state.winSize
    ? `${state.winSize.width} × ${state.winSize.height}`
    : "—";
  if (els.infoOrient) {
    els.infoOrient.textContent = state.winSize
      ? ORIENT_LABEL[state.orientation.orientation] || "—"
      : "—";
  }
}

const ORIENT_LABEL = {
  PORTRAIT: "竖屏",
  PORTRAIT_UPSIDE_DOWN: "竖屏（倒置）",
  LANDSCAPE_LEFT: "横屏（左）",
  LANDSCAPE_RIGHT: "横屏（右）",
};

async function onSelectDevice() {
  stopStream();
  const target = els.select.value;
  state.target = target;
  state.winSize = null;
  state.orientation = { orientation: "PORTRAIT", degrees: 0 };

  if (!target) {
    fillInfo(null);
    setStatus("未连接", "");
    showOverlay("请选择一个设备", "", false);
    return;
  }

  const dev = state.devices[target];
  fillInfo(dev);

  // Requirement 2: no WDA -> black screen + message.
  if (!dev || dev.state !== "online") {
    setStatus("该设备未安装 WDA", "error");
    showOverlay("该设备未安装 WebDriverAgent (WDA)", "无法镜像或控制此设备", false);
    return;
  }

  const gen = ++state.generation;
  setStatus("正在启动 WDA…", "busy");
  showOverlay("正在启动 WebDriverAgent…", "首次启动可能需要数十秒", true);

  try {
    const prep = await fetch("/api/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target }),
    });
    if (gen !== state.generation) return; // user switched away
    if (!prep.ok) {
      const detail = await safeDetail(prep);
      throw new Error(detail);
    }

    const sizeRes = await fetch(`/api/window_size?target=${encodeURIComponent(target)}`);
    if (gen !== state.generation) return;
    if (!sizeRes.ok) throw new Error(await safeDetail(sizeRes));
    state.winSize = await sizeRes.json();

    // Orientation drives how the (native-portrait) MJPEG frame is rotated to
    // appear upright; failure falls back to portrait rather than blocking.
    try {
      const oRes = await fetch(`/api/orientation?target=${encodeURIComponent(target)}`);
      if (gen !== state.generation) return;
      if (oRes.ok) state.orientation = await oRes.json();
    } catch (_) { /* keep portrait default */ }

    fillInfo(dev);
    sizePhone();

    // Apply the requested MJPEG framerate before opening the stream.
    try {
      await postJson("/api/stream_config", { target, framerate: state.streamFps });
    } catch (_) { /* non-fatal: defaults already set during prepare */ }
    if (gen !== state.generation) return;

    hideOverlay();
    setStatus("已连接", "online");
    els.homeBtn.disabled = false;
    els.switcherBtn.disabled = false;
    els.reloadBtn.disabled = false;
    state.streaming = true;
    els.kbdBtn.disabled = false;
    els.shotBtn.disabled = false;
    els.fpsReadout.textContent = `MJPEG ${state.streamFps}fps`;
    startStream(gen);
  } catch (err) {
    if (gen !== state.generation) return;
    setStatus("启动失败", "error");
    showOverlay("无法启动 WebDriverAgent", String(err.message || err), false);
  }
}

async function safeDetail(res) {
  try {
    const j = await res.json();
    return j.detail || `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

// ---------------------------------------------------------------------------
// MJPEG stream (continuous, high-fps)
// ---------------------------------------------------------------------------

function startStream(gen) {
  els.screen.onerror = () => {
    if (gen !== state.generation || !state.streaming) return;
    state.streaming = false;
    setStatus("画面已断开", "error");
    showOverlay("画面流已中断", "请重新选择设备重试", false);
  };
  // The browser keeps this connection open and renders frames as they arrive.
  els.screen.src = `/api/stream?target=${encodeURIComponent(state.target)}&_=${Date.now()}`;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

function sizePhone() {
  if (!state.winSize) return;
  // window_size is already in the current orientation, so its aspect ratio is
  // landscape when the device is rotated; the container follows it directly.
  const { width, height } = state.winSize;
  els.phone.style.aspectRatio = `${width} / ${height}`;
  els.phone.style.height = "min(86vh, 900px)";
  els.phone.style.width = "auto";
  applyOrientation();
}

// Orient the MJPEG frame inside the (current-orientation) container. The
// broadcaster may already emit current-orientation frames; only rotate when the
// frame's orientation differs from window_size (compared via natural size). For
// 90/270 the on-screen width/height swap, so the <img> box is sized from the
// container rect before rotating.
// Keep this logic in sync with slide6_console/mirror.py::_rotation_for_frame;
// `degrees` fully encodes the orientation (0/90/180/270).
function applyOrientation() {
  const img = els.screen;
  if (!state.winSize) return;
  const winLand = state.winSize.width > state.winSize.height;
  const fw = img.naturalWidth, fh = img.naturalHeight;
  // Until the first frame loads, naturalWidth is 0 — assume it already matches
  // (no rotation); the 'load' listener re-runs this once the size is known.
  const frameLand = fw > 0 && fh > 0 ? fw > fh : winLand;
  const degrees = (state.orientation && state.orientation.degrees) || 0;
  let deg;
  if (frameLand !== winLand) {
    // Aspect differs: rotate portrait->landscape using the device angle.
    deg = degrees === 90 || degrees === 270 ? degrees : 90;
  } else {
    // Aspect already matches; only the 180° flip (which aspect can't detect)
    // still needs correcting for upside-down portrait.
    deg = degrees === 180 ? 180 : 0;
  }
  if (deg === 90 || deg === 270) {
    const rect = els.phone.getBoundingClientRect();
    img.style.width = `${rect.height}px`;
    img.style.height = `${rect.width}px`;
    img.style.position = "absolute";
    img.style.left = "50%";
    img.style.top = "50%";
    img.style.transform = `translate(-50%, -50%) rotate(${deg}deg)`;
  } else {
    img.style.width = "100%";
    img.style.height = "100%";
    img.style.position = "static";
    img.style.left = "";
    img.style.top = "";
    img.style.transform = deg === 180 ? "rotate(180deg)" : "none";
  }
}

// Re-evaluate rotation once the first frame's natural size is known.
els.screen.addEventListener("load", applyOrientation);

window.addEventListener("resize", sizePhone);

// ---------------------------------------------------------------------------
// Touch / mouse -> device coordinate mapping
// ---------------------------------------------------------------------------

let gesture = null; // { x, y, t }

function toDevicePoint(clientX, clientY) {
  const rect = els.touch.getBoundingClientRect();
  let fx = (clientX - rect.left) / rect.width;
  let fy = (clientY - rect.top) / rect.height;
  fx = Math.min(1, Math.max(0, fx));
  fy = Math.min(1, Math.max(0, fy));
  return {
    x: Math.round(fx * state.winSize.width),
    y: Math.round(fy * state.winSize.height),
  };
}

els.touch.addEventListener("pointerdown", (e) => {
  if (!state.streaming || !state.winSize) return;
  els.touch.setPointerCapture(e.pointerId);
  gesture = { clientX: e.clientX, clientY: e.clientY, t: performance.now() };
});

els.touch.addEventListener("pointerup", async (e) => {
  if (!gesture || !state.winSize) return;
  const start = gesture;
  gesture = null;

  const dx = e.clientX - start.clientX;
  const dy = e.clientY - start.clientY;
  const dist = Math.hypot(dx, dy);
  const hold = Math.round(performance.now() - start.t);
  const startPt = toDevicePoint(start.clientX, start.clientY);

  try {
    // Displacement wins first (a moved finger is always a swipe); an in-place
    // hold long enough is a long press; everything else is a tap.
    if (dist >= TAP_THRESHOLD_PX) {
      const endPt = toDevicePoint(e.clientX, e.clientY);
      const durationMs = Math.min(1500, Math.max(120, hold));
      await postJson("/api/swipe", {
        target: state.target,
        x1: startPt.x, y1: startPt.y,
        x2: endPt.x, y2: endPt.y,
        durationMs,
      });
    } else if (hold >= LONG_PRESS_MIN_MS) {
      const durationMs = Math.min(LONG_PRESS_MAX_MS, hold);
      await postJson("/api/long_press", {
        target: state.target, x: startPt.x, y: startPt.y, durationMs,
      });
    } else {
      await postJson("/api/tap", { target: state.target, x: startPt.x, y: startPt.y });
    }
  } catch (err) {
    flashStatus(`操作失败: ${err.message || err}`);
  }

  // Tapping the screen must not steal keyboard capture focus.
  if (state.kbdOn) els.kbd.focus();
});

els.touch.addEventListener("pointercancel", () => { gesture = null; });
els.touch.addEventListener("contextmenu", (e) => e.preventDefault());
els.touch.addEventListener("dragstart", (e) => e.preventDefault());

// ---------------------------------------------------------------------------
// Keyboard capture (mirror the Mac keyboard to the focused field on device)
// ---------------------------------------------------------------------------

// iOS quirk: WDA's two key channels each only handle half of these keys.
//  - Navigation (arrows/Home/End/…): only keyboardInput/typeKey works (→ /api/chord).
//  - Editing (Enter/Backspace/Tab/Escape): typeKey is a no-op; the W3C key
//    event works instead (→ /api/key).
const NAV_KEYS = {
  ArrowUp: "UP",
  ArrowDown: "DOWN",
  ArrowLeft: "LEFT",
  ArrowRight: "RIGHT",
  Home: "HOME",
  End: "END",
  PageUp: "PAGEUP",
  PageDown: "PAGEDOWN",
};
const EDIT_KEYS = {
  Enter: "ENTER",
  Backspace: "BACKSPACE",
  Tab: "TAB",
  Escape: "ESCAPE",
};

function setKeyboard(on) {
  state.kbdOn = on && state.streaming;
  els.kbdBtn.textContent = `键盘输入: ${state.kbdOn ? "开" : "关"}`;
  els.kbdBtn.classList.toggle("active", state.kbdOn);
  if (state.kbdOn) {
    els.kbd.value = "";
    els.kbd.focus();
  } else {
    els.kbd.blur();
  }
}

// Serialized keyboard command queue. Fast typing fired many concurrent POSTs
// whose responses raced, so characters could land out of order. Every keyboard
// action (text / key / chord) now goes through one FIFO worker that sends them
// strictly one-at-a-time, and consecutive text is coalesced into one request.
const kbdQueue = [];
let kbdPumping = false;

async function pumpKbdQueue() {
  if (kbdPumping) return;
  kbdPumping = true;
  try {
    while (kbdQueue.length) {
      const cmd = kbdQueue.shift();
      try {
        if (cmd.type === "text") {
          await postJson("/api/type", { target: state.target, text: cmd.text });
        } else if (cmd.type === "key") {
          await postJson("/api/key", { target: state.target, key: cmd.name });
        } else if (cmd.type === "chord") {
          await postJson("/api/chord", { target: state.target, key: cmd.key, modifiers: cmd.modifiers });
        }
      } catch (err) {
        flashStatus(`输入失败: ${err.message || err}`);
      }
    }
  } finally {
    kbdPumping = false;
  }
}

function enqueueKbd(cmd) {
  // Coalesce with a still-queued (not yet sent) text command to batch bursts.
  const last = kbdQueue[kbdQueue.length - 1];
  if (cmd.type === "text" && last && last.type === "text") {
    last.text += cmd.text;
  } else {
    kbdQueue.push(cmd);
  }
  pumpKbdQueue();
}

function flushTyped() {
  const text = els.kbd.value;
  if (!text) return;
  els.kbd.value = "";
  enqueueKbd({ type: "text", text });
}

function sendKey(name) {
  enqueueKbd({ type: "key", name });
}

function sendChord(key, modifiers) {
  enqueueKbd({ type: "chord", key, modifiers });
}

// Keys that are modifiers themselves — never sent as a chord base key.
const MODIFIER_KEYS = new Set(["Meta", "Control", "Alt", "Shift"]);

function collectModifiers(e) {
  const mods = [];
  if (e.metaKey) mods.push("meta");
  if (e.ctrlKey) mods.push("control");
  if (e.altKey) mods.push("alt");
  if (e.shiftKey) mods.push("shift");
  return mods;
}

els.kbd.addEventListener("compositionstart", () => { state.composing = true; });
els.kbd.addEventListener("compositionend", () => {
  state.composing = false;
  flushTyped();
});
els.kbd.addEventListener("input", () => {
  if (state.composing) return; // wait for IME to finish
  flushTyped();
});
els.kbd.addEventListener("keydown", (e) => {
  if (!state.kbdOn) return;
  if (e.isComposing) return; // let the IME handle it
  if (MODIFIER_KEYS.has(e.key)) return; // wait for the actual key

  const hasCmdLike = e.metaKey || e.ctrlKey || e.altKey;

  // Navigation keys → keyboardInput (moves cursor / extends selection on iOS).
  if (NAV_KEYS[e.key]) {
    e.preventDefault();
    sendChord(NAV_KEYS[e.key], collectModifiers(e));
    return;
  }

  // Editing keys → W3C key event (typeKey is a no-op for these on iOS). With a
  // ⌘/⌃/⌥ modifier we still try keyboardInput as a best effort.
  if (EDIT_KEYS[e.key]) {
    e.preventDefault();
    if (hasCmdLike) sendChord(EDIT_KEYS[e.key], collectModifiers(e));
    else sendKey(EDIT_KEYS[e.key]);
    return;
  }

  // Any other ⌘/⌃/⌥ chord (letters, digits, punctuation).
  if (hasCmdLike) {
    const base = e.key.length === 1 ? e.key : null;
    if (base) {
      e.preventDefault();
      sendChord(base, collectModifiers(e));
    }
    return;
  }
  // Printable keys fall through and are captured via the 'input' event.
});
// Keep keyboard focus even if the hidden field loses it unexpectedly.
els.kbd.addEventListener("blur", () => {
  if (state.kbdOn) setTimeout(() => { if (state.kbdOn) els.kbd.focus(); }, 0);
});

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await safeDetail(res));
  return res.json();
}

let flashTimer = null;
function flashStatus(msg) {
  setStatus(msg, "error");
  if (flashTimer) clearTimeout(flashTimer);
  flashTimer = setTimeout(() => {
    if (state.streaming) setStatus("已连接", "online");
  }, 2500);
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

els.select.addEventListener("change", onSelectDevice);
els.refresh.addEventListener("click", loadDevices);
// Per-device refresh: re-run the full select flow (re-prepare, re-read
// window_size/orientation, reconnect stream) to resync after a rotation.
els.reloadBtn.addEventListener("click", onSelectDevice);
els.fps.addEventListener("change", async () => {
  state.streamFps = parseInt(els.fps.value, 10) || 20;
  if (!state.target || !state.streaming) return;
  els.fpsReadout.textContent = `MJPEG ${state.streamFps}fps`;
  try {
    await postJson("/api/stream_config", { target: state.target, framerate: state.streamFps });
  } catch (err) {
    flashStatus(`帧率设置失败: ${err.message || err}`);
  }
});
els.homeBtn.addEventListener("click", async () => {
  if (!state.target) return;
  try {
    await postJson("/api/key", { target: state.target, key: "HOME" });
  } catch (err) {
    flashStatus(`HOME 失败: ${err.message || err}`);
  }
});
els.switcherBtn.addEventListener("click", async () => {
  if (!state.target) return;
  // Gesture + verify (and a possible retry) take a second or two.
  els.switcherBtn.disabled = true;
  setStatus("正在打开应用切换…", "busy");
  try {
    const res = await postJson("/api/app_switcher", { target: state.target });
    if (res && res.extra && res.extra.confirmed === false) {
      flashStatus("应用切换可能未生效，请重试");
    } else if (state.streaming) {
      setStatus("已连接", "online");
    }
  } catch (err) {
    flashStatus(`应用切换失败: ${err.message || err}`);
  } finally {
    els.switcherBtn.disabled = false;
    if (state.kbdOn) els.kbd.focus();
  }
});
els.kbdBtn.addEventListener("click", () => {
  if (!state.streaming) return;
  setKeyboard(!state.kbdOn);
});
els.shotBtn.addEventListener("click", async () => {
  if (!state.target) return;
  els.shotBtn.disabled = true;
  try {
    const res = await fetch(`/api/screenshot?target=${encodeURIComponent(state.target)}`);
    if (!res.ok) throw new Error(await safeDetail(res));
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const a = document.createElement("a");
    a.href = url;
    a.download = `ios-${state.target.slice(0, 8)}-${ts}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    flashStatus(`截图失败: ${err.message || err}`);
  } finally {
    els.shotBtn.disabled = !state.streaming;
    if (state.kbdOn) els.kbd.focus();
  }
});

// initial load
state.streamFps = parseInt(els.fps.value, 10) || 20;
loadDevices();
