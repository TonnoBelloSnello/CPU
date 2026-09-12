const programEl = document.getElementById("program");
const memStartEl = document.getElementById("mem-start");
const memEndEl = document.getElementById("mem-end");
const runBtn = document.getElementById("run-btn");
const simulationEngineEl = document.getElementById("simulation-engine");
const statusEl = document.getElementById("status");
const registerTable = document.getElementById("register-table");
const memoryTable = document.getElementById("memory-table");
const labelsEl = document.getElementById("labels");
const logEl = document.getElementById("log");
const ledStrip = document.getElementById("led-strip");
const leValueEl = document.getElementById("le-value");
const hexStrip = document.getElementById("hex-strip");
const hexValueEl = document.getElementById("hex-value");
const keyButtonsHost = document.getElementById("key-buttons");
const keyButtons = keyButtonsHost ? Array.from(keyButtonsHost.querySelectorAll("[data-key-index]")) : [];
const keyReleaseBtn = document.getElementById("key-release-btn");
const keyValueEl = document.getElementById("key-value");
const vgaCanvas = document.getElementById("vga-canvas");
const vgaValueEl = document.getElementById("vga-value");
const vgaDimsEl = document.getElementById("vga-dims");
const vgaCtx = vgaCanvas ? vgaCanvas.getContext("2d", { alpha: false }) : null;

if (vgaCtx) {
  vgaCtx.imageSmoothingEnabled = false;
}

const LOG_MAX_LINES = 2000;
const VGA_DEFAULT_WIDTH = 160;
const VGA_DEFAULT_HEIGHT = 120;
let logLines = [];
let streamController = null;
let streamErrorMessage = null;
let streamDoneReceived = false;
let simulationRunning = false;
let vgaWidth = VGA_DEFAULT_WIDTH;
let vgaHeight = VGA_DEFAULT_HEIGHT;
let vgaPixels = new Uint8Array(vgaWidth * vgaHeight);
let vgaLitPixels = 0;
let vgaDirty = false;
let vgaFlushScheduled = false;
let vgaImage = null;
let vgaDirtyMinX = vgaWidth;
let vgaDirtyMinY = vgaHeight;
let vgaDirtyMaxX = -1;
let vgaDirtyMaxY = -1;
let pendingLogLines = [];
let logFlushTimer = null;
let keyPressedMask = 0;
const LOG_FLUSH_INTERVAL_MS = 50;

function setStatus(message, type) {
  statusEl.textContent = message;
  statusEl.classList.toggle("is-error", type === "error");
}

function formatHex(hex) {
  if (!hex) {
    return "X";
  }
  return `0x${hex}`;
}

// Bits run most-significant first, so the strip reads like LEDR[9:0] on the
// board instead of mirrored.
function renderLeds(leReg) {
  ledStrip.innerHTML = "";

  const value = (leReg && leReg.dec !== null) ? Number(leReg.dec) : null;
  leValueEl.textContent = value !== null ? `LE = ${value}` : "LE =";

  for (let bit = 9; bit >= 0; bit--) {
    const on = value !== null && ((value >> bit) & 1) === 1;

    const cell = document.createElement("div");
    cell.className = "bit";

    const led = document.createElement("span");
    led.className = on ? "led led-on" : "led";

    const label = document.createElement("span");
    label.className = "bit-label";
    label.textContent = bit;

    cell.appendChild(led);
    cell.appendChild(label);
    ledStrip.appendChild(cell);
  }
}

// 7-segment segment paths: each digit is defined by 7 boolean segments [a,b,c,d,e,f,g]
// Segment layout:
//  aaa
// f   b
// f   b
//  ggg
// e   c
// e   c
//  ddd
const SEG7 = {
  0: [1,1,1,1,1,1,0],
  1: [0,1,1,0,0,0,0],
  2: [1,1,0,1,1,0,1],
  3: [1,1,1,1,0,0,1],
  4: [0,1,1,0,0,1,1],
  5: [1,0,1,1,0,1,1],
  6: [1,0,1,1,1,1,1],
  7: [1,1,1,0,0,0,0],
  8: [1,1,1,1,1,1,1],
  9: [1,1,1,1,0,1,1],
  10: [1,1,1,0,1,1,1], // A
  11: [0,0,1,1,1,1,1], // b
  12: [1,0,0,1,1,1,0], // C
  13: [0,1,1,1,1,0,1], // d
  14: [1,0,0,1,1,1,1], // E
  15: [1,0,0,0,1,1,1], // F
};

