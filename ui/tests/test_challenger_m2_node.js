/**
 * ui/tests/test_challenger_m2_node.js
 *
 * Empirical Challenge Harness for Milestone 2 Frontend State Machine & Interactivity.
 * Executed via Node.js v22.
 *
 * Stress-tests:
 * 1. Process-input ordering logic: 0 images, 1 image, 10 images, 11th image addition attempt.
 * 2. Shared-reference role selection, independent limits, badges, and prompt-token mapping.
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

// The served HTML supplies the native input default before app.js loads.
const outputDirField = getOrCreateElement("param-output-dir", "input");
outputDirField.defaultValue = "/tmp/server-output-root";
outputDirField.value = outputDirField.defaultValue;

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
       ParamForm, PageNavigation, ModelManager, LoRAManager, SystemManager, RunController,
       TerminalViewer, OutputViewer, ComparisonSlider, JsonInspector, RunHistory, Dashboard, App
     };
   })();`
);

vm.createContext(sandbox);
vm.runInContext(wrappedCode, sandbox);

const modules = sandbox.__APP_MODULES__;
assert(modules, "Failed to load app.js modules in test sandbox");

const { Store, InputBrowser, ParamForm, PageNavigation, ModelManager, LoRAManager, SystemManager, RunController, ComparisonSlider, OutputViewer, JsonInspector, RunHistory, Dashboard, Toast, Utils, ApiClient, App } = modules;
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

runTest("Output directory initializes from the server and presets restore that default", () => {
  assert.strictEqual(Store.state.config.runtime.output_dir, outputDirField.defaultValue);
  outputDirField.value = "/tmp/user-override";
  outputDirField.dispatchEvent("input");
  assert.strictEqual(Store.state.config.runtime.output_dir, "/tmp/user-override");
  outputDirField.value = "";
  outputDirField.dispatchEvent("input");
  assert.strictEqual(Store.state.config.runtime.output_dir, "", "Clearing delegates to the server default");
  ParamForm.applyDefaultPresets();
  assert.strictEqual(Store.state.config.runtime.output_dir, outputDirField.defaultValue);
  assert.strictEqual(outputDirField.value, outputDirField.defaultValue);
});

runTest("Boundary at 0 images: initial state is empty", () => {
  InputBrowser.clearAll();
  assert.strictEqual(Store.state.inputs.inputImages.length, 0);
  assertJsonEqual(Store.state.config.generation.input_images, []);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "0 / 10");
});

runTest("Boundary at 0 images: RunHub blocks execution with error banner & warning toast", async () => {
  InputBrowser.clearAll();
  toastLog.length = 0;
  lastAlertMessages = [];

  await RunHub.startRun();

  assert.strictEqual(toastLog.length, 1);
  assert.strictEqual(toastLog[0].type, "warning");
  assert.match(toastLog[0].msg, /at least one input image/i);
  assert.strictEqual(lastAlertMessages.length, 1);
  assert.match(lastAlertMessages[0], /Provide 1–10 ordered input images/i);
  assert.strictEqual(Store.state.run.status, "idle");
});

runTest("Boundary at 1 image: select 1 process input", () => {
  InputBrowser.clearAll();
  const img1 = { name: "portrait_canvas.png", path: "/mnt/lab/farzine/inputs/portrait_canvas.png", width: 1024, height: 1024 };

  InputBrowser.toggleSelection(img1);

  assert.strictEqual(Store.state.inputs.inputImages.length, 1);
  assertJsonEqual(Store.state.config.generation.input_images, [img1.path]);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "1 / 10");

  // Inspect slot card rendering
  const slotCards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(slotCards.length, 1);
  const card = slotCards[0];
  assert(card.className.includes("slot-card-input"), "Process input card must have slot-card-input class");

  // Verify explicit process-input role
  const badge = card.querySelector(".badge");
  assert(badge, "Badge must be rendered");
  assert.strictEqual(badge.textContent, "Input 1");
  assert(badge.className.includes("badge-primary"));
});

runTest("Multiple process inputs remain independent ordered inputs", () => {
  InputBrowser.clearAll();
  const img1 = { name: "img1.png", path: "/inputs/img1.png", width: 512, height: 512 };
  const img2 = { name: "img2.png", path: "/inputs/img2.png", width: 512, height: 512 };
  const img3 = { name: "img3.png", path: "/inputs/img3.png", width: 512, height: 512 };

  InputBrowser.toggleSelection(img1);
  InputBrowser.toggleSelection(img2);
  InputBrowser.toggleSelection(img3);

  assert.strictEqual(Store.state.inputs.inputImages.length, 3);
  assertJsonEqual(Store.state.config.generation.input_images, [img1.path, img2.path, img3.path]);

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards.length, 3);

  assert(cards[0].className.includes("slot-card-input"));
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "Input 1");
  assert(cards[1].className.includes("slot-card-input"));
  assert.strictEqual(cards[1].querySelector(".badge").textContent, "Input 2");
  assert(cards[1].querySelector(".badge").className.includes("badge-primary"));
  assert(cards[2].className.includes("slot-card-input"));
  assert.strictEqual(cards[2].querySelector(".badge").textContent, "Input 3");
  assert(cards[2].querySelector(".badge").className.includes("badge-primary"));
});

runTest("ComparisonSlider consumes the first process input by default", () => {
  const outputs = [{ url: "/api/outputs/run_001.png", filename: "run_001.png" }];
  ComparisonSlider.setup(outputs, "/api/outputs/run_001_comparison.png");

  // ComparisonSlider sets beforeImg src to Slot 1 thumbnail
  assert.strictEqual(ComparisonSlider.beforeImg.src, "/api/inputs/thumbnail?path=%2Finputs%2Fimg1.png&size=1024");
  assert.strictEqual(ComparisonSlider.afterImg.src, "/api/outputs/run_001.png");
});

runTest("Reordering logic: moving input 0 down changes process order", () => {
  // Current order: [img1, img2, img3]
  InputBrowser.moveSlot(0, 1);

  // New order must be: [img2, img1, img3]
  assertJsonEqual(Store.state.config.generation.input_images, [
    "/inputs/img2.png",
    "/inputs/img1.png",
    "/inputs/img3.png",
  ]);

  const cards = InputBrowser.selectedSlotsList.children;
  // img2 is now process input 1.
  assert.strictEqual(cards[0].querySelector(".slot-filename").textContent, "img2.png");
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "Input 1");
  assert(cards[0].className.includes("slot-card-input"));

  // img1 is now process input 2.
  assert.strictEqual(cards[1].querySelector(".slot-filename").textContent, "img1.png");
  assert.strictEqual(cards[1].querySelector(".badge").textContent, "Input 2");
});

runTest("Reordering logic: out-of-bounds moves are safely ignored without modification", () => {
  // Move slot 0 earlier (direction -1) -> out of bounds
  InputBrowser.moveSlot(0, -1);
  assert.strictEqual(Store.state.inputs.inputImages[0].name, "img2.png");

  // Move slot 2 later (direction +1) -> out of bounds (targetIdx 3 >= length 3)
  InputBrowser.moveSlot(2, 1);
  assert.strictEqual(Store.state.inputs.inputImages[2].name, "img3.png");

  // Arbitrary out of bounds
  InputBrowser.moveSlot(-5, -1);
  InputBrowser.moveSlot(10, 1);
  assert.strictEqual(Store.state.inputs.inputImages.length, 3);
});

runTest("Input removal shifts subsequent ordered inputs", () => {
  // Current order: [img2, img1, img3]
  InputBrowser.removeSlot(0);

  // New order: [img1, img3]
  assert.strictEqual(Store.state.inputs.inputImages.length, 2);
  assertJsonEqual(Store.state.config.generation.input_images, ["/inputs/img1.png", "/inputs/img3.png"]);

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards[0].querySelector(".slot-filename").textContent, "img1.png");
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "Input 1");
  assert.strictEqual(cards[1].querySelector(".badge").textContent, "Input 2");
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

  assert.strictEqual(Store.state.inputs.inputImages.length, 10);
  assert.strictEqual(Store.state.config.generation.input_images.length, 10);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "10 / 10");

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards.length, 10);
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "Input 1");
  assert.strictEqual(cards[9].querySelector(".badge").textContent, "Input 10");
});

runTest("Boundary at 11th image: addition attempt is blocked with toast warning & banner", () => {
  toastLog.length = 0;
  lastAlertMessages = [];

  const img11 = { name: "img_11.png", path: "/inputs/img_11.png", width: 1024, height: 1024 };
  InputBrowser.toggleSelection(img11);

  // Selection must strictly remain 10 items
  assert.strictEqual(Store.state.inputs.inputImages.length, 10, "Selected items must NOT exceed 10");
  assert.strictEqual(Store.state.config.generation.input_images.length, 10);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "10 / 10");

  // Warning must be triggered
  assert(toastLog.some((t) => t.type === "warning" && t.msg.includes("Maximum 10 input images")));
  assert(lastAlertMessages.some((m) => m.includes("Maximum 10 input images")));
});

runTest("Deselection at boundary: removing 1 image drops count to 9, allowing new image", () => {
  // Deselect img_5 by toggling it
  InputBrowser.toggleSelection({ path: "/inputs/img_5.png" });
  assert.strictEqual(Store.state.inputs.inputImages.length, 9);
  assert.strictEqual(InputBrowser.selectedCountBadge.textContent, "9 / 10");

  // Now adding img_11 succeeds
  const img11 = { name: "img_11.png", path: "/inputs/img_11.png", width: 1024, height: 1024 };
  InputBrowser.toggleSelection(img11);
  assert.strictEqual(Store.state.inputs.inputImages.length, 10);
  assert.strictEqual(Store.state.inputs.inputImages[9].name, "img_11.png");
});

runTest("Reference role keeps shared references separate from process inputs", () => {
  InputBrowser.clearAll();
  const input = { name: "person.png", path: "/inputs/person.png", width: 512, height: 768 };
  const reference = { name: "style.png", path: "/inputs/style.png", width: 640, height: 640 };
  InputBrowser.setActiveRole("input");
  InputBrowser.toggleSelection(input);
  InputBrowser.setActiveRole("reference");
  InputBrowser.toggleSelection(reference);

  assertJsonEqual(Store.state.config.generation.input_images, [input.path]);
  assertJsonEqual(Store.state.config.generation.reference_images, [reference.path]);
  assert.strictEqual(InputBrowser.referenceCountBadge.textContent, "1 / 9");
  const refCard = InputBrowser.referenceSlotsList.children[0];
  assert(refCard.className.includes("slot-card-reference"));
  assert.strictEqual(refCard.querySelector(".badge").textContent, "Ref 1 · <image2>");
});

runTest("Explicit request JSON omits the retired combined images field", () => {
  const serialized = JSON.parse(JSON.stringify(Store.state.config.generation));
  assert(!Object.prototype.hasOwnProperty.call(serialized, "images"));
  assertJsonEqual(serialized.input_images, ["/inputs/person.png"]);
  assertJsonEqual(serialized.reference_images, ["/inputs/style.png"]);
});

runTest("Reference boundary accepts 9 and rejects the 10th reference", () => {
  InputBrowser.clearRole("reference");
  InputBrowser.setActiveRole("reference");
  for (let index = 1; index <= 9; index++) {
    InputBrowser.toggleSelection({ name: `ref_${index}.png`, path: `/inputs/ref_${index}.png`, width: 64, height: 64 });
  }
  assert.strictEqual(Store.state.inputs.referenceImages.length, 9);
  assert.strictEqual(InputBrowser.referenceCountBadge.textContent, "9 / 9");
  toastLog.length = 0;
  InputBrowser.toggleSelection({ name: "ref_10.png", path: "/inputs/ref_10.png", width: 64, height: 64 });
  assert.strictEqual(Store.state.inputs.referenceImages.length, 9);
  assert(toastLog.some((item) => item.type === "warning" && item.msg.includes("Maximum 9 reference images")));
  InputBrowser.setActiveRole("input");
});

runTest("Uploaded images are appended to the active reference role", async () => {
  InputBrowser.clearAll();
  InputBrowser.setActiveRole("reference");
  const originalUpload = ApiClient.uploadInputImages;
  const originalLoadFolder = InputBrowser.loadFolder;
  ApiClient.uploadInputImages = async () => ({
    count: 2,
    images: [
      { name: "style-a.png", original_name: "a-very-long-original-style-filename-that-must-remain-readable-in-the-selection-list.png", path: "/inputs/uploads/style-a.png", width: 320, height: 240 },
      { name: "style-b.png", original_name: "style.png", path: "/inputs/uploads/style-b.png", width: 640, height: 480 },
    ],
  });
  InputBrowser.loadFolder = async () => {};

  try {
    await InputBrowser.uploadFiles([{ name: "style.png" }, { name: "style.png" }]);
    assertJsonEqual(Store.state.config.generation.reference_images, [
      "/inputs/uploads/style-a.png",
      "/inputs/uploads/style-b.png",
    ]);
    assert.strictEqual(Store.state.config.generation.input_images.length, 0);
    assert.strictEqual(InputBrowser.referenceSlotsList.children.length, 2);
    assert.strictEqual(
      InputBrowser.referenceSlotsList.children[0].querySelector(".slot-filename").textContent,
      "a-very-long-original-style-filename-that-must-remain-readable-in-the-selection-list.png"
    );
    assert.strictEqual(InputBrowser.referenceSlotsList.children[1].querySelector(".badge").textContent, "Ref 2 · <image3>");
  } finally {
    ApiClient.uploadInputImages = originalUpload;
    InputBrowser.loadFolder = originalLoadFolder;
    InputBrowser.setActiveRole("input");
  }
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

runTest("Reordering and input badging preserve the process order", () => {
  InputBrowser.clearAll();
  const imgs = [
    { name: "A.png", path: "/inputs/A.png", width: 512, height: 512 },
    { name: "B.png", path: "/inputs/B.png", width: 512, height: 512 },
    { name: "C.png", path: "/inputs/C.png", width: 512, height: 512 },
    { name: "D.png", path: "/inputs/D.png", width: 512, height: 512 },
  ];
  imgs.forEach((img) => InputBrowser.toggleSelection(img));

  assert.strictEqual(Store.state.inputs.inputImages.length, 4);
  assert.strictEqual(Store.state.inputs.inputImages[0].name, "A.png");

  // Shift D from slot 3 to slot 0:
  InputBrowser.moveSlot(3, -1); // [A, B, D, C]
  InputBrowser.moveSlot(2, -1); // [A, D, B, C]
  InputBrowser.moveSlot(1, -1); // [D, A, B, C]

  assertJsonEqual(Store.state.config.generation.input_images, [
    "/inputs/D.png",
    "/inputs/A.png",
    "/inputs/B.png",
    "/inputs/C.png",
  ]);

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards.length, 4);

  // Slot 0 (D.png) is now the first process input.
  assert(cards[0].className.includes("slot-card-input"));
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "Input 1");
  assert(cards[0].querySelector(".badge").className.includes("badge-primary"));
  assert.strictEqual(cards[0].querySelector(".slot-filename").textContent, "D.png");

  // Slots 1-3 remain independently processed inputs.
  assert(cards[1].className.includes("slot-card-input"));
  assert.strictEqual(cards[1].querySelector(".badge").textContent, "Input 2");
  assert.strictEqual(cards[1].querySelector(".slot-filename").textContent, "A.png");

  assert(cards[2].className.includes("slot-card-input"));
  assert.strictEqual(cards[2].querySelector(".badge").textContent, "Input 3");
  assert.strictEqual(cards[2].querySelector(".slot-filename").textContent, "B.png");

  assert(cards[3].className.includes("slot-card-input"));
  assert.strictEqual(cards[3].querySelector(".badge").textContent, "Input 4");
  assert.strictEqual(cards[3].querySelector(".slot-filename").textContent, "C.png");

  // Verify ComparisonSlider setup now binds D.png as the source input.
  ComparisonSlider.setup([{ url: "/api/outputs/run_002.png", filename: "run_002.png" }]);
  assert(ComparisonSlider.beforeImg.src.includes("%2Finputs%2FD.png"));
});

runTest("Slot removal shifts subsequent process inputs", () => {
  // Current order: [D, A, B, C]. Remove slot 1 (A.png):
  InputBrowser.removeSlot(1);

  assert.strictEqual(Store.state.inputs.inputImages.length, 3);
  assertJsonEqual(Store.state.config.generation.input_images, [
    "/inputs/D.png",
    "/inputs/B.png",
    "/inputs/C.png",
  ]);

  const cards = InputBrowser.selectedSlotsList.children;
  assert.strictEqual(cards.length, 3);
  assert.strictEqual(cards[0].querySelector(".badge").textContent, "Input 1");
  assert.strictEqual(cards[0].querySelector(".slot-filename").textContent, "D.png");

  assert.strictEqual(cards[1].querySelector(".badge").textContent, "Input 2");
  assert.strictEqual(cards[1].querySelector(".slot-filename").textContent, "B.png");

  assert.strictEqual(cards[2].querySelector(".badge").textContent, "Input 3");
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

  assert.strictEqual(Store.state.inputs.inputImages.length, 1);
  const encodedThumb = ApiClient.getThumbnailUrl(specialImg.path, 256);
  assert(encodedThumb.includes("photo%20%26%20edit%20(v2)%20%5Bfinal%5D.png"));

  const card = InputBrowser.selectedSlotsList.children[0];
  assert.strictEqual(card.querySelector(".slot-filename").textContent, "photo & edit (v2) [final].png");
});

runTest("LoRA discovery, selection, strength, upload, and clear state stay synchronized", async () => {
  const first = {
    name: "portrait.safetensors",
    path: "/models/loras/portrait.safetensors",
    size: 4096,
    valid: true,
  };
  const uploaded = {
    name: "lighting.safetensors",
    path: "/models/loras/lighting.safetensors",
    size: 8192,
    valid: true,
  };
  let available = [first];
  const originalList = ApiClient.listLoras;
  const originalUpload = ApiClient.uploadLora;
  ApiClient.listLoras = async () => ({ loras: available });
  ApiClient.uploadLora = async () => {
    available = [first, uploaded];
    return { lora: uploaded };
  };

  LoRAManager.select = domRegistry.get("param-model-lora-path");
  LoRAManager.scaleInput = domRegistry.get("param-model-lora-scale");
  LoRAManager.activeStatus = domRegistry.get("lora-active-status");
  LoRAManager.uploadStatus = domRegistry.get("lora-upload-status");
  LoRAManager.fileInput = domRegistry.get("lora-file-input");
  Store.state.config.model.lora_path = null;
  Store.state.config.model.lora_scale = 1.0;

  await LoRAManager.loadLoras(false);
  assert.strictEqual(LoRAManager.select.children.length, 2);
  LoRAManager.select.value = first.path;
  LoRAManager.applySelection();
  assert.strictEqual(Store.state.config.model.lora_path, first.path);

  Store.state.config.model.lora_scale = 0.65;
  LoRAManager.renderActiveStatus();
  assert(LoRAManager.activeStatus.textContent.includes("portrait.safetensors"));
  assert(LoRAManager.activeStatus.textContent.includes("0.65"));

  await LoRAManager.uploadFile({ name: "lighting.safetensors", size: 8192 });
  assert.strictEqual(Store.state.config.model.lora_path, uploaded.path);
  assert(LoRAManager.uploadStatus.textContent.includes("ready and selected"));
  LoRAManager.clearSelection();
  assert.strictEqual(Store.state.config.model.lora_path, null);

  ApiClient.listLoras = originalList;
  ApiClient.uploadLora = originalUpload;
});

runTest("LoRA deletion confirms, removes stored file, and refreshes selection", async () => {
  const item = { name: "obsolete.safetensors", path: "/models/loras/obsolete.safetensors", size: 2048, valid: false };
  const originalDelete = ApiClient.deleteLora;
  const originalList = ApiClient.listLoras;
  const originalConfirm = mockWindow.confirm;
  let removed = null;
  ApiClient.deleteLora = async (filename) => { removed = filename; return { deleted: true }; };
  ApiClient.listLoras = async () => ({ loras: [] });
  LoRAManager.filesList = domRegistry.get("lora-files-list");
  Store.state.loras.available = [item];
  Store.state.config.model.lora_path = item.path;
  LoRAManager.renderFiles();
  assert.strictEqual(LoRAManager.filesList.children.length, 1);
  assert.strictEqual(LoRAManager.filesList.children[0].children[1].textContent, "Delete");
  mockWindow.confirm = () => false;
  await LoRAManager.deleteFile(item);
  assert.strictEqual(removed, null);
  mockWindow.confirm = () => true;
  await LoRAManager.deleteFile(item);
  assert.strictEqual(removed, item.name);
  assert.strictEqual(Store.state.config.model.lora_path, null);
  assert.strictEqual(LoRAManager.filesList.textContent, "No stored LoRA files.");
  ApiClient.deleteLora = originalDelete;
  ApiClient.listLoras = originalList;
  mockWindow.confirm = originalConfirm;
});

runTest("System inventory dynamically lists GPUs and applies the selected production device", async () => {
  SystemManager.init();
  const capabilities = {
    python: { version: "3.10.12" },
    platform: "Linux-test",
    torch: { version: "2.11.0", cuda_runtime: "12.6" },
    host: {
      cpu: { name: "Test CPU", physical_cores: 8, logical_cores: 16 },
      memory: { total_bytes: 64 * 1024 ** 3, available_bytes: 48 * 1024 ** 3, percent_used: 25 },
    },
    devices: [
      { id: "cpu", type: "cpu", name: "CPU", available: true },
      { id: "cuda:0", type: "cuda", name: "GPU Zero", total_memory_bytes: 24 * 1024 ** 3, free_memory_bytes: 12 * 1024 ** 3 },
      { id: "cuda:1", type: "cuda", name: "GPU One", total_memory_bytes: 24 * 1024 ** 3, free_memory_bytes: 20 * 1024 ** 3 },
    ],
    cuda: {
      devices: [
        { id: "cuda:0", type: "cuda", name: "GPU Zero", total_memory_bytes: 24 * 1024 ** 3, free_memory_bytes: 12 * 1024 ** 3, used_memory_bytes: 12 * 1024 ** 3, compute_capability: "8.6" },
        { id: "cuda:1", type: "cuda", name: "GPU One", total_memory_bytes: 24 * 1024 ** 3, free_memory_bytes: 20 * 1024 ** 3, used_memory_bytes: 4 * 1024 ** 3, compute_capability: "8.6" },
      ],
    },
    selected_device: { id: "cuda:0", ready: true },
    production_backend: { ready: true, message: "cuda:0 is ready" },
    backend: { default_mode: "production" },
    execution: { persistent_backend: false, active_job: null, last_run: null, message: "Models are loaded per run." },
  };
  Store.state.config.runtime.device = "cuda:0";
  SystemManager.render(capabilities);
  assert.strictEqual(domRegistry.get("param-device").children.length, 3);
  assert.strictEqual(domRegistry.get("system-gpu-count").textContent, "2 detected");
  assert.strictEqual(domRegistry.get("system-device-list").children.length, 2);
  assert(domRegistry.get("system-cpu-name").textContent.includes("Test CPU"));
  assert(domRegistry.get("system-ram-total").textContent.includes("GB"));

  const originalRefresh = App.refreshRuntimeCapabilities;
  App.refreshRuntimeCapabilities = async () => capabilities;
  domRegistry.get("param-device").value = "cuda:1";
  domRegistry.get("param-dtype").value = "float16";
  domRegistry.get("param-offload").value = "sequential";
  await SystemManager.applyConfiguration();
  assert.strictEqual(Store.state.config.runtime.device, "cuda:1");
  assert.strictEqual(Store.state.config.runtime.dtype, "float16");
  assert.strictEqual(Store.state.config.runtime.offload, "sequential");
  App.refreshRuntimeCapabilities = originalRefresh;
});

runTest("Catalog model selection uses stable IDs and excludes incompatible entries", async () => {
  const originalList = ApiClient.listModels;
  const originalSource = Store.state.config.model.source;
  const models = [
    { id: "model_a", name: "Model A", path: "/models/a", type: "diffusers", compatible: true },
    { id: "model_b", name: "Model B", path: "/models/b", type: "diffusers", compatible: true },
    { id: "model_old", name: "Old", path: "/models/old", type: "diffusers", compatible: false, compatibility_reason: "Wrong pipeline" },
  ];
  ApiClient.listModels = async () => ({ models });
  ModelManager.cachedSelect = domRegistry.get("select-cached-model");
  ModelManager.applyCachedBtn = domRegistry.get("btn-apply-cached-model");
  ModelManager.modelInfoBox = domRegistry.get("cached-model-info-box");
  ModelManager.infoPath = domRegistry.get("info-model-path");
  ModelManager.infoType = domRegistry.get("info-model-type");
  ModelManager.infoSize = domRegistry.get("info-model-size");
  Store.state.models.selectedId = null;
  await ModelManager.loadModels();
  assert.strictEqual(Store.state.models.selectedId, "model_a");
  assert.strictEqual(ModelManager.cachedSelect.children[3].disabled, true);
  ModelManager.cachedSelect.value = "model_b";
  ModelManager.applySelectedCachedModel();
  assert.strictEqual(Store.state.models.selectedId, "model_b");
  assert(domRegistry.get("model-active-status").textContent.includes("Model B"));
  assert.strictEqual(Store.state.config.model.source, originalSource);
  ApiClient.listModels = originalList;
});

runTest("Model deletion confirms, removes the catalog entry, and clears selection", async () => {
  const item = { id: "model_old", name: "Old model", path: "/models/old", type: "gguf", compatible: false };
  const originalDelete = ApiClient.deleteModel;
  const originalList = ApiClient.listModels;
  const originalConfirm = mockWindow.confirm;
  let deleted = null;
  ApiClient.deleteModel = async (id) => { deleted = id; return { deleted: true }; };
  ApiClient.listModels = async () => ({ models: [
    { id: "model_remaining", name: "Remaining model", path: "/models/remaining", type: "diffusers", compatible: true },
  ] });
  ModelManager.filesList = domRegistry.get("cached-model-files-list");
  Store.state.models.cached = [item];
  Store.state.models.selectedId = item.id;
  ModelManager.renderModelFiles([item]);
  assert.strictEqual(ModelManager.filesList.children[0].children[1].textContent, "Delete");
  mockWindow.confirm = () => false;
  await ModelManager.deleteFile(item);
  assert.strictEqual(deleted, null);
  mockWindow.confirm = () => true;
  await ModelManager.deleteFile(item);
  assert.strictEqual(deleted, item.id);
  assert.strictEqual(Store.state.models.selectedId, null);
  assert.strictEqual(ModelManager.filesList.children.length, 1);
  assert(ModelManager.filesList.children[0].children[0].textContent.includes("Remaining model"));
  ApiClient.deleteModel = originalDelete;
  ApiClient.listModels = originalList;
  mockWindow.confirm = originalConfirm;
});

runTest("Run deletion confirms, clears the displayed result, and refreshes history", async () => {
  const run = { run_id: "finished_run", status: "success" };
  const originalDelete = ApiClient.deleteRun;
  const originalConfirm = mockWindow.confirm;
  const originalLoad = RunHistory.loadHistory;
  const originalOutputs = OutputViewer.renderOutputs;
  const originalComparison = ComparisonSlider.setup;
  const originalInspector = JsonInspector.render;
  let deleted = null;
  let refreshed = 0;
  let cleared = 0;
  ApiClient.deleteRun = async (id) => { deleted = id; return { run_id: id }; };
  RunHistory.loadHistory = async () => { refreshed += 1; };
  OutputViewer.renderOutputs = (outputs) => { if (outputs.length === 0) cleared += 1; };
  ComparisonSlider.setup = () => {};
  JsonInspector.render = () => {};
  RunHistory.runsList = domRegistry.get("history-runs-list");
  RunHistory.render([run]);
  assert.strictEqual(RunHistory.runsList.children[0].children[1].children[1].textContent, "Delete");
  Store.state.run.currentRecord = { run_id: run.run_id };
  mockWindow.confirm = () => false;
  await RunHistory.deleteRun(run);
  assert.strictEqual(deleted, null);
  mockWindow.confirm = () => true;
  await RunHistory.deleteRun(run);
  assert.strictEqual(deleted, run.run_id);
  assert.strictEqual(Store.state.run.currentRecord, null);
  assert.strictEqual(cleared, 1);
  assert.strictEqual(refreshed, 1);
  ApiClient.deleteRun = async () => { throw new Error("Active inference"); };
  await RunHistory.deleteRun(run);
  assert.strictEqual(refreshed, 1);
  assert(toastLog.at(-1).msg.includes("Active inference"));
  assert.strictEqual(toastLog.at(-1).type, "error");
  ApiClient.deleteRun = originalDelete;
  mockWindow.confirm = originalConfirm;
  RunHistory.loadHistory = originalLoad;
  OutputViewer.renderOutputs = originalOutputs;
  ComparisonSlider.setup = originalComparison;
  JsonInspector.render = originalInspector;
});

runTest("Run details render readable facts and keep raw JSON optional", () => {
  JsonInspector.summaryElem = domRegistry.get("run-summary");
  JsonInspector.codeElem = domRegistry.get("json-record-code");
  const record = { run_id: "run_1", summary: { summary_version: 1, run_id: "run_1", status: "success",
    timestamp: "2026-09-27T12:00:00Z", input: { filename: "portrait.png", file_type: "PNG",
      width: 120, height: 80, aspect_ratio: "3:2", size_bytes: 1024 },
    references: [], model: { name: "owner/model", source: "owner/model", size_bytes: null,
      parameters_billion: null }, lora: null,
    generation: { steps: 12, guidance_scale: 1.5, seed: 9, width: 64, height: 64,
      duration_seconds: 2.5, device: "cuda:1", pipeline: "QwenImage21Pipeline",
      peak_gpu_allocated_bytes: 2 ** 30 },
    outputs: [{ filename: "output.png", width: 64, height: 64, size_bytes: 2048 }], error: null } };
  JsonInspector.render(record);
  assert.strictEqual(JsonInspector.summaryElem.children.length, 7);
  assert(JsonInspector.summaryElem.textContent.includes("portrait.png"));
  assert(JsonInspector.summaryElem.textContent.includes("owner/model"));
  assert(JsonInspector.summaryElem.textContent.includes("Unavailable"));
  assert(JsonInspector.codeElem.textContent.includes('"summary_version": 1'));
  JsonInspector.render({ ...record, summary: { ...record.summary, status: "error",
    outputs: [], error: { type: "RuntimeError", message: "LoRA could not be loaded" } } });
  assert.strictEqual(JsonInspector.summaryElem.children.length, 8);
  assert(JsonInspector.summaryElem.textContent.includes("LoRA could not be loaded"));
  JsonInspector.render(null);
  assert.strictEqual(JsonInspector.summaryElem.textContent, "No run record loaded.");
});

runTest("Batch progress shows measured counts, failures, ETA, and per-item details", async () => {
  RunController.batchPanel = domRegistry.get("batch-progress");
  RunController.batchSummary = domRegistry.get("batch-progress-summary");
  RunController.batchList = domRegistry.get("batch-progress-items");
  RunController.batchItems = new Map();
  RunController.progressBar = domRegistry.get("run-step-progress-bar");
  RunController.stepCounter = domRegistry.get("run-step-counter");
  RunController.percentLabel = domRegistry.get("run-percent-label");
  RunController.renderBatch({ total: 2, completed: 0, failed: 0, remaining: 2,
    current_operation: null, current_stage: "loading", elapsed_seconds: 0, eta_seconds: null,
    percent: 0, step: 0, steps: 2,
    items: [{ operation_index: 1, input_filename: "bad.png", status: "queued" },
      { operation_index: 2, input_filename: "good.png", status: "queued" }] });
  assert(RunController.batchList.textContent.includes("good.png · queued"));
  RunController.renderBatch({ total: 2, completed: 0, failed: 0, remaining: 2,
    current_operation: 1, current_stage: "generating", elapsed_seconds: 3, eta_seconds: null,
    percent: 25, step: 1, steps: 2,
    item: { operation_index: 1, input_filename: "bad.png", status: "generating" } });
  assert(RunController.batchSummary.textContent.includes("ETA Unavailable"));
  assert(RunController.stepCounter.textContent.includes("Current 1"));
  const originalStatus = Store.state.run.status;
  Store.state.run.status = "running";
  RunController.batchReceivedAt -= 61000;
  RunController.renderBatchSummary();
  assert(RunController.batchSummary.textContent.includes("Elapsed 1m"));
  Store.state.run.status = originalStatus;
  RunController.renderBatch({ total: 2, completed: 0, failed: 1, remaining: 1,
    current_operation: null, current_stage: "failed", elapsed_seconds: 5, eta_seconds: 5,
    percent: 50, step: 0, steps: 2,
    item: { operation_index: 1, input_filename: "bad.png", status: "failed",
      run_id: "run_bad", error: "Invalid image", duration_seconds: 5 } });
  assert(RunController.batchSummary.textContent.includes("Failed 1"));
  assert(RunController.batchSummary.textContent.includes("ETA 0m 5s"));
  assert(RunController.batchList.textContent.includes("Invalid image"));
  const originalFetch = ApiClient.getRunRecord;
  const originalRender = JsonInspector.render;
  const originalSwitch = RunController.switchOutputTab;
  let inspected = null;
  ApiClient.getRunRecord = async (runId) => ({ run_id: runId });
  JsonInspector.render = (record) => { inspected = record.run_id; };
  RunController.switchOutputTab = () => {};
  try {
    await RunController.inspectBatchItem("run_bad");
    assert.strictEqual(inspected, "run_bad");
  } finally {
    ApiClient.getRunRecord = originalFetch;
    JsonInspector.render = originalRender;
    RunController.switchOutputTab = originalSwitch;
  }
});

runTest("Model download renders measured progress and truthful unknown totals", () => {
  ModelManager.hfProgressWrap = domRegistry.get("hf-download-progress-container");
  ModelManager.hfProgressTrack = domRegistry.get("hf-download-progress-track");
  ModelManager.hfProgressBar = domRegistry.get("hf-download-bar");
  ModelManager.hfProgressBadge = domRegistry.get("hf-download-percent-badge");
  ModelManager.hfProgressStatus = domRegistry.get("hf-download-status-label");
  ModelManager.hfProgressFile = domRegistry.get("hf-download-file");
  ModelManager.hfProgressDetails = domRegistry.get("hf-download-details");
  ModelManager.hfProgressError = domRegistry.get("hf-download-error");
  ModelManager.hfCancelBtn = domRegistry.get("btn-cancel-hf-download");
  ModelManager.hfRetryBtn = domRegistry.get("btn-retry-hf-download");

  ModelManager.renderHfDownloadProgress({ status: "preparing", percent: null, downloaded_bytes: 0,
    total_bytes: null, completed_files: 0, total_files: null, remaining_files: null });
  assert.strictEqual(ModelManager.hfProgressBadge.textContent, "Size unknown");
  assert.strictEqual(ModelManager.hfProgressTrack.getAttribute("aria-valuenow"), null);
  assert(ModelManager.hfProgressTrack.classList.contains("is-indeterminate"));

  ModelManager.renderHfDownloadProgress({ status: "downloading", percent: 50, downloaded_bytes: 50,
    total_bytes: 100, completed_files: 1, total_files: 2, remaining_files: 1,
    current_file: "transformer/very_long_model_name.safetensors", speed_bytes_per_second: 20, eta_seconds: 3 });
  assert.strictEqual(ModelManager.hfProgressBadge.textContent, "50%");
  assert.strictEqual(ModelManager.hfProgressTrack.getAttribute("aria-valuenow"), "50");
  assert(ModelManager.hfProgressDetails.textContent.includes("1/2 files"));
  assert(ModelManager.hfProgressFile.textContent.includes("very_long_model_name"));

  ModelManager.renderHfDownloadProgress({ status: "failed", percent: 50, downloaded_bytes: 50,
    total_bytes: 100, completed_files: 1, total_files: 2, remaining_files: 1, error: "Connection closed" });
  assert(!ModelManager.hfRetryBtn.classList.contains("hidden"));
  assert(ModelManager.hfCancelBtn.classList.contains("hidden"));
  assert(ModelManager.hfProgressError.textContent.includes("Connection closed"));
});

runTest("Model download controls send cancellation and retry requests", async () => {
  const originalCancel = ApiClient.cancelDownload;
  const originalRetry = ApiClient.retryDownload;
  const originalTrack = ModelManager.trackHfDownload;
  const originalTask = ModelManager.activeDownloadTaskId;
  let cancelledTask = null;
  let retriedTask = null;
  let trackedTask = null;
  ModelManager.activeDownloadTaskId = "dl_old";
  ApiClient.cancelDownload = async (taskId) => {
    cancelledTask = taskId;
    return { status: "cancelling", percent: null, downloaded_bytes: 0 };
  };
  ApiClient.retryDownload = async (taskId) => {
    retriedTask = taskId;
    return { task_id: "dl_new" };
  };
  ModelManager.trackHfDownload = (taskId) => { trackedTask = taskId; };
  await ModelManager.cancelHfDownload();
  assert.strictEqual(cancelledTask, "dl_old");
  assert(ModelManager.hfProgressStatus.textContent.includes("Cancelling"));
  await ModelManager.retryHfDownload();
  assert.strictEqual(retriedTask, "dl_old");
  assert.strictEqual(trackedTask, "dl_new");
  ApiClient.cancelDownload = originalCancel;
  ApiClient.retryDownload = originalRetry;
  ModelManager.trackHfDownload = originalTrack;
  ModelManager.activeDownloadTaskId = originalTask;
});

runTest("Primary navigation keeps manager state and restores inference tabs", () => {
  mockDocument.body = createMockElement("body", "body");
  const links = ["inference", "models", "loras", "system", "batch", "history", "outputs", "dashboard"].map((page) => {
    const link = createMockElement(null, "a");
    link.dataset.pageTarget = page;
    return link;
  });
  const originalQueryAll = mockDocument.querySelectorAll;
  const originalQuery = mockDocument.querySelector;
  mockDocument.querySelectorAll = function (selector) {
    return selector === ".page-nav-link" ? links : originalQueryAll.call(this, selector);
  };
  mockDocument.querySelector = function (selector) {
    if (selector === ".config-tabs-nav .tab-btn.active") {
      return ["prompt", "generation", "runtime", "system", "model"]
        .map((name) => getOrCreateElement(`tab-btn-${name}`))
        .find((button) => button.classList.contains("active"));
    }
    return originalQuery.call(this, selector);
  };
  for (const name of ["prompt", "generation", "runtime", "system", "model"]) {
    const button = getOrCreateElement(`tab-btn-${name}`);
    button.click = () => button.dispatchEvent("click");
  }
  const hashListeners = [];
  mockWindow.location = { hash: "#models" };
  mockWindow.addEventListener = (event, handler) => {
    if (event === "hashchange") hashListeners.push(handler);
  };
  PageNavigation.init();
  assert.strictEqual(mockDocument.body.dataset.page, "models");
  assert(getOrCreateElement("tab-pane-model").classList.contains("active"));
  assert.strictEqual(links[1].getAttribute("aria-current"), "page");

  PageNavigation.show("inference");
  getOrCreateElement("tab-btn-generation").click();
  PageNavigation.show("loras");
  assert.strictEqual(mockDocument.body.dataset.page, "loras");
  assert.strictEqual(getOrCreateElement("heading-config").textContent, "LoRAs");
  PageNavigation.show("system");
  assert(getOrCreateElement("tab-pane-system").classList.contains("active"));
  PageNavigation.show("inference");
  assert(getOrCreateElement("tab-pane-generation").classList.contains("active"));
  assert.strictEqual(links[0].getAttribute("aria-current"), "page");
  assert.strictEqual(links[2].getAttribute("aria-current"), null);

  mockWindow.location.hash = "#runtime";
  hashListeners.forEach((handler) => handler());
  assert.strictEqual(mockDocument.body.dataset.page, "inference");
  assert(getOrCreateElement("tab-pane-runtime").classList.contains("active"));
  mockWindow.location.hash = "#model";
  hashListeners.forEach((handler) => handler());
  assert.strictEqual(mockDocument.body.dataset.page, "models");
  mockWindow.location.hash = "#toString";
  hashListeners.forEach((handler) => handler());
  assert.strictEqual(mockDocument.body.dataset.page, "inference");
  mockDocument.querySelectorAll = originalQueryAll;
  mockDocument.querySelector = originalQuery;
});

runTest("Batch destination preserves active progress, failures, and result details across pages", async () => {
  const previousStatus = Store.state.run.status;
  const originalFetch = ApiClient.getRunRecord;
  const stream = { close: () => { throw new Error("Navigation closed the active stream"); } };
  RunController.eventSource = stream;
  RunController.batchTimer = 1; // An existing clock must survive navigation.
  Store.state.run.status = "running";
  try {
    const snapshot = { total: 2, completed: 0, failed: 0, remaining: 2,
      current_operation: 1, current_stage: "generating", elapsed_seconds: 3,
      eta_seconds: null, percent: 25, step: 1, steps: 2,
      items: [{ operation_index: 1, input_filename: "bad.png", status: "generating" },
        { operation_index: 2, input_filename: "good.png", status: "queued" }] };
    RunController.renderBatch(snapshot);
    PageNavigation.show("batch", true);
    assert.strictEqual(mockDocument.body.dataset.page, "batch");
    assert.strictEqual(getOrCreateElement("heading-output").textContent, "Batch Inference");
    PageNavigation.show("models");
    RunController.renderBatch({ ...snapshot, items: undefined, failed: 1, remaining: 1,
      current_operation: 2, percent: 50,
      item: { operation_index: 1, input_filename: "bad.png", status: "failed",
        run_id: "run_bad", error: "Invalid image" } });
    PageNavigation.show("batch");
    assert.strictEqual(RunController.eventSource, stream);
    assert.strictEqual(RunController.batchTimer, 1);
    assert.strictEqual(RunController.batchItems.size, 2);
    assert(RunController.batchSummary.textContent.includes("Failed 1"));
    assert(RunController.batchList.textContent.includes("Invalid image"));
    assert.strictEqual(RunController.progressBar.style.width, "50%");
    ApiClient.getRunRecord = async () => ({ run_id: "run_bad", status: "error" });
    await RunController.inspectBatchItem("run_bad");
    assert(getOrCreateElement("pane-json").classList.contains("active"));
    assert.strictEqual(mockDocument.body.dataset.page, "batch");
    PageNavigation.show("inference");
    assert.strictEqual(getOrCreateElement("heading-output").textContent, "Execution Hub");
    assert(getOrCreateElement("pane-json").classList.contains("active"));
    RunController.batchTimer = null;
    RunController.setRunningState(true);
    assert.strictEqual(RunController.batchSummary.textContent, "Waiting for batch status…");
    assert.strictEqual(RunController.batchItems.size, 0);
    RunController.setRunningState(false);
  } finally {
    Store.state.run.status = previousStatus;
    ApiClient.getRunRecord = originalFetch;
    RunController.eventSource = null;
    RunController.batchTimer = null;
  }
});

runTest("History page exposes loading, empty, error, and latest-response states", async () => {
  const originalList = ApiClient.listRuns;
  try {
    RunHistory.openDrawer();
    assert.strictEqual(mockDocument.body.dataset.page, "history");
    assert.strictEqual(mockWindow.location.hash, "history");
    assert.strictEqual(getOrCreateElement("drawer-history").getAttribute("aria-hidden"), "false");
    let resolveFirst;
    ApiClient.listRuns = () => new Promise(resolve => { resolveFirst = resolve; });
    const oldRequest = RunHistory.loadHistory();
    assert.strictEqual(RunHistory.runsList.getAttribute("aria-busy"), "true");
    assert(RunHistory.runsList.textContent.includes("Loading run history"));
    ApiClient.listRuns = async () => ({ runs: [] });
    await RunHistory.loadHistory();
    assert(RunHistory.runsList.textContent.includes("No saved runs yet"));
    resolveFirst({ runs: [{ run_id: "stale", status: "success" }] });
    await oldRequest;
    assert(RunHistory.runsList.textContent.includes("No saved runs yet"));
    ApiClient.listRuns = async () => { throw new Error("Server unreachable"); };
    await RunHistory.loadHistory();
    assert(RunHistory.runsList.textContent.includes("Server unreachable"));
    assert(RunHistory.runsList.textContent.includes("Refresh"));
    assert.strictEqual(RunHistory.runsList.getAttribute("aria-busy"), "false");
    RunHistory.render([{ run_id: "active", status: "running" }]);
    const open = RunHistory.runsList.children[0].children[3];
    assert.strictEqual(open.textContent, "Open run");
    assert.strictEqual(open.disabled, true);
    assert.strictEqual(Utils.el("button", { disabled: false }).getAttribute("disabled"), null);
    RunHistory.render([{ run_id: "finished", status: "success" }]);
    assert.strictEqual(RunHistory.runsList.children[0].children[3].disabled, false);
    assert.strictEqual(RunHistory.runsList.children[0].children[1].children[1].disabled, false);
    RunHistory.closeDrawer();
    assert.strictEqual(mockDocument.body.dataset.page, "inference");
    assert.strictEqual(getOrCreateElement("drawer-history").getAttribute("aria-hidden"), "true");
  } finally { ApiClient.listRuns = originalList; }
});

runTest("Historical failures clear stale output and selecting a record preserves an active batch", async () => {
  const originalFetch = ApiClient.getRunRecord;
  const previousStatus = Store.state.run.status;
  const stream = { close: () => { throw new Error("History closed the active stream"); } };
  try {
    PageNavigation.show("history");
    RunController.eventSource = stream;
    Store.state.run.status = "running";
    const batch = RunController.batchState;
    ApiClient.getRunRecord = async () => ({ run_id: "success", input_image: "/input.png",
      outputs: [{ filename: "saved.png", width: 64, height: 64 }] });
    await RunHistory.selectRun("success");
    assert.strictEqual(Store.state.run.currentOutputs.length, 1);
    assert(getOrCreateElement("pane-json").classList.contains("active"));
    let resolveOld;
    ApiClient.getRunRecord = () => new Promise(resolve => { resolveOld = resolve; });
    const oldSelection = RunHistory.selectRun("old");
    ApiClient.getRunRecord = async () => ({ run_id: "failed", status: "error", error: { message: "Decode failed" } });
    await RunHistory.selectRun("failed");
    resolveOld({ run_id: "old", outputs: [{ filename: "old.png" }] });
    await oldSelection;
    assert.strictEqual(Store.state.run.currentRecord.run_id, "failed");
    assert.strictEqual(Store.state.run.currentOutputs.length, 0);
    assert(OutputViewer.activeView.classList.contains("hidden"));
    assert(getOrCreateElement("pane-json").classList.contains("active"));
    assert.strictEqual(RunController.eventSource, stream);
    assert.strictEqual(RunController.batchState, batch);
    assert.strictEqual(Store.state.run.status, "running");
    assert.strictEqual(mockDocument.body.dataset.page, "history");
  } finally {
    ApiClient.getRunRecord = originalFetch;
    Store.state.run.status = previousStatus;
    RunController.eventSource = null;
    PageNavigation.show("inference");
  }
});

runTest("Outputs library shares list states and opens the exact saved image with its input", async () => {
  const originalList = ApiClient.listRuns;
  const originalFetch = ApiClient.getRunRecord;
  const originalOutputList = RunHistory.outputsList;
  const previousStatus = Store.state.run.status;
  try {
    RunHistory.outputsList = createMockElement(null);
    PageNavigation.navigate("outputs");
    assert.strictEqual(mockDocument.body.dataset.page, "outputs");
    assert.strictEqual(mockWindow.location.hash, "outputs");
    const record = { run_id: "saved", status: "success", input_image: "/saved-input.png",
      comparison: "/results/comparison.png", outputs: [
        { filename: "first.png", url: "/api/outputs/first.png", width: 64, height: 64 },
        { filename: "second.png", url: "/api/outputs/second.png", width: 96, height: 64 },
      ] };
    let resolveList;
    ApiClient.listRuns = () => new Promise(resolve => { resolveList = resolve; });
    const loading = RunHistory.loadHistory();
    assert.strictEqual(RunHistory.outputsList.getAttribute("aria-busy"), "true");
    assert(RunHistory.outputsList.textContent.includes("Loading saved outputs"));
    resolveList({ runs: [record, { run_id: "failed", status: "error" }] });
    await loading;
    assert.strictEqual(RunHistory.outputsList.querySelectorAll(".saved-output").length, 2);
    ApiClient.getRunRecord = async id => { assert.strictEqual(id, "saved"); return record; };
    const stream = { close() { throw new Error("Outputs closed the active stream"); } };
    RunController.eventSource = stream;
    Store.state.run.status = "running";
    const second = RunHistory.outputsList.querySelectorAll(".saved-output")[1];
    second.dispatchEvent("click");
    await new Promise(resolve => setImmediate(resolve));
    assert.strictEqual(OutputViewer.primaryImage.src, record.outputs[1].url);
    assert.strictEqual(OutputViewer.downloadBtn.download, "second.png");
    assert.strictEqual(second.getAttribute("aria-current"), "true");
    assert(getOrCreateElement("comparison-before-img").src.includes("saved-input.png"));
    assert.strictEqual(getOrCreateElement("comparison-after-img").src, record.outputs[1].url);
    assert(getOrCreateElement("pane-outputs").classList.contains("active"));
    const firstThumb = OutputViewer.batchStrip.children[0];
    assert.strictEqual(firstThumb.tagName, "BUTTON");
    firstThumb.dispatchEvent("click");
    assert.strictEqual(OutputViewer.currentOutput.filename, "first.png");
    assert.strictEqual(firstThumb.getAttribute("aria-pressed"), "true");
    assert.strictEqual(RunController.eventSource, stream);
    ApiClient.listRuns = async () => ({ runs: [] });
    await RunHistory.loadHistory();
    assert(RunHistory.outputsList.textContent.includes("No saved outputs"));
    ApiClient.listRuns = async () => { throw new Error("Offline"); };
    await RunHistory.loadHistory();
    assert(RunHistory.outputsList.textContent.includes("Offline"));
    assert(RunHistory.outputsList.textContent.includes("Refresh"));
    assert.strictEqual(RunHistory.outputsList.getAttribute("aria-busy"), "false");
  } finally {
    ApiClient.listRuns = originalList;
    ApiClient.getRunRecord = originalFetch;
    RunHistory.outputsList = originalOutputList;
    Store.state.run.status = previousStatus;
    RunController.eventSource = null;
    PageNavigation.show("inference");
  }
});

runTest("Outputs library scales, handles missing previews, and deletes by owning run", async () => {
  const originalList = RunHistory.outputsList;
  const originalDelete = ApiClient.deleteRun;
  const originalFetch = ApiClient.getRunRecord;
  const originalLoad = RunHistory.loadHistory;
  const originalConfirm = mockWindow.confirm;
  try {
    RunHistory.outputsList = createMockElement(null);
    const outputs = Array.from({length: 30}, (_, i) => ({filename: `long_${"name_".repeat(30)}${i}.png`,
      url: `/api/outputs/${i}.png`, run_id: "owner"}));
    const run = {run_id: "owner", status: "success", outputs};
    RunHistory.renderLibrary([run, {run_id: "active", status: "running", outputs: [outputs[0]]}]);
    assert.strictEqual(RunHistory.outputsList.querySelectorAll(".saved-output").length, 31);
    assert.strictEqual(RunHistory.outputsList.querySelectorAll(".saved-output")[30].disabled, true);
    const image = RunHistory.outputsList.querySelectorAll(".saved-output")[0].children[0];
    image.dispatchEvent("error");
    assert.strictEqual(image.hidden, true);
    assert(image.parentNode.textContent.includes("Preview unavailable"));
    let deleted = 0, refreshed = 0;
    ApiClient.deleteRun = async id => { assert.strictEqual(id, "owner"); deleted++; };
    RunHistory.loadHistory = async () => { refreshed++; };
    Store.state.run.currentRecord = {run_id: "other"};
    Store.state.run.currentOutputs = outputs;
    OutputViewer.renderOutputs(outputs, 29);
    mockWindow.confirm = () => false;
    await RunHistory.deleteRun(run);
    assert.strictEqual(deleted, 0);
    let resolveSelection;
    ApiClient.getRunRecord = () => new Promise(resolve => { resolveSelection = resolve; });
    const pendingSelection = RunHistory.selectRun("owner");
    mockWindow.confirm = () => true;
    await RunHistory.deleteRun(run);
    resolveSelection(run);
    await pendingSelection;
    assert.strictEqual(deleted, 1);
    assert.strictEqual(refreshed, 1);
    assert.strictEqual(OutputViewer.currentOutput, null);
    assert.strictEqual(Store.state.run.currentOutputs.length, 0);
    assert(OutputViewer.activeView.classList.contains("hidden"));
  } finally {
    RunHistory.outputsList = originalList;
    ApiClient.deleteRun = originalDelete;
    ApiClient.getRunRecord = originalFetch;
    RunHistory.loadHistory = originalLoad;
    mockWindow.confirm = originalConfirm;
  }
});

runTest("Dashboard renders actual snapshots and live monitors without changing the active stream", () => {
  const originalRoot = Dashboard.root;
  const originalSystem = Store.state.system;
  const originalRun = Store.state.run;
  const originalTask = Store.state.models.activeTask;
  const originalBatch = RunController.batchState;
  const originalSummary = RunController.batchSummary.textContent;
  try {
    Dashboard.root = createMockElement(null);
    for (const key of ["server", "next", "gpus", "resources", "jobs", "download"]) {
      Dashboard.root.appendChild(Utils.el("p", {class: `dashboard-${key}-value`}));
    }
    Dashboard.root.appendChild(Utils.el("div", {class: "dashboard-recent-list"}));
    Store.state.system = {capabilities: null, error: null, updatedAt: null};
    Store.state.run = {status: "idle"};
    Store.state.models.activeTask = null;
    RunController.batchState = null;
    Dashboard.render();
    assert(Dashboard.root.querySelector(".dashboard-gpus-value").textContent.includes("Loading"));
    assert(Dashboard.root.querySelector(".dashboard-download-value").textContent.includes("No download monitored"));
    Dashboard.renderRecent([]);
    assert(Dashboard.root.querySelector(".dashboard-recent-list").textContent.includes("No saved runs"));
    Store.state.system.capabilities = {cuda: {devices: [{id: "cuda:1", name: "Actual GPU", free_memory_bytes: 0, total_memory_bytes: 1024}]},
      production_backend: {ready: true, message: "Ready on GPU"},
      execution: {cache: {slots: [{device: "cuda:1", state: "loaded", model: {source: "Actual loaded model"},
        pipeline: "ActualPipeline", lora: {applied: true, filename: "actual.safetensors"}}]}}};
    Store.state.system.updatedAt = "2026-09-28T05:00:00Z";
    Store.state.run = {status: "running", activeJobId: "live_job"};
    RunController.batchState = {current_stage: "generating"};
    RunController.batchSummary.textContent = "Completed 1/3 · Failed 0 · Stage generating";
    const stream = {close() { throw new Error("Dashboard stopped the stream"); }};
    RunController.eventSource = stream;
    ModelManager.renderHfDownloadProgress({repo_id: "Actual/Download", status: "downloading", percent: null, downloaded_bytes: 0, total_bytes: null});
    PageNavigation.navigate("dashboard");
    assert.strictEqual(mockDocument.body.dataset.page, "dashboard");
    const resources = Dashboard.root.querySelector(".dashboard-resources-value").textContent;
    assert(resources.includes("Actual loaded model") && resources.includes("actual.safetensors"));
    assert(Dashboard.root.querySelector(".dashboard-gpus-value").textContent.includes("0 B free"));
    assert(Dashboard.root.querySelector(".dashboard-jobs-value").textContent.includes("live_job"));
    assert(Dashboard.root.querySelector(".dashboard-download-value").textContent.includes("Total size unknown"));
    Store.state.system.error = "Probe offline";
    Dashboard.render();
    assert(Dashboard.root.querySelector(".dashboard-server-value").textContent.includes("Probe offline"));
    assert(Dashboard.root.querySelector(".dashboard-resources-value").textContent.includes("Last known data"));
    Dashboard.renderRecent(Array.from({length: 7}, (_, i) => ({run_id: `recent_${i}`, status: i === 6 ? "running" : "success", timestamp: `2026-09-28T05:0${i}:00Z`})));
    const recent = Dashboard.root.querySelector(".dashboard-recent-list");
    assert.strictEqual(recent.children.length, 5);
    assert.strictEqual(recent.children[0].getAttribute("aria-label"), "Inspect run recent_6");
    assert.strictEqual(recent.children[0].disabled, true);
    assert.strictEqual(RunController.eventSource, stream);
    assert.strictEqual(Store.state.run.status, "running");
  } finally {
    Dashboard.root = originalRoot;
    Store.state.system = originalSystem;
    Store.state.run = originalRun;
    Store.state.models.activeTask = originalTask;
    RunController.batchState = originalBatch;
    RunController.batchSummary.textContent = originalSummary;
    RunController.eventSource = null;
    PageNavigation.show("inference");
  }
});

runTest("Dashboard refresh shares existing requests, exposes errors, and recovers without resetting inference", async () => {
  const originalRoot = Dashboard.root;
  const originalHealth = ApiClient.checkHealth;
  const originalSystem = ApiClient.getSystemCapabilities;
  const originalList = ApiClient.listRuns;
  const originalState = Store.state.system;
  try {
    Dashboard.root = createMockElement(null);
    for (const key of ["server", "gpus", "resources", "jobs", "next", "download"]) Dashboard.root.appendChild(Utils.el("p", {class: `dashboard-${key}-value`}));
    const button = Utils.el("button", {class: "dashboard-refresh-btn"});
    const status = Utils.el("p", {class: "dashboard-refresh-status"});
    const recent = Utils.el("div", {class: "dashboard-recent-list"});
    [button, status, recent].forEach(element => Dashboard.root.appendChild(element));
    let healthCalls = 0, systemCalls = 0, listCalls = 0, resolveHealth;
    ApiClient.checkHealth = () => {healthCalls++; return new Promise(resolve => {resolveHealth = resolve;});};
    ApiClient.getSystemCapabilities = async () => {systemCalls++; throw new Error("System offline");};
    ApiClient.listRuns = async () => {listCalls++; throw new Error("History offline");};
    const refresh = Dashboard.refresh();
    assert.strictEqual(button.disabled, true);
    assert(status.textContent.includes("Refreshing"));
    assert.strictEqual(recent.getAttribute("aria-busy"), "true");
    await Dashboard.refresh();
    assert.strictEqual(healthCalls, 1);
    resolveHealth(); await refresh;
    assert.strictEqual(systemCalls, 1);
    assert.strictEqual(listCalls, 1);
    assert.strictEqual(button.disabled, false);
    assert(status.textContent.includes("unavailable"));
    assert(recent.textContent.includes("History offline"));
    assert(Dashboard.root.querySelector(".dashboard-server-value").textContent.includes("System offline"));
    ApiClient.checkHealth = async () => {throw new Error("Server offline");};
    await Dashboard.refresh();
    assert.strictEqual(Store.state.connected, false);
    assert.strictEqual(getOrCreateElement("backend-status-text").textContent, "Disconnected");
    ApiClient.checkHealth = async () => {};
    ApiClient.getSystemCapabilities = async () => ({cuda: {devices: []}, execution: {cache: {slots: []}}});
    ApiClient.listRuns = async () => ({runs: []});
    await Dashboard.refresh();
    assert.strictEqual(Store.state.connected, true);
    assert.strictEqual(Store.state.system.error, null);
    assert.strictEqual(status.textContent, "Status refreshed.");
    assert(Dashboard.root.querySelector(".dashboard-resources-value").textContent.includes("No resident"));
    assert(Dashboard.root.querySelector(".dashboard-gpus-value").textContent.includes("No CUDA"));
    assert(recent.textContent.includes("No saved runs"));
  } finally {
    Dashboard.root = originalRoot;
    ApiClient.checkHealth = originalHealth;
    ApiClient.getSystemCapabilities = originalSystem;
    ApiClient.listRuns = originalList;
    Store.state.system = originalState;
  }
});

runTest("Model upload conflicts show API details, stop chunks, and preserve selection", async () => {
  const originalFetch = sandbox.fetch;
  const originalFormData = sandbox.FormData;
  const originalLoad = ModelManager.loadModels;
  const originalSelect = ModelManager.cachedSelect;
  const originalProps = {};
  for (const [prop, id] of Object.entries({uploadProgressWrap: "model-upload-progress-container",
    uploadProgressBar: "model-upload-bar", uploadProgressStatus: "model-upload-status-label",
    uploadProgressBadge: "model-upload-percent-badge", uploadProgressError: "model-upload-error"})) {
    originalProps[prop] = ModelManager[prop];
    ModelManager[prop] = domRegistry.get(id);
  }
  const selected = JSON.stringify([Store.state.models.selectedId, Store.state.config.model]);
  let requests = 0, refreshes = 0;
  const detail = "Model file 'existing.gguf' already exists. Rename your upload or delete the stored model first.";
  const size = 6 * 1024 * 1024;
  const file = {name: "existing.gguf", size, slice: () => new Blob(["chunk"])};
  try {
    sandbox.FormData = FormData;
    sandbox.fetch = async (url) => {
      assert.strictEqual(url, "/api/models/upload");
      requests++;
      return {ok: false, status: 409, json: async () => ({detail})};
    };
    ModelManager.loadModels = async () => { refreshes++; return true; };
    ModelManager.cachedSelect = null;
    await ModelManager.uploadFile(file);
    assert.strictEqual(requests, 1, "A conflict must stop remaining chunks");
    assert.strictEqual(refreshes, 0);
    assert.strictEqual(ModelManager.uploadProgressStatus.textContent, "Upload failed");
    assert(ModelManager.uploadProgressError.textContent.includes(detail));
    assert(!ModelManager.uploadProgressError.classList.contains("hidden"));
    assert.strictEqual(ModelManager.uploadProgressBadge.textContent, "0%");
    assert.strictEqual(toastLog.at(-1).type, "error");
    assert.strictEqual(JSON.stringify([Store.state.models.selectedId, Store.state.config.model]), selected);

    sandbox.fetch = async () => { requests++; return {ok: true, json: async () => ({
      success: true, status: requests === 2 ? "uploading" : "completed", path: "/models/new.gguf",
    })}; };
    await ModelManager.uploadFile({...file, name: "new.gguf"});
    assert.strictEqual(requests, 3);
    assert.strictEqual(refreshes, 1, "Successful uploads must refresh the catalog");
    assert(ModelManager.uploadProgressError.classList.contains("hidden"));
    assert.strictEqual(ModelManager.uploadProgressBadge.textContent, "100%");
    assert.strictEqual(toastLog.at(-1).type, "warning", "Stored files without a selectable entry must not claim selection");
  } finally {
    sandbox.fetch = originalFetch;
    sandbox.FormData = originalFormData;
    ModelManager.loadModels = originalLoad;
    ModelManager.cachedSelect = originalSelect;
    Object.assign(ModelManager, originalProps);
  }
});

runTest("Uploaded model selection uses the final receipt path and authoritative catalog ID", async () => {
  const originalUpload = ApiClient.uploadModelChunk, originalList = ApiClient.listModels;
  const originalTrigger = ParamForm.triggerValidation, originalValidate = ApiClient.validateConfig;
  const originalStart = ApiClient.startRun, originalStream = RunController.connectStream;
  const originalState = JSON.parse(JSON.stringify(Store.state));
  const old = {id: "model_111", name: "Old model", path: "/models/old", compatible: true, type: "diffusers"};
  const uploaded = {id: "model_222", name: "stored.safetensors", path: "/models/stored.safetensors", compatible: true};
  const decoy = {...uploaded, id: "model_333", path: "/models/another/stored.safetensors"};
  let catalog, completion, catalogFailure, calls, refreshes;
  const reset = (selection = old.id) => {
    Store.state.models.selectedId = selection;
    Store.state.models.cached = [old, uploaded]; // Stale matching entries cannot authorize selection.
    catalog = [old, decoy, uploaded];
    completion = {success: true, status: "completed", path: uploaded.path};
    catalogFailure = false; calls = 0; refreshes = 0;
  };
  try {
    ParamForm.triggerValidation = () => {};
    ApiClient.listModels = async () => {
      refreshes++;
      if (catalogFailure) throw new Error("Catalog offline");
      return {models: catalog};
    };
    ApiClient.uploadModelChunk = async (_blob, _name, index, total) => {
      calls++;
      return index === total - 1 ? completion : {success: true, status: "uploading", path: decoy.path};
    };
    const file = {name: "browser-name.safetensors", size: 1, slice: () => new Blob(["fixture"])};
    for (const [size, selection] of [[1, old.id], [6 * 1024 * 1024, old.id], [1, null]]) {
      reset(selection);
      const modelConfig = JSON.stringify(Store.state.config.model);
      await ModelManager.uploadFile({...file, size});
      assert.strictEqual(calls, size === 1 ? 1 : 2);
      assert.strictEqual(refreshes, 1);
      assert.strictEqual(Store.state.models.selectedId, uploaded.id);
      assert.strictEqual(ModelManager.cachedSelect.value, uploaded.id);
      assert.strictEqual(ModelManager.applyCachedBtn.disabled, false);
      assert.strictEqual(ModelManager.infoPath.textContent, uploaded.path);
      assert(domRegistry.get("model-active-status").textContent.includes(uploaded.name));
      assert.strictEqual(JSON.stringify(Store.state.config.model), modelConfig, "Download/advanced fields cannot change selection");
      assert.strictEqual(toastLog.at(-1).type, "success");
    }

    // Exercise the real validation and submission controllers with the selected ID.
    ParamForm.applyDefaultPresets();
    Store.state.config.demo_mode = false;
    Store.state.config.model.source = "deliberately-wrong-download-source";
    Store.state.inputs.inputImages = [{path: "/inputs/input.png"}];
    Store.state.inputs.referenceImages = [];
    Store.state.run.status = "idle";
    const requests = [];
    ApiClient.validateConfig = async (payload) => { requests.push(payload); return {valid: true}; };
    ApiClient.startRun = async (payload) => { requests.push(payload); return {run_id: "selected_upload", stream_url: "/stream"}; };
    RunController.connectStream = () => {};
    await RunController.startRun();
    assert.strictEqual(requests.length, 2, "Validation and run submission must both execute");
    for (const payload of requests) {
      assert.strictEqual(payload.selected_model_id, uploaded.id);
      assert.strictEqual(payload.model.source, undefined);
      assert.strictEqual(payload.model.base_model, undefined);
    }

    for (const failure of ["incompatible", "missing", "catalog offline"]) {
      reset();
      if (failure === "incompatible") catalog = [old, {...uploaded, compatible: false, compatibility_reason: "Wrong transformer"}];
      if (failure === "missing") catalog = [old, decoy];
      if (failure === "catalog offline") catalogFailure = true;
      await ModelManager.uploadFile(file);
      assert.strictEqual(Store.state.models.selectedId, old.id, failure);
      assert.strictEqual(toastLog.at(-1).type, "warning");
      assert(toastLog.at(-1).msg.includes(failure === "incompatible" ? "Wrong transformer" : "not selected"));
    }
    reset(null);
    catalog = [old, {...uploaded, compatible: false}];
    await ModelManager.uploadFile(file);
    assert.strictEqual(Store.state.models.selectedId, null, "An incompatible upload cannot trigger default selection");

    for (const receipt of [null, {}, {success: false, status: "completed", path: uploaded.path},
      {success: true, status: "uploading", path: uploaded.path},
      {success: true, status: "completed"}, {success: true, status: "completed", path: " "},
      {success: true, status: "completed", path: {path: uploaded.path}}]) {
      reset(); completion = receipt;
      await ModelManager.uploadFile(file);
      assert.strictEqual(Store.state.models.selectedId, old.id);
      assert.strictEqual(refreshes, 0, "Unconfirmed uploads cannot refresh or select");
      assert.strictEqual(toastLog.at(-1).type, "error");
      assert(toastLog.at(-1).msg.includes("did not confirm"));
    }
  } finally {
    ApiClient.uploadModelChunk = originalUpload; ApiClient.listModels = originalList;
    ParamForm.triggerValidation = originalTrigger; ApiClient.validateConfig = originalValidate;
    ApiClient.startRun = originalStart; RunController.connectStream = originalStream;
    Store.state = originalState;
    RunController.setRunningState(false);
  }
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
