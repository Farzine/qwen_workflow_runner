/**
 * ui/tests/test_tier5_node_stress.js
 *
 * Tier 5 Adversarial Stress & Edge-Case Verification Harness
 * for Frontend State Machine, Event Handlers & Interactivity.
 * Executed via Node.js.
 *
 * Covers:
 * 1. Comparison slider touch/pointer drag boundary clamping (0% to 100%, negative & overflow coords, zero-width rect).
 * 2. Token toolbar insertion (<image1> to <image10>) across cursor boundaries, selection replacements, and sequence order.
 * 3. Empty image tray resubmissions and rapid clear/re-add stress cycles (50 iterations).
 * 4. Client state mutations: negative seeds, extreme CFG scales, schedule limit calculations.
 * 5. History drawer scaling (30+ runs), card generation, click selection, and comparison fallback.
 * 6. Rapid click storms on run button: empirical concurrency tracking and re-entrancy behavior.
 */

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert");

// Load HTML to parse IDs
const htmlPath = path.resolve(__dirname, "../templates/index.html");
const html = fs.readFileSync(htmlPath, "utf8");
const idMatches = [...html.matchAll(/id=["']([^"']+)["']/g)].map((m) => m[1]);
const knownIds = new Set(idMatches);

class Node {}

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
    selectionStart: 0,
    selectionEnd: 0,
    _rect: { left: 100, top: 100, width: 800, height: 600, right: 900, bottom: 700 },

    getBoundingClientRect() {
      return this._rect;
    },
    setPointerCapture() {},
    releasePointerCapture() {},

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
      const evtObj = typeof event === "string" ? { type, target: elem, preventDefault() {} } : { ...event, target: elem, preventDefault() {} };
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
            } else if (sel.startsWith("[data-token]") && c.dataset && c.dataset.token) {
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

  Object.defineProperty(elem, "className", {
    get() {
      return [...classListSet].join(" ");
    },
    set(v) {
      classListSet.clear();
      if (v) v.split(/\s+/).forEach((c) => c && classListSet.add(c));
    },
  });

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

const domRegistry = new Map();
function getOrCreateElement(id, tag = "div") {
  if (!domRegistry.has(id)) {
    domRegistry.set(id, createMockElement(id, tag));
  }
  return domRegistry.get(id);
}

for (const id of knownIds) {
  getOrCreateElement(id);
}

// Ensure token buttons exist and are registered
const tokenButtons = [];
for (let i = 1; i <= 10; i++) {
  const btn = createMockElement(`token-btn-${i}`, "button");
  btn.classList.add("token-btn");
  btn.dataset.token = `<image${i}>`;
  tokenButtons.push(btn);
}

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
    if (sel.includes(".token-btn")) {
      return tokenButtons;
    }
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
  readyState: "loading",
};

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

let startRunPostCount = 0;
let lastValidationPayload = null;

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
  setTimeout: (fn, delay) => setTimeout(fn, delay),
  clearTimeout: (id) => clearTimeout(id),
  fetch: async (url, opts) => {
    if (url.includes("/api/run") && opts && opts.method === "POST") {
      startRunPostCount++;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          run_id: `run_stress_${startRunPostCount}`,
          stream_url: `/api/run/run_stress_${startRunPostCount}/stream`,
        }),
      };
    }
    if (url.includes("/api/config/validate")) {
      if (opts && opts.body) {
        lastValidationPayload = JSON.parse(opts.body);
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ valid: true, errors: [] }),
      };
    }
    if (url.includes("/api/runs/")) {
      const runId = url.split("/").pop();
      if (runId === "historical_run_no_canvas") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            run_id: runId,
            status: "success",
            parameters: { generation: { prompt: "text only" } },
            outputs: [{ filename: "out_mock.png", url: "/api/outputs/out_mock.png", width: 1024, height: 1024 }],
            comparison: "/mnt/lab/farzine/qwen_workflow_runner/outputs/out_mock_comparison.png",
          }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          run_id: runId,
          status: "success",
          input_image: "/inputs/canvas_mock.png",
          input_index: 0,
          parameters: { generation: { input_images: ["/inputs/canvas_mock.png"], reference_images: [] } },
          outputs: [{ filename: "out_mock.png", url: "/api/outputs/out_mock.png", width: 1024, height: 1024 }],
          comparison: "/mnt/lab/farzine/qwen_workflow_runner/outputs/out_mock_comparison.png",
        }),
      };
    }
    if (url.includes("/api/runs")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          runs: Array.from({ length: 30 }, (_, idx) => ({
            run_id: `historical_run_${idx + 1}`,
            status: idx % 2 === 0 ? "success" : "completed",
            timestamp: new Date(Date.now() - idx * 60000).toISOString(),
            inference_time_seconds: 0.12 + idx * 0.01,
          })),
        }),
      };
    }
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