// Segment colours live in the stylesheet so the digits stay in step with the
// LEDs; here we only say which segments are lit.
function make7SegSVG(nibble, active) {
  const segs = active ? (SEG7[nibble] || [0,0,0,0,0,0,0]) : [0,0,0,0,0,0,0];
  const seg = (on) => (on ? "seg seg-on" : "seg");
  const [sa, sb, sc, sd, se, sf, sg] = segs;
  // SVG viewBox: 0 0 20 34  (width=20, height=34)
  return `<svg width="26" height="44" viewBox="0 0 20 34" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
    <!-- a: top    --> <polygon class="${seg(sa)}" points="3,1 17,1 15,3 5,3"/>
    <!-- b: top-R  --> <polygon class="${seg(sb)}" points="17,1 19,3 19,15 17,17"/>
    <!-- c: bot-R  --> <polygon class="${seg(sc)}" points="17,17 19,19 19,31 17,33"/>
    <!-- d: bot    --> <polygon class="${seg(sd)}" points="3,33 17,33 15,31 5,31"/>
    <!-- e: bot-L  --> <polygon class="${seg(se)}" points="1,19 3,17 5,31 3,33"/>
    <!-- f: top-L  --> <polygon class="${seg(sf)}" points="1,3 3,1 5,15 3,17"/>
    <!-- g: mid    --> <polygon class="${seg(sg)}" points="3,17 5,15 15,15 17,17 15,19 5,19"/>
  </svg>`;
}

// Most-significant digit first, so a value reads left to right the way it is
// written.
function renderHexDisplay(hexReg) {
  hexStrip.innerHTML = "";

  const value = (hexReg && hexReg.dec !== null) ? Number(hexReg.dec) : null;
  hexValueEl.textContent = value !== null ? `HEX = ${value}` : "HEX =";

  // Use the hex string length to know how many digits the hardware shows
  const numDigits = (hexReg && hexReg.hex) ? hexReg.hex.length : 3;

  for (let i = numDigits - 1; i >= 0; i--) {
    const nibble = value !== null ? (value >> (i * 4)) & 0xF : null;

    const cell = document.createElement("div");
    cell.className = "bit";

    const digit = document.createElement("div");
    digit.className = "digit-cell";
    digit.innerHTML = make7SegSVG(nibble, value !== null);

    const label = document.createElement("span");
    label.className = "bit-label";
    label.textContent = `HEX${i}`;

    cell.appendChild(digit);
    cell.appendChild(label);
    hexStrip.appendChild(cell);
  }
}

function rgb332ToRgb888(value) {
  const r3 = (value >> 5) & 0x07;
  const g3 = (value >> 2) & 0x07;
  const b2 = value & 0x03;
  const r = (r3 << 5) | (r3 << 2) | (r3 >> 1);
  const g = (g3 << 5) | (g3 << 2) | (g3 >> 1);
  const b = (b2 << 6) | (b2 << 4) | (b2 << 2) | b2;
  return [r, g, b];
}

function resetVgaDirtyRegion() {
  vgaDirtyMinX = vgaWidth;
  vgaDirtyMinY = vgaHeight;
  vgaDirtyMaxX = -1;
  vgaDirtyMaxY = -1;
}

function markVgaDirtyPixel(addr) {
  const x = addr % vgaWidth;
  const y = Math.floor(addr / vgaWidth);

  vgaDirtyMinX = Math.min(vgaDirtyMinX, x);
  vgaDirtyMaxX = Math.max(vgaDirtyMaxX, x);
  vgaDirtyMinY = Math.min(vgaDirtyMinY, y);
  vgaDirtyMaxY = Math.max(vgaDirtyMaxY, y);
  vgaDirty = true;
}

function markVgaDirtyFullFrame() {
  if (vgaWidth <= 0 || vgaHeight <= 0) {
    return;
  }
  vgaDirtyMinX = 0;
  vgaDirtyMinY = 0;
  vgaDirtyMaxX = vgaWidth - 1;
  vgaDirtyMaxY = vgaHeight - 1;
  vgaDirty = true;
}

function setOpaque(data) {
  for (let i = 3; i < data.length; i += 4) {
    data[i] = 255;
  }
}

function ensureVgaImageBuffer() {
  if (!vgaCtx) {
    return;
  }
  if (!vgaImage || vgaImage.width !== vgaWidth || vgaImage.height !== vgaHeight) {
    vgaImage = vgaCtx.createImageData(vgaWidth, vgaHeight);
    setOpaque(vgaImage.data);
  }
}

function clearVgaImageBuffer() {
  ensureVgaImageBuffer();
  if (!vgaImage) {
    return;
  }
  const data = vgaImage.data;
  data.fill(0);
  setOpaque(data);
}

