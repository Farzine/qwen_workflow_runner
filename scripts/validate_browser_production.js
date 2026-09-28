#!/usr/bin/env node

/**
 * Hardware-gated production browser validation.
 *
 * Start the UI in production mode and Chrome with remote debugging, then run:
 *   node scripts/validate_browser_production.js \
 *     http://[::1]:9229 http://127.0.0.1:7891
 *
 * The script drives the public DOM exactly as a user does. It requires at least
 * three images in the Child input folder and writes one diagnostic screenshot.
 * Add --navigation-only for a model-free route/layout/status-recovery check.
 * Use --output-dir=/tmp/... to isolate generated records and images.
 * Use --model-id=model_... to validate a specific compatible catalog entry.
 * Use --lora-path=/absolute/adapter.safetensors and --lora-scale=1 for adapters.
 * Use --prompt-file=/path/to/prompt.txt for a model-specific prompt.
 */

const fs = require("node:fs");
const assert = require("node:assert/strict");

const devtoolsUrl = process.argv[2] || "http://[::1]:9229";
const appUrl = process.argv[3] || "http://127.0.0.1:7891";
const collectExisting = process.argv.includes("--collect-existing");
const navigationOnly = process.argv.includes("--navigation-only");
const device = process.argv.find((arg) => arg.startsWith("--device="))?.slice(9) || "cuda:0";
const outputDir = process.argv.find((arg) => arg.startsWith("--output-dir="))?.slice(13);
const modelId = process.argv.find((arg) => arg.startsWith("--model-id="))?.slice(11);
const loraPath = process.argv.find((arg) => arg.startsWith("--lora-path="))?.slice(12) || "";
const loraScale = Number(process.argv.find((arg) => arg.startsWith("--lora-scale="))?.slice(13) || "1");
const promptFile = process.argv.find((arg) => arg.startsWith("--prompt-file="))?.slice(14);
const prompt = promptFile ? fs.readFileSync(promptFile, "utf8").trim()
  : "Transform <image1> into a detailed watercolor portrait. Use the soft blue and gold color palette from <image2>. Preserve the subject's pose and identity.";
const prefix = `browser_validation_${Date.now()}`;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function createTarget() {
  if (collectExisting) {
    const response = await fetch(`${devtoolsUrl}/json/list`);
    if (!response.ok) throw new Error(`Could not list browser targets: HTTP ${response.status}`);
    const targets = await response.json();
    const existing = targets.find((item) => item.type === "page" && item.url.startsWith(appUrl));
    if (!existing) throw new Error(`No existing browser tab found for ${appUrl}`);
    return existing;
  }
  const targetUrl = `${devtoolsUrl}/json/new?${encodeURIComponent(appUrl)}`;
  const response = await fetch(targetUrl, { method: "PUT" });
  if (!response.ok) throw new Error(`Could not create browser target: HTTP ${response.status}`);
  return response.json();
}

class CdpClient {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.sequence = 0;
    this.pending = new Map();
    this.events = [];
  }

  async connect() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
        else pending.resolve(message.result || {});
      } else {
        this.events.push(message);
      }
    });
  }

  call(method, params = {}) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.call("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    }
    return result.result?.value;
  }

  close() {
    this.socket.close();
  }
}

