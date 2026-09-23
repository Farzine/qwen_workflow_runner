/**
 * ui/tests/test_challenger_m2_node.js
 *
 * Empirical Challenge Harness for Milestone 2 Frontend State Machine & Interactivity.
 * Executed via Node.js v22.
 *
 * Stress-tests:
 * 1. Reference slot ordering logic: 0 images, 1 image, 10 images, 11th image addition attempt.
 * 2. Slot 1 strictly canvas vs slots 2-10 references in badges, classes, and comparison viewer.
 * 3. Reordering logic: move up/down, boundaries, removing slots, clearing all.
 * 4. Slider <-> numeric input bidirectional synchronization.
 * 5. Parameter validation for out-of-bounds numbers and invalid characters.
 */

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert");

// Load HTML and extract all element IDs
const htmlPath = path.resolve(__dirname, "../templates/index.html");
const html = fs.readFileSync(htmlPath, "utf8");

// Simple regex to extract IDs from index.html
const idMatches = [...html.matchAll(/id=["']([^"']+)["']/g)].map((m) => m[1]);
const knownIds = new Set(idMatches);

class Node {}

// Build mock DOM environment
function createMockElement(id, tag = "div") {
  const listeners = {};
  const classListSet = new Set();
  const attributes = {};
  const dataset = {};
  const children = [];

  let directText = "";
  let innerHTMLVal = "";

  const elem = {
    id: id || "",
    tagName: tag.toUpperCase(),
    value: "",
    checked: false,
    disabled: false,
    style: {},
    dataset,
    children,
    parentNode: null,

    classList: {
      add(...classes) {
        classes.forEach((c) => classListSet.add(c));
      },
      remove(...classes) {
        classes.forEach((c) => classListSet.delete(c));
      },
      contains(c) {
        return classListSet.has(c);
      },
      toggle(c, force) {
        if (force !== undefined) {
          if (force) classListSet.add(c);
          else classListSet.delete(c);
        } else {
          if (classListSet.has(c)) classListSet.delete(c);
          else classListSet.add(c);
        }
      },
    },

    setAttribute(k, v) {
      attributes[k] = String(v);
    },
    getAttribute(k) {
      return attributes[k] !== undefined ? attributes[k] : null;
    },
    removeAttribute(k) {
      delete attributes[k];
    },

    addEventListener(event, fn) {
      if (!listeners[event]) listeners[event] = [];
      listeners[event].push(fn);
    },
    removeEventListener(event, fn) {
      if (!listeners[event]) return;
      listeners[event] = listeners[event].filter((f) => f !== fn);
    },
    dispatchEvent(event) {
      const type = typeof event === "string" ? event : event.type;
      const evtObj = typeof event === "string" ? { type, target: elem } : { ...event, target: elem };
      if (listeners[type]) {
        for (const fn of listeners[type]) {
          fn(evtObj);
        }
      }
    },

    appendChild(child) {
      if (!child) return child;
      if (child.tagName === "FRAGMENT") {
        for (const sub of [...child.children]) {
          sub.parentNode = elem;
          children.push(sub);
        }
        child.children.length = 0;
        return child;
      }
      children.push(child);
      if (typeof child === "object") {
        child.parentNode = elem;
      }
      return child;
    },
    removeChild(child) {
      const idx = children.indexOf(child);
      if (idx !== -1) children.splice(idx, 1);
      return child;
    },
    querySelectorAll(sel) {
      const res = [];
      function recurse(node) {
        for (const c of node.children || []) {
          if (typeof c === "object" && c !== null && c.classList) {
            if (sel.startsWith(".") && c.classList.contains(sel.slice(1))) {
              res.push(c);
            } else if (sel.startsWith("#") && c.id === sel.slice(1)) {
              res.push(c);
            }
            recurse(c);
          }
        }
      }
      recurse(elem);
      return res;
    },
    querySelector(sel) {
      return this.querySelectorAll(sel)[0] || null;
    },
    focus() {},
  };

  // Sync className property
  Object.defineProperty(elem, "className", {
    get() {
      return [...classListSet].join(" ");
    },
    set(v) {
      classListSet.clear();
      if (v) v.split(/\s+/).forEach((c) => c && classListSet.add(c));
    },
  });

  // textContent property
  Object.defineProperty(elem, "textContent", {
    get() {
      if (children.length > 0) {
        return children
          .map((c) => (typeof c === "object" && c !== null ? c.textContent || "" : String(c)))
          .join("");
      }
      return directText;
    },
    set(v) {
      directText = String(v);
      children.length = 0;
    },
  });

  // innerHTML property
  Object.defineProperty(elem, "innerHTML", {
    get() {
      return innerHTMLVal;
    },
    set(v) {
      innerHTMLVal = String(v);
      if (v === "") {
        children.length = 0;
        directText = "";
      }
    },
  });

  Object.setPrototypeOf(elem, Node.prototype);
  return elem;
}