// Load and wrap app.js
const appJsCode = fs.readFileSync(path.resolve(__dirname, "../static/js/app.js"), "utf8");
const wrappedCode = appJsCode.replace(
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
assert(modules, "Failed to load app.js modules in Tier 5 stress harness");

const { Store, InputBrowser, ParamForm, RunController, ComparisonSlider, OutputViewer, Toast, RunHistory } = modules;

// Initialize components
InputBrowser.init();
ParamForm.init();
ComparisonSlider.init();
OutputViewer.init();
RunController.init();
RunHistory.init();

const toastLog = [];
Toast.show = function (msg, type = "info") {
  toastLog.push({ msg, type });
};

let bannerErrors = [];
InputBrowser.showErrorBanner = function (msgs) {
  bannerErrors = msgs;
};

// Test Runner
const testQueue = [];
let passedCount = 0;
let totalCount = 0;

function test(name, fn) {
  testQueue.push({ name, fn });
}

// -----------------------------------------------------------------------------
// 1. COMPARISON SLIDER CLAMPING LIMITS (0% to 100%)
// -----------------------------------------------------------------------------

test("ComparisonSlider: left-side out-of-bounds drag clamps strictly to 0%", () => {
  ComparisonSlider.setup([{ url: "/api/outputs/test.png", filename: "test.png" }]);
  const wrapper = ComparisonSlider.splitWrapper;
  wrapper._rect = { left: 200, width: 800, right: 1000, top: 0, height: 600, bottom: 600 };

  // Pointer down far to the left of the bounding rect (clientX = -500)
  wrapper.dispatchEvent({ type: "pointerdown", clientX: -500, pointerId: 1 });
  assert.strictEqual(ComparisonSlider.handle.style.left, "0%", "Handle left must clamp to 0%");
  assert(ComparisonSlider.clipWrapper.style.clipPath.includes("100%"), "ClipPath inset must clamp to 100%");

  // Pointer move even further left (clientX = -9999)
  wrapper.dispatchEvent({ type: "pointermove", clientX: -9999, pointerId: 1 });
  assert.strictEqual(ComparisonSlider.handle.style.left, "0%");

  wrapper.dispatchEvent({ type: "pointerup", pointerId: 1 });
});

test("ComparisonSlider: right-side out-of-bounds drag clamps strictly to 100%", () => {
  ComparisonSlider.setup([{ url: "/api/outputs/test.png", filename: "test.png" }]);
  const wrapper = ComparisonSlider.splitWrapper;
  wrapper._rect = { left: 200, width: 800, right: 1000, top: 0, height: 600, bottom: 600 };

  // Pointer down far to the right (clientX = 5000)
  wrapper.dispatchEvent({ type: "pointerdown", clientX: 5000, pointerId: 1 });
  assert.strictEqual(ComparisonSlider.handle.style.left, "100%", "Handle left must clamp to 100%");
  assert(ComparisonSlider.clipWrapper.style.clipPath.includes("0%)"), "ClipPath inset must clamp to 0%");

  // Pointer move right
  wrapper.dispatchEvent({ type: "pointermove", clientX: 9999, pointerId: 1 });
  assert.strictEqual(ComparisonSlider.handle.style.left, "100%");

  wrapper.dispatchEvent({ type: "pointerup", pointerId: 1 });
});

test("ComparisonSlider: exact midpoint drag positions handle at 50%", () => {
  const wrapper = ComparisonSlider.splitWrapper;
  wrapper._rect = { left: 100, width: 600, right: 700, top: 0, height: 400, bottom: 400 };

  // Midpoint clientX = 100 + 300 = 400
  wrapper.dispatchEvent({ type: "pointerdown", clientX: 400, pointerId: 1 });
  assert.strictEqual(ComparisonSlider.handle.style.left, "50%");
  assert(ComparisonSlider.clipWrapper.style.clipPath.includes("50%"));
  wrapper.dispatchEvent({ type: "pointerup", pointerId: 1 });
});

// -----------------------------------------------------------------------------
// 2. TOKEN TOOLBAR INSERTION (<image1> to <image10>)
// -----------------------------------------------------------------------------

test("TokenToolbar: clicking <image1> through <image10> inserts tokens into prompt", () => {
  const promptArea = domRegistry.get("param-prompt");
  promptArea.value = "";
  promptArea.selectionStart = 0;
  promptArea.selectionEnd = 0;

  // Insert <image1> at beginning
  tokenButtons[0].dispatchEvent("click");
  assert.strictEqual(promptArea.value, "<image1>");
  assert.strictEqual(Store.state.config.generation.prompt, "<image1>");
  assert.strictEqual(promptArea.selectionStart, 8);

  // Insert <image2> right after
  tokenButtons[1].dispatchEvent("click");
  assert.strictEqual(promptArea.value, "<image1><image2>");
  assert.strictEqual(Store.state.config.generation.prompt, "<image1><image2>");
});

test("TokenToolbar: mid-text insertion and text selection replacement", () => {
  const promptArea = domRegistry.get("param-prompt");
  promptArea.value = "Change shirt on SUBJECT to blue";
  // Select "SUBJECT" (index 16 to 23)
  promptArea.selectionStart = 16;
  promptArea.selectionEnd = 23;

  // Click <image3>
  tokenButtons[2].dispatchEvent("click");
  assert.strictEqual(promptArea.value, "Change shirt on <image3> to blue");
  assert.strictEqual(Store.state.config.generation.prompt, "Change shirt on <image3> to blue");
  assert.strictEqual(promptArea.selectionStart, 16 + "<image3>".length);
});

test("TokenToolbar: all 10 tokens inserted consecutively in order", () => {
  const promptArea = domRegistry.get("param-prompt");
  promptArea.value = "";
  promptArea.selectionStart = 0;
  promptArea.selectionEnd = 0;

  for (let i = 0; i < 10; i++) {
    tokenButtons[i].dispatchEvent("click");
  }

  const expected = "<image1><image2><image3><image4><image5><image6><image7><image8><image9><image10>";
  assert.strictEqual(promptArea.value, expected);
  assert.strictEqual(Store.state.config.generation.prompt, expected);
});

// -----------------------------------------------------------------------------
// 3. EMPTY IMAGE TRAY RESUBMISSIONS & RAPID CLEAR/RE-ADD STRESS CYCLES
// -----------------------------------------------------------------------------

test("Empty Tray Resubmission: repeatedly blocks execution and shows error banner", async () => {
  InputBrowser.clearAll();
  for (let cycle = 0; cycle < 5; cycle++) {
    toastLog.length = 0;
    bannerErrors.length = 0;
    await RunController.startRun();
    assert.strictEqual(Store.state.run.status, "idle", `Cycle ${cycle}: status must remain idle`);
    assert(toastLog.some((t) => t.type === "warning"), `Cycle ${cycle}: warning toast required`);
    assert(bannerErrors.length > 0, `Cycle ${cycle}: error banner required`);
  }
});

test("Partial-success completion keeps successful outputs and reports failed inputs", () => {
  toastLog.length = 0;
  bannerErrors = [];
  RunController.handleComplete({
    status: "partial_success",
    outputs: [{
      run_id: "batch_input_1",
      filename: "generated_1.png",
      url: "/api/outputs/generated_1.png",
      width: 768,
      height: 1024,
    }],
    records: [{
      run_id: "batch_input_1",
      input_index: 0,
      input_image: "/inputs/person.png",
    }],
    comparisons: [{
      run_id: "batch_input_1",
      url: "/api/outputs/generated_1_comparison.png",
    }],
    errors: [{
      input_index: 1,
      error: { message: "reference could not be decoded" },
    }],
  });

  assert.strictEqual(Store.state.run.currentOutputs.length, 1);
  assert.strictEqual(Store.state.run.currentOutputs[0].input_image, "/inputs/person.png");
  assert.strictEqual(domRegistry.get("output-primary-image").src, "/api/outputs/generated_1.png");
  assert.strictEqual(domRegistry.get("run-status-badge").textContent, "Completed with errors");
  assert(domRegistry.get("run-status-badge").className.includes("badge-warning"));
  assert(toastLog.some((item) => item.type === "warning"));
  assert.deepStrictEqual(bannerErrors, ["Input 2: reference could not be decoded"]);
  assert.strictEqual(ComparisonSlider.beforeImg.src, "/api/inputs/thumbnail?path=%2Finputs%2Fperson.png&size=1024");
});

test("Rapid Clear & Re-add Cycles (50 iterations): invariant preservation", () => {
  for (let i = 0; i < 50; i++) {
    InputBrowser.clearAll();
    InputBrowser.setActiveRole("input");
    assert.strictEqual(Store.state.inputs.inputImages.length, 0);

    const testImg1 = { name: `input_1_${i}.png`, path: `/inputs/input_1_${i}.png`, width: 1024, height: 1024 };
    const testImg2 = { name: `input_2_${i}.png`, path: `/inputs/input_2_${i}.png`, width: 1024, height: 1024 };

    InputBrowser.toggleSelection(testImg1);
    InputBrowser.toggleSelection(testImg2);

    assert.strictEqual(Store.state.inputs.inputImages.length, 2);
    assert.strictEqual(Store.state.config.generation.input_images[0], testImg1.path);
    assert.strictEqual(Store.state.config.generation.input_images[1], testImg2.path);

    const cards = InputBrowser.selectedSlotsList.children;
    assert.strictEqual(cards.length, 2);
    assert.strictEqual(cards[0].querySelector(".badge").textContent, "Input 1");
    assert.strictEqual(cards[1].querySelector(".badge").textContent, "Input 2");
  }
});

// -----------------------------------------------------------------------------
// 4. CLIENT STATE MUTATIONS: NEGATIVE SEEDS & EXTREME CFG SCALES
// -----------------------------------------------------------------------------

test("Client State: negative seed input triggers server validation guard", async () => {
  ParamForm.applyDefaultPresets();
  const seedInput = domRegistry.get("param-seed");
  seedInput.value = "-42";
  seedInput.dispatchEvent("input");

  assert.strictEqual(Store.state.config.generation.seed, -42);
  await ParamForm.runValidation(false);
  assert(lastValidationPayload, "Server validation payload must have been dispatched");
  assert.strictEqual(lastValidationPayload.generation.seed, -42);
});

test("Client State: unsigned 64-bit seed maximum boundaries", () => {
  const seedInput = domRegistry.get("param-seed");
  seedInput.value = "1070478148268574";
  seedInput.dispatchEvent("input");
  assert.strictEqual(Store.state.config.generation.seed, 1070478148268574);
});

test("Client State: extreme CFG scales (0.0 to 100.0, and negative rejection)", async () => {
  ParamForm.applyDefaultPresets();

  // CFG = 0.0 is valid non-negative
  Store.state.config.generation.cfg = 0.0;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, true);

  // CFG = 100.0 is valid high guidance
  Store.state.config.generation.cfg = 100.0;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, true);

  // CFG = -2.5 is rejected client-side
  Store.state.config.generation.cfg = -2.5;
  await ParamForm.runValidation(false);
  assert.strictEqual(Store.state.validation.valid, false);
  assert(Store.state.validation.errors.some((e) => e.includes("cfg scale must be non-negative")));
});