async function waitFor(client, expression, timeoutMs = 30000, label = expression) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await client.evaluate(expression)) return;
    await delay(250);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function checkNavigation(client) {
  const pages = {
    dashboard: ".dashboard-page", inference: "#panel-inputs", batch: "#panel-output",
    history: "#drawer-history", outputs: ".outputs-library", models: "#select-cached-model",
    loras: "#param-model-lora-path", system: "#param-device",
  };
  const selection = () => client.evaluate(`JSON.stringify(['param-prompt', 'select-cached-model',
    'param-model-lora-path', 'param-device'].map(id=>document.getElementById(id).value))`);
  const initial = await selection();
  const layouts = [];
  for (const width of [1440, 900, 390]) {
    await client.call("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: width === 390 });
    for (const [page, selector] of Object.entries(pages)) {
      await client.evaluate(`document.querySelector('[data-page-target="${page}"]').click()`);
      const layout = await client.evaluate(`({page:document.body.dataset.page,
        visible:!!document.querySelector(${JSON.stringify(selector)}).getClientRects().length,
        active:document.querySelector('.page-nav-link[aria-current="page"]').dataset.pageTarget,
        width:innerWidth,scrollWidth:document.documentElement.scrollWidth})`);
      assert.equal(layout.page, page);
      assert.equal(layout.active, page);
      assert(layout.visible && layout.scrollWidth <= layout.width, JSON.stringify(layout));
      assert.equal(await selection(), initial, `${page} changed the selection`);
      layouts.push(layout);
    }
  }
  await client.evaluate(`document.querySelector('[data-page-target="dashboard"]').click()`);
  // Failure injection stays in this diagnostic tab and never reaches the server.
  await client.evaluate(`(async()=>{
    const original=window.fetch;
    try {
      window.fetch=(url,...args)=>url==='/api/health'||url==='/api/runs'||String(url).startsWith('/api/system')
        ? Promise.resolve(new Response(JSON.stringify({detail:'Navigation diagnostic failure'}),{status:503}))
        : original(url,...args);
      document.querySelector('.dashboard-refresh-btn').click();
      while(document.querySelector('.dashboard-refresh-btn').disabled) await new Promise(r=>setTimeout(r,25));
    } finally { window.fetch=original; }
  })()`);
  assert(await client.evaluate(`document.querySelector('.dashboard-server-value').textContent.includes('Disconnected')
    && document.querySelector('.dashboard-recent-list').textContent.includes('retry')
    && document.querySelector('.dashboard-refresh-status').textContent.includes('Some status is unavailable')`));
  await client.evaluate(`document.querySelector('.dashboard-refresh-btn').click()`);
  await waitFor(client, `document.querySelector('.dashboard-refresh-status').textContent==='Status refreshed.'`, 30000, "status recovery");
  assert.equal(await selection(), initial);
  return { layouts, statusRecovery: true };
}

async function collectEvidence(client, filenamePrefix = null) {
  await client.evaluate(`document.querySelector('[data-page-target="batch"]').click();document.getElementById('tab-btn-comparison').click()`);
  await waitFor(client, `[...document.querySelectorAll('#batch-thumbnails-strip .batch-thumb img')].length===2
    && [...document.querySelectorAll('#batch-thumbnails-strip .batch-thumb img')].every(img=>img.complete&&img.naturalWidth>0)`, 30000, "two loaded output images");
  const evidence = await client.evaluate(`(async()=>{
    const response=await fetch('/api/runs');
    if(!response.ok) throw new Error('History request failed: '+response.status);
    const listing=await response.json();
    const filenames=new Set([...document.querySelectorAll('#batch-thumbnails-strip .batch-thumb img')]
      .map(img=>decodeURIComponent(new URL(img.src).pathname.split('/').pop())));
    const summaries=(listing.runs||[]).filter(run=>(run.outputs||[]).some(output=>
      ${filenamePrefix ? `(output.filename||'').startsWith(${JSON.stringify(filenamePrefix)})` : "filenames.has(output.filename)"}));
    const records=[];
    for(const run of summaries) {
      const result=await fetch('/api/runs/'+encodeURIComponent(run.run_id));
      if(!result.ok) throw new Error('Record request failed: '+result.status);
      records.push(await result.json());
    }
    return {
      status:document.getElementById('run-status-badge').textContent.trim(),
      progress:document.getElementById('run-percent-label').textContent.trim(),
      selectedInputs:document.getElementById('selected-count-badge').textContent.trim(),
      selectedReferences:document.getElementById('reference-count-badge').textContent.trim(),
      selectedModelId:document.getElementById('select-cached-model').value,
      selectedLoraPath:document.getElementById('param-model-lora-path').value,
      loraScale:Number(document.getElementById('param-model-lora-scale').value),
      device:document.getElementById('param-device').value,
      outputCount:filenames.size,outputImagesLoaded:true,
      primaryOutput:document.getElementById('output-primary-image').src,
      comparisonBefore:document.getElementById('comparison-before-img').src,
      comparisonAfter:document.getElementById('comparison-after-img').src,
      historyCount:Number(document.getElementById('history-counter').textContent||'0'),
      terminal:document.getElementById('terminal-log-lines').innerText,records,
    };
  })()`);
  assert.equal(evidence.records.length, 2, "Expected two durable records for the displayed batch");
  for (const record of evidence.records) {
    assert.equal(record.status, "success");
    assert.equal(record.backend?.pipeline, "WorkflowQwenImage21Pipeline", "Synthetic output is not production evidence");
    assert.equal(record.parameters.model.selected_model_id, evidence.selectedModelId);
    if (modelId) assert.equal(record.parameters.model.selected_model_id, modelId, "Requested model was not used");
    assert.equal(record.parameters.model.lora_path || "", evidence.selectedLoraPath);
    assert.equal(record.backend.lora.applied, Boolean(evidence.selectedLoraPath));
    if (loraPath) assert.equal(record.backend.lora.path, loraPath, "Requested LoRA was not used");
    assert.equal(record.backend.lora.scale, evidence.loraScale);
    assert.equal(record.parameters.runtime.device, evidence.device);
    assert.equal(record.backend.device, evidence.device);
    assert(record.outputs?.length > 0, "Record has no outputs");
  }
  return evidence;
}

async function main() {
  const target = await createTarget();
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();
  try {
    await Promise.all([
      client.call("Runtime.enable"),
      client.call("Page.enable"),
      client.call("Network.enable"),
    ]);
    await client.call("Network.setCacheDisabled", { cacheDisabled: true });

    await waitFor(
      client,
      `document.readyState === "complete" && document.querySelector('.page-nav-link[aria-current="page"]')
        && document.querySelector('.dashboard-server-value').textContent.includes('Snapshot:')`,
      60000,
      "application initialization"
    );

    if (navigationOnly) {
      console.log(JSON.stringify(await checkNavigation(client), null, 2));
      return;
    }

    if (collectExisting) {
      const browserEvidence = await collectEvidence(client);
      const shot = await client.call("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
      const screenshotPath = "/tmp/phase8-browser-production.png";
      fs.writeFileSync(screenshotPath, Buffer.from(shot.data, "base64"));
      console.log(JSON.stringify({ collectExisting: true, screenshotPath, browserEvidence }, null, 2));
      return;
    }

    const initialHistoryCount = Number(await client.evaluate(
      `document.getElementById("history-counter").textContent || "0"`
    ));
    if (modelId) {
      await client.evaluate(`document.querySelector('[data-page-target="models"]').click()`);
      assert(await client.evaluate(`(() => {
        const select = document.getElementById('select-cached-model');
        const option = [...select.options].find(option => option.value === ${JSON.stringify(modelId)} && !option.disabled);
        if (!option) return false;
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        document.getElementById('btn-apply-cached-model').click();
        return true;
      })()`), "Requested model is missing or incompatible");
    }
    assert(await client.evaluate(`document.getElementById('select-cached-model').value`), "Select a compatible downloaded model before production validation");
    await client.evaluate(`document.querySelector('[data-page-target="inference"]').click()`);

    const openedChild = await client.evaluate(`(() => {
      const button = [...document.querySelectorAll(".subfolder-chip")]
        .find((item) => item.textContent.includes("Child"));
      if (!button) return false;
      button.click();
      return true;
    })()`);
    if (!openedChild) throw new Error("Child input folder was not rendered");
    await waitFor(client, `document.querySelectorAll(".input-image-card").length >= 3`, 30000, "Child gallery");

    const selectedNames = [];
    for (const index of [0, 1]) {
      selectedNames.push(await client.evaluate(`(() => {
        const card = document.querySelectorAll(".input-image-card")[${index}];
        if (!card) return null;
        const name = card.dataset.name;
        card.click();
        return name;
      })()`));
      await waitFor(
        client,
        `document.getElementById("selected-count-badge").textContent.startsWith("${index + 1} ")`,
        10000,
        `${index + 1} selected inputs`
      );
    }

    await client.evaluate(`document.getElementById("btn-select-references").click()`);
    selectedNames.push(await client.evaluate(`(() => {
      const card = document.querySelectorAll(".input-image-card")[2];
      if (!card) return null;
      const name = card.dataset.name;
      card.click();
      return name;
    })()`));
    await waitFor(
      client,
      `document.getElementById("reference-count-badge").textContent.startsWith("1 ")`,
      10000,
      "one selected reference"
    );

    const configResult = await client.evaluate(`(() => {
      const setValue = (id, value, eventName = "input") => {
        const element = document.getElementById(id);
        if (!element) throw new Error("Missing control: " + id);
        element.value = String(value);
        element.dispatchEvent(new Event(eventName, { bubbles: true }));
      };
      const setChecked = (id, checked) => {
        const element = document.getElementById(id);
        if (!element) throw new Error("Missing control: " + id);
        element.checked = checked;
        element.dispatchEvent(new Event("change", { bubbles: true }));
      };

      setValue("param-prompt", ${JSON.stringify(prompt)});
      document.getElementById("tab-btn-generation").click();
      setValue("param-steps", 4);
      setValue("param-resolution", 512, "change");
      setChecked("param-custom-size", true);
      setValue("param-width", 256);
      setValue("param-height", 256);
      setValue("param-filename-prefix", ${JSON.stringify(prefix)});
      if (${JSON.stringify(Boolean(outputDir))}) setValue("param-output-dir", ${JSON.stringify(outputDir || "")});
      setChecked("param-save-comparison", true);
      setChecked("toggle-demo-mode", false);

      document.getElementById("tab-btn-system").click();
      setValue("param-device", ${JSON.stringify(device)}, "change");
      setValue("param-dtype", "bfloat16", "change");
      setValue("param-offload", "model", "change");
      document.getElementById("btn-apply-system").click();

      document.getElementById("tab-btn-model").click();
      setChecked("param-model-offline", true);
      const loraSelect = document.getElementById("param-model-lora-path");
      if (![...loraSelect.options].some(option => option.value === ${JSON.stringify(loraPath)} && !option.disabled))
        throw new Error("Requested LoRA is missing or invalid");
      setValue("param-model-lora-path", ${JSON.stringify(loraPath)}, "change");
      setValue("param-model-lora-scale", ${JSON.stringify(loraScale)});
      document.getElementById("tab-btn-prompt").click();
      return {
        prompt: document.getElementById("param-prompt").value,
        device: document.getElementById("param-device").value,
        dtype: document.getElementById("param-dtype").value,
        offload: document.getElementById("param-offload").value,
        demo: document.getElementById("toggle-demo-mode").checked,
        prefix: document.getElementById("param-filename-prefix").value,
      };
    })()`);

    await delay(1000);
    await waitFor(client, `!document.getElementById('btn-run-pipeline').disabled`, 30000, "valid production configuration");
    await client.evaluate(`document.getElementById("btn-run-pipeline").click()`);
    await client.evaluate(`document.querySelector('[data-page-target="batch"]').click()`);

    let observedRunning = false;
    let observedProgress = false;
    let maxPercent = 0;
    const statuses = [];
    const started = Date.now();
    const timeoutMs = 10 * 60 * 1000;
    while (Date.now() - started < timeoutMs) {
      const state = await client.evaluate(`(() => ({
        status: document.getElementById("run-status-badge").textContent.trim(),
        percent: Number((document.getElementById("run-percent-label").textContent || "0").replace("%", "")),
        busy: document.getElementById("panel-output").getAttribute("aria-busy"),
        outputs: document.querySelectorAll("#batch-thumbnails-strip .batch-thumb").length,
        error: [document.getElementById("batch-progress-items")?.innerText,
          document.getElementById("terminal-log-lines")?.innerText.slice(-2000)].filter(Boolean).join("\\n")
      }))()`);
      if (!statuses.includes(state.status)) statuses.push(state.status);
      observedRunning ||= state.busy === "true" || /RUNNING|QUEUED/i.test(state.status);
      maxPercent = Math.max(maxPercent, state.percent || 0);
      observedProgress ||= state.percent > 0;
      if (/Completed/i.test(state.status) && state.outputs === 2) break;
      if (/Failed|Completed with errors/i.test(state.status)) {
        throw new Error(`Browser run ${state.status}: ${state.error}`);
      }
      await delay(500);
    }

    await waitFor(
      client,
      `document.querySelectorAll("#batch-thumbnails-strip .batch-thumb").length === 2`,
      30000,
      "two rendered outputs"
    );
    await waitFor(
      client,
      `[...document.querySelectorAll("#batch-thumbnails-strip .batch-thumb img")].every((img) => img.complete && img.naturalWidth > 0)`,
      30000,
      "loaded output thumbnails"
    );
    await waitFor(
      client,
      `Number(document.getElementById("history-counter").textContent || "0") >= ${initialHistoryCount + 2}`,
      30000,
      "updated run history"
    );

    const browserEvidence = await collectEvidence(client, prefix);
    const shot = await client.call("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    const screenshotPath = "/tmp/phase8-browser-production.png";
    fs.writeFileSync(screenshotPath, Buffer.from(shot.data, "base64"));

    const result = {
      prefix,
      selectedNames,
      configResult,
      observedRunning,
      observedProgress,
      maxPercent,
      statuses,
      screenshotPath,
      browserEvidence,
    };
    console.log(JSON.stringify(result, null, 2));
  } finally { client.close(); }
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