// Global registry of DOM elements
const domRegistry = new Map();
function getOrCreateElement(id, tag = "div") {
  if (!domRegistry.has(id)) {
    domRegistry.set(id, createMockElement(id, tag));
  }
  return domRegistry.get(id);
}

// Pre-populate with all known IDs from index.html
for (const id of knownIds) {
  getOrCreateElement(id);
}

// Specific input attributes from index.html
const stepsSlider = getOrCreateElement("slider-steps", "input");
stepsSlider.value = "25";
const stepsParam = getOrCreateElement("param-steps", "input");
stepsParam.value = "25";

const cfgSlider = getOrCreateElement("slider-cfg", "input");
cfgSlider.value = "1.0";
const cfgParam = getOrCreateElement("param-cfg", "input");
cfgParam.value = "1.0";

const strSlider = getOrCreateElement("slider-strength", "input");
strSlider.value = "1.0";
const strParam = getOrCreateElement("param-strength", "input");
strParam.value = "1.0";

const shiftSlider = getOrCreateElement("slider-shift", "input");
shiftSlider.value = "0.69";
const shiftParam = getOrCreateElement("param-shift", "input");
shiftParam.value = "0.69";

// Mock document object
const mockDocument = {
  getElementById(id) {
    return domRegistry.get(id) || null;
  },
  createElement(tag) {
    return createMockElement(null, tag);
  },
  createDocumentFragment() {
    return createMockElement(null, "fragment");
  },
  createTextNode(text) {
    const textNode = {
      nodeType: 3,
      textContent: String(text),
      parentNode: null,
    };
    Object.setPrototypeOf(textNode, Node.prototype);
    return textNode;
  },
  querySelectorAll(sel) {
    const res = [];
    for (const elem of domRegistry.values()) {
      if (sel.startsWith("#") && elem.id === sel.slice(1)) {
        res.push(elem);
      } else if (sel.startsWith(".") && elem.classList.contains(sel.slice(1))) {
        res.push(elem);
      }
    }
    return res;
  },
  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  },
  addEventListener() {},
  readyState: "complete",
};

// Mock window object
const mockWindow = {
  Node,
  crypto: {
    getRandomValues(arr) {
      for (let i = 0; i < arr.length; i++) {
        arr[i] = Math.floor(Math.random() * 0xffffffff);
      }
      return arr;
    },
  },
};

// Sandbox context
const sandbox = {
  Node,
  document: mockDocument,
  window: mockWindow,
  globalThis: null,
  console: {
    log: () => {},
    warn: () => {},
    error: () => {},
    info: () => {},
  },
  setTimeout: (fn, delay) => {
    return setTimeout(fn, delay);
  },
  clearTimeout: (id) => clearTimeout(id),
  fetch: async (url, opts) => {
    return {
      ok: true,
      status: 200,
      json: async () => ({ status: "ok", valid: true }),
    };
  },
  EventSource: class {
    constructor() {}
    close() {}
    addEventListener() {}
  },
};
sandbox.globalThis = sandbox;

// Read app.js and expose modules for empirical testing
let appJsCode = fs.readFileSync(path.resolve(__dirname, "../static/js/app.js"), "utf8");

// Expose internal modules to sandbox.__APP_MODULES__ without modifying the source file
const wrappedCode = appJsCode.replace(
  /\(function\s*\(\)\s*\{/,
  `(function () {\n`
).replace(
  /\}\)\(\);?\s*$/,
  `  globalThis.__APP_MODULES__ = {
       Utils, Toast, Store, ApiClient, Lightbox, InputBrowser,
       ParamForm, ModelManager, RunController,
       TerminalViewer, OutputViewer, ComparisonSlider, JsonInspector, RunHistory, App
     };
   })();`
);