function writeVgaPixelToImage(addr, color) {
  if (!vgaImage) {
    return;
  }
  const [r, g, b] = rgb332ToRgb888(color);
  const base = addr * 4;
  const data = vgaImage.data;
  data[base] = r;
  data[base + 1] = g;
  data[base + 2] = b;
  data[base + 3] = 255;
}

function validFbSize(value, fallback) {
  const size = Number(value);
  return Number.isFinite(size) && size > 0 ? size : fallback;
}

function ensureVgaSize(width = VGA_DEFAULT_WIDTH, height = VGA_DEFAULT_HEIGHT) {
  const fbWidth = validFbSize(width, VGA_DEFAULT_WIDTH);
  const fbHeight = validFbSize(height, VGA_DEFAULT_HEIGHT);
  if (fbWidth === vgaWidth && fbHeight === vgaHeight) {
    return;
  }
  vgaWidth = fbWidth;
  vgaHeight = fbHeight;
  vgaPixels = new Uint8Array(vgaWidth * vgaHeight);
  vgaLitPixels = 0;
  vgaImage = null;
  resetVgaDirtyRegion();
  if (vgaCanvas) {
    vgaCanvas.width = vgaWidth;
    vgaCanvas.height = vgaHeight;
  }
}

function updateVgaLabel() {
  if (vgaValueEl) {
    vgaValueEl.textContent = `${vgaLitPixels} px lit`;
  }
  if (vgaDimsEl) {
    vgaDimsEl.textContent = `${vgaWidth} × ${vgaHeight}`;
  }
}

function drawVgaBuffer() {
  if (!vgaCtx) {
    return;
  }
  ensureVgaImageBuffer();
  if (!vgaImage) {
    return;
  }

  if (vgaDirtyMaxX < vgaDirtyMinX || vgaDirtyMaxY < vgaDirtyMinY) {
    vgaDirty = false;
    updateVgaLabel();
    return;
  }

  const dirtyX = vgaDirtyMinX;
  const dirtyY = vgaDirtyMinY;
  const dirtyWidth = (vgaDirtyMaxX - vgaDirtyMinX) + 1;
  const dirtyHeight = (vgaDirtyMaxY - vgaDirtyMinY) + 1;
  vgaCtx.putImageData(vgaImage, 0, 0, dirtyX, dirtyY, dirtyWidth, dirtyHeight);

  resetVgaDirtyRegion();
  vgaDirty = false;
  updateVgaLabel();
}

function scheduleVgaFlush() {
  if (vgaFlushScheduled) {
    return;
  }
  vgaFlushScheduled = true;
  requestAnimationFrame(() => {
    vgaFlushScheduled = false;
    if (!vgaDirty) {
      return;
    }
    drawVgaBuffer();
  });
}

function resetVga(width = VGA_DEFAULT_WIDTH, height = VGA_DEFAULT_HEIGHT) {
  ensureVgaSize(width, height);
  vgaPixels.fill(0);
  vgaLitPixels = 0;
  clearVgaImageBuffer();
  markVgaDirtyFullFrame();
  scheduleVgaFlush();
}

function setVgaPixel(addr, color, schedule = true) {
  if (!Number.isFinite(addr) || addr < 0 || addr >= vgaPixels.length) {
    return;
  }
  const next = Number(color) & 0xFF;
  const prev = vgaPixels[addr];
  if (prev === next) {
    return;
  }
  if (prev === 0 && next !== 0) {
    vgaLitPixels += 1;
  } else if (prev !== 0 && next === 0) {
    vgaLitPixels -= 1;
  }
  vgaPixels[addr] = next;
  ensureVgaImageBuffer();
  writeVgaPixelToImage(addr, next);
  markVgaDirtyPixel(addr);
  if (schedule) {
    scheduleVgaFlush();
  }
}

function setVgaPixels(pixels) {
  if (!Array.isArray(pixels)) {
    return;
  }
  for (const pixel of pixels) {
    if (Array.isArray(pixel) && pixel.length >= 2) {
      setVgaPixel(Number(pixel[0]), Number(pixel[1]), false);
    }
  }
  if (vgaDirty) {
    scheduleVgaFlush();
  }
}

