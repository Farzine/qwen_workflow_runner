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
 */

const fs = require("node:fs");

const devtoolsUrl = process.argv[2] || "http://[::1]:9229";
const appUrl = process.argv[3] || "http://127.0.0.1:7891";
const collectExisting = process.argv.includes("--collect-existing");
const prefix = `phase8_browser_${Date.now()}`;

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

async function main() {
  const target = await createTarget();
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();
  await Promise.all([
    client.call("Runtime.enable"),
    client.call("Page.enable"),
    client.call("Network.enable"),
  ]);

  await waitFor(
    client,
    `document.readyState === "complete" && document.querySelectorAll(".subfolder-chip").length > 0`,
    60000,
    "application initialization"
  );

  if (collectExisting) {
    const browserEvidence = await client.evaluate(`(async () => {
      const listing = await (await fetch("/api/runs")).json();
      const summaries = (listing.runs || []).filter((item) =>
        (item.outputs || []).some((output) => (output.filename || "").startsWith("phase8_browser_"))
      ).slice(0, 2);
      const records = [];
      for (const summary of summaries) {
        records.push(await (await fetch("/api/runs/" + encodeURIComponent(summary.run_id))).json());
      }
      document.getElementById("tab-btn-comparison").click();
      return {
        status: document.getElementById("run-status-badge").textContent.trim(),
        progress: document.getElementById("run-percent-label").textContent.trim(),
        selectedInputs: document.getElementById("selected-count-badge").textContent.trim(),
        selectedReferences: document.getElementById("reference-count-badge").textContent.trim(),
        outputCount: document.querySelectorAll("#batch-thumbnails-strip .batch-thumb").length,
        outputImagesLoaded: [...document.querySelectorAll("#batch-thumbnails-strip .batch-thumb")]
          .every((img) => img.complete && img.naturalWidth > 0),
        primaryOutput: document.getElementById("output-primary-image").src,
        comparisonBefore: document.getElementById("comparison-before-img").src,
        comparisonAfter: document.getElementById("comparison-after-img").src,
        historyCount: Number(document.getElementById("history-counter").textContent || "0"),
        terminal: document.getElementById("terminal-log-lines").innerText,
        records,
      };
    })()`);
    const shot = await client.call("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    const screenshotPath = "/tmp/phase8-browser-production.png";
    fs.writeFileSync(screenshotPath, Buffer.from(shot.data, "base64"));
    console.log(JSON.stringify({ collectExisting: true, screenshotPath, browserEvidence }, null, 2));
    client.close();
    return;
  }

  const initialHistoryCount = Number(await client.evaluate(
    `document.getElementById("history-counter").textContent || "0"`
  ));

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

    setValue("param-prompt", "Transform <image1> into a detailed watercolor portrait. Use the soft blue and gold color palette from <image2>. Preserve the subject's pose and identity.");
    document.getElementById("tab-btn-generation").click();
    setValue("param-steps", 4);
    setValue("param-resolution", 512, "change");
    setChecked("param-custom-size", true);
    setValue("param-width", 256);
    setValue("param-height", 256);
    setValue("param-filename-prefix", ${JSON.stringify(prefix)});
    setChecked("param-save-comparison", true);
    setChecked("toggle-demo-mode", false);

    document.getElementById("tab-btn-system").click();
    setValue("param-device", "cuda:0", "change");
    setValue("param-dtype", "bfloat16", "change");
    setValue("param-offload", "model", "change");
    document.getElementById("btn-apply-system").click();

    document.getElementById("tab-btn-model").click();
    setChecked("param-model-offline", true);
    setValue("param-model-lora-path", "", "change");
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
  await client.evaluate(`document.getElementById("btn-run-pipeline").click()`);

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
      alert: document.getElementById("validation-alert")?.textContent.trim() || ""
    }))()`);
    if (!statuses.includes(state.status)) statuses.push(state.status);
    observedRunning ||= state.busy === "true" || /RUNNING|QUEUED/i.test(state.status);
    maxPercent = Math.max(maxPercent, state.percent || 0);
    observedProgress ||= state.percent > 0;
    if (/Completed/i.test(state.status) && state.outputs === 2) break;
    if (/Failed/i.test(state.status)) throw new Error(`Browser run failed: ${state.alert}`);
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
    `[...document.querySelectorAll("#batch-thumbnails-strip .batch-thumb")].every((img) => img.complete && img.naturalWidth > 0)`,
    30000,
    "loaded output thumbnails"
  );
  await waitFor(
    client,
    `Number(document.getElementById("history-counter").textContent || "0") >= ${initialHistoryCount + 2}`,
    30000,
    "updated run history"
  );

  const browserEvidence = await client.evaluate(`(async () => {
    const listing = await (await fetch("/api/runs")).json();
    const summaries = (listing.runs || []).filter((item) =>
      (item.parameters?.runtime?.filename_prefix || "") === ${JSON.stringify(prefix)}
    );
    const records = [];
    for (const summary of summaries) {
      records.push(await (await fetch("/api/runs/" + encodeURIComponent(summary.run_id))).json());
    }
    document.getElementById("tab-btn-comparison").click();
    return {
      status: document.getElementById("run-status-badge").textContent.trim(),
      selectedInputs: document.getElementById("selected-count-badge").textContent.trim(),
      selectedReferences: document.getElementById("reference-count-badge").textContent.trim(),
      outputCount: document.querySelectorAll("#batch-thumbnails-strip .batch-thumb").length,
      outputImagesLoaded: [...document.querySelectorAll("#batch-thumbnails-strip .batch-thumb")]
        .every((img) => img.complete && img.naturalWidth > 0),
      primaryOutput: document.getElementById("output-primary-image").src,
      comparisonBefore: document.getElementById("comparison-before-img").src,
      comparisonAfter: document.getElementById("comparison-after-img").src,
      historyCount: Number(document.getElementById("history-counter").textContent || "0"),
      terminal: document.getElementById("terminal-log-lines").innerText,
      records,
    };
  })()`);

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
  client.close();
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