vm.createContext(sandbox);
vm.runInContext(wrappedCode, sandbox);

const modules = sandbox.__APP_MODULES__;
assert(modules, "Failed to load app.js modules in test sandbox");

const { Store, InputBrowser, ParamForm, RunController, ComparisonSlider, Toast, Utils, ApiClient } = modules;
const RunHub = RunController;

// Intercept Toast messages for verification
const toastLog = [];
const originalToastShow = Toast.show;
Toast.show = function (msg, type = "info") {
  toastLog.push({ msg, type });
};

// Intercept alert messages
let lastAlertMessages = [];
InputBrowser.showErrorBanner = function (msgs) {
  lastAlertMessages = msgs;
};

// Run tests
let totalTests = 0;
let passedTests = 0;
const testQueue = [];

function runTest(name, fn) {
  testQueue.push({ name, fn });
}

// Initialize components
InputBrowser.init();
ParamForm.init();
ComparisonSlider.init();
RunHub.init();

function assertJsonEqual(actual, expected, msg) {
  assert.deepStrictEqual(JSON.parse(JSON.stringify(actual)), JSON.parse(JSON.stringify(expected)), msg);
}

runTest("Boundary at 0 images: initial state is empty", () => {
  InputBrowser.clearAll();
  assert.strictEqual(Store.state.inputs.selected.length, 0);
  assertJsonEqual(Store.state.config.generation.images, []);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "0 / 10");
});

runTest("Boundary at 0 images: RunHub blocks execution with error banner & warning toast", async () => {
  InputBrowser.clearAll();
  toastLog.length = 0;
  lastAlertMessages = [];

  await RunHub.startRun();

  assert.strictEqual(toastLog.length, 1);
  assert.strictEqual(toastLog[0].type, "warning");
  assert.match(toastLog[0].msg, /at least 1 reference image/i);
  assert.strictEqual(lastAlertMessages.length, 1);
  assert.match(lastAlertMessages[0], /Provide 1–10 ordered reference images/i);
  assert.strictEqual(Store.state.run.status, "idle");
});

runTest("Boundary at 1 image: select 1 image assigns #1 Canvas", () => {
  InputBrowser.clearAll();
  const img1 = { name: "portrait_canvas.png", path: "/mnt/lab/farzine/inputs/portrait_canvas.png", width: 1024, height: 1024 };

  InputBrowser.toggleSelection(img1);

  assert.strictEqual(Store.state.inputs.selected.length, 1);
  assertJsonEqual(Store.state.config.generation.images, [img1.path]);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "1 / 10");

  // Inspect slot card rendering
  const slotCards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(slotCards.length, 1);
  const card = slotCards[0];
  assert(card.className.includes("slot-card-canvas"), "Slot 1 card must have slot-card-canvas class");

  // Verify badge text is #1 Canvas
  const badge = card.querySelector(".badge");
  assert(badge, "Badge must be rendered");
  assert.strictEqual(badge.textContent, "#1 Canvas");
  assert(badge.className.includes("badge-accent"), "Slot 1 must have badge-accent");
});

runTest("Slot 1 Canvas vs Slots 2–10 References: distinct badges and classes", () => {
  InputBrowser.clearAll();
  const img1 = { name: "img1.png", path: "/inputs/img1.png", width: 512, height: 512 };
  const img2 = { name: "img2.png", path: "/inputs/img2.png", width: 512, height: 512 };
  const img3 = { name: "img3.png", path: "/inputs/img3.png", width: 512, height: 512 };

  InputBrowser.toggleSelection(img1);
  InputBrowser.toggleSelection(img2);
  InputBrowser.toggleSelection(img3);

  assert.strictEqual(Store.state.inputs.selected.length, 3);
  assertJsonEqual(Store.state.config.generation.images, [img1.path, img2.path, img3.path]);

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards.length, 3);

  // Slot 1: Canvas
  assert(cards[0].className.includes("slot-card-canvas"));
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "#1 Canvas");
  assert(cards[0].querySelector(".badge").className.includes("badge-accent"));

  // Slot 2: Ref
  assert(!cards[1].className.includes("slot-card-canvas"));
  assert.strictEqual(cards[1].querySelector(".badge").textContent, "#2 Ref");
  assert(cards[1].querySelector(".badge").className.includes("badge-primary"));

  // Slot 3: Ref
  assert(!cards[2].className.includes("slot-card-canvas"));
  assert.strictEqual(cards[2].querySelector(".badge").textContent, "#3 Ref");
  assert(cards[2].querySelector(".badge").className.includes("badge-primary"));
});

