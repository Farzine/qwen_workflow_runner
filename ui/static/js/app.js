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
        activeTask: null,
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
      this.bindField("param-model-source", "model.source", "input");
      this.bindField("param-model-revision", "model.revision", "input");
      this.bindField("param-model-filename", "model.filename", "input");
      this.bindField("param-gguf-quantization", "model.gguf_quantization", "input");
      this.bindField("param-base-model", "model.base_model", "input");
      this.bindField("param-base-revision", "model.base_revision", "input");
      this.bindField("param-text-encoder-source", "model.text_encoder_source", "input");
      this.bindField("param-model-cache-dir", "model.cache_dir", "input");
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

      // If client errors exist, render directly
      if (errors.length > 0) {
        this.renderValidationResult(false, errors);
        return;
      }

      // Query server validator
      try {
        const payload = {
          model: c.model,
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
        });
      }

      if (this.hfDownloadBtn) {
        this.hfDownloadBtn.addEventListener("click", () => this.startHfDownload());
      }

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
      } catch (err) {
        console.error("Failed to list models:", err);
      }
    },

    renderCachedSelect(models) {
      if (!this.cachedSelect) return;
      this.cachedSelect.innerHTML = "";

      const defaultOpt = Utils.el("option", { value: "" }, "-- Select a discovered / cached model --");
      this.cachedSelect.appendChild(defaultOpt);

      for (const m of models) {
        const typeBadge = m.type ? m.type.toUpperCase() : "WEIGHTS";
        const sizeStr = m.size ? ` (${Utils.formatBytes(m.size)})` : "";
        const label = `[${typeBadge}] ${m.name}${sizeStr}`;

        const opt = Utils.el("option", { value: m.path || m.name }, label);
        this.cachedSelect.appendChild(opt);
      }
    },

    displayCachedModelInfo(selectedVal) {
      const models = Store.state.models.cached;
      const model = models.find((m) => m.path === selectedVal || m.name === selectedVal);

      if (!model) {
        if (this.modelInfoBox) this.modelInfoBox.classList.add("hidden");
        return;
      }

      if (this.modelInfoBox) this.modelInfoBox.classList.remove("hidden");
      if (this.infoPath) this.infoPath.textContent = model.path || model.name;
      if (this.infoType) this.infoType.textContent = (model.type || "unknown").toUpperCase();
      if (this.infoSize) this.infoSize.textContent = model.size ? Utils.formatBytes(model.size) : "N/A";
    },

    applySelectedCachedModel() {
      const selectedVal = this.cachedSelect ? this.cachedSelect.value : "";
      if (!selectedVal) {
        Toast.show("Please select a cached model from the dropdown first.", "warning");
        return;
      }

      const model = Store.state.models.cached.find((m) => m.path === selectedVal || m.name === selectedVal);
      if (!model) return;

      const sourceInput = document.getElementById("param-model-source");
      const filenameInput = document.getElementById("param-model-filename");

      if (model.type === "gguf" || (model.filename && model.filename.endsWith(".gguf"))) {
        if (filenameInput) {
          filenameInput.value = model.filename || model.name;
          Store.state.config.model.filename = filenameInput.value;
        }
      } else {
        if (sourceInput) {
          sourceInput.value = model.path || model.name;
          Store.state.config.model.source = sourceInput.value;
        }
      }

      Toast.show(`Applied model: ${model.name}`, "success");
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
        if (this.hfProgressBar) this.hfProgressBar.style.width = "0%";
        if (this.hfProgressBadge) this.hfProgressBadge.textContent = "0%";
        if (this.hfProgressStatus) this.hfProgressStatus.textContent = "Initiating download...";

        const data = await ApiClient.downloadModel(repoId, filename, revision);
        const taskId = data.task_id;
        Toast.show(`Download started: ${repoId}`, "info");

        // Poll progress
        const pollInterval = setInterval(async () => {
          try {
            const p = await ApiClient.getDownloadProgress(taskId);
            const pct = Math.min(100, Math.max(0, Math.round(p.percent || p.progress * 100 || 0)));

            if (this.hfProgressBar) this.hfProgressBar.style.width = `${pct}%`;
            if (this.hfProgressBadge) this.hfProgressBadge.textContent = `${pct}%`;
            if (this.hfProgressStatus) this.hfProgressStatus.textContent = `Status: ${p.status} (${pct}%)`;

            if (p.status === "completed") {
              clearInterval(pollInterval);
              Toast.show(`Model download completed: ${repoId}`, "success");
              this.loadModels();
            } else if (p.status === "failed") {
              clearInterval(pollInterval);
              const errMsg = p.error || "Download failed.";
              if (this.hfProgressError) {
                this.hfProgressError.textContent = `Error: ${errMsg}`;
                this.hfProgressError.classList.remove("hidden");
              }
              Toast.show(`Download failed: ${errMsg}`, "error");
            }
          } catch (err) {
            clearInterval(pollInterval);
            console.error("Progress polling error:", err);
          }
        }, 750);
      } catch (err) {
        if (this.hfProgressError) {
          this.hfProgressError.textContent = `Error: ${err.message}`;
          this.hfProgressError.classList.remove("hidden");
        }
        Toast.show(`Download request failed: ${err.message}`, "error");
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
  // 8. R4: RUN EXECUTION & LIVE SSE STREAMING
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
            model: Store.state.config.model,
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
      InputBrowser.init();
      ParamForm.init();
      ModelManager.init();
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