function renderVga(framebuffer, width = VGA_DEFAULT_WIDTH, height = VGA_DEFAULT_HEIGHT) {
  if (!vgaCanvas || !vgaCtx) {
    return;
  }

  ensureVgaSize(width, height);
  const pixelCount = vgaWidth * vgaHeight;
  vgaPixels.fill(0);
  vgaLitPixels = 0;
  clearVgaImageBuffer();

  for (const entry of framebuffer || []) {
    if (!entry || entry.dec === null) {
      continue;
    }
    const addr = Number(entry.addr);
    if (Number.isNaN(addr) || addr < 0 || addr >= pixelCount) {
      continue;
    }
    const value = Number(entry.dec) & 0xFF;
    vgaPixels[addr] = value;
    writeVgaPixelToImage(addr, value);
    if (value !== 0) {
      vgaLitPixels += 1;
    }
  }
  markVgaDirtyFullFrame();
  drawVgaBuffer();
}

function appendRow(table, cells, className) {
  const row = document.createElement("tr");
  for (const text of cells) {
    const cell = document.createElement("td");
    cell.textContent = text;
    if (className) {
      cell.className = className;
    }
    row.appendChild(cell);
  }
  table.appendChild(row);
  return row;
}

function renderRegisters(registers) {
  registerTable.innerHTML = "";
  const order = [];
  for (let i = 0; i < 15; i += 1) {
    order.push(`R${i}`);
  }
  order.push("LE", "HEX", "PC", "CPSR");
  for (let i = 0; i < 8; i += 1) {
    order.push(`Q${i}`);
  }
  for (let i = 0; i < 4; i += 1) {
    order.push(`A${i}`);
  }
  renderLeds(registers["LE"]);
  renderHexDisplay(registers["HEX"]);

  for (const name of order) {
    const reg = registers[name];
    const dec = reg ? (reg.dec === null ? "X" : reg.dec) : "-";
    const hex = reg ? formatHex(reg.hex) : "-";
    appendRow(registerTable, [name, dec, hex]);
  }
}

function renderMemory(memory) {
  memoryTable.innerHTML = "";
  if (!memory.length) {
    const row = appendRow(memoryTable, ["No memory data yet."], "is-empty");
    row.firstChild.colSpan = 3;
    return;
  }
  for (const entry of memory) {
    const dec = entry.dec === null ? "X" : entry.dec;
    appendRow(memoryTable, [entry.addr, dec, formatHex(entry.hex)]);
  }
}

function renderLabels(labels) {
  labelsEl.innerHTML = "";
  const entries = Object.entries(labels || {});
  if (!entries.length) {
    labelsEl.innerHTML = '<span class="empty-state">No labels in this program.</span>';
    return;
  }
  for (const [name, value] of entries) {
    const chip = document.createElement("span");
    chip.className = "chip";

    const chipValue = document.createElement("span");
    chipValue.className = "chip-value";
    chipValue.textContent = value;

    chip.append(`${name} `, chipValue);
    labelsEl.appendChild(chip);
  }
}

function renderLog(log) {
  pendingLogLines = [];
  if (logFlushTimer !== null) {
    clearTimeout(logFlushTimer);
    logFlushTimer = null;
  }
  if (!log) {
    logLines = [];
    logEl.textContent = "No output yet.";
    return;
  }
  logLines = String(log).split("\n").filter((line) => line.length > 0).slice(-LOG_MAX_LINES);
  logEl.textContent = logLines.join("\n");
}

function flushPendingLogs() {
  if (!pendingLogLines.length) {
    return;
  }
  if (logLines.length === 0 && logEl.textContent === "No output yet.") {
    logEl.textContent = "";
  }
  logLines.push(...pendingLogLines);
  pendingLogLines = [];
  if (logLines.length > LOG_MAX_LINES) {
    logLines = logLines.slice(logLines.length - LOG_MAX_LINES);
  }
  logEl.textContent = logLines.join("\n");
  logEl.scrollTop = logEl.scrollHeight;
}

function scheduleLogFlush() {
  if (logFlushTimer !== null) {
    return;
  }
  logFlushTimer = setTimeout(() => {
    logFlushTimer = null;
    flushPendingLogs();
  }, LOG_FLUSH_INTERVAL_MS);
}

function appendLogLine(line) {
  const text = String(line || "").trim();
  if (!text) {
    return;
  }
  pendingLogLines.push(text);
  scheduleLogFlush();
}

function setRunButtonState(running) {
  simulationRunning = running;
  runBtn.textContent = running ? "Stop" : "Run";
  if (simulationEngineEl) {
    simulationEngineEl.disabled = running;
  }
}

function keyIndexOf(button) {
  const index = Number(button.dataset.keyIndex);
  return Number.isInteger(index) && index >= 0 && index <= 3 ? index : null;
}