runTest("ComparisonSlider strictly consumes Slot 1 as Canvas for comparison", () => {
  const outputs = [{ url: "/api/outputs/run_001.png", filename: "run_001.png" }];
  ComparisonSlider.setup(outputs, "/api/outputs/run_001_comparison.png");

  // ComparisonSlider sets beforeImg src to Slot 1 thumbnail
  assert.strictEqual(ComparisonSlider.beforeImg.src, "/api/inputs/thumbnail?path=%2Finputs%2Fimg1.png&size=1024");
  assert.strictEqual(ComparisonSlider.afterImg.src, "/api/outputs/run_001.png");
});

runTest("Reordering logic: moving slot 0 down swaps Canvas role to new first item", () => {
  // Current order: [img1, img2, img3]
  InputBrowser.moveSlot(0, 1);

  // New order must be: [img2, img1, img3]
  assertJsonEqual(Store.state.config.generation.images, [
    "/inputs/img2.png",
    "/inputs/img1.png",
    "/inputs/img3.png",
  ]);

  const cards = InputBrowser.selectedSlotsList.children;
  // img2 is now Slot 1 Canvas!
  assert.strictEqual(cards[0].querySelector(".slot-filename").textContent, "img2.png");
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "#1 Canvas");
  assert(cards[0].className.includes("slot-card-canvas"));

  // img1 is now Slot 2 Ref!
  assert.strictEqual(cards[1].querySelector(".slot-filename").textContent, "img1.png");
  assert.strictEqual(cards[1].querySelector(".badge").textContent, "#2 Ref");
});

runTest("Reordering logic: out-of-bounds moves are safely ignored without modification", () => {
  // Move slot 0 earlier (direction -1) -> out of bounds
  InputBrowser.moveSlot(0, -1);
  assert.strictEqual(Store.state.inputs.selected[0].name, "img2.png");

  // Move slot 2 later (direction +1) -> out of bounds (targetIdx 3 >= length 3)
  InputBrowser.moveSlot(2, 1);
  assert.strictEqual(Store.state.inputs.selected[2].name, "img3.png");

  // Arbitrary out of bounds
  InputBrowser.moveSlot(-5, -1);
  InputBrowser.moveSlot(10, 1);
  assert.strictEqual(Store.state.inputs.selected.length, 3);
});

runTest("Slot removal: removing slot 0 shifts subsequent items and re-badges Slot 1 Canvas", () => {
  // Current order: [img2, img1, img3]
  InputBrowser.removeSlot(0);

  // New order: [img1, img3]
  assert.strictEqual(Store.state.inputs.selected.length, 2);
  assertJsonEqual(Store.state.config.generation.images, ["/inputs/img1.png", "/inputs/img3.png"]);

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards[0].querySelector(".slot-filename").textContent, "img1.png");
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "#1 Canvas");
  assert.strictEqual(cards[1].querySelector(".badge").textContent, "#2 Ref");
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "2 / 10");
});

runTest("Boundary at 10 images: can select up to exactly 10 images", () => {
  InputBrowser.clearAll();
  for (let i = 1; i <= 10; i++) {
    InputBrowser.toggleSelection({
      name: `img_${i}.png`,
      path: `/inputs/img_${i}.png`,
      width: 1024,
      height: 1024,
    });
  }

  assert.strictEqual(Store.state.inputs.selected.length, 10);
  assert.strictEqual(Store.state.config.generation.images.length, 10);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "10 / 10");

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards.length, 10);
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "#1 Canvas");
  assert.strictEqual(cards[9].querySelector(".badge").textContent, "#10 Ref");
});

