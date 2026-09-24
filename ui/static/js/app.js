/**
 * ui/static/js/app.js
 *
 * Modern Frontend Controller for Qwen Image 2.1 Workflow Runner
 * Pure Vanilla ES6 — Zero External CDN / Library Dependencies
 *
 * Requirements Covered:
 * - R1: Separate ordered process inputs and shared references with upload/drop support
 * - R2: Parameter Form & Live Debounced Validation against POST /api/config/validate
 * - R3: Model Management (Cached models catalog, HF async download with live progress, chunked file upload)
 * - R4: Run Execution & Live SSE Streaming (console logs, progress bar, output gallery, SHA-256 badge, comparison slider, JSON record, run history)
 */

(function () {
  "use strict";

  // ==========================================================================
  // 1. UTILITIES & DOM HELPERS (Security, Formatting, ANSI, Random Seed)
  // ==========================================================================

  const Utils = {
    escapeHtml(str) {
      if (str === null || str === undefined) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    },

    el(tag, props = {}, ...children) {
      const element = document.createElement(tag);

      for (const [key, value] of Object.entries(props || {})) {
        if (value === undefined || value === null) continue;

        if (key === "class" || key === "className") {
          element.className = value;
        } else if (key === "style" && typeof value === "object") {
          Object.assign(element.style, value);
        } else if (key === "dataset" && typeof value === "object") {
          for (const [dKey, dVal] of Object.entries(value)) {
            element.dataset[dKey] = dVal;
          }
        } else if (key.startsWith("on") && typeof value === "function") {
          const evt = key.slice(2).toLowerCase();
          element.addEventListener(evt, value);
        } else if (key === "attrs" && typeof value === "object") {
          for (const [aKey, aVal] of Object.entries(value)) {
            element.setAttribute(aKey, aVal);
          }
        } else {
          element.setAttribute(key, value);
        }
      }

      for (const child of children) {
        if (child === null || child === undefined) continue;
        if (typeof child === "string" || typeof child === "number") {
          element.appendChild(document.createTextNode(String(child)));
        } else if (child instanceof Node) {
          element.appendChild(child);
        } else if (Array.isArray(child)) {
          for (const subChild of child) {
            if (subChild instanceof Node) {
              element.appendChild(subChild);
            } else if (subChild !== null && subChild !== undefined) {
              element.appendChild(document.createTextNode(String(subChild)));
            }
          }
        }
      }

      return element;
    },

    debounce(fn, wait = 300) {
      let timeout = null;
      const debounced = function (...args) {
        if (timeout) clearTimeout(timeout);
        timeout = setTimeout(() => {
          timeout = null;
          fn.apply(this, args);
        }, wait);
      };
      debounced.cancel = () => {
        if (timeout) {
          clearTimeout(timeout);
          timeout = null;
        }
      };
      return debounced;
    },

    formatBytes(bytes, decimals = 1) {
      if (!bytes || bytes === 0) return "0 B";
      const k = 1024;
      const dm = decimals < 0 ? 0 : decimals;
      const sizes = ["B", "KB", "MB", "GB", "TB"];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
    },

    async copyToClipboard(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
          await navigator.clipboard.writeText(text);
          return true;
        } catch (e) {
          // fallback below
        }
      }
      const textArea = document.createElement("textarea");
      textArea.value = text;
      textArea.style.position = "fixed";
      textArea.style.opacity = "0";
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      let success = false;
      try {
        success = document.execCommand("copy");
      } catch (err) {
        success = false;
      }
      document.body.removeChild(textArea);
      return success;
    },

    parseLogLine(text, stream = "stdout") {
      const lineContainer = document.createElement("div");
      lineContainer.className = `terminal-line stream-${stream}`;

      const clean = text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "");

      let levelClass = "log-info";
      if (/error|traceback|exception|failed/i.test(clean)) {
        levelClass = "log-error";
      } else if (/warning|warn/i.test(clean)) {
        levelClass = "log-warning";
      } else if (/step\s*\d+|progress|completed|done|success/i.test(clean)) {
        levelClass = "log-success";
      }

      lineContainer.classList.add(levelClass);
      lineContainer.appendChild(document.createTextNode(clean));
      return lineContainer;
    },

    generateRandomSeed() {
      const arr = new Uint32Array(2);
      window.crypto.getRandomValues(arr);
      const seed = (BigInt(arr[0]) << 32n) | BigInt(arr[1]);
      return seed.toString();
    },
  };


  // ==========================================================================
  // 2. TOAST NOTIFICATION MANAGER
  // ==========================================================================

  const Toast = {
    container: null,

    init() {
      this.container = document.getElementById("toast-container");
      if (!this.container) {
        this.container = Utils.el("div", { id: "toast-container", class: "toast-container" });
        document.body.appendChild(this.container);
      }
    },

    show(message, type = "info", duration = 4000) {
      if (!this.container) this.init();

      const toast = Utils.el(
        "div",
        { class: `toast toast-${type} fade-in` },
        Utils.el("div", { class: "toast-content" }, message),
        Utils.el(
          "button",
          {
            class: "toast-close-btn",
            attrs: { "aria-label": "Close" },
            onclick: () => this.dismiss(toast),
          },
          "×"
        )
      );

      this.container.appendChild(toast);

      if (duration > 0) {
        setTimeout(() => {
          this.dismiss(toast);
        }, duration);
      }
    },

    dismiss(toast) {
      if (!toast || !toast.parentNode) return;
      toast.classList.add("fade-out");
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 250);
    },
  };


  // ==========================================================================
  // 3. REACTIVE STATE STORE
  // ==========================================================================

  const Store = {
    state: {
      connected: false,
      inputs: {
        currentFolder: "",
        parentFolder: null,
        folders: [],
        images: [],
        inputImages: [], // Ordered process inputs
        referenceImages: [], // Ordered shared conditioning references
        activeRole: "input",
      },
      config: {
        model: {
          source: "https://huggingface.co/Qwen/Qwen-Image-2.1",
          revision: "main",
          filename: null,
          gguf_quantization: "Q4_K_M",
          base_model: "Qwen/Qwen-Image-2.1",
          base_revision: null,
          text_encoder_source: null,
          cache_dir: "models",
          offline: false,
          lora_path: null,
          lora_scale: 1.0,
        },
        generation: {
          input_images: [],
          reference_images: [],
          prompt: "Keep the character and pose in <image1> unchanged, put this light blue denim shirt from <image2> on the character...",
          negative_prompt: "",
          steps: 25,
          cfg: 1.0,
          seed: 1070478148268574,
          strength: 1.0,
          resolution: 0,
          custom_size: false,
          width: 1024,
          height: 1024,
          batch_size: 1,
          sampler: "euler",
          scheduler: "simple",
          shift: 0.69,
          kv_cache: true,
          kv_cache_device: "auto",
          kv_cache_reserve_gib: 1.0,
          reference_mode: "rgb",
        },
        runtime: {
          device: "cuda:0",
          dtype: "bfloat16",
          offload: "model",
          vae_tiling: false,
          repeats: 1,
          warmup_runs: 0,
          increment_seed: false,
          memory_poll_seconds: 0.02,
          output_dir: "outputs",
          filename_prefix: "Qwen_image_2.1",
          save_comparison: true,
        },
        demo_mode: false,
      },
      system: {
        capabilities: null,
      },
      models: {
        cached: [],
        selectedId: null,
        activeTask: null,
      },
      loras: {
        available: [],
      },
      run: {
        status: "idle", // idle, running, completed, error
        activeJobId: null,
        progress: { step: 0, total: 25, percent: 0 },
        currentOutputs: [],
        currentRecord: null,
      },
      history: [],
      validation: {
        valid: true,
        errors: [],
      },
    },

    listeners: [],

    subscribe(fn) {
      this.listeners.push(fn);
    },

    notify(key) {
      for (const fn of this.listeners) {
        fn(key, this.state);
      }
    },
  };


  // ==========================================================================
  // 4. RESPONSIVE WORKSPACE NAVIGATION
  // ==========================================================================

  const ResponsiveWorkspace = {
    navButtons: [],
    outputPanel: null,
    outputBackdrop: null,
    outputCloseBtn: null,
    lastTrigger: null,

    init() {
      this.navButtons = Array.from(document.querySelectorAll("[data-workflow-target]"));
      this.outputPanel = document.getElementById("panel-output");
      this.outputBackdrop = document.querySelector(".output-drawer-backdrop");
      this.outputCloseBtn = document.querySelector(".output-drawer-close");

      this.navButtons.forEach((button) => {
        button.addEventListener("click", () => this.showSection(button.dataset.workflowTarget, button));
      });
      if (this.outputCloseBtn) this.outputCloseBtn.addEventListener("click", () => this.closeOutput(true));
      if (this.outputBackdrop) this.outputBackdrop.addEventListener("click", () => this.closeOutput(true));

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && this.outputPanel && this.outputPanel.classList.contains("drawer-open")) {
          this.closeOutput(true);
        }
      });
      if (typeof window.addEventListener === "function") {
        window.addEventListener("resize", () => this.handleResize());
      }
    },

    viewportWidth() {
      return window.innerWidth || (document.documentElement && document.documentElement.clientWidth) || 1200;
    },

    setActive(targetId) {
      this.navButtons.forEach((button) => {
        const active = button.dataset.workflowTarget === targetId;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    },

    showSection(targetId, trigger = null) {
      const target = document.getElementById(targetId);
      if (!target) return;
      this.setActive(targetId);

      const width = this.viewportWidth();
      if (targetId === "panel-output" && width > 768 && width <= 1024) {
        this.openOutput(trigger);
        return;
      }

      this.closeOutput(false);
      if (typeof target.scrollIntoView === "function") {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      target.setAttribute("tabindex", "-1");
      if (typeof target.focus === "function") target.focus({ preventScroll: true });
    },

    openOutput(trigger = null) {
      if (!this.outputPanel) return;
      this.lastTrigger = trigger || this.lastTrigger;
      this.outputPanel.classList.add("drawer-open");
      const resultsButton = this.navButtons.find((button) => button.dataset.workflowTarget === "panel-output");
      if (resultsButton) resultsButton.setAttribute("aria-expanded", "true");
      if (this.outputBackdrop) {
        this.outputBackdrop.classList.remove("hidden");
        this.outputBackdrop.setAttribute("aria-hidden", "false");
      }
      if (this.outputCloseBtn && typeof this.outputCloseBtn.focus === "function") {
        this.outputCloseBtn.focus();
      }
    },

    closeOutput(restoreFocus = false) {
      if (this.outputPanel) this.outputPanel.classList.remove("drawer-open");
      const resultsButton = this.navButtons.find((button) => button.dataset.workflowTarget === "panel-output");
      if (resultsButton) resultsButton.setAttribute("aria-expanded", "false");
      if (this.outputBackdrop) {
        this.outputBackdrop.classList.add("hidden");
        this.outputBackdrop.setAttribute("aria-hidden", "true");
      }
      if (restoreFocus && this.lastTrigger && typeof this.lastTrigger.focus === "function") {
        this.lastTrigger.focus();
      }
    },

    handleResize() {
      const width = this.viewportWidth();
      if (width > 1024 || width <= 768) this.closeOutput(false);
    },

    revealRunStatus() {
      const width = this.viewportWidth();
      this.setActive("panel-output");
      if (width > 768 && width <= 1024) this.openOutput();
    },
  };


  // ==========================================================================
  // 5. IMPLEMENTATION-BACKED PARAMETER HELP
  // ==========================================================================

  const PARAMETER_HELP = Object.freeze({
    "param-prompt": {
      title: "Positive Prompt",
      summary: "Text instructions and image tokens are encoded together to condition generation.",
      details: [["Use", "<image1> is the current process input; <image2> onward follow the ordered reference list."], ["Trade-off", "Specific instructions improve control, while conflicting or very long instructions can weaken adherence."]],
    },
    "param-negative-prompt": {
      title: "Negative Prompt",
      summary: "Describes content to suppress through a second conditioning pass.",
      details: [["Activation", "This implementation uses it only when the text is non-empty and CFG is not exactly 1."], ["Trade-off", "It adds another model prediction per denoising step and therefore increases inference work."]],
    },
    "param-steps": {
      title: "Denoising Steps",
      summary: "Number of Euler updates applied to the generated latent.",
      details: [["Higher", "Usually allows more refinement but increases inference time almost linearly; gains eventually diminish."], ["Lower", "Runs faster but may leave composition or fine detail underdeveloped."], ["Range", "Validated from 1 to 10,000; default 25. Steps divided by strength must remain at most 10,000."]],
    },
    "param-cfg": {
      title: "CFG Scale",
      summary: "Scales the difference between positive and negative conditioning predictions.",
      details: [["Higher", "Strengthens that guidance but can overconstrain the result or amplify artifacts."], ["Lower", "Reduces guidance; values below 1 invert or weaken the positive-versus-negative difference."], ["Activation", "CFG 1 disables the negative pass. Other values require a non-empty negative prompt to have an effect."]],
    },
    "param-strength": {
      title: "Denoise Strength",
      summary: "Chooses the tail of the flow schedule used to denoise an empty generated latent.",
      details: [["Higher", "Starts from a noisier point and permits broader generation."], ["Lower", "Starts later in the schedule and generally limits variation, but it does not blend or preserve input pixels directly."], ["Range", "Greater than 0 through 1. Steps divided by strength must remain at most 10,000."]],
    },
    "param-shift": {
      title: "Flow Shift",
      summary: "Transforms every sigma in the flow-matching schedule.",
      details: [["Higher", "Raises intermediate sigma values, retaining stronger noise later in denoising."], ["Lower", "Reduces intermediate sigma values and moves the trajectory toward lower-noise states sooner."], ["Range", "Validated from -10 to 10; the workflow default is 0.69 and changes are model-sensitive."]],
    },
    "param-seed": {
      title: "Seed",
      summary: "Initializes the deterministic CPU float32 noise used for generation.",
      details: [["Same value", "Reproduces the same starting noise when the model, inputs, parameters, and runtime are unchanged."], ["Different value", "Changes the generated composition and details."], ["Range", "Unsigned 64-bit integer from 0 through 18,446,744,073,709,551,615."]],
    },
    "param-increment-seed": {
      title: "Increment Seed",
      summary: "Advances the configured seed once per measured repeat.",
      details: [["Enabled", "Repeat 1 uses the base seed, repeat 2 uses seed + 1, wrapping at 64 bits."], ["Input batches", "All process inputs within the same repeat share that repeat's seed."]],
    },
    "param-resolution": {
      title: "Reference Resolution",
      summary: "Resizes every conditioning image to approximately this square-pixel budget while preserving aspect ratio.",
      details: [["Higher", "Retains more conditioning detail but increases VAE, attention, memory, and processing cost."], ["Lower", "Reduces memory and latency but may lose fine reference detail."], ["Native (0)", "Keeps original image dimensions rounded to multiples of 32. Large references can exhaust VRAM or degrade results; use a bounded preset unless native size is intentional."]],
    },
    "param-custom-size": {
      title: "Custom Output Canvas",
      summary: "Overrides the generated canvas dimensions instead of using the first process input's resized dimensions.",
      details: [["Enabled", "Width and height below control only the generated canvas; reference resizing still follows Reference Resolution."], ["Trade-off", "Larger canvases increase latent and attention memory sharply and take longer to generate."]],
    },
    "param-width": {
      title: "Output Width",
      summary: "Generated canvas width when Custom Output Canvas is enabled.",
      details: [["Higher", "Produces more horizontal pixels at greater memory and compute cost."], ["Lower", "Uses less memory and runs faster with less spatial detail."], ["Range", "Positive multiple of 32, up to the UI limit of 4096."]],
    },
    "param-height": {
      title: "Output Height",
      summary: "Generated canvas height when Custom Output Canvas is enabled.",
      details: [["Higher", "Produces more vertical pixels at greater memory and compute cost."], ["Lower", "Uses less memory and runs faster with less spatial detail."], ["Range", "Positive multiple of 32, up to the UI limit of 4096."]],
    },
    "param-sampler": {
      title: "Sampler",
      summary: "Numerical method used for each denoising update.",
      details: [["Supported", "Euler is the only implemented sampler and unsupported values are rejected rather than ignored."], ["Behavior", "It consumes the explicit sigma schedule produced by Strength, Shift, and Scheduler."]],
    },
    "param-scheduler": {
      title: "Sigma Scheduler",
      summary: "Controls how denoising sigma values are spaced before the flow shift is applied.",
      details: [["Simple", "Samples the 10,000-point Comfy-compatible training schedule by index."], ["Normal", "Interpolates evenly through the shifted sigma range."], ["Trade-off", "The schedules can change texture and convergence; neither adds steps or reduces the configured step count."]],
    },
    "param-batch-size": {
      title: "Batch Size",
      summary: "Number of output images generated together for each process input and repeat.",
      details: [["Higher", "Produces more alternatives per model call but increases latent and model memory, often substantially."], ["Lower", "Uses less memory; batch size 1 is the safest production default."], ["Interaction", "Total outputs are process inputs × repeats × batch size, excluding warmups from the completion gallery."]],
    },
    "param-reference-mode": {
      title: "Reference Color Mode",
      summary: "Pillow conversion applied to every process and reference image before model preprocessing.",
      details: [["RGB", "Matches the connected Comfy LoadImage IMAGE output and discards alpha."], ["RGBA", "Preserves an alpha channel during loading; downstream processor and VAE behavior determines how it contributes."], ["Trade-off", "RGB is the verified default and avoids unexpected transparency handling."]],
    },
    "param-kv-cache": {
      title: "Transformer KV Cache",
      summary: "Caches the unchanged conditioning prefix across denoising steps without quantizing it.",
      details: [["Enabled", "Can reduce repeated transformer work but consumes GPU or system memory."], ["Disabled", "Recomputes the prefix every step, reducing cache storage at the cost of longer inference."], ["Scope", "The cache is lossless and is rebuilt for each generation call."]],
    },
    "param-kv-cache-device": {
      title: "KV Cache Device",
      summary: "Chooses where lossless transformer prefix keys and values are stored.",
      details: [["Auto", "Keeps a layer on CUDA only when enough free memory remains after the configured reserve and safety allowance; otherwise spills it to CPU."], ["GPU", "Always stores the cache on the compute device for speed and higher VRAM use."], ["CPU", "Stores it in system RAM and transfers it back synchronously, lowering VRAM use but increasing latency."]],
    },
    "param-kv-cache-reserve-gib": {
      title: "KV Cache VRAM Reserve",
      summary: "CUDA headroom preserved by the automatic KV-cache placement policy.",
      details: [["Higher", "Causes auto mode to spill cache layers to CPU sooner, reducing out-of-memory risk but slowing transfers."], ["Lower", "Keeps more cache layers on GPU for speed with less safety headroom."], ["Scope", "Used only by Auto on CUDA; default 1 GiB."]],
    },
    "param-vae-tiling": {
      title: "VAE Tiling",
      summary: "Enables tiled VAE decoding instead of decoding the complete latent at once.",
      details: [["Enabled", "Reduces peak decode memory and can prevent out-of-memory failures on large canvases."], ["Trade-off", "May decode more slowly and can introduce tile-boundary differences."], ["Use", "Enable when VAE decoding fails or high-resolution output is close to the memory limit."]],
    },
    "param-repeats": {
      title: "Measured Repeats",
      summary: "Runs the complete input batch this many times after warmups while reusing one loaded model.",
      details: [["Higher", "Creates more measured samples and durable records but multiplies total runtime and output storage."], ["Lower", "One repeat is appropriate for normal generation."], ["Interaction", "Increment Seed changes the seed between repeats; process inputs within a repeat share it."]],
    },
    "param-warmup-runs": {
      title: "Warmup Runs",
      summary: "Runs the complete input batch before measured repeats to warm kernels and caches.",
      details: [["Higher", "Can make later benchmark timings more representative but adds full inference time."], ["Artifacts", "Warmups still write JSON and image files, although the completion gallery excludes their outputs."], ["Default", "Zero avoids extra generation work for interactive use."]],
    },
    "param-memory-poll-seconds": {
      title: "Memory Poll Interval",
      summary: "Sampling interval used by the inference memory monitor.",
      details: [["Lower", "Samples peaks more frequently but increases monitoring overhead."], ["Higher", "Reduces polling overhead but may miss brief allocation peaks."], ["Range", "0.001 to 1 second; default 0.02 seconds."]],
    },
    "param-output-dir": {
      title: "Output Directory",
      summary: "Directory used for generated PNGs, comparisons, and durable JSON run records.",
      details: [["Web safety", "The API accepts locations only within the project, configured outputs root, or system temporary directory."], ["Behavior", "Relative paths resolve from the project process working directory and are created when needed."]],
    },
    "param-filename-prefix": {
      title: "Filename Prefix",
      summary: "Prefix placed before generated run IDs and output indexes.",
      details: [["Allowed", "A non-empty filename component without forward or backward slashes."], ["Behavior", "Run IDs and numeric image indexes are appended automatically to avoid collisions."]],
    },
    "param-save-comparison": {
      title: "Comparison Image",
      summary: "Saves a side-by-side PNG of the process input and first generated image for each input attempt.",
      details: [["Enabled", "Adds a review artifact and extra image resize/write work."], ["Disabled", "Generated outputs and JSON records are still saved normally."]],
    },
    "param-device": {
      title: "Execution Device",
      summary: "Exact CPU, MPS, or CUDA device used for model placement, metrics, and inference.",
      details: [["CUDA", "Uses the selected GPU index; available memory and readiness are shown on this page."], ["CPU", "Requires float32 with no offload and is expected to be very slow."], ["Lifecycle", "Changes apply to the next job. A compatible pipeline stays resident on its selected device between jobs."]],
    },
    "param-dtype": {
      title: "Model Precision",
      summary: "Torch dtype used when loading model components and running inference.",
      details: [["bfloat16", "Verified default on the host's Ampere GPUs; keeps a wider exponent range than float16."], ["float16", "Similar storage with different numeric range and device-dependent stability."], ["float32", "Uses roughly twice the model memory; required for CPU execution."]],
    },
    "param-offload": {
      title: "Model Offload Mode",
      summary: "Controls how model components move between CPU memory and the selected accelerator.",
      details: [["None", "Keeps the full pipeline on the selected device for speed and highest accelerator-memory use."], ["Model", "Moves whole components as needed for a balance of speed and memory."], ["Sequential", "Offloads more granularly for the lowest accelerator-memory use and highest transfer overhead."]],
    },
    "param-model-source": {
      title: "Primary Model Source",
      summary: "Hugging Face repository, local Diffusers directory, or supported single transformer file to resolve.",
      details: [["Diffusers", "A complete QwenImage21Pipeline layout can load directly."], ["Single file", "GGUF or floating-point SafeTensors uses Base Model for companion tokenizer, encoder, scheduler, and VAE components."], ["Compatibility", "Older Qwen Image/Edit pipeline classes and Comfy int8_convrot weights are intentionally rejected."]],
    },
    "param-model-filename": {
      title: "Specific Model Filename",
      summary: "Selects one file from a model repository instead of resolving a complete Diffusers directory.",
      details: [["Use", "Provide the exact GGUF or floating-point SafeTensors filename when the repository contains multiple weights."], ["Blank", "The resolver uses the repository layout or the configured GGUF quantization preference."]],
    },
    "param-model-revision": {
      title: "Model Revision",
      summary: "Branch, tag, or commit used when resolving the primary model source.",
      details: [["Pinned commit", "Improves reproducibility and prevents upstream changes from altering later runs."], ["Branch", "Tracks updates and may download different files over time."], ["Offline", "The requested revision must already exist in the local cache."]],
    },
    "param-model-lora-path": {
      title: "LoRA Adapter",
      summary: "Optional local Qwen Image transformer adapter loaded for production inference.",
      details: [["Selected", "The adapter is loaded unfused, activated under one fixed name, and recorded with its SHA-256."], ["No LoRA", "Uses only the base transformer."], ["Compatibility", "Upload validation checks tensor pairs; Diffusers performs the authoritative architecture and shape check during loading."]],
    },
    "param-model-lora-scale": {
      title: "LoRA Strength",
      summary: "Weight passed to Diffusers when activating the selected adapter.",
      details: [["Higher", "Amplifies the learned adapter contribution and may exaggerate its style or produce artifacts."], ["Lower", "Reduces the adapter contribution; 0 effectively disables its effect while keeping the selection."], ["Range", "Validated from 0 through 2; 1 uses the adapter's trained scale."]],
    },
    "param-base-model": {
      title: "Companion Base Model",
      summary: "Complete Qwen Image 2.1 model used to supply components missing from a single transformer file.",
      details: [["Used for", "GGUF and single-file SafeTensors sources need its model index, VAE, scheduler, processor, and usually text encoder."], ["Ignored for", "A complete primary Diffusers directory already contains its companion components."]],
    },
    "param-gguf-quantization": {
      title: "GGUF Quantization Preference",
      summary: "Filename preference used when resolving a GGUF repository without an exact filename.",
      details: [["Lower-bit variants", "Usually reduce storage and model memory with potential quality or compatibility trade-offs."], ["Selection", "Use the variant token present in the desired repository filename, such as Q4_K_M."]],
    },
    "param-model-cache-dir": {
      title: "Model Cache Directory",
      summary: "Local root used for downloaded model snapshots, manifests, and resolution.",
      details: [["Local path", "Changing it can make existing cached weights undiscoverable until copied or downloaded again."], ["Storage", "Full Qwen Image 2.1 snapshots are large; ensure the target filesystem has adequate free space."]],
    },
    "param-base-revision": {
      title: "Companion Model Revision",
      summary: "Optional branch, tag, or commit for the companion Base Model.",
      details: [["Use", "Pin it when a single-file transformer must be paired with reproducible companion components."], ["Blank", "Uses the model resolver's default revision."]],
    },
    "param-text-encoder-source": {
      title: "Text Encoder Override",
      summary: "Optional Diffusers-layout source that replaces the companion model's text encoder and processor.",
      details: [["Expected layout", "Must provide compatible text_encoder and processor subdirectories."], ["Trade-off", "An incompatible override fails model loading; leave blank to use the verified companion components."]],
    },
    "param-model-offline": {
      title: "Offline Mode",
      summary: "Restricts model resolution to local files and cached snapshots.",
      details: [["Enabled", "Prevents Hub downloads and fails clearly when a requested model or revision is absent."], ["Disabled", "Allows the model store to retrieve missing repository files when network access is available."]],
    },
    "toggle-demo-mode": {
      title: "Synthetic Demo Mode",
      summary: "Runs a fast input-derived preview backend instead of loading or executing Qwen Image 2.1.",
      details: [["Enabled", "Resizes and blends the first input with overlays for UI testing; selected models and LoRAs are not applied."], ["Disabled", "Uses the production Qwen backend and reports setup or inference failures directly."], ["Caution", "Demo output can resemble the input and must not be used to judge model transformation quality."]],
    },
  });

  const ParameterHelp = {
    popover: null,
    title: null,
    summary: null,
    details: null,
    activeButton: null,
    closeTimer: null,

    init() {
      this.popover = document.querySelector(".parameter-help-popover");
      if (!this.popover) return;
      this.popover.id = "parameter-help-popover";
      this.title = this.popover.querySelector(".parameter-help-title");
      this.summary = this.popover.querySelector(".parameter-help-summary");
      this.details = this.popover.querySelector(".parameter-help-details");

      for (const [controlId, help] of Object.entries(PARAMETER_HELP)) {
        const control = document.getElementById(controlId);
        if (!control) continue;
        const label = document.querySelector(`label[for="${controlId}"]`);
        let anchor = label;
        if (!anchor && typeof control.closest === "function") {
          const row = control.closest(".checkbox-row");
          anchor = row && row.querySelector(".toggle-label");
        }
        if (!anchor || !anchor.parentNode) continue;

        const button = Utils.el(
          "button",
          {
            type: "button",
            class: "parameter-help-button",
            dataset: { helpFor: controlId },
            attrs: {
              "aria-label": `Show help for ${help.title}`,
              "aria-controls": "parameter-help-popover",
              "aria-describedby": "parameter-help-popover",
              "aria-expanded": "false",
            },
          },
          Utils.el("span", { attrs: { "aria-hidden": "true" } }, "i")
        );
        anchor.parentNode.insertBefore(button, anchor.nextSibling);
        button.addEventListener("mouseenter", () => this.open(button));
        button.addEventListener("mouseleave", () => this.scheduleClose());
        button.addEventListener("focus", () => this.open(button));
        button.addEventListener("blur", () => this.scheduleClose());
        button.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (this.activeButton === button && !this.popover.classList.contains("hidden")) this.close();
          else this.open(button);
        });
      }

      this.popover.addEventListener("mouseenter", () => this.cancelClose());
      this.popover.addEventListener("mouseleave", () => this.scheduleClose());
      document.addEventListener("pointerdown", (event) => {
        if (this.popover.classList.contains("hidden")) return;
        if (this.popover.contains(event.target) || (event.target.closest && event.target.closest(".parameter-help-button"))) return;
        this.close();
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !this.popover.classList.contains("hidden")) {
          const button = this.activeButton;
          this.close();
          if (button && typeof button.focus === "function") button.focus();
        }
      });
      if (typeof window.addEventListener === "function") {
        window.addEventListener("resize", () => this.close());
        window.addEventListener("scroll", () => this.close(), true);
      }
    },

    open(button) {
      const help = PARAMETER_HELP[button.dataset.helpFor];
      if (!help || !this.popover) return;
      this.cancelClose();
      if (this.activeButton && this.activeButton !== button) {
        this.activeButton.setAttribute("aria-expanded", "false");
      }
      this.activeButton = button;
      if (this.title) this.title.textContent = help.title;
      if (this.summary) this.summary.textContent = help.summary;
      if (this.details) {
        this.details.innerHTML = "";
        const fragment = document.createDocumentFragment();
        for (const [term, description] of help.details) {
          fragment.appendChild(Utils.el("div", { class: "parameter-help-detail" },
            Utils.el("dt", {}, term), Utils.el("dd", {}, description)));
        }
        this.details.appendChild(fragment);
      }
      button.setAttribute("aria-expanded", "true");
      this.popover.classList.remove("hidden");
      this.popover.setAttribute("aria-hidden", "false");
      this.position(button);
    },

    position(button) {
      const rect = button.getBoundingClientRect();
      const margin = 12;
      const width = Math.min(this.popover.offsetWidth || 360, window.innerWidth - margin * 2);
      let left = rect.left + rect.width / 2 - width / 2;
      left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
      let top = rect.bottom + 8;
      const height = this.popover.offsetHeight || 220;
      if (top + height > window.innerHeight - margin) top = Math.max(margin, rect.top - height - 8);
      this.popover.style.left = `${Math.round(left)}px`;
      this.popover.style.top = `${Math.round(top)}px`;
    },

    scheduleClose() {
      this.cancelClose();
      this.closeTimer = setTimeout(() => this.close(), 140);
    },

    cancelClose() {
      if (this.closeTimer) clearTimeout(this.closeTimer);
      this.closeTimer = null;
    },

    close() {
      this.cancelClose();
      if (this.activeButton) this.activeButton.setAttribute("aria-expanded", "false");
      this.activeButton = null;
      if (this.popover) {
        this.popover.classList.add("hidden");
        this.popover.setAttribute("aria-hidden", "true");
      }
    },
  };

  // Non-enumerable migration aliases keep embedded integrations functional
  // without putting the retired combined field into API request JSON.
  Object.defineProperty(Store.state.inputs, "selected", {
    enumerable: false,
    get() { return this.inputImages; },
    set(value) { this.inputImages = Array.isArray(value) ? value : []; },
  });
  Object.defineProperty(Store.state.config.generation, "images", {
    enumerable: false,
    get() { return this.input_images; },
    set(value) { this.input_images = Array.isArray(value) ? value : []; },
  });


  // ==========================================================================
  // 4. API CLIENT LAYER
  // ==========================================================================

  const ApiClient = {
    async checkHealth() {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error(`Health check failed: HTTP ${res.status}`);
      return await res.json();
    },

    async getSystemCapabilities(runtime = {}) {
      const params = new URLSearchParams({
        device: runtime.device || "cuda:0",
        dtype: runtime.dtype || "bfloat16",
        offload: runtime.offload || "model",
      });
      const res = await fetch(`/api/system?${params.toString()}`);
      if (!res.ok) throw new Error(`Runtime capability check failed: HTTP ${res.status}`);
      return await res.json();
    },

    async browseInputs(folder = "") {
      const query = folder ? `?folder=${encodeURIComponent(folder)}` : "";
      const res = await fetch(`/api/inputs/browse${query}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Browse failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    },

    getThumbnailUrl(path, size = 256) {
      return `/api/inputs/thumbnail?path=${encodeURIComponent(path)}&size=${size}`;
    },

    async uploadInputImages(files) {
      const formData = new FormData();
      for (const file of files) formData.append("files", file);
      const res = await fetch("/api/inputs/upload", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Image upload failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    },

    async listModels() {
      const res = await fetch("/api/models");
      if (!res.ok) throw new Error(`Failed to list models: HTTP ${res.status}`);
      return await res.json();
    },

    async listLoras() {
      const res = await fetch("/api/loras");
      if (!res.ok) throw new Error(`Failed to list LoRA adapters: HTTP ${res.status}`);
      return await res.json();
    },

    async uploadLora(file) {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/loras/upload", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "LoRA upload failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    },

    async deleteLora(filename) {
      const res = await fetch(`/api/loras/${encodeURIComponent(filename)}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "LoRA deletion failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    },

    async downloadModel(repoId, filename = null, revision = "main") {
      const payload = { repo_id: repoId, revision: revision || "main" };
      if (filename) payload.filename = filename;

      const res = await fetch("/api/models/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Download start failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    },

    async getDownloadProgress(taskId, isStream = false) {
      const headers = isStream ? { Accept: "text/event-stream" } : {};
      const res = await fetch(`/api/models/download/progress/${encodeURIComponent(taskId)}`, { headers });
      if (!res.ok) throw new Error(`Progress fetch failed: HTTP ${res.status}`);
      return await res.json();
    },

    async cancelDownload(taskId) {
      const res = await fetch(`/api/models/download/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Cancellation failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    },

    async retryDownload(taskId) {
      const res = await fetch(`/api/models/download/${encodeURIComponent(taskId)}/retry`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Retry failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    },

    async uploadModelChunk(file, filename, chunkIndex, totalChunks, uploadId) {
      const formData = new FormData();
      formData.append("file", file);
      if (filename) formData.append("filename", filename);
      formData.append("chunk_index", String(chunkIndex));
      formData.append("total_chunks", String(totalChunks));
      if (uploadId) formData.append("upload_id", uploadId);

      const res = await fetch("/api/models/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Chunk upload failed" }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return await res.json();
    },

    async validateConfig(configPayload, checkImages = false) {
      const payload = { ...configPayload, check_images: checkImages };
      const res = await fetch("/api/config/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      return await res.json();
    },

    async startRun(configPayload) {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(configPayload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Run initiation failed" }));
        const msg = err.errors ? err.errors.join("; ") : err.detail || `HTTP ${res.status}`;
        throw new Error(msg);
      }
      return await res.json();
    },

    async listRuns() {
      const res = await fetch("/api/runs");
      if (!res.ok) throw new Error(`Failed to list runs: HTTP ${res.status}`);
      return await res.json();
    },

    async getRunRecord(runId) {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
      if (!res.ok) throw new Error(`Failed to fetch run record: HTTP ${res.status}`);
      return await res.json();
    },

    getOutputUrl(filename) {
      return `/api/outputs/${encodeURIComponent(filename)}`;
    },
  };


  // ==========================================================================
  // 5. R1: INPUT IMAGE BROWSER CONTROLLER
  // ==========================================================================

  const InputBrowser = {
    breadcrumbsContainer: null,
    subfoldersList: null,
    searchFilter: null,
    galleryGrid: null,
    loadingSpinner: null,
    selectedCountBadge: null,
    clearBtn: null,
    selectedSlotsList: null,
    emptySelectionNotice: null,
    referenceCountBadge: null,
    clearReferencesBtn: null,
    referenceSlotsList: null,
    emptyReferenceNotice: null,
    selectInputsBtn: null,
    selectReferencesBtn: null,
    uploadDropzone: null,
    uploadInput: null,
    uploadRoleHint: null,
    uploadStatus: null,
    refreshBtn: null,

    init() {
      this.breadcrumbsContainer = document.getElementById("folder-breadcrumbs");
      this.subfoldersList = document.getElementById("subfolders-list");
      this.searchFilter = document.getElementById("input-search-filter");
      this.galleryGrid = document.getElementById("input-gallery-grid");
      this.loadingSpinner = document.getElementById("inputs-loading-spinner");
      this.selectedCountBadge = document.getElementById("selected-count-badge");
      this.clearBtn = document.getElementById("btn-clear-selection");
      this.selectedSlotsList = document.getElementById("selected-slots-list");
      this.emptySelectionNotice = document.getElementById("empty-selection-notice");
      this.referenceCountBadge = document.getElementById("reference-count-badge");
      this.clearReferencesBtn = document.getElementById("btn-clear-references");
      this.referenceSlotsList = document.getElementById("reference-slots-list");
      this.emptyReferenceNotice = document.getElementById("empty-reference-notice");
      this.selectInputsBtn = document.getElementById("btn-select-inputs");
      this.selectReferencesBtn = document.getElementById("btn-select-references");
      this.uploadDropzone = document.getElementById("image-upload-dropzone");
      this.uploadInput = document.getElementById("image-file-input");
      this.uploadRoleHint = document.getElementById("image-upload-role-hint");
      this.uploadStatus = document.getElementById("image-upload-status");
      this.refreshBtn = document.getElementById("btn-refresh-inputs");

      if (this.refreshBtn) {
        this.refreshBtn.addEventListener("click", () => {
          this.loadFolder(Store.state.inputs.currentFolder);
        });
      }

      if (this.clearBtn) {
        this.clearBtn.addEventListener("click", () => this.clearRole("input"));
      }
      if (this.clearReferencesBtn) {
        this.clearReferencesBtn.addEventListener("click", () => this.clearRole("reference"));
      }
      if (this.selectInputsBtn) {
        this.selectInputsBtn.addEventListener("click", () => this.setActiveRole("input"));
      }
      if (this.selectReferencesBtn) {
        this.selectReferencesBtn.addEventListener("click", () => this.setActiveRole("reference"));
      }

      if (this.searchFilter) {
        this.searchFilter.addEventListener("input", (e) => {
          this.filterGallery(e.target.value);
        });
      }

      this.bindImageUpload();
      this.setActiveRole(Store.state.inputs.activeRole || "input");
      this.syncSelectionState();

      // Initial browse scan
      this.loadFolder("");
    },

    roleState(role) {
      return role === "reference" ? Store.state.inputs.referenceImages : Store.state.inputs.inputImages;
    },

    setActiveRole(role) {
      Store.state.inputs.activeRole = role === "reference" ? "reference" : "input";
      const isInput = Store.state.inputs.activeRole === "input";
      if (this.selectInputsBtn) {
        this.selectInputsBtn.className = `btn btn-xs ${isInput ? "btn-active" : "btn-ghost"}`;
        this.selectInputsBtn.setAttribute("aria-pressed", String(isInput));
      }
      if (this.selectReferencesBtn) {
        this.selectReferencesBtn.className = `btn btn-xs ${isInput ? "btn-ghost" : "btn-active"}`;
        this.selectReferencesBtn.setAttribute("aria-pressed", String(!isInput));
      }
      if (this.uploadRoleHint) {
        this.uploadRoleHint.textContent = `Uploads will be added to ${isInput ? "Input Images" : "Reference Images"}.`;
      }
      this.renderGallery(Store.state.inputs.images);
    },

    bindImageUpload() {
      if (!this.uploadDropzone || !this.uploadInput) return;
      const openPicker = () => this.uploadInput.click();
      this.uploadDropzone.addEventListener("click", openPicker);
      this.uploadDropzone.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openPicker();
        }
      });
      this.uploadInput.addEventListener("change", () => {
        this.uploadFiles(Array.from(this.uploadInput.files || []));
        this.uploadInput.value = "";
      });
      for (const eventName of ["dragenter", "dragover"]) {
        this.uploadDropzone.addEventListener(eventName, (event) => {
          event.preventDefault();
          this.uploadDropzone.classList.add("dragover");
        });
      }
      for (const eventName of ["dragleave", "drop"]) {
        this.uploadDropzone.addEventListener(eventName, (event) => {
          event.preventDefault();
          this.uploadDropzone.classList.remove("dragover");
        });
      }
      this.uploadDropzone.addEventListener("drop", (event) => {
        this.uploadFiles(Array.from((event.dataTransfer && event.dataTransfer.files) || []));
      });
    },

    async uploadFiles(files) {
      if (!files.length) return;
      const role = Store.state.inputs.activeRole;
      const selected = this.roleState(role);
      const limit = role === "reference" ? 9 : 10;
      const remaining = limit - selected.length;
      if (files.length > remaining) {
        const message = `${role === "reference" ? "References" : "Inputs"} can contain at most ${limit} images; ${remaining} slot${remaining === 1 ? " is" : "s are"} available.`;
        Toast.show(message, "warning");
        this.showErrorBanner([message]);
        return;
      }
      if (this.uploadStatus) {
        this.uploadStatus.textContent = `Uploading ${files.length} image${files.length === 1 ? "" : "s"}...`;
        this.uploadStatus.className = "image-upload-status";
      }
      try {
        const response = await ApiClient.uploadInputImages(files);
        const destination = this.roleState(role);
        for (const image of response.images || []) {
          if (!destination.some((item) => item.path === image.path)) {
            destination.push({
              ...image,
              stored_name: image.name,
              name: image.original_name || image.name,
            });
          }
        }
        this.syncSelectionState();
        if (this.uploadStatus) {
          this.uploadStatus.textContent = `Uploaded ${response.count || files.length} image${files.length === 1 ? "" : "s"} to ${role === "reference" ? "References" : "Inputs"}.`;
        }
        Toast.show(`Uploaded ${response.count || files.length} image${files.length === 1 ? "" : "s"}.`, "success");
        await this.loadFolder(Store.state.inputs.currentFolder);
      } catch (error) {
        if (this.uploadStatus) {
          this.uploadStatus.textContent = `Upload failed: ${error.message}`;
          this.uploadStatus.className = "image-upload-status error";
        }
        this.showErrorBanner([`Image upload failed: ${error.message}`]);
        Toast.show(`Image upload failed: ${error.message}`, "error");
      }
    },

    async loadFolder(folderPath = "") {
      try {
        if (this.galleryGrid) {
          this.galleryGrid.innerHTML = `
            <div class="loading-state" id="inputs-loading-spinner">
              <div class="spinner"></div>
              <span>Scanning inputs directory...</span>
            </div>
          `;
        }

        const data = await ApiClient.browseInputs(folderPath);
        Store.state.inputs.currentFolder = data.current_folder || "";
        Store.state.inputs.parentFolder = data.parent_folder;
        Store.state.inputs.folders = data.folders || [];
        Store.state.inputs.images = data.images || [];

        // Update footer count
        const footerCount = document.getElementById("status-bar-inputs-count");
        if (footerCount) {
          footerCount.textContent = String(Store.state.inputs.images.length);
        }

        this.renderBreadcrumbs(data);
        this.renderSubfolders(data);
        this.renderGallery(data.images || []);
      } catch (err) {
        console.error("Failed to browse inputs:", err);
        Toast.show(`Failed to browse inputs: ${err.message}`, "error");
        if (this.galleryGrid) {
          this.galleryGrid.innerHTML = `
            <div class="empty-state-text text-danger">Error scanning folder: ${Utils.escapeHtml(err.message)}</div>
          `;
        }
      }
    },

    renderBreadcrumbs(data) {
      if (!this.breadcrumbsContainer) return;
      this.breadcrumbsContainer.innerHTML = "";

      // Root breadcrumb
      const isRoot = !data.current_folder;
      const rootBtn = Utils.el(
        "button",
        {
          class: `breadcrumb-item ${isRoot ? "active" : ""}`,
          dataset: { folder: "" },
          onclick: () => this.loadFolder(""),
        },
        "/inputs (root)"
      );
      this.breadcrumbsContainer.appendChild(rootBtn);

      if (data.current_folder) {
        const parts = data.current_folder.split("/");
        let accumulated = "";
        for (let i = 0; i < parts.length; i++) {
          accumulated = accumulated ? `${accumulated}/${parts[i]}` : parts[i];
          const isLast = i === parts.length - 1;
          const folderTarget = accumulated;
          const partBtn = Utils.el(
            "button",
            {
              class: `breadcrumb-item ${isLast ? "active" : ""}`,
              dataset: { folder: folderTarget },
              onclick: () => this.loadFolder(folderTarget),
            },
            parts[i]
          );
          this.breadcrumbsContainer.appendChild(partBtn);
        }
      }
    },

    renderSubfolders(data) {
      if (!this.subfoldersList) return;
      this.subfoldersList.innerHTML = "";

      // If parent exists and we are in a subfolder, add back chip
      if (data.current_folder) {
        const parentTarget = data.parent_folder !== null ? data.parent_folder : "";
        const backBtn = Utils.el(
          "button",
          {
            class: "subfolder-chip subfolder-back",
            onclick: () => this.loadFolder(parentTarget),
          },
          "📁 .. (Up)"
        );
        this.subfoldersList.appendChild(backBtn);
      }

      const folderDetails = data.folder_details || [];
      if (data.folders) {
        for (const f of data.folders) {
          const detail = folderDetails.find((d) => d.name === f);
          const countStr = detail ? ` (${detail.image_count})` : "";
          const folderVal = data.current_folder ? `${data.current_folder}/${f}` : f;

          const chip = Utils.el(
            "button",
            {
              class: "subfolder-chip",
              onclick: () => this.loadFolder(folderVal),
            },
            `📁 ${f}${countStr}`
          );
          this.subfoldersList.appendChild(chip);
        }
      }
    },

    renderGallery(images) {
      if (!this.galleryGrid) return;
      this.galleryGrid.innerHTML = "";

      if (!images || images.length === 0) {
        this.galleryGrid.innerHTML = `
          <div class="empty-state-text">No image files found in this folder.</div>
        `;
        return;
      }

      const frag = document.createDocumentFragment();

      for (const img of images) {
        const inputIndex = Store.state.inputs.inputImages.findIndex((item) => item.path === img.path);
        const referenceIndex = Store.state.inputs.referenceImages.findIndex((item) => item.path === img.path);
        const isInput = inputIndex !== -1;
        const isReference = referenceIndex !== -1;

        const card = Utils.el(
          "div",
          {
            class: `input-image-card ${isInput ? "selected selected-input" : ""} ${isReference ? "selected-reference" : ""}`,
            dataset: { path: img.path, name: img.name },
            onclick: () => this.toggleSelection(img, Store.state.inputs.activeRole),
          },
          Utils.el(
            "div",
            { class: "card-thumb-wrapper" },
            Utils.el("img", {
              src: img.thumb_url || ApiClient.getThumbnailUrl(img.path),
              loading: "lazy",
              alt: img.name,
              onerror: (e) => {
                e.target.style.display = "none";
              },
            }),
            isInput ? Utils.el("div", { class: "slot-badge-overlay badge-input" }, `Input ${inputIndex + 1}`) : null,
            isReference ? Utils.el("div", { class: "slot-badge-overlay badge-ref" }, `Ref ${referenceIndex + 1}`) : null
          ),
          Utils.el(
            "div",
            { class: "card-meta" },
            Utils.el("span", { class: "card-name", title: img.name }, img.name),
            Utils.el(
              "span",
              { class: "card-dims" },
              img.width && img.height ? `${img.width}×${img.height}` : Utils.formatBytes(img.size)
            )
          )
        );

        frag.appendChild(card);
      }

      this.galleryGrid.appendChild(frag);
    },

    filterGallery(query) {
      if (!this.galleryGrid) return;
      const lower = (query || "").trim().toLowerCase();
      const cards = this.galleryGrid.querySelectorAll(".input-image-card");
      cards.forEach((card) => {
        const name = (card.dataset.name || "").toLowerCase();
        if (!lower || name.includes(lower)) {
          card.style.display = "";
        } else {
          card.style.display = "none";
        }
      });
    },

    toggleSelection(img, role = Store.state.inputs.activeRole) {
      role = role === "reference" ? "reference" : "input";
      const selected = this.roleState(role);
      const existingIdx = selected.findIndex((s) => s.path === img.path);

      if (existingIdx !== -1) {
        selected.splice(existingIdx, 1);
      } else {
        const limit = role === "reference" ? 9 : 10;
        if (selected.length >= limit) {
          const message = `Maximum ${limit} ${role === "reference" ? "reference" : "input"} images allowed.`;
          Toast.show(message, "warning");
          this.showErrorBanner([message]);
          return;
        }
        selected.push({
          name: img.name,
          path: img.path,
          width: img.width,
          height: img.height,
          thumb_url: img.thumb_url || ApiClient.getThumbnailUrl(img.path),
        });
      }

      this.syncSelectionState();
    },

    moveSlot(role, index, direction) {
      if (typeof role !== "string") {
        direction = index;
        index = role;
        role = "input";
      }
      const selected = this.roleState(role);
      const targetIdx = index + direction;
      if (targetIdx < 0 || targetIdx >= selected.length) return;

      const temp = selected[index];
      selected[index] = selected[targetIdx];
      selected[targetIdx] = temp;

      this.syncSelectionState();
    },

    removeSlot(role, index) {
      if (typeof role !== "string") {
        index = role;
        role = "input";
      }
      const selected = this.roleState(role);
      if (index >= 0 && index < selected.length) {
        selected.splice(index, 1);
        this.syncSelectionState();
      }
    },

    clearAll() {
      Store.state.inputs.inputImages = [];
      Store.state.inputs.referenceImages = [];
      this.syncSelectionState();
    },

    clearRole(role) {
      if (role === "reference") Store.state.inputs.referenceImages = [];
      else Store.state.inputs.inputImages = [];
      this.syncSelectionState();
    },

    syncSelectionState() {
      const inputs = Store.state.inputs.inputImages;
      const references = Store.state.inputs.referenceImages;
      Store.state.config.generation.input_images = inputs.map((item) => item.path);
      Store.state.config.generation.reference_images = references.map((item) => item.path);

      if (this.selectedCountBadge) {
        this.selectedCountBadge.textContent = `${inputs.length} / 10`;
      }
      if (this.referenceCountBadge) {
        this.referenceCountBadge.textContent = `${references.length} / 9`;
      }

      this.renderSelectedSlots();
      this.renderGallery(Store.state.inputs.images);

      // Trigger parameter validation
      ParamForm.triggerValidation();
    },

    renderSelectedSlots() {
      this.renderRoleSlots("input", this.selectedSlotsList, this.emptySelectionNotice);
      this.renderRoleSlots("reference", this.referenceSlotsList, this.emptyReferenceNotice);
    },

    renderRoleSlots(role, container, emptyNotice) {
      if (!container) return;
      container.innerHTML = "";
      const selected = this.roleState(role);
      if (selected.length === 0) {
        if (emptyNotice) container.appendChild(emptyNotice);
        return;
      }
      const frag = document.createDocumentFragment();
      for (let i = 0; i < selected.length; i++) {
        const item = selected[i];
        const label = role === "reference" ? `Ref ${i + 1} · <image${i + 2}>` : `Input ${i + 1}`;
        const slotCard = Utils.el(
          "div",
          { class: `selected-slot-card slot-card-${role}` },
          Utils.el(
            "div",
            { class: "slot-order-badge-col" },
            Utils.el(
              "span",
              { class: `badge ${role === "reference" ? "badge-accent" : "badge-primary"}` },
              label
            )
          ),
          Utils.el(
            "div",
            { class: "slot-thumb-wrapper" },
            Utils.el("img", {
              src: item.thumb_url || ApiClient.getThumbnailUrl(item.path),
              alt: item.name,
              onclick: () => Lightbox.open(item.thumb_url || ApiClient.getThumbnailUrl(item.path), item.name, item.width, item.height),
            })
          ),
          Utils.el(
            "div",
            { class: "slot-info-col" },
            Utils.el("span", { class: "slot-filename", title: item.path }, item.name),
            Utils.el(
              "span",
              { class: "slot-dims-label" },
              item.width && item.height ? `${item.width}×${item.height} px` : ""
            )
          ),
          Utils.el(
            "div",
            { class: "slot-actions-col" },
            i > 0
              ? Utils.el(
                  "button",
                  {
                    class: "btn-icon-slot",
                    title: "Move earlier in sequence",
                    onclick: () => this.moveSlot(role, i, -1),
                  },
                  "◀"
                )
              : null,
            i < selected.length - 1
              ? Utils.el(
                  "button",
                  {
                    class: "btn-icon-slot",
                    title: "Move later in sequence",
                    onclick: () => this.moveSlot(role, i, 1),
                  },
                  "▶"
                )
              : null,
            Utils.el(
              "button",
              {
                class: "btn-icon-slot btn-remove-slot",
                title: `Remove from ${role === "reference" ? "references" : "inputs"}`,
                onclick: () => this.removeSlot(role, i),
              },
              "✕"
            )
          )
        );

        frag.appendChild(slotCard);
      }

      container.appendChild(frag);
    },

    showErrorBanner(messages) {
      const banner = document.getElementById("global-alert-container");
      const list = document.getElementById("alert-messages-list");
      if (banner && list) {
        list.innerHTML = "";
        for (const msg of messages) {
          list.appendChild(Utils.el("li", {}, msg));
        }
        banner.classList.remove("hidden");
      }
    },
  };


  // ==========================================================================
  // 6. R2: PARAMETER FORM & LIVE VALIDATOR
  // ==========================================================================

  const ParamForm = {
    alertContainer: null,
    alertList: null,
    alertDismissBtn: null,
    validateBtn: null,
    randomSeedBtn: null,
    debouncedValidate: null,

    init() {
      this.alertContainer = document.getElementById("global-alert-container");
      this.alertList = document.getElementById("alert-messages-list");
      this.alertDismissBtn = document.getElementById("btn-dismiss-alert");
      this.validateBtn = document.getElementById("btn-validate-config");
      this.randomSeedBtn = document.getElementById("btn-random-seed");

      if (this.alertDismissBtn && this.alertContainer) {
        this.alertDismissBtn.addEventListener("click", () => {
          this.alertContainer.classList.add("hidden");
        });
      }

      if (this.validateBtn) {
        this.validateBtn.addEventListener("click", () => {
          this.runValidation(true);
        });
      }

      if (this.randomSeedBtn) {
        this.randomSeedBtn.addEventListener("click", () => {
          const seedInput = document.getElementById("param-seed");
          if (seedInput) {
            const newSeed = Utils.generateRandomSeed();
            seedInput.value = newSeed;
            Store.state.config.generation.seed = parseInt(newSeed, 10) || 0;
            this.triggerValidation();
          }
        });
      }

      // Presets button
      const presetsBtn = document.getElementById("btn-quick-presets");
      if (presetsBtn) {
        presetsBtn.addEventListener("click", () => this.applyDefaultPresets());
      }

      this.debouncedValidate = Utils.debounce(() => this.runValidation(false), 300);

      this.bindTabs();
      this.bindPromptControls();
      this.bindGenerationInputs();
      this.bindRuntimeInputs();
      this.bindModelInputs();
      this.bindLaunchControls();

      // Initial validation
      this.runValidation(false);
    },

    applyDefaultPresets() {
      const g = Store.state.config.generation;
      const r = Store.state.config.runtime;

      g.steps = 25;
      g.cfg = 1.0;
      g.strength = 1.0;
      g.shift = 0.69;
      g.sampler = "euler";
      g.scheduler = "simple";
      g.reference_mode = "rgb";
      g.batch_size = 1;
      g.resolution = 0;
      g.custom_size = false;
      g.kv_cache = true;
      g.kv_cache_device = "auto";
      g.kv_cache_reserve_gib = 1.0;

      r.device = "cuda:0";
      r.dtype = "bfloat16";
      r.offload = "model";
      r.vae_tiling = false;
      r.repeats = 1;
      r.warmup_runs = 0;
      r.increment_seed = false;
      r.memory_poll_seconds = 0.02;
      r.output_dir = "outputs";
      r.filename_prefix = "Qwen_image_2.1";
      r.save_comparison = true;

      this.syncAllInputsToStore();
      Toast.show("Default workflow presets applied.", "info");
      this.triggerValidation();
    },

    syncAllInputsToStore() {
      const setVal = (id, val) => {
        const elem = document.getElementById(id);
        if (!elem) return;
        if (elem.type === "checkbox") {
          elem.checked = Boolean(val);
        } else {
          elem.value = val !== null && val !== undefined ? String(val) : "";
        }
      };

      const g = Store.state.config.generation;
      const r = Store.state.config.runtime;

      setVal("param-steps", g.steps);
      setVal("slider-steps", g.steps);
      setVal("param-cfg", g.cfg);
      setVal("slider-cfg", g.cfg);
      setVal("param-strength", g.strength);
      setVal("slider-strength", g.strength);
      setVal("param-shift", g.shift);
      setVal("slider-shift", g.shift);
      setVal("param-seed", g.seed);
      setVal("param-resolution", g.resolution);
      setVal("param-custom-size", g.custom_size);
      setVal("param-width", g.width);
      setVal("param-height", g.height);
      setVal("param-sampler", g.sampler);
      setVal("param-scheduler", g.scheduler);
      setVal("param-batch-size", g.batch_size);
      setVal("param-reference-mode", g.reference_mode);
      setVal("param-kv-cache", g.kv_cache);
      setVal("param-kv-cache-device", g.kv_cache_device);
      setVal("param-kv-cache-reserve-gib", g.kv_cache_reserve_gib);

      setVal("param-device", r.device);
      setVal("param-dtype", r.dtype);
      setVal("param-offload", r.offload);
      setVal("param-vae-tiling", r.vae_tiling);
      setVal("param-repeats", r.repeats);
      setVal("param-warmup-runs", r.warmup_runs);
      setVal("param-increment-seed", r.increment_seed);
      setVal("param-memory-poll-seconds", r.memory_poll_seconds);
      setVal("param-output-dir", r.output_dir);
      setVal("param-filename-prefix", r.filename_prefix);
      setVal("param-save-comparison", r.save_comparison);

      this.updateCustomSizeVisibility(g.custom_size);
      this.updateKvCacheVisibility(g.kv_cache);
      this.updateScheduleRatio();
    },

    bindTabs() {
      const tabMap = [
        { btn: "tab-btn-prompt", pane: "tab-pane-prompt" },
        { btn: "tab-btn-generation", pane: "tab-pane-generation" },
        { btn: "tab-btn-runtime", pane: "tab-pane-runtime" },
        { btn: "tab-btn-system", pane: "tab-pane-system" },
        { btn: "tab-btn-model", pane: "tab-pane-model" },
      ];

      tabMap.forEach(({ btn, pane }) => {
        const btnElem = document.getElementById(btn);
        if (btnElem) {
          btnElem.addEventListener("click", () => {
            tabMap.forEach((t) => {
              const b = document.getElementById(t.btn);
              const p = document.getElementById(t.pane);
              if (b) {
                b.classList.remove("active");
                b.setAttribute("aria-selected", "false");
              }
              if (p) p.classList.remove("active");
            });

            btnElem.classList.add("active");
            btnElem.setAttribute("aria-selected", "true");
            const paneElem = document.getElementById(pane);
            if (paneElem) paneElem.classList.add("active");
          });
        }
      });

      const requestedPane = window.location && window.location.hash
        ? `tab-pane-${window.location.hash.slice(1)}`
        : "";
      const requestedTab = tabMap.find((item) => item.pane === requestedPane);
      if (requestedTab) {
        const button = document.getElementById(requestedTab.btn);
        if (button && typeof button.click === "function") button.click();
        const pane = document.getElementById(requestedTab.pane);
        if (pane && typeof pane.scrollIntoView === "function") {
          setTimeout(() => pane.scrollIntoView({ block: "start" }), 0);
        }
      }
    },

    bindPromptControls() {
      this.bindField("param-prompt", "generation.prompt", "input");
      this.bindField("param-negative-prompt", "generation.negative_prompt", "input");

      // Token insertion buttons
      document.querySelectorAll("#prompt-token-toolbar .token-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          const token = btn.dataset.token;
          const promptArea = document.getElementById("param-prompt");
          if (promptArea && token) {
            const start = promptArea.selectionStart;
            const end = promptArea.selectionEnd;
            const text = promptArea.value;
            promptArea.value = text.substring(0, start) + token + text.substring(end);
            promptArea.focus();
            promptArea.selectionStart = promptArea.selectionEnd = start + token.length;
            Store.state.config.generation.prompt = promptArea.value;
            this.triggerValidation();
          }
        });
      });
    },

    bindGenerationInputs() {
      // Synchronized range and number inputs
      this.syncSliderWithNumber("slider-steps", "param-steps", (val) => {
        Store.state.config.generation.steps = parseInt(val, 10) || 25;
        this.updateScheduleRatio();
      });

      this.syncSliderWithNumber("slider-cfg", "param-cfg", (val) => {
        Store.state.config.generation.cfg = parseFloat(val) || 1.0;
      });

      this.syncSliderWithNumber("slider-strength", "param-strength", (val) => {
        Store.state.config.generation.strength = parseFloat(val) || 1.0;
        this.updateScheduleRatio();
      });

      this.syncSliderWithNumber("slider-shift", "param-shift", (val) => {
        Store.state.config.generation.shift = parseFloat(val) || 0.69;
      });

      this.bindField("param-seed", "generation.seed", "input", (v) => parseInt(v, 10) || 0);
      this.bindField("param-resolution", "generation.resolution", "change", (v) => parseInt(v, 10) || 0);

      // Custom size toggle
      const customToggle = document.getElementById("param-custom-size");
      if (customToggle) {
        customToggle.addEventListener("change", (e) => {
          const checked = e.target.checked;
          Store.state.config.generation.custom_size = checked;
          this.updateCustomSizeVisibility(checked);
          this.triggerValidation();
        });
      }
      this.bindField("param-width", "generation.width", "input", (v) => parseInt(v, 10) || 1024);
      this.bindField("param-height", "generation.height", "input", (v) => parseInt(v, 10) || 1024);

      this.bindField("param-sampler", "generation.sampler", "change");
      this.bindField("param-scheduler", "generation.scheduler", "change");
      this.bindField("param-batch-size", "generation.batch_size", "input", (v) => parseInt(v, 10) || 1);
      this.bindField("param-reference-mode", "generation.reference_mode", "change");

      // KV cache toggle
      const kvToggle = document.getElementById("param-kv-cache");
      if (kvToggle) {
        kvToggle.addEventListener("change", (e) => {
          Store.state.config.generation.kv_cache = e.target.checked;
          this.updateKvCacheVisibility(e.target.checked);
          this.triggerValidation();
        });
      }
      this.bindField("param-kv-cache-device", "generation.kv_cache_device", "change");
      this.bindField("param-kv-cache-reserve-gib", "generation.kv_cache_reserve_gib", "input", (v) =>
        parseFloat(v) || 1.0
      );
    },

    updateCustomSizeVisibility(visible) {
      const wrap = document.getElementById("custom-size-fields");
      if (wrap) {
        wrap.style.display = visible ? "grid" : "none";
      }
    },

    updateKvCacheVisibility(visible) {
      const wrap = document.getElementById("kv-cache-subcontrols");
      if (wrap) {
        wrap.style.display = visible ? "grid" : "none";
      }
    },

    updateScheduleRatio() {
      const ratioElem = document.getElementById("schedule-calc-ratio");
      const steps = Store.state.config.generation.steps || 25;
      const strength = Store.state.config.generation.strength || 1.0;
      const ratio = strength > 0 ? Math.floor(steps / strength) : 0;

      if (ratioElem) {
        ratioElem.textContent = `steps/strength = ${ratio}`;
        if (ratio > 10000) {
          ratioElem.style.color = "var(--color-danger, #f43f5e)";
          ratioElem.style.fontWeight = "bold";
        } else {
          ratioElem.style.color = "";
          ratioElem.style.fontWeight = "";
        }
      }
    },

    bindRuntimeInputs() {
      this.bindField("param-device", "runtime.device", "change", (v) => {
        this.handleDeviceChange(v);
        return v;
      });
      this.bindField("param-dtype", "runtime.dtype", "change");
      this.bindField("param-offload", "runtime.offload", "change");
      this.bindCheckbox("param-vae-tiling", "runtime.vae_tiling");
      this.bindField("param-repeats", "runtime.repeats", "input", (v) => parseInt(v, 10) || 1);
      this.bindField("param-warmup-runs", "runtime.warmup_runs", "input", (v) => parseInt(v, 10) || 0);
      this.bindCheckbox("param-increment-seed", "runtime.increment_seed");
      this.bindField("param-memory-poll-seconds", "runtime.memory_poll_seconds", "input", (v) =>
        parseFloat(v) || 0.02
      );
      this.bindField("param-output-dir", "runtime.output_dir", "input");
      this.bindField("param-filename-prefix", "runtime.filename_prefix", "input");
      this.bindCheckbox("param-save-comparison", "runtime.save_comparison");
    },

    handleDeviceChange(device) {
      const dtypeSelect = document.getElementById("param-dtype");
      const offloadSelect = document.getElementById("param-offload");

      if (device === "cpu") {
        if (dtypeSelect) {
          dtypeSelect.value = "float32";
          Store.state.config.runtime.dtype = "float32";
        }
        if (offloadSelect) {
          offloadSelect.value = "none";
          Store.state.config.runtime.offload = "none";
        }
        Toast.show("CPU selected: precision adjusted to float32, offload set to none.", "info");
      } else if (device.startsWith("mps")) {
        if (offloadSelect) {
          offloadSelect.value = "none";
          Store.state.config.runtime.offload = "none";
        }
        Toast.show("MPS selected: offload set to none.", "info");
      }

      App.refreshRuntimeCapabilities(false, false).catch((err) => {
        console.warn("Runtime capability refresh failed:", err);
      });
    },

    bindModelInputs() {
      this.bindField("param-model-lora-path", "model.lora_path", "change", (v) => v || null);
      this.bindField("param-model-lora-scale", "model.lora_scale", "input", (v) => {
        const parsed = Number.parseFloat(v);
        return Number.isFinite(parsed) ? parsed : 1.0;
      });
      this.bindCheckbox("param-model-offline", "model.offline");
    },

    bindLaunchControls() {
      this.bindCheckbox("toggle-demo-mode", "demo_mode");
      const demoToggle = document.getElementById("toggle-demo-mode");
      if (demoToggle) {
        demoToggle.addEventListener("change", () => App.renderRuntimeStatus());
      }
    },

    syncSliderWithNumber(sliderId, numberId, onUpdate) {
      const slider = document.getElementById(sliderId);
      const number = document.getElementById(numberId);
      if (!slider || !number) return;

      slider.addEventListener("input", (e) => {
        number.value = e.target.value;
        onUpdate(e.target.value);
        this.triggerValidation();
      });

      number.addEventListener("input", (e) => {
        slider.value = e.target.value;
        onUpdate(e.target.value);
        this.triggerValidation();
      });
    },

    bindField(elemId, statePath, eventName, transform = (v) => v) {
      const elem = document.getElementById(elemId);
      if (!elem) return;

      elem.addEventListener(eventName, (e) => {
        const val = transform(e.target.value);
        const parts = statePath.split(".");
        if (parts.length === 2) {
          Store.state.config[parts[0]][parts[1]] = val;
        } else {
          Store.state.config[statePath] = val;
        }
        this.triggerValidation();
      });
    },

    bindCheckbox(elemId, statePath) {
      const elem = document.getElementById(elemId);
      if (!elem) return;

      elem.addEventListener("change", (e) => {
        const val = e.target.checked;
        const parts = statePath.split(".");
        if (parts.length === 2) {
          Store.state.config[parts[0]][parts[1]] = val;
        } else {
          Store.state.config[statePath] = val;
        }
        this.triggerValidation();
      });
    },

    triggerValidation() {
      if (this.debouncedValidate) {
        this.debouncedValidate();
      }
    },

    async runValidation(isExplicit = false) {
      const errors = [];
      const c = Store.state.config;
      const g = c.generation;
      const r = c.runtime;

      // Fast client-side sanity checks
      if (!Array.isArray(g.input_images) || g.input_images.length < 1 || g.input_images.length > 10) {
        errors.push("Provide 1–10 ordered input images.");
      }
      if (!Array.isArray(g.reference_images) || g.reference_images.length > 9) {
        errors.push("Provide at most 9 ordered reference images.");
      }
      if (g.steps < 1 || g.steps > 10000) {
        errors.push("steps must be between 1 and 10000.");
      }
      if (g.cfg < 0 || !Number.isFinite(g.cfg)) {
        errors.push("cfg scale must be non-negative and finite.");
      }
      if (g.strength <= 0 || g.strength > 1.0) {
        errors.push("denoise strength must be in range (0, 1].");
      }
      if (g.strength > 0 && Math.floor(g.steps / g.strength) > 10000) {
        errors.push("steps / strength exceeds the 10000-point schedule.");
      }
      if (g.shift < -10 || g.shift > 10) {
        errors.push("shift must be between -10.0 and 10.0.");
      }
      if (g.batch_size < 1) {
        errors.push("batch_size must be at least 1.");
      }
      if (g.resolution !== 0 && (g.resolution % 32 !== 0 || g.resolution < 0 || g.resolution > 4096)) {
        errors.push("resolution must be 0 or a multiple of 32 up to 4096.");
      }
      if (g.custom_size) {
        if (g.width <= 0 || g.width % 32 !== 0) {
          errors.push("custom width must be a positive multiple of 32.");
        }
        if (g.height <= 0 || g.height % 32 !== 0) {
          errors.push("custom height must be a positive multiple of 32.");
        }
      }
      if (r.device === "cpu" && r.dtype !== "float32") {
        errors.push("For CPU execution, dtype must be float32.");
      }
      if (r.device === "cpu" && r.offload !== "none") {
        errors.push("For CPU execution, offload must be none.");
      }
      if (r.device.startsWith("mps") && r.offload !== "none") {
        errors.push("MPS requires offload='none'.");
      }
      if (r.filename_prefix && (r.filename_prefix.includes("/") || r.filename_prefix.includes("\\"))) {
        errors.push("filename_prefix must be a clean filename without directory slashes.");
      }
      if (r.repeats < 1) {
        errors.push("repeats must be at least 1.");
      }
      if (r.warmup_runs < 0) {
        errors.push("warmup_runs must be at least 0.");
      }
      if (r.memory_poll_seconds < 0.001 || r.memory_poll_seconds > 1.0) {
        errors.push("memory_poll_seconds must be between 0.001 and 1.0.");
      }
      if (!Store.state.models.selectedId && !c.demo_mode) {
        errors.push("Select a compatible downloaded model before running inference.");
      }

      // If client errors exist, render directly
      if (errors.length > 0) {
        this.renderValidationResult(false, errors);
        return;
      }

      // Query server validator
      try {
        const payload = {
          selected_model_id: Store.state.models.selectedId,
          model: { lora_path: c.model.lora_path, lora_scale: c.model.lora_scale },
          generation: c.generation,
          runtime: c.runtime,
          demo_mode: c.demo_mode,
        };
        const res = await ApiClient.validateConfig(payload, false);
        this.renderValidationResult(res.valid, res.errors || []);
        if (isExplicit && res.valid) {
          Toast.show("Configuration parameters are valid!", "success");
        }
      } catch (err) {
        console.warn("Validation endpoint failed:", err);
      }
    },

    renderValidationResult(valid, errors) {
      Store.state.validation.valid = valid;
      Store.state.validation.errors = errors;

      const runBtn = document.getElementById("btn-run-pipeline");

      if (valid) {
        if (this.alertContainer) this.alertContainer.classList.add("hidden");
        if (runBtn && Store.state.run.status !== "running") {
          runBtn.disabled = false;
        }
      } else {
        if (this.alertContainer && this.alertList) {
          this.alertList.innerHTML = "";
          for (const err of errors) {
            this.alertList.appendChild(Utils.el("li", {}, err));
          }
          this.alertContainer.classList.remove("hidden");
        }
        if (runBtn && Store.state.run.status !== "running") {
          runBtn.disabled = true;
        }
      }
    },
  };


  // ==========================================================================
  // 7. R3: MODEL SELECTION & MANAGEMENT
  // ==========================================================================

  const ModelManager = {
    cachedSelect: null,
    refreshModelsBtn: null,
    applyCachedBtn: null,
    modelInfoBox: null,
    infoPath: null,
    infoType: null,
    infoSize: null,

    // HF Download
    hfDownloadBtn: null,
    hfProgressWrap: null,
    hfProgressBar: null,
    hfProgressStatus: null,
    hfProgressBadge: null,
    hfProgressError: null,
    hfProgressTrack: null,
    hfProgressFile: null,
    hfProgressDetails: null,
    hfCancelBtn: null,
    hfRetryBtn: null,
    activeDownloadTaskId: null,
    downloadPollTimer: null,

    // File Upload
    dropzone: null,
    fileInput: null,
    uploadProgressWrap: null,
    uploadProgressBar: null,
    uploadProgressStatus: null,
    uploadProgressBadge: null,
    uploadProgressError: null,

    init() {
      this.cachedSelect = document.getElementById("select-cached-model");
      this.refreshModelsBtn = document.getElementById("btn-refresh-models");
      this.applyCachedBtn = document.getElementById("btn-apply-cached-model");
      this.modelInfoBox = document.getElementById("cached-model-info-box");
      this.infoPath = document.getElementById("info-model-path");
      this.infoType = document.getElementById("info-model-type");
      this.infoSize = document.getElementById("info-model-size");

      this.hfDownloadBtn = document.getElementById("btn-download-hf-model");
      this.hfProgressWrap = document.getElementById("hf-download-progress-container");
      this.hfProgressBar = document.getElementById("hf-download-bar");
      this.hfProgressStatus = document.getElementById("hf-download-status-label");
      this.hfProgressBadge = document.getElementById("hf-download-percent-badge");
      this.hfProgressError = document.getElementById("hf-download-error");
      this.hfProgressTrack = document.getElementById("hf-download-progress-track");
      this.hfProgressFile = document.getElementById("hf-download-file");
      this.hfProgressDetails = document.getElementById("hf-download-details");
      this.hfCancelBtn = document.getElementById("btn-cancel-hf-download");
      this.hfRetryBtn = document.getElementById("btn-retry-hf-download");

      this.dropzone = document.getElementById("model-upload-dropzone");
      this.fileInput = document.getElementById("model-file-input");
      this.uploadProgressWrap = document.getElementById("model-upload-progress-container");
      this.uploadProgressBar = document.getElementById("model-upload-bar");
      this.uploadProgressStatus = document.getElementById("model-upload-status-label");
      this.uploadProgressBadge = document.getElementById("model-upload-percent-badge");
      this.uploadProgressError = document.getElementById("model-upload-error");

      if (this.refreshModelsBtn) {
        this.refreshModelsBtn.addEventListener("click", () => this.loadModels());
      }

      if (this.applyCachedBtn) {
        this.applyCachedBtn.addEventListener("click", () => this.applySelectedCachedModel());
      }

      if (this.cachedSelect) {
        this.cachedSelect.addEventListener("change", (e) => {
          this.displayCachedModelInfo(e.target.value);
          if (this.applyCachedBtn) this.applyCachedBtn.disabled = !e.target.value;
        });
      }

      if (this.hfDownloadBtn) {
        this.hfDownloadBtn.addEventListener("click", () => this.startHfDownload());
      }
      if (this.hfCancelBtn) this.hfCancelBtn.addEventListener("click", () => this.cancelHfDownload());
      if (this.hfRetryBtn) this.hfRetryBtn.addEventListener("click", () => this.retryHfDownload());

      this.bindUploadDropzone();
      this.loadModels();
    },

    async loadModels() {
      try {
        const data = await ApiClient.listModels();
        const models = data.models || [];
        Store.state.models.cached = models;

        const footerCount = document.getElementById("status-bar-models-count");
        if (footerCount) {
          footerCount.textContent = String(models.length);
        }

        this.renderCachedSelect(models);
        if (!models.some((model) => model.id === Store.state.models.selectedId && model.compatible)) {
          const preferred = models.find((model) => model.compatible && model.type === "diffusers")
            || models.find((model) => model.compatible);
          Store.state.models.selectedId = (preferred || {}).id || null;
        }
        if (this.cachedSelect) this.cachedSelect.value = Store.state.models.selectedId || "";
        if (this.applyCachedBtn) this.applyCachedBtn.disabled = !Store.state.models.selectedId;
        this.displayCachedModelInfo(Store.state.models.selectedId);
        this.renderActiveModel();
        ParamForm.triggerValidation();
      } catch (err) {
        console.error("Failed to list models:", err);
        const status = document.getElementById("model-active-status");
        if (status) status.textContent = `Model catalog unavailable: ${err.message}`;
      }
    },

    renderActiveModel() {
      const status = document.getElementById("model-active-status");
      if (!status) return;
      const active = Store.state.models.cached.find((model) => model.id === Store.state.models.selectedId);
      status.textContent = active ? `Active for next run: ${active.name}` : "No compatible model selected.";
    },

    renderCachedSelect(models) {
      if (!this.cachedSelect) return;
      this.cachedSelect.innerHTML = "";

      const defaultOpt = Utils.el("option", { value: "" }, "-- Select a discovered / cached model --");
      this.cachedSelect.appendChild(defaultOpt);

      for (const m of models) {
        const typeBadge = m.type ? m.type.toUpperCase() : "WEIGHTS";
        const sizeStr = m.size ? ` (${Utils.formatBytes(m.size)})` : "";
        const label = `[${typeBadge}] ${m.name}${sizeStr}${m.compatible ? "" : " — incompatible"}`;

        const opt = Utils.el("option", { value: m.id || m.path || m.name }, label);
        opt.disabled = m.compatible === false;
        if (m.compatibility_reason) opt.title = m.compatibility_reason;
        this.cachedSelect.appendChild(opt);
      }
    },

    displayCachedModelInfo(selectedVal) {
      const models = Store.state.models.cached;
      const model = models.find((m) => m.id === selectedVal || m.path === selectedVal || m.name === selectedVal);

      if (!model) {
        if (this.modelInfoBox) this.modelInfoBox.classList.add("hidden");
        return;
      }

      if (this.modelInfoBox) this.modelInfoBox.classList.remove("hidden");
      if (this.infoPath) this.infoPath.textContent = model.path || model.name;
      if (this.infoType) this.infoType.textContent = model.compatible
        ? `${(model.type || "unknown").toUpperCase()} · Compatible`
        : `Incompatible: ${model.compatibility_reason || "unsupported model"}`;
      if (this.infoSize) this.infoSize.textContent = model.size ? Utils.formatBytes(model.size) : "N/A";
    },

    applySelectedCachedModel() {
      const selectedVal = this.cachedSelect ? this.cachedSelect.value : "";
      if (!selectedVal) {
        Toast.show("Please select a cached model from the dropdown first.", "warning");
        return;
      }

      const model = Store.state.models.cached.find((m) => m.id === selectedVal);
      if (!model) return;
      if (!model.compatible) {
        Toast.show(model.compatibility_reason || "This model is incompatible.", "error");
        return;
      }
      Store.state.models.selectedId = model.id;
      this.displayCachedModelInfo(model.id);
      this.renderActiveModel();
      Toast.show(`Selected model: ${model.name}`, "success");
      ParamForm.triggerValidation();
    },

    async startHfDownload() {
      const sourceInput = document.getElementById("param-model-source");
      const filenameInput = document.getElementById("param-model-filename");
      const revisionInput = document.getElementById("param-model-revision");

      const repoId = (sourceInput ? sourceInput.value : "").trim();
      const filename = filenameInput ? filenameInput.value.trim() : null;
      const revision = revisionInput ? revisionInput.value.trim() || "main" : "main";

      if (!repoId) {
        Toast.show("Please enter a Hugging Face Repo ID or URL.", "warning");
        return;
      }

      try {
        if (this.hfProgressWrap) this.hfProgressWrap.classList.remove("hidden");
        if (this.hfProgressError) this.hfProgressError.classList.add("hidden");
        if (this.hfDownloadBtn) this.hfDownloadBtn.disabled = true;
        if (this.hfProgressStatus) this.hfProgressStatus.textContent = "Preparing download…";

        const data = await ApiClient.downloadModel(repoId, filename, revision);
        Toast.show(`Download started: ${repoId}`, "info");
        this.trackHfDownload(data.task_id);
      } catch (err) {
        if (this.hfDownloadBtn) this.hfDownloadBtn.disabled = false;
        if (this.hfProgressError) {
          this.hfProgressError.textContent = `Error: ${err.message}`;
          this.hfProgressError.classList.remove("hidden");
        }
        Toast.show(`Download request failed: ${err.message}`, "error");
      }
    },

    trackHfDownload(taskId) {
      if (this.downloadPollTimer) clearTimeout(this.downloadPollTimer);
      this.activeDownloadTaskId = taskId;
      if (this.hfRetryBtn) this.hfRetryBtn.classList.add("hidden");
      if (this.hfCancelBtn) this.hfCancelBtn.classList.remove("hidden");
      this.pollHfDownload(taskId);
    },

    async pollHfDownload(taskId) {
      if (taskId !== this.activeDownloadTaskId) return;
      try {
        const progress = await ApiClient.getDownloadProgress(taskId);
        if (taskId !== this.activeDownloadTaskId) return;
        this.renderHfDownloadProgress(progress);
        if (["completed", "failed", "cancelled"].includes(progress.status)) {
          if (this.hfDownloadBtn) this.hfDownloadBtn.disabled = false;
          if (progress.status === "completed") {
            Toast.show(`Model download completed: ${progress.repo_id}`, "success");
            this.loadModels();
          } else if (progress.status === "failed") {
            Toast.show(`Download failed: ${progress.error || "Unknown error"}`, "error");
          } else {
            Toast.show("Model download cancelled.", "info");
          }
          return;
        }
      } catch (err) {
        if (this.hfProgressError) {
          this.hfProgressError.textContent = `Status temporarily unavailable: ${err.message}. Retrying…`;
          this.hfProgressError.classList.remove("hidden");
        }
      }
      this.downloadPollTimer = setTimeout(() => this.pollHfDownload(taskId), 750);
    },

    renderHfDownloadProgress(progress) {
      const terminal = ["completed", "failed", "cancelled"].includes(progress.status);
      const percent = Number.isFinite(progress.percent) ? Math.min(100, Math.max(0, progress.percent)) : null;
      if (this.hfProgressWrap) this.hfProgressWrap.classList.remove("hidden");
      if (this.hfProgressTrack) {
        this.hfProgressTrack.classList.toggle("is-indeterminate", percent === null && !terminal);
        if (percent === null) this.hfProgressTrack.removeAttribute("aria-valuenow");
        else this.hfProgressTrack.setAttribute("aria-valuenow", String(Math.round(percent)));
      }
      if (this.hfProgressBar) this.hfProgressBar.style.width = `${percent === null ? 0 : percent}%`;
      if (this.hfProgressBadge) this.hfProgressBadge.textContent = percent === null ? "Size unknown" : `${Math.round(percent)}%`;
      const labels = { queued: "Queued", preparing: "Preparing", downloading: "Downloading", verifying: "Verifying",
        cancelling: "Cancelling after current file", completed: "Completed", failed: "Failed", cancelled: "Cancelled" };
      if (this.hfProgressStatus) this.hfProgressStatus.textContent = labels[progress.status] || progress.status;
      if (this.hfProgressFile) this.hfProgressFile.textContent = progress.current_file
        ? `Current file: ${progress.current_file}` : "No file currently transferring.";
      const doneBytes = Number.isFinite(progress.downloaded_bytes) ? Utils.formatBytes(progress.downloaded_bytes) : "Unknown";
      const totalBytes = Number.isFinite(progress.total_bytes) ? Utils.formatBytes(progress.total_bytes) : "total unknown";
      const completedFiles = progress.completed_files ?? 0;
      const fileCount = Number.isFinite(progress.total_files) ? progress.total_files : "?";
      const remaining = Number.isFinite(progress.remaining_files) ? ` · ${progress.remaining_files} remaining` : "";
      const speed = Number.isFinite(progress.speed_bytes_per_second) && progress.speed_bytes_per_second > 0
        ? ` · ${Utils.formatBytes(progress.speed_bytes_per_second)}/s` : "";
      const eta = Number.isFinite(progress.eta_seconds)
        ? ` · ETA ${Math.ceil(progress.eta_seconds)}s` : "";
      if (this.hfProgressDetails) this.hfProgressDetails.textContent =
        `${doneBytes} / ${totalBytes} · ${completedFiles}/${fileCount} files${remaining}${speed}${eta}`;
      if (this.hfCancelBtn) this.hfCancelBtn.classList.toggle("hidden", terminal || progress.status === "cancelling");
      if (this.hfRetryBtn) this.hfRetryBtn.classList.toggle("hidden", !["failed", "cancelled"].includes(progress.status));
      if (this.hfProgressError) {
        this.hfProgressError.textContent = progress.status === "failed" ? `Error: ${progress.error || "Download failed."}` : "";
        this.hfProgressError.classList.toggle("hidden", progress.status !== "failed");
      }
    },

    async cancelHfDownload() {
      if (!this.activeDownloadTaskId) return;
      try {
        const progress = await ApiClient.cancelDownload(this.activeDownloadTaskId);
        this.renderHfDownloadProgress(progress);
      } catch (err) {
        Toast.show(`Cancellation failed: ${err.message}`, "error");
      }
    },

    async retryHfDownload() {
      if (!this.activeDownloadTaskId) return;
      try {
        const result = await ApiClient.retryDownload(this.activeDownloadTaskId);
        if (this.hfDownloadBtn) this.hfDownloadBtn.disabled = true;
        this.trackHfDownload(result.task_id);
      } catch (err) {
        Toast.show(`Retry failed: ${err.message}`, "error");
      }
    },

    bindUploadDropzone() {
      if (!this.dropzone || !this.fileInput) return;

      this.dropzone.addEventListener("click", () => {
        this.fileInput.click();
      });

      this.fileInput.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (file) this.uploadFile(file);
      });

      this.dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        this.dropzone.classList.add("drag-over");
      });

      this.dropzone.addEventListener("dragleave", () => {
        this.dropzone.classList.remove("drag-over");
      });

      this.dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        this.dropzone.classList.remove("drag-over");
        const file = e.dataTransfer.files[0];
        if (file) this.uploadFile(file);
      });
    },

    async uploadFile(file) {
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      if (ext !== ".gguf" && ext !== ".safetensors") {
        Toast.show("Invalid file format. Only .gguf and .safetensors files are allowed.", "error");
        return;
      }

      if (file.name.includes("int8_convrot")) {
        Toast.show("ComfyUI int8_convrot format is not supported.", "error");
        return;
      }

      if (file.size === 0) {
        Toast.show("File is empty (0 bytes).", "error");
        return;
      }

      try {
        if (this.uploadProgressWrap) this.uploadProgressWrap.classList.remove("hidden");
        if (this.uploadProgressError) this.uploadProgressError.classList.add("hidden");
        if (this.uploadProgressBar) this.uploadProgressBar.style.width = "0%";
        if (this.uploadProgressBadge) this.uploadProgressBadge.textContent = "0%";
        if (this.uploadProgressStatus) this.uploadProgressStatus.textContent = `Uploading ${file.name}...`;

        const chunkSize = 5 * 1024 * 1024; // 5MB chunks
        const totalChunks = Math.max(1, Math.ceil(file.size / chunkSize));
        const uploadId = `up_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;

        for (let i = 0; i < totalChunks; i++) {
          const start = i * chunkSize;
          const end = Math.min(file.size, start + chunkSize);
          const chunkBlob = file.slice(start, end);

          await ApiClient.uploadModelChunk(chunkBlob, file.name, i, totalChunks, uploadId);

          const pct = Math.round(((i + 1) / totalChunks) * 100);
          if (this.uploadProgressBar) this.uploadProgressBar.style.width = `${pct}%`;
          if (this.uploadProgressBadge) this.uploadProgressBadge.textContent = `${pct}%`;
          if (this.uploadProgressStatus) {
            this.uploadProgressStatus.textContent = `Chunk ${i + 1} / ${totalChunks} (${pct}%)`;
          }
        }

        Toast.show(`Model file uploaded successfully: ${file.name}`, "success");
        await this.loadModels();

        // Auto select uploaded model
        if (this.cachedSelect) {
          for (const opt of this.cachedSelect.options) {
            if (opt.value.includes(file.name)) {
              opt.selected = true;
              this.displayCachedModelInfo(opt.value);
              this.applySelectedCachedModel();
              break;
            }
          }
        }
      } catch (err) {
        console.error("Upload error:", err);
        if (this.uploadProgressError) {
          this.uploadProgressError.textContent = `Upload failed: ${err.message}`;
          this.uploadProgressError.classList.remove("hidden");
        }
        Toast.show(`Upload failed: ${err.message}`, "error");
      }
    },
  };


  // ==========================================================================
  // 8. LORA ADAPTER MANAGEMENT
  // ==========================================================================

  const LoRAManager = {
    select: null,
    scaleInput: null,
    activeStatus: null,
    refreshBtn: null,
    clearBtn: null,
    dropzone: null,
    fileInput: null,
    uploadStatus: null,
    filesList: null,

    init() {
      this.select = document.getElementById("param-model-lora-path");
      this.scaleInput = document.getElementById("param-model-lora-scale");
      this.activeStatus = document.getElementById("lora-active-status");
      this.refreshBtn = document.getElementById("btn-refresh-loras");
      this.clearBtn = document.getElementById("btn-clear-lora");
      this.dropzone = document.getElementById("lora-upload-dropzone");
      this.fileInput = document.getElementById("lora-file-input");
      this.uploadStatus = document.getElementById("lora-upload-status");
      this.filesList = document.getElementById("lora-files-list");

      if (this.refreshBtn) this.refreshBtn.addEventListener("click", () => this.loadLoras(true));
      if (this.clearBtn) this.clearBtn.addEventListener("click", () => this.clearSelection());
      if (this.select) this.select.addEventListener("change", () => this.applySelection());
      if (this.scaleInput) this.scaleInput.addEventListener("input", () => this.renderActiveStatus());

      this.bindUploadDropzone();
      this.loadLoras(false);
    },

    async loadLoras(showToast = false) {
      try {
        const data = await ApiClient.listLoras();
        Store.state.loras.available = data.loras || [];
        this.renderOptions();
        this.renderFiles();
        if (showToast) Toast.show(`Found ${Store.state.loras.available.length} LoRA adapter(s).`, "success");
      } catch (err) {
        console.error("Failed to list LoRA adapters:", err);
        this.setUploadStatus(`Could not refresh adapters: ${err.message}`, true);
        if (showToast) Toast.show(`LoRA refresh failed: ${err.message}`, "error");
      }
    },

    renderOptions() {
      if (!this.select) return;
      const selectedPath = Store.state.config.model.lora_path || "";
      this.select.innerHTML = "";
      this.select.appendChild(Utils.el("option", { value: "" }, "No LoRA"));

      for (const item of Store.state.loras.available) {
        const size = item.size ? ` · ${Utils.formatBytes(item.size)}` : "";
        const suffix = item.valid ? size : ` · invalid: ${item.error || "unsupported adapter"}`;
        const option = Utils.el("option", { value: item.path }, `${item.name}${suffix}`);
        option.value = item.path;
        option.disabled = !item.valid;
        this.select.appendChild(option);
      }

      const selectedExists = Store.state.loras.available.some(
        (item) => item.valid && item.path === selectedPath
      );
      if (selectedPath && selectedExists) {
        this.select.value = selectedPath;
      } else if (selectedPath) {
        Store.state.config.model.lora_path = null;
        this.select.value = "";
      }
      this.renderActiveStatus();
    },

    renderFiles() {
      if (!this.filesList) return;
      this.filesList.innerHTML = "";
      if (!Store.state.loras.available.length) {
        this.filesList.textContent = "No stored LoRA files.";
        return;
      }
      for (const item of Store.state.loras.available) {
        this.filesList.appendChild(Utils.el("div", { class: "lora-file-row" },
          Utils.el("span", { class: "lora-file-name", title: item.name },
            `${item.name} · ${Utils.formatBytes(item.size || 0)}${item.valid ? "" : " · invalid"}`),
          Utils.el("button", { class: "btn btn-ghost btn-xs", type: "button",
            title: `Delete ${item.name}`, onclick: () => this.deleteFile(item) }, "Delete")
        ));
      }
    },

    async deleteFile(item) {
      if (!window.confirm(`Delete LoRA "${item.name}" from local storage? Any idle pipeline using it will be unloaded.`)) return;
      try {
        await ApiClient.deleteLora(item.name);
        if (Store.state.config.model.lora_path === item.path) {
          Store.state.config.model.lora_path = null;
        }
        await this.loadLoras(false);
        ParamForm.triggerValidation();
        this.setUploadStatus(`Deleted ${item.name}.`, false);
        Toast.show(`Deleted LoRA: ${item.name}`, "success");
      } catch (error) {
        this.setUploadStatus(`Could not delete ${item.name}: ${error.message}`, true);
        Toast.show(`LoRA deletion failed: ${error.message}`, "error");
      }
    },

    applySelection() {
      Store.state.config.model.lora_path = this.select && this.select.value ? this.select.value : null;
      this.renderActiveStatus();
      ParamForm.triggerValidation();
    },

    clearSelection() {
      if (this.select) this.select.value = "";
      Store.state.config.model.lora_path = null;
      this.renderActiveStatus();
      ParamForm.triggerValidation();
      Toast.show("LoRA selection cleared.", "info");
    },

    renderActiveStatus() {
      if (!this.activeStatus) return;
      const path = Store.state.config.model.lora_path;
      const scale = Number(Store.state.config.model.lora_scale);
      if (!path) {
        this.activeStatus.textContent = "No LoRA selected. Production inference will use the base model.";
        this.activeStatus.classList.remove("is-active");
        return;
      }
      const item = Store.state.loras.available.find((entry) => entry.path === path);
      const name = item ? item.name : path.split(/[\\/]/).pop();
      this.activeStatus.textContent = `Selected: ${name} · strength ${Number.isFinite(scale) ? scale : 1}`;
      this.activeStatus.classList.add("is-active");
    },

    bindUploadDropzone() {
      if (!this.dropzone || !this.fileInput) return;
      const openPicker = () => this.fileInput.click();
      this.dropzone.addEventListener("click", openPicker);
      this.dropzone.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openPicker();
        }
      });
      this.fileInput.addEventListener("change", (event) => {
        const file = event.target.files[0];
        if (file) this.uploadFile(file);
      });
      this.dropzone.addEventListener("dragover", (event) => {
        event.preventDefault();
        this.dropzone.classList.add("dragover");
      });
      this.dropzone.addEventListener("dragleave", () => this.dropzone.classList.remove("dragover"));
      this.dropzone.addEventListener("drop", (event) => {
        event.preventDefault();
        this.dropzone.classList.remove("dragover");
        const file = event.dataTransfer.files[0];
        if (file) this.uploadFile(file);
      });
    },

    async uploadFile(file) {
      if (!file.name.toLowerCase().endsWith(".safetensors")) {
        const message = "LoRA adapters must use the .safetensors format.";
        this.setUploadStatus(message, true);
        Toast.show(message, "error");
        return;
      }
      if (file.size === 0) {
        const message = "The selected LoRA file is empty.";
        this.setUploadStatus(message, true);
        Toast.show(message, "error");
        return;
      }

      this.setUploadStatus(`Validating and uploading ${file.name}…`, false);
      try {
        const data = await ApiClient.uploadLora(file);
        await this.loadLoras(false);
        const uploaded = data.lora;
        Store.state.config.model.lora_path = uploaded.path;
        if (this.select) this.select.value = uploaded.path;
        this.renderActiveStatus();
        ParamForm.triggerValidation();
        this.setUploadStatus(`${uploaded.name} is ready and selected.`, false);
        Toast.show(`LoRA uploaded and selected: ${uploaded.name}`, "success");
      } catch (err) {
        console.error("LoRA upload failed:", err);
        this.setUploadStatus(`Upload failed: ${err.message}`, true);
        Toast.show(`LoRA upload failed: ${err.message}`, "error");
      } finally {
        if (this.fileInput) this.fileInput.value = "";
      }
    },

    setUploadStatus(message, isError) {
      if (!this.uploadStatus) return;
      this.uploadStatus.textContent = message;
      this.uploadStatus.classList.toggle("error", Boolean(isError));
    },
  };


  // ==========================================================================
  // 9. SYSTEM INVENTORY & DEVICE CONFIGURATION
  // ==========================================================================

  const SystemManager = {
    deviceSelect: null,
    dtypeSelect: null,
    offloadSelect: null,
    applyBtn: null,
    refreshBtn: null,

    init() {
      this.deviceSelect = document.getElementById("param-device");
      this.dtypeSelect = document.getElementById("param-dtype");
      this.offloadSelect = document.getElementById("param-offload");
      this.applyBtn = document.getElementById("btn-apply-system");
      this.refreshBtn = document.getElementById("btn-refresh-system");
      if (this.applyBtn) this.applyBtn.addEventListener("click", () => this.applyConfiguration());
      if (this.refreshBtn) this.refreshBtn.addEventListener("click", () => this.refreshInventory());
    },

    async applyConfiguration() {
      const runtime = Store.state.config.runtime;
      if (this.deviceSelect) runtime.device = this.deviceSelect.value;
      if (this.dtypeSelect) runtime.dtype = this.dtypeSelect.value;
      if (this.offloadSelect) runtime.offload = this.offloadSelect.value;

      if (runtime.device === "cpu") {
        runtime.dtype = "float32";
        runtime.offload = "none";
        if (this.dtypeSelect) this.dtypeSelect.value = "float32";
        if (this.offloadSelect) this.offloadSelect.value = "none";
      } else if (runtime.device.startsWith("mps")) {
        runtime.offload = "none";
        if (this.offloadSelect) this.offloadSelect.value = "none";
      }

      if (this.applyBtn) this.applyBtn.disabled = true;
      try {
        const capabilities = await App.refreshRuntimeCapabilities(false, false);
        ParamForm.triggerValidation();
        const production = capabilities.production_backend || {};
        if (production.ready) {
          Toast.show(`Configuration ready for ${runtime.device}. It will be used by the next run.`, "success");
        } else {
          Toast.show(`Configuration blocked: ${production.message || "runtime unavailable"}`, "error", 8000);
        }
      } catch (err) {
        Toast.show(`System configuration failed: ${err.message}`, "error");
      } finally {
        if (this.applyBtn) this.applyBtn.disabled = false;
      }
    },

    async refreshInventory() {
      if (this.refreshBtn) this.refreshBtn.disabled = true;
      try {
        await App.refreshRuntimeCapabilities(false, false);
        Toast.show("System inventory refreshed.", "success", 2000);
      } catch (err) {
        Toast.show(`System inventory refresh failed: ${err.message}`, "error");
      } finally {
        if (this.refreshBtn) this.refreshBtn.disabled = false;
      }
    },

    render(capabilities) {
      if (!capabilities) return;
      this.renderDeviceOptions(capabilities.devices || []);
      this.renderReadiness(capabilities);
      this.renderHost(capabilities);
      this.renderGpuInventory((capabilities.cuda && capabilities.cuda.devices) || []);
      this.renderLifecycle(capabilities);
    },

    renderDeviceOptions(devices) {
      if (!this.deviceSelect) return;
      const selected = Store.state.config.runtime.device;
      this.deviceSelect.innerHTML = "";
      for (const device of devices) {
        let label = `${device.id} — ${device.name}`;
        if (device.type === "cuda" && device.total_memory_bytes) {
          const free = device.free_memory_bytes === null || device.free_memory_bytes === undefined
            ? "free memory unknown"
            : `${Utils.formatBytes(device.free_memory_bytes)} free`;
          label += ` · ${free} / ${Utils.formatBytes(device.total_memory_bytes)}`;
        }
        const option = Utils.el("option", { value: device.id }, label);
        option.value = device.id;
        this.deviceSelect.appendChild(option);
      }
      if (!devices.some((device) => device.id === selected)) {
        const unavailable = Utils.el("option", { value: selected }, `${selected} — unavailable`);
        unavailable.value = selected;
        this.deviceSelect.appendChild(unavailable);
      }
      this.deviceSelect.value = selected;
    },

    renderReadiness(capabilities) {
      const card = document.getElementById("system-readiness-card");
      const status = document.getElementById("system-readiness-status");
      const message = document.getElementById("system-readiness-message");
      const production = capabilities.production_backend || {};
      const selected = capabilities.selected_device || {};
      if (card) {
        card.classList.toggle("ready", Boolean(production.ready));
        card.classList.toggle("blocked", !production.ready);
      }
      if (status) status.textContent = production.ready
        ? `${selected.id || "Selected device"} is ready`
        : `${selected.id || "Selected device"} is blocked`;
      if (message) message.textContent = production.message || "No runtime diagnostic was returned.";
    },

    renderHost(capabilities) {
      const host = capabilities.host || {};
      const cpu = host.cpu || {};
      const memory = host.memory || {};
      const setText = (id, value) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
      };
      const physical = cpu.physical_cores ? `${cpu.physical_cores} physical` : "physical count unknown";
      const logical = cpu.logical_cores ? `${cpu.logical_cores} logical` : "logical count unknown";
      setText("system-cpu-name", cpu.name || "Unknown CPU");
      setText("system-cpu-cores", `${physical} · ${logical}`);
      setText("system-ram-total", memory.total_bytes ? Utils.formatBytes(memory.total_bytes) : "Unknown");
      setText("system-ram-available", memory.available_bytes
        ? `${Utils.formatBytes(memory.available_bytes)} available · ${memory.percent_used}% used`
        : "Availability unknown");
      setText("system-torch-version", `PyTorch ${(capabilities.torch && capabilities.torch.version) || "unavailable"}`);
      setText("system-cuda-version", capabilities.torch && capabilities.torch.cuda_runtime
        ? `CUDA runtime ${capabilities.torch.cuda_runtime}`
        : "CUDA runtime unavailable");
      setText("system-python-version", `Python ${(capabilities.python && capabilities.python.version) || "unknown"}`);
      setText("system-platform", capabilities.platform || "Unknown platform");
    },

    renderGpuInventory(devices) {
      const list = document.getElementById("system-device-list");
      const count = document.getElementById("system-gpu-count");
      if (count) count.textContent = `${devices.length} detected`;
      if (!list) return;
      list.innerHTML = "";
      if (!devices.length) {
        list.appendChild(Utils.el("div", { class: "empty-state-text" }, "No CUDA GPU is available to this PyTorch runtime."));
        return;
      }
      for (const device of devices) {
        const total = device.total_memory_bytes || 0;
        const used = device.used_memory_bytes;
        const free = device.free_memory_bytes;
        const percent = total && used !== null && used !== undefined
          ? Math.min(100, Math.max(0, used / total * 100))
          : 0;
        const selected = device.id === Store.state.config.runtime.device;
        const card = Utils.el(
          "div",
          { class: `system-device-card${selected ? " selected" : ""}` },
          Utils.el(
            "div",
            { class: "system-device-heading" },
            Utils.el("strong", { class: "system-device-name" }, `${device.id} — ${device.name}`),
            Utils.el("span", { class: `badge ${selected ? "badge-accent" : "badge-muted"}` }, selected ? "Selected" : `CC ${device.compute_capability || "?"}`)
          ),
          Utils.el(
            "div",
            { class: "system-device-memory-row" },
            Utils.el("span", {}, free === null || free === undefined ? "Free memory unknown" : `${Utils.formatBytes(free)} free`),
            Utils.el("span", {}, total ? `${Utils.formatBytes(total)} total` : "Total memory unknown")
          ),
          Utils.el(
            "div",
            { class: "system-memory-track", attrs: { "aria-label": `${device.id} memory used`, role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(percent)) } },
            Utils.el("div", { class: "system-memory-fill", style: { width: `${percent}%` } })
          )
        );
        list.appendChild(card);
      }
    },

    renderLifecycle(capabilities) {
      const execution = capabilities.execution || {};
      const active = execution.active_job;
      const last = execution.last_run;
      const cache = execution.cache || {};
      const slots = Array.isArray(cache.slots) ? cache.slots : [];
      const selectedDevice = Store.state.config.runtime.device === "cuda"
        ? "cuda:0"
        : Store.state.config.runtime.device;
      const resident = slots.find((slot) => slot.device === selectedDevice && slot.pipeline)
        || slots.find((slot) => slot.pipeline);
      const backend = capabilities.backend || {};
      const setText = (id, value) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
      };
      setText("system-backend-mode", backend.default_mode === "demo" ? "Synthetic demo default" : "Production default");
      if (active) {
        setText("system-model-state", `${active.status}: ${active.requested_model}`);
        setText("system-lora-state", active.requested_lora ? `Requested: ${active.requested_lora.split(/[\\/]/).pop()}` : "No LoRA requested");
      } else if (resident) {
        const model = resident.model || {};
        const lora = resident.lora || {};
        const source = model.source || "loaded model";
        setText("system-model-state", `Loaded on ${resident.device}: ${source}`);
        setText("system-lora-state", lora.applied ? `Loaded: ${lora.filename || lora.path || "adapter"}` : "No loaded LoRA");
      } else if (last) {
        const model = last.model || {};
        const lora = last.lora || {};
        setText("system-model-state", `Last run: ${model.repo_id || model.source || last.run_id || "unknown"}`);
        setText("system-lora-state", lora.applied ? `Applied: ${lora.filename || lora.path || "adapter"}` : "No applied LoRA in last run");
      } else {
        setText("system-model-state", "No active run");
        setText("system-lora-state", "No run state available");
      }
      setText("system-lifecycle-message", execution.message || "Pipeline lifecycle information is unavailable.");
    },
  };


  // ==========================================================================
  // 10. R4: RUN EXECUTION & LIVE SSE STREAMING
  // ==========================================================================

  const RunController = {
    runBtn: null,
    runText: null,
    cancelBtn: null,
    statusBadge: null,
    progressWrap: null,
    progressBar: null,
    stepCounter: null,
    percentLabel: null,
    eventSource: null,

    init() {
      this.runBtn = document.getElementById("btn-run-pipeline");
      this.runText = document.getElementById("btn-run-text");
      this.cancelBtn = document.getElementById("btn-cancel-run");
      this.statusBadge = document.getElementById("run-status-badge");
      this.progressWrap = document.getElementById("execution-progress-container");
      this.progressBar = document.getElementById("run-step-progress-bar");
      this.stepCounter = document.getElementById("run-step-counter");
      this.percentLabel = document.getElementById("run-percent-label");

      if (this.runBtn) {
        this.runBtn.addEventListener("click", () => this.startRun());
      }

      if (this.cancelBtn) {
        this.cancelBtn.addEventListener("click", () => this.cancelRun());
      }
    },

    async startRun() {
      if (this.isSubmitting || Store.state.run.status === "running") return;
      this.isSubmitting = true;

      try {
        // 1. Every job needs at least one process input; references are optional.
        const inputs = Store.state.inputs.inputImages;
        const references = Store.state.inputs.referenceImages;
        if (inputs.length === 0) {
          Toast.show("Please select at least one input image before running.", "warning");
          InputBrowser.showErrorBanner(["Provide 1–10 ordered input images to process."]);
          return;
        }

        // 2. Validate configuration
        await ParamForm.runValidation(false);
        if (!Store.state.validation.valid) {
          Toast.show("Please resolve configuration validation errors before running.", "error");
          return;
        }

        try {
          this.setRunningState(true);
          TerminalViewer.clear();
          TerminalViewer.appendSystemLog("Initiating inference workflow pipeline...");

          Store.state.config.generation.input_images = inputs.map((item) => item.path);
          Store.state.config.generation.reference_images = references.map((item) => item.path);

          const payload = {
            selected_model_id: Store.state.models.selectedId,
            model: {
              lora_path: Store.state.config.model.lora_path,
              lora_scale: Store.state.config.model.lora_scale,
            },
            generation: Store.state.config.generation,
            runtime: Store.state.config.runtime,
            demo_mode: Store.state.config.demo_mode ?? false,
          };

          const res = await ApiClient.startRun(payload);
          const runId = res.run_id;
          Store.state.run.activeJobId = runId;

          TerminalViewer.appendSystemLog(`Job submitted successfully. Run ID: ${runId}`);
          TerminalViewer.appendSystemLog(`Connected to live SSE stream: ${res.stream_url}`);

          // Automatically switch view to logs tab during run
          this.switchOutputTab("tab-btn-logs", "pane-logs");

          // Connect SSE stream
          this.connectStream(runId);
        } catch (err) {
          this.setRunningState(false);
          Toast.show(`Failed to launch run: ${err.message}`, "error");
          TerminalViewer.appendLogLine(`Execution initiation error: ${err.message}`, "stderr");
        }
      } finally {
        this.isSubmitting = false;
      }
    },

    connectStream(runId) {
      if (this.eventSource) {
        this.eventSource.close();
      }

      const streamUrl = `/api/run/${encodeURIComponent(runId)}/stream`;
      this.eventSource = new EventSource(streamUrl);

      // Status event
      this.eventSource.addEventListener("status", (e) => {
        try {
          const data = JSON.parse(e.data);
          if (this.statusBadge) {
            this.statusBadge.textContent = (data.status || "RUNNING").toUpperCase();
          }
        } catch (err) {}
      });

      // Log event
      this.eventSource.addEventListener("log", (e) => {
        try {
          const data = JSON.parse(e.data);
          TerminalViewer.appendLogLine(data.text || "", data.stream || "stdout");
        } catch (err) {
          TerminalViewer.appendLogLine(e.data, "stdout");
        }
      });

      // Progress event
      this.eventSource.addEventListener("progress", (e) => {
        try {
          const data = JSON.parse(e.data);
          this.updateProgress(data.step, data.total, data.percent);
        } catch (err) {}
      });

      // Complete event
      this.eventSource.addEventListener("complete", (e) => {
        try {
          const data = JSON.parse(e.data);
          this.handleComplete(data);
        } catch (err) {
          console.error("Failed to parse complete event payload:", err);
        }
        if (this.eventSource) {
          this.eventSource.close();
          this.eventSource = null;
        }
      });

      this.eventSource.onerror = () => {
        if (this.eventSource) {
          this.eventSource.close();
          this.eventSource = null;
        }
        if (Store.state.run.status === "running") {
          this.setRunningState(false);
          TerminalViewer.appendSystemLog("SSE stream connection closed.");
        }
      };
    },

    updateProgress(step, total, percent) {
      const pct = Math.min(100, Math.max(0, Math.round(percent || (step / total) * 100)));
      Store.state.run.progress = { step, total, percent: pct };

      if (this.progressBar) {
        this.progressBar.style.width = `${pct}%`;
      }
      if (this.stepCounter) {
        this.stepCounter.textContent = `Step ${step} / ${total}`;
      }
      if (this.percentLabel) {
        this.percentLabel.textContent = `${pct}%`;
      }
    },

    handleComplete(payload) {
      this.setRunningState(false);

      if (payload.status === "success" || payload.status === "partial_success") {
        const isPartial = payload.status === "partial_success";
        if (this.statusBadge) {
          this.statusBadge.textContent = isPartial ? "Completed with errors" : "Completed";
          this.statusBadge.className = `status-pill badge ${isPartial ? "badge-warning" : "badge-success"}`;
        }
        Toast.show(
          isPartial ? "Some inputs failed; successful outputs are available." : "Workflow completed successfully!",
          isPartial ? "warning" : "success"
        );

        // Format outputs
        const records = payload.records || [];
        const comparisons = payload.comparisons || [];
        const outputs = (payload.outputs || []).map((o) => {
          const record = records.find((item) => item.run_id === o.run_id) || payload.record || {};
          const comparison = comparisons.find((item) => item.run_id === o.run_id);
          return {
            filename: o.filename || (o.path ? o.path.split("/").pop() : "output.png"),
            url: o.url || ApiClient.getOutputUrl(o.filename || (o.path ? o.path.split("/").pop() : "output.png")),
            width: o.width || 1024,
            height: o.height || 1024,
            sha256: o.sha256 || "",
            run_id: o.run_id || record.run_id,
            input_index: o.input_index ?? record.input_index,
            input_image: record.input_image,
            comparison_url: comparison ? comparison.url : null,
          };
        });

        Store.state.run.currentOutputs = outputs;
        Store.state.run.currentRecord = payload.record || payload;

        // Render Outputs View
        OutputViewer.renderOutputs(outputs);

        // Render Comparison View
        const firstOutput = outputs[0];
        ComparisonSlider.setup(
          outputs,
          (firstOutput && firstOutput.comparison_url) || payload.comparison_url,
          firstOutput && firstOutput.input_image
        );

        // Render JSON Record
        JsonInspector.render(payload.record || payload);

        // Refresh Run History
        RunHistory.loadHistory();

        // Switch to Outputs view tab
        this.switchOutputTab("tab-btn-outputs", "pane-outputs");
        if (isPartial) {
          const errors = (payload.errors || []).map((item) => {
            const detail = item.error || {};
            return `Input ${(item.input_index ?? 0) + 1}: ${detail.message || "generation failed"}`;
          });
          if (errors.length) {
            InputBrowser.showErrorBanner(errors);
            errors.forEach((message) => TerminalViewer.appendLogLine(message, "stderr"));
          }
        }
      } else {
        if (this.statusBadge) {
          this.statusBadge.textContent = "Failed";
          this.statusBadge.className = "status-pill badge badge-danger";
        }
        const errObj = payload.error || {};
        const errMsg = errObj.message || "Pipeline execution failed.";
        Toast.show(`Run failed: ${errMsg}`, "error");
        TerminalViewer.appendLogLine(`Execution error: ${errMsg}`, "stderr");
        if (errObj.traceback) {
          TerminalViewer.appendLogLine(errObj.traceback, "stderr");
        }
        this.switchOutputTab("tab-btn-logs", "pane-logs");
      }
    },

    setRunningState(isRunning) {
      Store.state.run.status = isRunning ? "running" : "idle";

      if (this.runBtn) {
        this.runBtn.disabled = isRunning;
        this.runBtn.classList.toggle("is-loading", isRunning);
        this.runBtn.setAttribute("aria-busy", isRunning ? "true" : "false");
      }
      if (this.runText) {
        this.runText.textContent = isRunning ? "Running..." : "Run Pipeline";
      }
      if (this.cancelBtn) {
        if (isRunning) this.cancelBtn.classList.remove("hidden");
        else this.cancelBtn.classList.add("hidden");
      }
      if (this.statusBadge) {
        if (isRunning) {
          this.statusBadge.textContent = "Running";
          this.statusBadge.className = "status-pill badge badge-primary";
        } else {
          this.statusBadge.textContent = "Idle";
          this.statusBadge.className = "status-pill badge badge-muted";
        }
      }
      if (this.progressWrap) {
        if (isRunning) this.progressWrap.classList.remove("hidden");
        else this.progressWrap.classList.add("hidden");
      }
      const outputPanel = document.getElementById("panel-output");
      if (outputPanel) outputPanel.setAttribute("aria-busy", isRunning ? "true" : "false");
      if (isRunning) ResponsiveWorkspace.revealRunStatus();
    },

    cancelRun() {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
      this.setRunningState(false);
      Toast.show("Execution monitor stopped.", "info");
      TerminalViewer.appendSystemLog("Execution monitor aborted by user.");
    },

    switchOutputTab(btnId, paneId) {
      const tabs = [
        { btn: "tab-btn-outputs", pane: "pane-outputs" },
        { btn: "tab-btn-comparison", pane: "pane-comparison" },
        { btn: "tab-btn-logs", pane: "pane-logs" },
        { btn: "tab-btn-json", pane: "pane-json" },
      ];

      tabs.forEach((t) => {
        const b = document.getElementById(t.btn);
        const p = document.getElementById(t.pane);
        if (b) {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        }
        if (p) p.classList.remove("active");
      });

      const activeBtn = document.getElementById(btnId);
      const activePane = document.getElementById(paneId);
      if (activeBtn) {
        activeBtn.classList.add("active");
        activeBtn.setAttribute("aria-selected", "true");
      }
      if (activePane) activePane.classList.add("active");
    },
  };


  // ==========================================================================
  // 9. TERMINAL LOG VIEWER
  // ==========================================================================

  const TerminalViewer = {
    consoleContainer: null,
    logLinesContainer: null,
    autoscrollToggle: null,
    copyBtn: null,
    clearBtn: null,

    init() {
      this.consoleContainer = document.getElementById("terminal-stream-console");
      this.logLinesContainer = document.getElementById("terminal-log-lines");
      this.autoscrollToggle = document.getElementById("toggle-log-autoscroll");
      this.copyBtn = document.getElementById("btn-copy-logs");
      this.clearBtn = document.getElementById("btn-clear-logs");

      if (this.clearBtn) {
        this.clearBtn.addEventListener("click", () => this.clear());
      }

      if (this.copyBtn) {
        this.copyBtn.addEventListener("click", async () => {
          if (!this.logLinesContainer) return;
          const text = this.logLinesContainer.innerText || this.logLinesContainer.textContent;
          const ok = await Utils.copyToClipboard(text);
          Toast.show(ok ? "Logs copied to clipboard" : "Failed to copy logs", ok ? "success" : "error");
        });
      }
    },

    appendLogLine(text, stream = "stdout") {
      if (!this.logLinesContainer) return;
      const lineNode = Utils.parseLogLine(text, stream);
      this.logLinesContainer.appendChild(lineNode);

      if (this.autoscrollToggle && this.autoscrollToggle.checked && this.consoleContainer) {
        this.consoleContainer.scrollTop = this.consoleContainer.scrollHeight;
      }
    },

    appendSystemLog(text) {
      if (!this.logLinesContainer) return;
      const line = Utils.el("div", { class: "terminal-line log-system" }, `[SYSTEM] ${text}`);
      this.logLinesContainer.appendChild(line);

      if (this.autoscrollToggle && this.autoscrollToggle.checked && this.consoleContainer) {
        this.consoleContainer.scrollTop = this.consoleContainer.scrollHeight;
      }
    },

    clear() {
      if (this.logLinesContainer) {
        this.logLinesContainer.innerHTML = "";
      }
    },
  };


  // ==========================================================================
  // 10. OUTPUT VIEWER
  // ==========================================================================

  const OutputViewer = {
    emptyState: null,
    activeView: null,
    primaryImage: null,
    fullscreenBtn: null,
    metaFilename: null,
    metaDimensions: null,
    metaSha256: null,
    downloadBtn: null,
    batchStrip: null,

    init() {
      this.emptyState = document.getElementById("output-empty-state");
      this.activeView = document.getElementById("output-active-view");
      this.primaryImage = document.getElementById("output-primary-image");
      this.fullscreenBtn = document.getElementById("btn-fullscreen-output");
      this.metaFilename = document.getElementById("output-meta-filename");
      this.metaDimensions = document.getElementById("output-meta-dimensions");
      this.metaSha256 = document.getElementById("output-meta-sha256");
      this.downloadBtn = document.getElementById("btn-download-output");
      this.batchStrip = document.getElementById("batch-thumbnails-strip");

      if (this.fullscreenBtn && this.primaryImage) {
        this.fullscreenBtn.addEventListener("click", () => {
          Lightbox.open(this.primaryImage.src, this.metaFilename ? this.metaFilename.textContent : "Output");
        });
      }

      if (this.metaSha256) {
        this.metaSha256.addEventListener("click", async () => {
          const hash = this.metaSha256.dataset.fullHash || this.metaSha256.textContent;
          if (hash) {
            const ok = await Utils.copyToClipboard(hash);
            Toast.show(ok ? "SHA-256 hash copied to clipboard" : "Copy failed", ok ? "success" : "error");
          }
        });
      }

      // Output Tabs Binding
      this.bindOutputTabs();
    },

    bindOutputTabs() {
      const tabs = [
        { btn: "tab-btn-outputs", pane: "pane-outputs" },
        { btn: "tab-btn-comparison", pane: "pane-comparison" },
        { btn: "tab-btn-logs", pane: "pane-logs" },
        { btn: "tab-btn-json", pane: "pane-json" },
      ];

      tabs.forEach(({ btn, pane }) => {
        const btnElem = document.getElementById(btn);
        if (btnElem) {
          btnElem.addEventListener("click", () => {
            tabs.forEach((t) => {
              const b = document.getElementById(t.btn);
              const p = document.getElementById(t.pane);
              if (b) {
                b.classList.remove("active");
                b.setAttribute("aria-selected", "false");
              }
              if (p) p.classList.remove("active");
            });

            btnElem.classList.add("active");
            btnElem.setAttribute("aria-selected", "true");
            const paneElem = document.getElementById(pane);
            if (paneElem) paneElem.classList.add("active");
          });
        }
      });
    },

    renderOutputs(outputs) {
      if (!outputs || outputs.length === 0) {
        if (this.emptyState) this.emptyState.classList.remove("hidden");
        if (this.activeView) this.activeView.classList.add("hidden");
        return;
      }

      if (this.emptyState) this.emptyState.classList.add("hidden");
      if (this.activeView) this.activeView.classList.remove("hidden");

      const primary = outputs[0];
      this.setPrimaryOutput(primary);

      // Render batch strip if more than 1 output
      if (this.batchStrip) {
        if (outputs.length > 1) {
          this.batchStrip.innerHTML = "";
          this.batchStrip.classList.remove("hidden");

          outputs.forEach((out, idx) => {
            const thumb = Utils.el("img", {
              class: `batch-thumb ${idx === 0 ? "active" : ""}`,
              src: out.url,
              alt: out.filename,
              onclick: () => {
                this.setPrimaryOutput(out);
                this.batchStrip.querySelectorAll(".batch-thumb").forEach((b) => b.classList.remove("active"));
                thumb.classList.add("active");
                ComparisonSlider.setup([out], out.comparison_url, out.input_image);
              },
            });
            this.batchStrip.appendChild(thumb);
          });
        } else {
          this.batchStrip.classList.add("hidden");
        }
      }
    },

    setPrimaryOutput(out) {
      if (this.primaryImage) {
        this.primaryImage.src = out.url;
      }
      if (this.metaFilename) {
        this.metaFilename.textContent = out.filename;
      }
      if (this.metaDimensions) {
        this.metaDimensions.textContent = out.width && out.height ? `${out.width} × ${out.height}` : "";
      }
      if (this.metaSha256) {
        const hash = out.sha256 || "";
        this.metaSha256.dataset.fullHash = hash;
        this.metaSha256.textContent = hash ? `${hash.substring(0, 16)}...` : "None";
      }
      if (this.downloadBtn) {
        this.downloadBtn.href = out.url;
        this.downloadBtn.download = out.filename;
      }
    },
  };


  // ==========================================================================
  // 11. COMPARISON SLIDER (Split & Side-by-Side)
  // ==========================================================================

  const ComparisonSlider = {
    emptyState: null,
    splitWrapper: null,
    beforeImg: null,
    afterImg: null,
    clipWrapper: null,
    handle: null,
    twoUpWrapper: null,
    twoUpBeforeImg: null,
    twoUpAfterImg: null,
    modeSplitBtn: null,
    modeSideBtn: null,

    init() {
      this.emptyState = document.getElementById("comparison-empty-state");
      this.splitWrapper = document.getElementById("comparison-split-wrapper");
      this.beforeImg = document.getElementById("comparison-before-img");
      this.afterImg = document.getElementById("comparison-after-img");
      this.clipWrapper = document.getElementById("comparison-clip-wrapper");
      this.handle = document.getElementById("comparison-slider-handle");
      this.twoUpWrapper = document.getElementById("comparison-two-up-wrapper");
      this.twoUpBeforeImg = document.getElementById("two-up-before-img");
      this.twoUpAfterImg = document.getElementById("two-up-after-img");
      this.modeSplitBtn = document.getElementById("btn-mode-split");
      this.modeSideBtn = document.getElementById("btn-mode-side");

      if (this.modeSplitBtn) {
        this.modeSplitBtn.addEventListener("click", () => {
          this.setMode("split");
        });
      }

      if (this.modeSideBtn) {
        this.modeSideBtn.addEventListener("click", () => {
          this.setMode("side");
        });
      }

      this.bindHandleDrag();

      // Ensure comparison badges align with displayed image halves:
      // In split view, clipWrapper (Output) is on the left; process input is on the right.
      if (this.splitWrapper && typeof this.splitWrapper.querySelector === "function") {
        const badgeBefore = this.splitWrapper.querySelector(".badge-before");
        const badgeAfter = this.splitWrapper.querySelector(".badge-after");
        if (badgeBefore) {
          badgeBefore.style.right = "12px";
          badgeBefore.style.left = "auto";
        }
        if (badgeAfter) {
          badgeAfter.style.left = "12px";
          badgeAfter.style.right = "auto";
        }
      }
    },

    setMode(mode) {
      if (mode === "split") {
        if (this.modeSplitBtn) this.modeSplitBtn.className = "btn btn-xs btn-active";
        if (this.modeSideBtn) this.modeSideBtn.className = "btn btn-xs btn-ghost";
        if (this.splitWrapper) this.splitWrapper.classList.remove("hidden");
        if (this.twoUpWrapper) this.twoUpWrapper.classList.add("hidden");
      } else {
        if (this.modeSplitBtn) this.modeSplitBtn.className = "btn btn-xs btn-ghost";
        if (this.modeSideBtn) this.modeSideBtn.className = "btn btn-xs btn-active";
        if (this.splitWrapper) this.splitWrapper.classList.add("hidden");
        if (this.twoUpWrapper) this.twoUpWrapper.classList.remove("hidden");
      }
    },

    setup(outputs, comparisonUrl = null, sourceImagePath = null) {
      if (comparisonUrl && typeof comparisonUrl === "string") {
        if (comparisonUrl.startsWith("/api/outputs/")) {
          // Already an API URL
        } else if (comparisonUrl.includes("/") || comparisonUrl.endsWith(".png")) {
          const filename = comparisonUrl.split("/").pop();
          comparisonUrl = ApiClient.getOutputUrl(filename);
        }
      }

      let canvasThumb = null;
      let canvasImgPath = sourceImagePath;
      const curRec = Store.state.run.currentRecord;
      if (!canvasImgPath && curRec) {
        canvasImgPath = curRec?.input_image
          || curRec?.parameters?.generation?.input_images?.[curRec?.input_index || 0]
          || curRec?.parameters?.generation?.images?.[0]
          || curRec?.config?.generation?.images?.[0]
          || curRec?.effective_parameters?.reference_images?.[0]?.path;
      }
      if (!canvasImgPath) {
        const selected = Store.state.inputs.inputImages;
        if (selected && selected.length > 0) {
          canvasImgPath = selected[0].path;
        }
      }
      if (canvasImgPath) {
        canvasThumb = ApiClient.getThumbnailUrl(canvasImgPath, 1024);
      }

      if ((!canvasThumb && !comparisonUrl) || !outputs || outputs.length === 0) {
        if (this.emptyState) this.emptyState.classList.remove("hidden");
        if (this.splitWrapper) this.splitWrapper.classList.add("hidden");
        if (this.twoUpWrapper) this.twoUpWrapper.classList.add("hidden");
        return;
      }

      const generatedImgUrl = outputs[0].url;

      if (this.emptyState) this.emptyState.classList.add("hidden");

      if (this.beforeImg) this.beforeImg.src = canvasThumb || comparisonUrl;
      if (this.afterImg) this.afterImg.src = generatedImgUrl;
      if (this.twoUpBeforeImg) this.twoUpBeforeImg.src = canvasThumb || comparisonUrl;
      if (this.twoUpAfterImg) this.twoUpAfterImg.src = generatedImgUrl;

      if (this.handle) this.handle.style.left = "50%";
      if (this.clipWrapper) this.clipWrapper.style.clipPath = "inset(0 50% 0 0)";

      this.setMode("split");
    },

    bindHandleDrag() {
      if (!this.splitWrapper || !this.handle || !this.clipWrapper) return;

      let isDragging = false;

      const updatePos = (clientX) => {
        const rect = this.splitWrapper.getBoundingClientRect();
        let offsetX = clientX - rect.left;
        offsetX = Math.max(0, Math.min(offsetX, rect.width));
        const pct = rect.width > 0 ? (offsetX / rect.width) * 100 : 50;

        this.handle.style.left = `${pct}%`;
        this.clipWrapper.style.clipPath = `inset(0 calc(100% - ${pct}%) 0 0)`;
      };

      this.splitWrapper.addEventListener("pointerdown", (e) => {
        isDragging = true;
        updatePos(e.clientX);
        this.splitWrapper.setPointerCapture(e.pointerId);
      });

      this.splitWrapper.addEventListener("pointermove", (e) => {
        if (!isDragging) return;
        updatePos(e.clientX);
      });

      this.splitWrapper.addEventListener("pointerup", (e) => {
        isDragging = false;
        try {
          this.splitWrapper.releasePointerCapture(e.pointerId);
        } catch (err) {}
      });

      this.splitWrapper.addEventListener("pointercancel", () => {
        isDragging = false;
      });
    },
  };


  // ==========================================================================
  // 12. JSON RECORD INSPECTOR & RUN HISTORY
  // ==========================================================================

  const JsonInspector = {
    runIdLabel: null,
    codeElem: null,
    copyBtn: null,
    downloadBtn: null,
    currentData: null,

    init() {
      this.runIdLabel = document.getElementById("json-run-id-label");
      this.codeElem = document.getElementById("json-record-code");
      this.copyBtn = document.getElementById("btn-copy-json");
      this.downloadBtn = document.getElementById("btn-download-json");

      if (this.copyBtn) {
        this.copyBtn.addEventListener("click", async () => {
          if (!this.currentData) return;
          const jsonStr = JSON.stringify(this.currentData, null, 2);
          const ok = await Utils.copyToClipboard(jsonStr);
          Toast.show(ok ? "JSON record copied to clipboard" : "Failed to copy JSON", ok ? "success" : "error");
        });
      }

      if (this.downloadBtn) {
        this.downloadBtn.addEventListener("click", () => {
          if (!this.currentData) return;
          const jsonStr = JSON.stringify(this.currentData, null, 2);
          const blob = new Blob([jsonStr], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          const runId = (this.currentData && this.currentData.run_id) || "run_record";
          a.href = url;
          a.download = `${runId}.json`;
          a.click();
          URL.revokeObjectURL(url);
        });
      }
    },

    render(record) {
      this.currentData = record;
      if (!this.codeElem) return;

      if (!record) {
        this.codeElem.textContent = '{\n  "message": "No run record loaded."\n}';
        if (this.runIdLabel) this.runIdLabel.textContent = "Run: None";
        return;
      }

      if (this.runIdLabel) {
        this.runIdLabel.textContent = `Run: ${record.run_id || "active"}`;
      }
      this.codeElem.textContent = JSON.stringify(record, null, 2);
    },
  };


  const RunHistory = {
    drawerBackdrop: null,
    drawerHistory: null,
    toggleBtn: null,
    closeBtn: null,
    historyCounter: null,
    runsList: null,
    emptyNotice: null,

    init() {
      this.drawerBackdrop = document.getElementById("drawer-backdrop");
      this.drawerHistory = document.getElementById("drawer-history");
      this.toggleBtn = document.getElementById("btn-toggle-history");
      this.closeBtn = document.getElementById("btn-close-history");
      this.historyCounter = document.getElementById("history-counter");
      this.runsList = document.getElementById("history-runs-list");
      this.emptyNotice = document.getElementById("empty-history-notice");

      if (this.toggleBtn) {
        this.toggleBtn.addEventListener("click", () => this.openDrawer());
      }

      if (this.closeBtn) {
        this.closeBtn.addEventListener("click", () => this.closeDrawer());
      }

      if (this.drawerBackdrop) {
        this.drawerBackdrop.addEventListener("click", () => this.closeDrawer());
      }

      this.loadHistory();
    },

    openDrawer() {
      if (this.drawerBackdrop) this.drawerBackdrop.classList.remove("hidden");
      if (this.drawerHistory) {
        this.drawerHistory.classList.add("open");
        this.drawerHistory.setAttribute("aria-hidden", "false");
      }
    },

    closeDrawer() {
      if (this.drawerBackdrop) this.drawerBackdrop.classList.add("hidden");
      if (this.drawerHistory) {
        this.drawerHistory.classList.remove("open");
        this.drawerHistory.setAttribute("aria-hidden", "true");
      }
    },

    async loadHistory() {
      try {
        const data = await ApiClient.listRuns();
        const runs = data.runs || [];
        Store.state.history = runs;

        if (this.historyCounter) {
          this.historyCounter.textContent = String(runs.length);
        }

        const footerRuns = document.getElementById("status-bar-runs-count");
        if (footerRuns) {
          footerRuns.textContent = String(runs.length);
        }

        this.render(runs);
      } catch (err) {
        console.error("Failed to load run history:", err);
      }
    },

    render(runs) {
      if (!this.runsList) return;
      this.runsList.innerHTML = "";

      if (!runs || runs.length === 0) {
        if (this.emptyNotice) {
          this.runsList.appendChild(this.emptyNotice);
        } else {
          this.runsList.innerHTML = `<div class="empty-state-text">No runs in this session yet.</div>`;
        }
        return;
      }

      const frag = document.createDocumentFragment();

      for (const r of runs) {
        const isSuccess = r.status === "completed" || r.status === "success";
        const isPartial = r.status === "partial_success";
        const badgeClass = isSuccess ? "badge-success" : isPartial ? "badge-warning" : "badge-danger";

        const item = Utils.el(
          "div",
          {
            class: "history-item history-card",
            onclick: () => {
              this.selectRun(r.run_id);
              this.closeDrawer();
            },
          },
          Utils.el(
            "div",
            { class: "history-item-header history-card-header" },
            Utils.el("span", { class: "history-run-id font-mono" }, r.run_id),
            Utils.el("span", { class: `badge ${badgeClass}` }, (r.status || "UNKNOWN").toUpperCase())
          ),
          Utils.el(
            "div",
            { class: "history-item-meta history-card-meta" },
            Utils.el("span", {}, r.timestamp ? new Date(r.timestamp).toLocaleTimeString() : ""),
            r.inference_time_seconds
              ? Utils.el("span", {}, `${r.inference_time_seconds.toFixed(2)}s`)
              : null
          )
        );

        frag.appendChild(item);
      }

      this.runsList.appendChild(frag);
    },

    async selectRun(runId) {
      try {
        Toast.show(`Loading run ${runId}...`, "info", 1500);
        const record = await ApiClient.getRunRecord(runId);

        if (record.outputs) {
          const outputs = record.outputs.map((o) => {
            const filename = o.filename || (o.path ? o.path.split("/").pop() : "output.png");
            return {
              filename,
              url: o.url || ApiClient.getOutputUrl(filename),
              width: o.width || 1024,
              height: o.height || 1024,
              sha256: o.sha256 || "",
            };
          });
          OutputViewer.renderOutputs(outputs);
          Store.state.run.currentRecord = record;
          let compUrl = record.comparison;
          if (compUrl && typeof compUrl === "string" && !compUrl.startsWith("/api/")) {
            compUrl = ApiClient.getOutputUrl(compUrl.split("/").pop());
          }
          ComparisonSlider.setup(outputs, compUrl);
        }

        JsonInspector.render(record);
        RunController.switchOutputTab("tab-btn-outputs", "pane-outputs");
        TerminalViewer.appendSystemLog(`Inspecting past run: ${runId}`);
      } catch (err) {
        Toast.show(`Failed to fetch run record: ${err.message}`, "error");
      }
    },
  };


  // ==========================================================================
  // 13. FULLSCREEN LIGHTBOX MODAL
  // ==========================================================================

  const Lightbox = {
    dialog: null,
    img: null,
    title: null,
    closeBtn: null,

    init() {
      this.dialog = document.getElementById("modal-image-preview");
      this.img = document.getElementById("modal-preview-img");
      this.title = document.getElementById("modal-preview-title");
      this.closeBtn = document.getElementById("btn-close-modal");

      if (this.closeBtn) {
        this.closeBtn.addEventListener("click", () => this.close());
      }

      if (this.dialog) {
        this.dialog.addEventListener("click", (e) => {
          if (e.target === this.dialog) this.close();
        });
      }
    },

    open(src, titleText = "Image Preview", width = null, height = null) {
      if (!this.dialog || !this.img) return;
      this.img.src = src;
      if (this.title) {
        const dims = width && height ? ` (${width}×${height})` : "";
        this.title.textContent = `${titleText}${dims}`;
      }
      if (typeof this.dialog.showModal === "function") {
        try {
          this.dialog.showModal();
        } catch (e) {
          this.dialog.setAttribute("open", "");
        }
      } else {
        this.dialog.setAttribute("open", "");
      }
    },

    close() {
      if (!this.dialog) return;
      if (typeof this.dialog.close === "function") {
        try {
          this.dialog.close();
        } catch (e) {
          this.dialog.removeAttribute("open");
        }
      } else {
        this.dialog.removeAttribute("open");
      }
      if (this.img) this.img.src = "";
    },
  };


  // ==========================================================================
  // 14. APPLICATION BOOTSTRAP
  // ==========================================================================

  const App = {
    async refreshRuntimeCapabilities(applyServerDefault = false, notifyBlocked = false) {
      const capabilities = await ApiClient.getSystemCapabilities(Store.state.config.runtime);
      Store.state.system.capabilities = capabilities;

      if (applyServerDefault) {
        const demoDefault = Boolean(capabilities.backend && capabilities.backend.demo_default);
        Store.state.config.demo_mode = demoDefault;
        const demoToggle = document.getElementById("toggle-demo-mode");
        if (demoToggle) demoToggle.checked = demoDefault;
      }

      this.renderRuntimeStatus(capabilities);
      SystemManager.render(capabilities);

      const production = capabilities.production_backend || {};
      if (notifyBlocked && !Store.state.config.demo_mode && !production.ready) {
        Toast.show(`Real inference unavailable: ${production.message || "selected runtime is not ready"}`, "warning", 8000);
      }
      return capabilities;
    },

    renderRuntimeStatus(capabilities = Store.state.system.capabilities) {
      const pill = document.getElementById("backend-status-pill");
      const text = document.getElementById("backend-status-text");
      const footerMode = document.getElementById("status-bar-mode");
      const demoMode = Boolean(Store.state.config.demo_mode);

      if (demoMode) {
        if (pill) {
          pill.className = "status-pill status-online";
          pill.title = "Synthetic demo is enabled. Qwen model inference will not run.";
        }
        if (text) text.textContent = "Synthetic Demo";
        if (footerMode) footerMode.textContent = "Synthetic Demo • No model inference";
        return;
      }

      const production = capabilities && capabilities.production_backend;
      const selected = capabilities && capabilities.selected_device;
      if (production && production.ready) {
        if (pill) {
          pill.className = "status-pill status-online";
          pill.title = production.message || "Production backend is ready";
        }
        if (text) text.textContent = "Real Backend Ready";
        if (footerMode) footerMode.textContent = `Real • ${(selected && selected.id) || "selected device"}`;
      } else {
        const message = (production && production.message) || "Runtime capability information is unavailable.";
        if (pill) {
          pill.className = "status-pill status-warning";
          pill.title = message;
        }
        if (text) text.textContent = production ? "Real Backend Blocked" : "Runtime Unknown";
        if (footerMode) {
          const deviceName = (selected && selected.id) || Store.state.config.runtime.device;
          footerMode.textContent = `Real • ${deviceName} unavailable`;
          footerMode.title = message;
        }
      }
    },

    async init() {
      console.log("Qwen Image 2.1 Workflow UI: Starting application controller...");

      Toast.init();
      ResponsiveWorkspace.init();
      ParameterHelp.init();
      InputBrowser.init();
      ParamForm.init();
      SystemManager.init();
      ModelManager.init();
      LoRAManager.init();
      RunController.init();
      TerminalViewer.init();
      OutputViewer.init();
      ComparisonSlider.init();
      JsonInspector.init();
      RunHistory.init();
      Lightbox.init();

      // Check backend connectivity first, then inspect production runtime readiness.
      try {
        await ApiClient.checkHealth();
        Store.state.connected = true;

        const pill = document.getElementById("backend-status-pill");
        const text = document.getElementById("backend-status-text");
        if (pill) pill.className = "status-pill status-online";
        if (text) text.textContent = "Connected";
      } catch (err) {
        console.warn("Backend health check failed:", err);
        const pill = document.getElementById("backend-status-pill");
        const text = document.getElementById("backend-status-text");
        if (pill) pill.className = "status-pill status-offline";
        if (text) text.textContent = "Disconnected";

        Toast.show("Backend server unreachable. Verify server is running on localhost:7878.", "warning");
        return;
      }

      try {
        await this.refreshRuntimeCapabilities(true, true);
        console.log("Qwen Image 2.1 Workflow UI: Backend connected and runtime inspected.");
      } catch (err) {
        console.warn("Runtime capability check failed:", err);
        this.renderRuntimeStatus(null);
        Toast.show("Backend connected, but runtime capability inspection failed.", "warning");
      }
    },
  };

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => App.init());
  } else {
    App.init();
  }
})();