function renderKeys() {
  if (!keyValueEl) {
    return;
  }

  const keyNValue = (~keyPressedMask) & 0xF;
  keyValueEl.textContent = `KEY = ${keyNValue.toString(2).padStart(4, "0")} (mask=0x${keyPressedMask.toString(16).toUpperCase()})`;

  for (const button of keyButtons) {
    const index = keyIndexOf(button);
    if (index === null) {
      continue;
    }
    const pressed = ((keyPressedMask >> index) & 1) === 1;
    button.setAttribute("aria-pressed", pressed ? "true" : "false");
  }
}

function handleStreamEvent(event) {
  if (!event || typeof event !== "object") {
    return;
  }

  switch (event.type) {
    case "start":
      renderLabels(event.labels || {});
      ensureVgaSize(event.vga_width, event.vga_height);
      updateVgaLabel();
      setStatus(
        event.cycle_accurate
          ? "Running RTL, cycle-accurate"
          : "Running fast, architectural",
        "ok",
      );
      break;
    case "pixel":
      setVgaPixel(Number(event.addr), Number(event.color));
      break;
    case "pixels":
      setVgaPixels(event.pixels);
      break;
    case "snapshot":
      renderRegisters(event.registers || {});
      renderMemory(event.memory || []);
      renderLabels(event.labels || {});
      renderVga(event.framebuffer || [], event.vga_width, event.vga_height);
      break;
    case "log":
      appendLogLine(event.line || "");
      break;
    case "error":
      streamErrorMessage = event.message || "Simulation error";
      appendLogLine(streamErrorMessage);
      setStatus(streamErrorMessage, "error");
      break;
    case "done":
      streamDoneReceived = true;
      if (!streamErrorMessage) {
        appendLogLine("Simulation finished.");
      }
      break;
  }
}

function dispatchJsonLine(line, onEvent) {
  const trimmed = line.trim();
  if (!trimmed) {
    return;
  }
  try {
    onEvent(JSON.parse(trimmed));
  } catch {
    appendLogLine(`Invalid stream payload: ${trimmed}`);
  }
}

async function consumeNdjsonStream(response, onEvent) {
  if (!response.body) {
    throw new Error("Streaming response body not available.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      dispatchJsonLine(line, onEvent);
    }
  }

  dispatchJsonLine(buffer, onEvent);
}

function resetPanels() {
  renderRegisters({});
  renderMemory([]);
  renderLabels({});
  renderLog("");
  resetVga();
}

async function runSimulation() {
  if (simulationRunning && streamController) {
    streamController.abort();
    return;
  }

  setStatus("Assembling…", "ok");
  setRunButtonState(true);

  const payload = {
    program: programEl.value,
    mem_start: Number(memStartEl.value || 0),
    mem_end: Number(memEndEl.value || 0),
    key_mask: keyPressedMask,
    engine: simulationEngineEl ? simulationEngineEl.value : "fast",
  };
  resetPanels();
  streamErrorMessage = null;
  streamDoneReceived = false;

  const controller = new AbortController();
  streamController = controller;

  try {
    const response = await fetch("/api/simulate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || "Simulation stream failed");
    }

    await consumeNdjsonStream(response, handleStreamEvent);
    if (!controller.signal.aborted && !streamErrorMessage && !streamDoneReceived) {
      throw new Error("Simulation stream ended before the final done event.");
    }
    if (!controller.signal.aborted && !streamErrorMessage) {
      setStatus("Finished", "ok");
    }
  } catch (err) {
    if (controller.signal.aborted) {
      if (!streamErrorMessage) {
        appendLogLine("Simulation stopped by user.");
        setStatus("Stopped", "ok");
      }
    } else {
      const msg = err instanceof Error ? err.message : String(err);
      appendLogLine(msg);
      setStatus(msg, "error");
    }
  } finally {
    if (logFlushTimer !== null) {
      clearTimeout(logFlushTimer);
      logFlushTimer = null;
    }
    flushPendingLogs();
    if (vgaDirty) {
      drawVgaBuffer();
    }
    if (streamController === controller) {
      streamController = null;
    }
    setRunButtonState(false);
  }
}


programEl.addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    const target = e.target;
    target.setRangeText("    ", target.selectionStart, target.selectionEnd, "end");
  }
});

runBtn.addEventListener("click", runSimulation);

for (const button of keyButtons) {
  button.addEventListener("click", () => {
    const index = keyIndexOf(button);
    if (index === null) {
      return;
    }
    keyPressedMask ^= (1 << index);
    renderKeys();
  });
}

if (keyReleaseBtn) {
  keyReleaseBtn.addEventListener("click", () => {
    keyPressedMask = 0;
    renderKeys();
  });
}

resetPanels();
renderKeys();
setStatus("Ready", "ok");