runTest("Boundary at 11th image: addition attempt is blocked with toast warning & banner", () => {
  toastLog.length = 0;
  lastAlertMessages = [];

  const img11 = { name: "img_11.png", path: "/inputs/img_11.png", width: 1024, height: 1024 };
  InputBrowser.toggleSelection(img11);

  // Selection must strictly remain 10 items
  assert.strictEqual(Store.state.inputs.selected.length, 10, "Selected items must NOT exceed 10");
  assert.strictEqual(Store.state.config.generation.images.length, 10);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "10 / 10");

  // Warning must be triggered
  assert(toastLog.some((t) => t.type === "warning" && t.msg.includes("Maximum 10 reference images")));
  assert(lastAlertMessages.some((m) => m.includes("Maximum 10 reference images")));
});

runTest("Deselection at boundary: removing 1 image drops count to 9, allowing new image", () => {
  // Deselect img_5 by toggling it
  InputBrowser.toggleSelection({ path: "/inputs/img_5.png" });
  assert.strictEqual(Store.state.inputs.selected.length, 9);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "9 / 10");

  // Now adding img_11 succeeds
  const img11 = { name: "img_11.png", path: "/inputs/img_11.png", width: 1024, height: 1024 };
  InputBrowser.toggleSelection(img11);
  assert.strictEqual(Store.state.inputs.selected.length, 10);
  assert.strictEqual(Store.state.inputs.selected[9].name, "img_11.png");
});

console.log("\n[TEST GROUP 2: Parameter Inputs, Slider Sync & Live Validation]");

runTest("Slider <-> numeric input synchronization: steps slider to number", () => {
  stepsSlider.value = "45";
  stepsSlider.dispatchEvent("input");

  assert.strictEqual(stepsParam.value, "45");
  assert.strictEqual(Store.state.config.generation.steps, 45);
});

runTest("Slider <-> numeric input synchronization: steps number to slider", () => {
  stepsParam.value = "60";
  stepsParam.dispatchEvent("input");

  assert.strictEqual(stepsSlider.value, "60");
  assert.strictEqual(Store.state.config.generation.steps, 60);
});

runTest("Slider <-> numeric input synchronization: CFG, Strength, Shift", () => {
  cfgSlider.value = "3.5";
  cfgSlider.dispatchEvent("input");
  assert.strictEqual(cfgParam.value, "3.5");
  assert.strictEqual(Store.state.config.generation.cfg, 3.5);

  strSlider.value = "0.85";
  strSlider.dispatchEvent("input");
  assert.strictEqual(strParam.value, "0.85");
  assert.strictEqual(Store.state.config.generation.strength, 0.85);

  shiftSlider.value = "1.5";
  shiftSlider.dispatchEvent("input");
  assert.strictEqual(shiftParam.value, "1.5");
  assert.strictEqual(Store.state.config.generation.shift, 1.5);
});

runTest("Boundary Validation: steps out of bounds (< 1 or > 10000)", async () => {
  // Reset presets
  ParamForm.applyDefaultPresets();

  // Test steps = 0 or -5
  Store.state.config.generation.steps = -5;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("steps must be between 1 and 10000")));
  assert.strictEqual(domRegistry.get("btn-run-pipeline").disabled, true);

  // Test steps = 10001
  Store.state.config.generation.steps = 10001;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("steps must be between 1 and 10000")));
});

runTest("Boundary Validation: negative CFG scale", async () => {
  ParamForm.applyDefaultPresets();
  Store.state.config.generation.cfg = -0.5;

  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("cfg scale must be non-negative")));
  assert.strictEqual(domRegistry.get("btn-run-pipeline").disabled, true);
});

runTest("Boundary Validation: denoise strength <= 0 or > 1.0", async () => {
  ParamForm.applyDefaultPresets();

  Store.state.config.generation.strength = 0.0;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("denoise strength must be in range (0, 1]")));

  Store.state.config.generation.strength = 1.25;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("denoise strength must be in range (0, 1]")));
});

runTest("Boundary Validation: steps / strength schedule limit (> 10000)", async () => {
  ParamForm.applyDefaultPresets();
  Store.state.config.generation.steps = 2000;
  Store.state.config.generation.strength = 0.05; // 2000 / 0.05 = 40000 > 10000

  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("steps / strength exceeds the 10000-point schedule")));
});

runTest("Boundary Validation: shift out of bounds [-10, 10]", async () => {
  ParamForm.applyDefaultPresets();

  Store.state.config.generation.shift = 12.5;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("shift must be between -10.0 and 10.0")));

  Store.state.config.generation.shift = -15.0;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("shift must be between -10.0 and 10.0")));
});