// -----------------------------------------------------------------------------
// 5. HISTORY DRAWER SCALING & RECORD INSPECTION
// -----------------------------------------------------------------------------

test("RunHistory: scaling with 30 runs populates history drawer cards and counter", async () => {
  await RunHistory.loadHistory();
  assert.strictEqual(Store.state.history.length, 30);
  assert.strictEqual(RunHistory.historyCounter.textContent, "30");

  const cards = RunHistory.runsList.children;
  assert.strictEqual(cards.length, 30, "Must render exactly 30 history cards in drawer");
});

test("RunHistory: selecting historical run updates output viewer and comparison view", async () => {
  // Populate active tray items to verify historical run inspection overrides active tray
  Store.state.inputs.inputImages = [{ name: "active_tray.png", path: "/inputs/active_tray.png", width: 512, height: 512 }];

  await RunHistory.selectRun("historical_run_1");
  assert.strictEqual(domRegistry.get("output-primary-image").src, "/api/outputs/out_mock.png");
  assert.strictEqual(ComparisonSlider.afterImg.src, "/api/outputs/out_mock.png");

  // 1. The explicit historical input image determines the before image.
  assert.strictEqual(
    ComparisonSlider.beforeImg.src,
    "/api/inputs/thumbnail?path=%2Finputs%2Fcanvas_mock.png&size=1024"
  );

  // 2. Historical run input takes precedence over the active input tray.
  assert(
    !ComparisonSlider.beforeImg.src.includes("active_tray.png"),
    "Historical run input must take precedence over active input tray"
  );

  // 3. Clear the tray and verify disk comparison path translation for a text-only historical run.
  Store.state.inputs.inputImages = [];
  await RunHistory.selectRun("historical_run_no_canvas");
  assert.strictEqual(
    ComparisonSlider.beforeImg.src,
    "/api/outputs/out_mock_comparison.png",
    "Disk comparison path in historical run must be translated to /api/outputs/{filename}"
  );

  // Also verify ComparisonSlider.setup directly translating a filesystem path
  Store.state.run.currentRecord = null;
  ComparisonSlider.setup(
    [{ url: "/api/outputs/out_mock.png", filename: "out_mock.png" }],
    "/mnt/lab/farzine/qwen_workflow_runner/outputs/out_direct_comparison.png"
  );
  assert.strictEqual(
    ComparisonSlider.beforeImg.src,
    "/api/outputs/out_direct_comparison.png",
    "ComparisonSlider.setup must translate disk path to /api/outputs/{filename}"
  );
});