runTest("Boundary Validation: custom resolution and width not divisible by 32", async () => {
  ParamForm.applyDefaultPresets();

  // Resolution = 500 (not divisible by 32)
  Store.state.config.generation.resolution = 500;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("resolution must be 0 or a multiple of 32")));

  // Custom size width = 500
  Store.state.config.generation.resolution = 0;
  Store.state.config.generation.custom_size = true;
  Store.state.config.generation.width = 500;
  Store.state.config.generation.height = 1024;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("custom width must be a positive multiple of 32")));
});

runTest("Boundary Validation: hardware compatibility guards (CPU with float16 / offload)", async () => {
  ParamForm.applyDefaultPresets();

  // CPU with float16
  Store.state.config.runtime.device = "cpu";
  Store.state.config.runtime.dtype = "float16";
  Store.state.config.runtime.offload = "none";
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("For CPU execution, dtype must be float32")));

  // CPU with offload != none
  Store.state.config.runtime.dtype = "float32";
  Store.state.config.runtime.offload = "model";
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("For CPU execution, offload must be none")));

  // MPS with offload != none
  Store.state.config.runtime.device = "mps";
  Store.state.config.runtime.offload = "sequential";
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("MPS requires offload='none'")));
});

runTest("Boundary Validation: filename prefix with directory slashes rejected", async () => {
  ParamForm.applyDefaultPresets();

  Store.state.config.runtime.filename_prefix = "subdir/my_prefix";
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("filename_prefix must be a clean filename without directory slashes")));
});

runTest("Invalid characters resilience: non-numeric inputs do not crash or produce unhandled errors", () => {
  ParamForm.applyDefaultPresets();

  // Entering invalid characters into numeric fields
  stepsParam.value = "not_a_number_abc";
  stepsParam.dispatchEvent("input");
  assert.strictEqual(Store.state.config.generation.steps, 25); // Fallback to 25

  cfgParam.value = "xyz_invalid";
  cfgParam.dispatchEvent("input");
  assert.strictEqual(Store.state.config.generation.cfg, 1.0); // Fallback to 1.0

  strParam.value = "invalid!@#";
  strParam.dispatchEvent("input");
  assert.strictEqual(Store.state.config.generation.strength, 1.0); // Fallback to 1.0

  shiftParam.value = "invalid_shift";
  shiftParam.dispatchEvent("input");
  assert.strictEqual(Store.state.config.generation.shift, 0.69); // Fallback to 0.69
});

runTest("Reordering & Canvas Badging: Multi-step slot shift promotes item to Canvas", () => {
  InputBrowser.clearAll();
  const imgs = [
    { name: "A.png", path: "/inputs/A.png", width: 512, height: 512 },
    { name: "B.png", path: "/inputs/B.png", width: 512, height: 512 },
    { name: "C.png", path: "/inputs/C.png", width: 512, height: 512 },
    { name: "D.png", path: "/inputs/D.png", width: 512, height: 512 },
  ];
  imgs.forEach((img) => InputBrowser.toggleSelection(img));

  assert.strictEqual(Store.state.inputs.selected.length, 4);
  assert.strictEqual(Store.state.inputs.selected[0].name, "A.png");

  // Shift D from slot 3 to slot 0:
  InputBrowser.moveSlot(3, -1); // [A, B, D, C]
  InputBrowser.moveSlot(2, -1); // [A, D, B, C]
  InputBrowser.moveSlot(1, -1); // [D, A, B, C]

  assertJsonEqual(Store.state.config.generation.images, [
    "/inputs/D.png",
    "/inputs/A.png",
    "/inputs/B.png",
    "/inputs/C.png",
  ]);

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards.length, 4);

  // Slot 0 (D.png): strictly #1 Canvas
  assert(cards[0].className.includes("slot-card-canvas"));
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "#1 Canvas");
  assert(cards[0].querySelector(".badge").className.includes("badge-accent"));
  assert.strictEqual(cards[0].querySelector(".slot-filename").textContent, "D.png");

  // Slots 1-3 (A, B, C): strictly References
  assert(!cards[1].className.includes("slot-card-canvas"));
  assert.strictEqual(cards[1].querySelector(".badge").textContent, "#2 Ref");
  assert.strictEqual(cards[1].querySelector(".slot-filename").textContent, "A.png");

  assert(!cards[2].className.includes("slot-card-canvas"));
  assert.strictEqual(cards[2].querySelector(".badge").textContent, "#3 Ref");
  assert.strictEqual(cards[2].querySelector(".slot-filename").textContent, "B.png");

  assert(!cards[3].className.includes("slot-card-canvas"));
  assert.strictEqual(cards[3].querySelector(".badge").textContent, "#4 Ref");
  assert.strictEqual(cards[3].querySelector(".slot-filename").textContent, "C.png");

  // Verify ComparisonSlider setup now binds D.png as Canvas
  ComparisonSlider.setup([{ url: "/api/outputs/run_002.png", filename: "run_002.png" }]);
  assert(ComparisonSlider.beforeImg.src.includes("%2Finputs%2FD.png"));
});

runTest("Slot Removal: Removing mid-sequence slot shifts subsequent items preserving Canvas", () => {
  // Current order: [D, A, B, C]. Remove slot 1 (A.png):
  InputBrowser.removeSlot(1);

  assert.strictEqual(Store.state.inputs.selected.length, 3);
  assertJsonEqual(Store.state.config.generation.images, [
    "/inputs/D.png",
    "/inputs/B.png",
    "/inputs/C.png",
  ]);

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards.length, 3);
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "#1 Canvas");
  assert.strictEqual(cards[0].querySelector(".slot-filename").textContent, "D.png");

  assert.strictEqual(cards[1].querySelector(".badge").textContent, "#2 Ref");
  assert.strictEqual(cards[1].querySelector(".slot-filename").textContent, "B.png");

  assert.strictEqual(cards[2].querySelector(".badge").textContent, "#3 Ref");
  assert.strictEqual(cards[2].querySelector(".slot-filename").textContent, "C.png");
});

runTest("Schedule calculation ratio hint dynamically computes steps/strength and turns red over 10000", () => {
  const ratioLabel = domRegistry.get("schedule-calc-ratio");

  // Valid ratio: 25 / 1.0 = 25
  Store.state.config.generation.steps = 25;
  Store.state.config.generation.strength = 1.0;
  ParamForm.updateScheduleRatio();
  assert.strictEqual(ratioLabel.textContent, "steps/strength = 25");
  assert.strictEqual(ratioLabel.style.color, "");

  // Out of bound ratio: 50 / 0.001 = 50000 > 10000
  Store.state.config.generation.steps = 50;
  Store.state.config.generation.strength = 0.001;
  ParamForm.updateScheduleRatio();
  assert.strictEqual(ratioLabel.textContent, "steps/strength = 50000");
  assert.notStrictEqual(ratioLabel.style.color, ""); // Red/danger style applied
});

runTest("Special characters in image paths: URL encoding and escape safety", () => {
  InputBrowser.clearAll();
  const specialImg = {
    name: "photo & edit (v2) [final].png",
    path: "/mnt/lab/inputs/photo & edit (v2) [final].png",
    width: 1024,
    height: 1024,
  };
  InputBrowser.toggleSelection(specialImg);

  assert.strictEqual(Store.state.inputs.selected.length, 1);
  const encodedThumb = ApiClient.getThumbnailUrl(specialImg.path, 256);
  assert(encodedThumb.includes("photo%20%26%20edit%20(v2)%20%5Bfinal%5D.png"));

  const card = InputBrowser.selectedSlotsList.children[0];
  assert.strictEqual(card.querySelector(".slot-filename").textContent, "photo & edit (v2) [final].png");
});

(async function runAll() {
  console.log("\n=======================================================");
  console.log("CHALLENGER M2: Node.js Frontend State Machine Harness");
  console.log("=======================================================\n");

  for (const { name, fn } of testQueue) {
    totalTests++;
    try {
      await fn();
      passedTests++;
      console.log(`  ✓ ${name}`);
    } catch (err) {
      console.error(`  ✗ FAIL: ${name}`);
      console.error(`    ${err.stack || err.message}`);
      process.exitCode = 1;
    }
  }

  console.log("\n=======================================================");
  console.log(`RESULTS: ${passedTests} / ${totalTests} tests passed`);
  console.log("=======================================================\n");

  if (passedTests !== totalTests) {
    process.exit(1);
  }
})();