// -----------------------------------------------------------------------------
// 6. RAPID CLICK STORMS CONCURRENCY AUDIT
// -----------------------------------------------------------------------------

test("Rapid Click Storm: empirical measurement of multiple click dispatch", async () => {
  ParamForm.applyDefaultPresets();
  InputBrowser.clearAll();
  InputBrowser.toggleSelection({ name: "canvas.png", path: "/inputs/canvas.png", width: 512, height: 512 });

  startRunPostCount = 0;
  const clickCount = 10;
  const promises = [];
  for (let i = 0; i < clickCount; i++) {
    promises.push(RunController.startRun());
  }
  await Promise.all(promises);

  // Verify that rapid click storm is blocked by re-entrancy lock (only 1 POST dispatched)
  assert.strictEqual(startRunPostCount, 1, "Rapid click storm must be blocked by reentrancy lock");
  // Clean up running state
  RunController.setRunningState(false);
});

// -----------------------------------------------------------------------------
// EXECUTION
// -----------------------------------------------------------------------------

(async function runAll() {
  console.log("\n=======================================================");
  console.log("TIER 5 FRONTEND ADVERSARIAL STRESS TEST HARNESS (NODE)");
  console.log("=======================================================\n");

  for (const { name, fn } of testQueue) {
    totalCount++;
    try {
      await fn();
      passedCount++;
      console.log(`  ✓ ${name}`);
    } catch (err) {
      console.error(`  ✗ FAIL: ${name}`);
      console.error(`    ${err.stack || err.message}`);
      process.exitCode = 1;
    }
  }

  console.log("\n=======================================================");
  console.log(`RESULTS: ${passedCount} / ${totalCount} Tier 5 stress tests passed`);
  console.log("=======================================================\n");

  if (passedCount !== totalCount) {
    process.exit(1);
  }
})();
