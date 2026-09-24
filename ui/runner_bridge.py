"""ui/runner_bridge.py

Background runner execution engine, thread-safe stdout/stderr interception,
progress parsing, Server-Sent Events (SSE) distribution, and demo mode integrity layer.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Set, Tuple, Type
import uuid

from PIL import Image, ImageDraw, ImageFont
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
import torch

import qwen_runner.runner
from qwen_runner.config import Config
from qwen_runner.resources import PipelineManager


logger = logging.getLogger("ui.runner_bridge")


# ============================================================================
# 1. SAFE TORCH WRAPPER (CPU / Headless GPU Resilience)
# ============================================================================

class SafeTorchWrapper:
    """Safeguards torch.cuda invocations on CPU-only or unsupported GPU hosts.

    Prevents crashes in InferenceMetrics and runner.environment when device='cuda:0'
    is configured on systems without working CUDA drivers.
    """

    def __init__(self, real_torch: Any):
        self._real_torch = real_torch

    class _SafeCuda:
        def __init__(self, real_cuda: Any):
            self._real_cuda = real_cuda

        def is_available(self) -> bool:
            try:
                return bool(self._real_cuda.is_available())
            except Exception:
                return False

        def synchronize(self, *args, **kwargs) -> None:
            if self.is_available():
                try:
                    return self._real_cuda.synchronize(*args, **kwargs)
                except Exception:
                    pass

        def memory_allocated(self, *args, **kwargs) -> int:
            if self.is_available():
                try:
                    return int(self._real_cuda.memory_allocated(*args, **kwargs))
                except Exception:
                    pass
            return 0

        def memory_reserved(self, *args, **kwargs) -> int:
            if self.is_available():
                try:
                    return int(self._real_cuda.memory_reserved(*args, **kwargs))
                except Exception:
                    pass
            return 0

        def reset_peak_memory_stats(self, *args, **kwargs) -> None:
            if self.is_available():
                try:
                    return self._real_cuda.reset_peak_memory_stats(*args, **kwargs)
                except Exception:
                    pass

        def max_memory_allocated(self, *args, **kwargs) -> int:
            if self.is_available():
                try:
                    return int(self._real_cuda.max_memory_allocated(*args, **kwargs))
                except Exception:
                    pass
            return 0

        def max_memory_reserved(self, *args, **kwargs) -> int:
            if self.is_available():
                try:
                    return int(self._real_cuda.max_memory_reserved(*args, **kwargs))
                except Exception:
                    pass
            return 0

        def get_device_properties(self, *args, **kwargs) -> Any:
            if self.is_available():
                try:
                    return self._real_cuda.get_device_properties(*args, **kwargs)
                except Exception:
                    pass

            class _MockProps:
                name = "CPU (Demo Mode)"
                total_memory = 0
                major = 0
                minor = 0

            return _MockProps()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real_cuda, name)

    def __getattr__(self, name: str) -> Any:
        if name == "cuda":
            return self._SafeCuda(self._real_torch.cuda)
        return getattr(self._real_torch, name)


# ============================================================================
# 2. DEMO INTEGRITY BACKEND
# ============================================================================

class DemoBackend:
    """Synthetic, input-derived preview backend for UI and API testing.

    Produces canvas-sized composited PIL images derived from user inputs, computes
    exact SHA-256 hashes, supports comparisons, and writes valid JSON records.
    Duck-typed to match qwen_runner.backend.QwenBackend interface.
    """

    def __init__(self, config: Config):
        self.config = config
        cuda_ok = False
        try:
            cuda_ok = hasattr(torch, "cuda") and torch.cuda.is_available()
        except Exception:
            cuda_ok = False

        self.torch = torch if cuda_ok else SafeTorchWrapper(torch)
        self.metadata = {
            "model": {
                "source": config.model.source,
                "repo_id": config.model.source,
                "revision": config.model.revision,
                "filename": config.model.filename,
                "mode": "demo",
                "backend": "DemoBackend",
            },
            "pipeline": "WorkflowQwenImage21Pipeline[Demo]",
            "text_encoder": {
                "class": "DemoTextEncoder",
                "repo_id": config.model.text_encoder_source or config.model.source,
                "path": "synthetic",
            },
            "vae": {"class": "DemoAutoencoderKL", "path": "synthetic"},
            "transformer": "DemoTransformer2DModel",
            "precision": config.runtime.dtype,
            "device": config.runtime.device,
            "scheduler_config": {
                "num_train_timesteps": 1000,
                "shift": config.generation.shift,
                "scheduler": config.generation.scheduler,
            },
            "parity": "Synthetic input-derived preview for UI feedback and schema validation; no model inference",
            "kv_cache_policy": "Demo mode simulated lossless prefix cache",
            "lora": {
                "enabled": bool(config.model.lora_path),
                "applied": False,
                "path": config.model.lora_path,
                "scale": config.model.lora_scale,
                "reason": "Synthetic demo mode does not load model adapters",
            },
        }

    def load(self) -> "DemoBackend":
        """Fast load lifecycle hook matching QwenBackend.load()."""
        return self

    def generate(
        self, images: List[Image.Image], canvas: Tuple[int, int], seed: int
    ) -> List[Image.Image]:
        """Generate labeled synthetic previews matching the requested canvas dimensions.

        Composites:
          - Sized base canvas from images[0] (or neutral background if empty)
          - Seed-based subtle aesthetic tinting
          - Reference image miniatures in upper right corner with color-coded borders
          - High-contrast header watermark with seed and batch index
          - Parameter card footer with prompt, dimensions, steps, CFG, and denoise strength
        """
        w, h = canvas
        g = self.config.generation
        batch_size = max(1, g.batch_size)
        results = []
        font = ImageFont.load_default()

        for b_idx in range(batch_size):
            cur_seed = (seed + b_idx * 100003) % (2**64)

            # 1. Base Layer
            if images and len(images) > 0:
                base = images[0].convert("RGB").resize((w, h), Image.Resampling.BILINEAR)
                r_tint = int((cur_seed & 0xFF) % 50)
                g_tint = int(((cur_seed >> 8) & 0xFF) % 50)
                b_tint = int(((cur_seed >> 16) & 0xFF) % 50)
                tint = Image.new("RGB", (w, h), (r_tint, g_tint, b_tint))
                img = Image.blend(base, tint, alpha=0.15)
            else:
                img = Image.new("RGB", (w, h), color=(30 + (cur_seed % 80), 45, 70))

            draw = ImageDraw.Draw(img)

            # 2. Header Bar
            header_h = min(36, max(20, h // 16))
            draw.rectangle([0, 0, w, header_h], fill=(14, 18, 26))
            header_text = f"QWEN DEMO • Seed {cur_seed} • Batch {b_idx + 1}/{batch_size}"
            draw.text((10, max(2, (header_h - 12) // 2)), header_text, fill=(0, 230, 180), font=font)

            # 3. Reference Miniatures (if dimensions allow)
            if w >= 256 and h >= 256 and images:
                max_thumb = (min(w // 5, 140), min(h // 5, 140))
                margin = 12
                cur_x = w - margin
                for i, ref in enumerate(images[:3]):
                    th = ref.copy().convert("RGB")
                    th.thumbnail(max_thumb)
                    x0 = cur_x - th.width
                    y0 = margin + header_h
                    if x0 > 10:
                        outline_col = (70, 160, 255) if i == 0 else (255, 160, 70) if i == 1 else (160, 255, 70)
                        draw.rectangle(
                            [x0 - 2, y0 - 2, x0 + th.width + 1, y0 + th.height + 1],
                            outline=outline_col,
                            width=2,
                        )
                        img.paste(th, (x0, y0))
                        draw.text((x0 + 2, y0 + th.height + 4), f"Img {i + 1}", fill=(240, 240, 240), font=font)
                        cur_x = x0 - margin

            # 4. Parameter Footer Card (if sufficient height)
            if h >= 160:
                footer_h = min(110, h // 4)
                footer_y = h - footer_h
                draw.rectangle([0, footer_y, w, h], fill=(12, 15, 20))
                draw.line([0, footer_y, w, footer_y], fill=(60, 70, 90), width=1)
                y_cursor = footer_y + 8

                p = g.prompt if len(g.prompt) < 85 else g.prompt[:82] + "..."
                draw.text((12, y_cursor), f"Prompt: {p}", fill=(230, 235, 245), font=font)
                y_cursor += 18
                draw.text(
                    (12, y_cursor),
                    f"Canvas: {w}x{h} | Steps: {g.steps} | CFG: {g.cfg} | Denoise: {g.strength} | Sampler: {g.sampler}/{g.scheduler}",
                    fill=(160, 175, 195),
                    font=font,
                )
                y_cursor += 18
                draw.text(
                    (12, y_cursor),
                    f"Model: {self.config.model.source} [Demo Mode]",
                    fill=(130, 145, 165),
                    font=font,
                )

            results.append(img)
        return results


def resolve_backend_factory(demo_mode: bool = False, force_qwen: bool = False) -> Type:
    """Resolve the explicitly requested backend without silently changing modes."""
    if demo_mode:
        return DemoBackend

    from qwen_runner.backend import QwenBackend
    return QwenBackend


class _BorrowedBackend:
    """Runner-compatible view of a backend already loaded by PipelineManager."""

    def __init__(self, backend: Any):
        object.__setattr__(self, "_backend", backend)

    def load(self) -> "_BorrowedBackend":
        return self

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_backend":
            object.__setattr__(self, name, value)
        else:
            setattr(self._backend, name, value)


# ============================================================================
# 3. THREAD-AWARE STDOUT / STDERR INTERCEPTION
# ============================================================================

class ThreadAwareStream(io.TextIOBase):
    """Intercepts stdout/stderr writes per thread while passing through to the original stream."""

    def __init__(self, original_stream: Any, stream_name: str = "stdout"):
        self.original_stream = original_stream
        self.stream_name = stream_name
        self._callbacks: Dict[int, Callable[[str, str], None]] = {}
        self._buffers: Dict[int, str] = {}
        self._lock = threading.Lock()

    def register(self, thread_id: int, callback: Callable[[str, str], None]) -> None:
        with self._lock:
            self._callbacks[thread_id] = callback
            self._buffers[thread_id] = ""

    def unregister(self, thread_id: int) -> None:
        with self._lock:
            callback = self._callbacks.pop(thread_id, None)
            buf = self._buffers.pop(thread_id, "")
        if callback and buf.strip():
            try:
                callback(buf.strip(), self.stream_name)
            except Exception:
                pass

    def write(self, s: str) -> int:
        try:
            self.original_stream.write(s)
            self.original_stream.flush()
        except Exception:
            pass

        if not s:
            return 0

        tid = threading.get_ident()
        with self._lock:
            callback = self._callbacks.get(tid)
            if not callback:
                return len(s)
            buf = self._buffers.get(tid, "") + s

        # Split on both \n and \r for tqdm live line updates
        lines = []
        while True:
            nl = buf.find("\n")
            cr = buf.find("\r")
            if nl == -1 and cr == -1:
                break
            if nl != -1 and (cr == -1 or nl < cr):
                lines.append(buf[:nl])
                buf = buf[nl + 1:]
            else:
                lines.append(buf[:cr])
                buf = buf[cr + 1:]

        with self._lock:
            self._buffers[tid] = buf

        for line in lines:
            line_str = line.strip()
            if line_str:
                try:
                    callback(line_str, self.stream_name)
                except Exception:
                    pass

        return len(s)

    def flush(self) -> None:
        tid = threading.get_ident()
        with self._lock:
            callback = self._callbacks.get(tid)
            buf = self._buffers.get(tid, "")
            self._buffers[tid] = ""

        if callback and buf and buf.strip():
            try:
                callback(buf.strip(), self.stream_name)
            except Exception:
                pass

        try:
            self.original_stream.flush()
        except Exception:
            pass


class CaptureManager:
    """Manages global stream hooks on sys.stdout and sys.stderr."""

    _instance: Optional[CaptureManager] = None
    _lock = threading.Lock()

    def __init__(self):
        self.stdout_hook = ThreadAwareStream(sys.__stdout__, "stdout")
        self.stderr_hook = ThreadAwareStream(sys.__stderr__, "stderr")
        self.installed = False

    @classmethod
    def get_instance(cls) -> CaptureManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = CaptureManager()
                cls._instance.install()
            return cls._instance

    def install(self) -> None:
        if not self.installed:
            sys.stdout = self.stdout_hook
            sys.stderr = self.stderr_hook
            self.installed = True

    def register_thread(self, thread_id: int, callback: Callable[[str, str], None]) -> None:
        self.stdout_hook.register(thread_id, callback)
        self.stderr_hook.register(thread_id, callback)

    def unregister_thread(self, thread_id: int) -> None:
        self.stdout_hook.unregister(thread_id)
        self.stderr_hook.unregister(thread_id)


# ============================================================================
# 4. PROGRESS PARSER
# ============================================================================

STEP_REGEX = re.compile(r"(?:[Ss]tep\s*|(?:\d+%\s*\|.*?))(\d+)\s*(?:/|of)\s*(\d+)")
PCT_REGEX = re.compile(r"(\d+(?:\.\d+)?)%")


def parse_progress(text: str) -> Optional[Dict[str, Any]]:
    """Extract step, total, and percent from tqdm or runner step log messages."""
    m = STEP_REGEX.search(text)
    if m:
        step, total = int(m.group(1)), int(m.group(2))
        if 0 <= step <= total and total > 0:
            return {"step": step, "total": total, "percent": round(step / total * 100, 1)}

    m_step = re.search(r"(\d+)\s*/\s*(\d+)", text)
    m_pct = PCT_REGEX.search(text)
    if m_step and m_pct:
        step, total = int(m_step.group(1)), int(m_step.group(2))
        if 0 <= step <= total and total > 0:
            return {"step": step, "total": total, "percent": float(m_pct.group(1))}
    return None


# ============================================================================
# 5. RUN JOB STATE & SSE DISPATCH
# ============================================================================

class RunJob:
    """Encapsulates execution state, log history, and SSE subscriber queues for one run."""

    def __init__(
        self,
        job_id: str,
        config: Config,
        demo_mode: bool,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        target_uuid_hex: Optional[str] = None,
        created_dt: Optional[datetime] = None,
    ):
        self.job_id = job_id
        self.config = config
        self.demo_mode = demo_mode
        self.loop = loop
        self.target_uuid_hex = target_uuid_hex or uuid.uuid4().hex
        self.created_dt = created_dt or datetime.now(timezone.utc)
        self.created_at = self.created_dt.isoformat()
        self.status = "queued"  # queued | running | completed | partial_success | error | interrupted
        self.history: List[Dict[str, Any]] = []
        self.subscribers: Dict[asyncio.Queue, Optional[asyncio.AbstractEventLoop]] = {}
        self.records: List[Dict[str, Any]] = []
        self.primary_run_id: str = job_id
        self.error: Optional[Dict[str, Any]] = None
        self.done_event = threading.Event()
        self.is_done = False
        self._lock = threading.RLock()

    def push_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Thread-safe event broadcast to history and all active SSE subscriber queues."""
        event = {"event": event_type, "data": data}
        with self._lock:
            if len(self.history) < 5000:
                self.history.append(event)
            elif event_type in {"complete", "error", "status"}:
                self.history.append(event)
            subs = list(self.subscribers.items())

        for q, loop in subs:
            if loop and loop.is_running():
                try:
                    loop.call_soon_threadsafe(q.put_nowait, event)
                except Exception:
                    try:
                        q.put_nowait(event)
                    except Exception:
                        pass
            else:
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

    def push_sentinel(self) -> None:
        """Signals end of stream to subscribers and unblocks waiters."""
        self.is_done = True
        self.done_event.set()
        with self._lock:
            subs = list(self.subscribers.items())

        for q, loop in subs:
            if loop and loop.is_running():
                try:
                    loop.call_soon_threadsafe(q.put_nowait, None)
                except Exception:
                    try:
                        q.put_nowait(None)
                    except Exception:
                        pass
            else:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass

    def add_subscriber(
        self, q: asyncio.Queue, loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> None:
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        with self._lock:
            self.subscribers[q] = loop

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        with self._lock:
            self.subscribers.pop(q, None)


# ============================================================================
# 6. RUNNER BRIDGE SINGLETON
# ============================================================================

class RunnerBridge:
    """Coordinates background run execution, event queues, and output serving."""

    def __init__(self, output_dir: str = "outputs"):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: Dict[str, RunJob] = {}
        self.run_id_map: Dict[str, str] = {}  # disk run_id -> job_id
        self.custom_output_dirs: Set[Path] = {self.output_dir}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qwen_worker")
        self.capture_mgr = CaptureManager.get_instance()
        self._lock = threading.RLock()
        self._accepting_jobs = True
        self.pipeline_manager = PipelineManager()

    def runtime_snapshot(self) -> Dict[str, Any]:
        """Describe queued work, resident pipelines, and the latest result."""
        with self._lock:
            unique_jobs = {job.job_id: job for job in self.jobs.values()}
        jobs = sorted(unique_jobs.values(), key=lambda item: item.created_dt, reverse=True)
        active = next((job for job in jobs if job.status in {"queued", "running"}), None)
        completed = next((job for job in jobs if job.records), None)

        active_job = None
        if active is not None:
            active_job = {
                "job_id": active.job_id,
                "status": active.status,
                "demo_mode": bool(active.demo_mode),
                "requested_device": active.config.runtime.device,
                "requested_model": active.config.model.source,
                "requested_lora": active.config.model.lora_path,
                "created_at": active.created_at,
            }

        last_run = None
        if completed is not None and completed.records:
            record = completed.records[-1]
            backend = record.get("backend") or {}
            parameters = record.get("parameters") or {}
            runtime = parameters.get("runtime") or {}
            effective = record.get("effective_parameters") or {}
            last_run = {
                "run_id": record.get("run_id"),
                "status": record.get("status"),
                "model": record.get("model") or {},
                "device": backend.get("device") or runtime.get("device"),
                "lora": effective.get("lora") or backend.get("lora") or {},
                "finished_at": record.get("finished_at"),
            }

        cache = self.pipeline_manager.snapshot()
        return {
            "model_lifecycle": "persistent_per_device",
            "persistent_backend": True,
            "cache": cache,
            "active_job": active_job,
            "last_run": last_run,
            "message": (
                "One compatible production pipeline is retained per device. Configuration "
                "changes apply to the next submitted run and never mutate an active job."
            ),
        }

    def delete_lora_file(self, path: Path) -> None:
        """Remove an idle adapter after releasing any resident pipeline using it.

        The bridge lock excludes new web submissions while the active-job check,
        pipeline teardown, and file removal complete.
        """
        target = path.resolve()
        with self._lock:
            for job in self.jobs.values():
                requested = job.config.model.lora_path
                if (job.status in {"queued", "running"} and requested
                        and Path(requested).expanduser().resolve() == target):
                    raise RuntimeError("LoRA is used by an active or queued inference job")

            for slot in self.pipeline_manager.snapshot()["slots"]:
                loaded = (slot.get("lora") or {}).get("path")
                if loaded and Path(loaded).expanduser().resolve() == target:
                    if slot["active_leases"]:
                        raise RuntimeError("LoRA is used by an active inference pipeline")
                    self.pipeline_manager.unload_device(slot["device"])

            path.unlink()

    def submit_run(
        self,
        config: Config,
        demo_mode: bool = False,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> RunJob:
        """Create and submit a background inference job."""
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

        with self._lock:
            if not self._accepting_jobs:
                raise RuntimeError("The runner is shutting down and is not accepting new jobs")

        now = datetime.now(timezone.utc)
        target_uuid_hex = uuid.UUID(bytes=os.urandom(16)).hex
        session_id = now.strftime("%Y%m%dT%H%M%S") + "_" + target_uuid_hex[:10]
        is_warmup = bool(config.runtime.warmup_runs > 0)
        predicted_run_id = f"{session_id}_{'warmup' if is_warmup else 'run'}_000"

        job = RunJob(
            job_id=predicted_run_id,
            config=config,
            demo_mode=demo_mode,
            loop=loop,
            target_uuid_hex=target_uuid_hex,
            created_dt=now,
        )

        with self._lock:
            if not self._accepting_jobs:
                raise RuntimeError("The runner is shutting down and is not accepting new jobs")
            self.jobs[predicted_run_id] = job
            self.run_id_map[predicted_run_id] = predicted_run_id
            if config.runtime.output_dir:
                od = Path(config.runtime.output_dir).resolve()
                allowed_roots = [
                    self.output_dir.resolve(),
                    Path(__file__).resolve().parent.parent.resolve(),
                    Path(tempfile.gettempdir()).resolve(),
                    Path("/tmp").resolve(),
                ]
                if any(od.is_relative_to(root) for root in allowed_roots):
                    self.custom_output_dirs.add(od)
            self._executor.submit(self._execute_run, job)
        return job

    def _execute_run(self, job: RunJob) -> None:
        tid = threading.get_ident()
        job.status = "running"
        job.push_event("status", {"status": "running", "job_id": job.job_id})

        def on_line_captured(line: str, stream: str) -> None:
            now_iso = datetime.now(timezone.utc).isoformat()
            job.push_event("log", {"text": line, "stream": stream, "timestamp": now_iso})
            prog = parse_progress(line)
            if prog:
                job.push_event("progress", prog)

        self.capture_mgr.register_thread(tid, on_line_captured)

        # Patch runner uuid/datetime so predicted_run_id matches disk output exactly
        orig_uuid4 = qwen_runner.runner.uuid.uuid4
        orig_datetime = qwen_runner.runner.datetime

        class _MockUUID:
            hex = job.target_uuid_hex

        class _MockDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return job.created_dt

        try:
            job.push_event("log", {
                "text": f"Initializing workflow execution for job {job.job_id} (demo_mode={job.demo_mode})...",
                "stream": "stdout",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            total_steps = max(1, job.config.generation.steps)
            job.push_event("progress", {"step": 1, "total": total_steps, "percent": round(100.0 / total_steps, 1)})

            backend_factory = resolve_backend_factory(demo_mode=job.demo_mode)

            qwen_runner.runner.uuid.uuid4 = lambda: _MockUUID()
            qwen_runner.runner.datetime = _MockDateTime

            if job.demo_mode:
                records = qwen_runner.runner.run(job.config, backend_factory=backend_factory)
            else:
                with self.pipeline_manager.acquire(job.config, backend_factory) as lease:
                    records = qwen_runner.runner.run(
                        job.config,
                        backend_factory=lambda _config: _BorrowedBackend(lease.backend),
                    )

            job.records = records

            if records:
                primary = next((r for r in records if r.get("status") == "success"), records[0])
                job.primary_run_id = primary.get("run_id", job.job_id)
                with self._lock:
                    for r in records:
                        rid = r.get("run_id")
                        if rid:
                            self.run_id_map[rid] = job.job_id
                            self.run_id_map[job.job_id] = job.job_id

            complete_payload = self._build_complete_payload(job, records)
            job.status = {
                "success": "completed",
                "partial_success": "partial_success",
                "error": "error",
            }.get(complete_payload["status"], complete_payload["status"])
            job.push_event("complete", complete_payload)

        except BaseException as exc:
            job.status = "error"
            err_record = self._inspect_or_build_error(job, exc)
            job.error = err_record

            job.push_event("log", {
                "text": f"Execution failed with {err_record['type']}: {err_record['message']}",
                "stream": "stderr",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if err_record.get("traceback"):
                job.push_event("log", {
                    "text": err_record["traceback"],
                    "stream": "stderr",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            complete_payload = {
                "status": "error",
                "job_id": job.job_id,
                "run_id": job.primary_run_id or job.job_id,
                "records": job.records,
                "record": job.records[0] if job.records else None,
                "outputs": [],
                "comparison_url": None,
                "error": err_record,
            }
            job.push_event("complete", complete_payload)

        finally:
            qwen_runner.runner.uuid.uuid4 = orig_uuid4
            qwen_runner.runner.datetime = orig_datetime
            sys.stdout.flush()
            sys.stderr.flush()
            self.capture_mgr.unregister_thread(tid)
            job.push_sentinel()

    def shutdown(self) -> None:
        """Drain queued work, release cached pipelines, and reject new jobs."""
        with self._lock:
            if not self._accepting_jobs:
                return
            self._accepting_jobs = False
        self._executor.shutdown(wait=True, cancel_futures=False)
        self.pipeline_manager.shutdown()

    def _build_complete_payload(
        self, job: RunJob, records: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        successful = [r for r in records if r.get("status") == "success"]
        failed = [r for r in records if r.get("status") in {"error", "interrupted"}]
        primary = successful[0] if successful else (records[0] if records else {})
        explicit_batch = (
            job.config.generation.input_images is not None
            or job.config.generation.reference_images is not None
        )
        output_records = [r for r in successful if not r.get("is_warmup")]
        if not explicit_batch:
            output_records = [primary] if primary else []
        outputs = []
        for record in output_records:
            for out in record.get("outputs", []):
                path_str = out.get("path", "")
                filename = Path(path_str).name
                outputs.append({
                    "filename": filename,
                    "url": f"/api/outputs/{filename}",
                    "width": out.get("width"),
                    "height": out.get("height"),
                    "sha256": out.get("sha256"),
                    "path": path_str,
                    "run_id": record.get("run_id"),
                    "input_index": record.get("input_index"),
                })

        comparison_url = None
        if primary.get("comparison"):
            comp_filename = Path(primary["comparison"]).name
            comparison_url = f"/api/outputs/{comp_filename}"

        status = "partial_success" if successful and failed else "success" if successful else "error"
        comparisons = [
            {
                "run_id": record.get("run_id"),
                "input_index": record.get("input_index"),
                "url": f"/api/outputs/{Path(record['comparison']).name}",
            }
            for record in output_records if record.get("comparison")
        ]
        error = None
        if status == "error":
            error = {
                "type": "InputBatchFailed",
                "message": "All input image attempts failed.",
            }
        return {
            "status": status,
            "job_id": job.job_id,
            "run_id": primary.get("run_id", job.job_id),
            "records": records,
            "record": primary,
            "outputs": outputs,
            "comparison_url": comparison_url,
            "comparisons": comparisons,
            "errors": [
                {
                    "run_id": record.get("run_id"),
                    "input_index": record.get("input_index"),
                    "error": record.get("error"),
                }
                for record in failed
            ],
            "error": error,
        }

    def _inspect_or_build_error(self, job: RunJob, exc: BaseException) -> Dict[str, Any]:
        """Inspect output directories for the exact setup error JSON corresponding to this job."""
        out_dirs = [self.output_dir]
        if job.config.runtime.output_dir:
            out_dirs.append(Path(job.config.runtime.output_dir).resolve())

        session_prefix = job.job_id.rsplit("_run_", 1)[0].rsplit("_warmup_", 1)[0]
        expected_name = f"{session_prefix}_setup_error.json"

        for od in out_dirs:
            try:
                if not od.is_dir():
                    continue

                target_file = od / expected_name
                matched_file: Optional[Path] = None
                if target_file.is_file():
                    matched_file = target_file
                else:
                    uuid_prefix = job.target_uuid_hex[:10]
                    for cand in od.glob(f"*{uuid_prefix}*_setup_error.json"):
                        if cand.is_file():
                            matched_file = cand
                            break

                if matched_file and matched_file.is_file():
                    data = json.loads(matched_file.read_text(encoding="utf-8"))
                    err = data.get("error", {})
                    job.primary_run_id = matched_file.stem
                    job.records = [data]
                    with self._lock:
                        self.run_id_map[job.primary_run_id] = job.job_id
                        self.run_id_map[job.job_id] = job.primary_run_id
                        self.jobs[job.primary_run_id] = job
                        self.jobs[job.job_id] = job
                    return {
                        "type": err.get("type", type(exc).__name__),
                        "message": err.get("message", str(exc)),
                        "traceback": err.get("traceback", traceback.format_exc()),
                        "setup_error_json": matched_file.name,
                    }
            except Exception:
                pass

        return {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }

    async def event_generator(self, run_id: str, request: Request) -> AsyncGenerator[str, None]:
        """Stream SSE events for a run with full replay and ping keep-alive."""
        with self._lock:
            job = self.jobs.get(run_id)
            if not job and run_id in self.run_id_map:
                job = self.jobs.get(self.run_id_map[run_id])

        if not job:
            # Check disk for completed historical record
            record = self._load_disk_record(run_id)
            if record:
                complete_data = {
                    "status": record.get("status", "success"),
                    "job_id": run_id,
                    "run_id": record.get("run_id", run_id),
                    "records": [record],
                    "record": record,
                    "outputs": [
                        {
                            "filename": Path(o["path"]).name,
                            "url": f"/api/outputs/{Path(o['path']).name}",
                            "width": o.get("width"),
                            "height": o.get("height"),
                            "sha256": o.get("sha256"),
                            "path": o.get("path"),
                        }
                        for o in record.get("outputs", [])
                    ],
                    "comparison_url": (
                        f"/api/outputs/{Path(record['comparison']).name}"
                        if record.get("comparison")
                        else None
                    ),
                    "error": record.get("error"),
                }
                yield f"event: log\ndata: {json.dumps({'text': f'Replaying finished run {run_id}'})}\n\n"
                yield f"event: progress\ndata: {json.dumps({'step': 1, 'total': 1, 'percent': 100.0})}\n\n"
                yield f"event: complete\ndata: {json.dumps(complete_data)}\n\n"
                return

            yield f"event: error\ndata: {json.dumps({'message': f'Run {run_id} not found'})}\n\n"
            return

        # 1. Replay historical events
        sub_queue: asyncio.Queue = asyncio.Queue()
        try:
            curr_loop = asyncio.get_running_loop()
        except RuntimeError:
            curr_loop = None

        has_completed = False
        with job._lock:
            history_snapshot = list(job.history)
            for item in history_snapshot:
                if item.get("event") == "complete":
                    has_completed = True
            if not has_completed and not job.is_done:
                job.add_subscriber(sub_queue, curr_loop)

        try:
            for item in history_snapshot:
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
                if item.get("event") == "complete":
                    return

            if has_completed:
                return

            # 2. Stream live events
            while True:
                if await request.is_disconnected():
                    break
                if job.is_done and sub_queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(sub_queue.get(), timeout=1.0)
                    if event is None:  # Sentinel
                        break
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
                    if event.get("event") == "complete":
                        break
                except asyncio.TimeoutError:
                    if job.is_done:
                        break
                    yield ": ping\n\n"
        finally:
            job.remove_subscriber(sub_queue)

    def _load_disk_record(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Search registered output directories for {run_id}.json."""
        target_name = run_id if run_id.endswith(".json") else f"{run_id}.json"
        for od in self._get_search_output_dirs():
            candidate = od / target_name
            if candidate.is_file():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return None

    def _get_search_output_dirs(self) -> List[Path]:
        """Aggregate all candidate output directories."""
        dirs: List[Path] = []
        for d in self.custom_output_dirs:
            if d not in dirs:
                dirs.append(d)
        if self.output_dir not in dirs:
            dirs.append(self.output_dir)

        if "OUTPUTS_DIR" in os.environ and os.environ["OUTPUTS_DIR"].strip():
            env_out = Path(os.environ["OUTPUTS_DIR"]).resolve()
            if env_out not in dirs:
                dirs.append(env_out)

        try:
            import ui.server
            s_out = ui.server.get_outputs_dir()
            if s_out and s_out not in dirs:
                dirs.append(s_out)
            state_out = getattr(ui.server.app.state, "outputs_dir", None)
            if state_out:
                p = Path(state_out).resolve()
                if p not in dirs:
                    dirs.append(p)
        except Exception:
            pass

        return dirs

    def list_runs(self) -> List[Dict[str, Any]]:
        """Return list of all runs in current session and on-disk records."""
        runs_dict: Dict[str, Dict[str, Any]] = {}

        # 1. On-disk records
        for od in self._get_search_output_dirs():
            if od.is_dir():
                for p in sorted(od.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                    if p.name.endswith(".tmp") or p.name.endswith(".tmp.json"):
                        continue
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                        rid = data.get("run_id") or p.stem
                        runs_dict[rid] = {
                            "run_id": rid,
                            "job_id": self.run_id_map.get(rid, rid),
                            "status": data.get("status", "completed"),
                            "timestamp": data.get("timestamp"),
                            "is_warmup": data.get("is_warmup", False),
                            "inference_time_seconds": data.get("inference_time_seconds"),
                            "outputs": [
                                {
                                    "filename": Path(o["path"]).name,
                                    "url": f"/api/outputs/{Path(o['path']).name}",
                                    "width": o.get("width"),
                                    "height": o.get("height"),
                                    "sha256": o.get("sha256"),
                                    "path": o.get("path"),
                                }
                                for o in data.get("outputs", [])
                            ],
                            "comparison_url": (
                                f"/api/outputs/{Path(data['comparison']).name}"
                                if data.get("comparison")
                                else None
                            ),
                            "json_url": f"/api/runs/{rid}",
                        }
                    except Exception:
                        pass

        # 2. Overlay in-memory session jobs
        with self._lock:
            active_jobs = list(self.jobs.values())

        for job in active_jobs:
            rid = job.primary_run_id or job.job_id
            primary = job.records[0] if job.records else {}
            runs_dict[rid] = {
                "run_id": rid,
                "job_id": job.job_id,
                "status": job.status,
                "timestamp": job.created_at,
                "is_warmup": primary.get("is_warmup", False),
                "inference_time_seconds": primary.get("inference_time_seconds"),
                "outputs": [
                    {
                        "filename": Path(o["path"]).name,
                        "url": f"/api/outputs/{Path(o['path']).name}",
                        "width": o.get("width"),
                        "height": o.get("height"),
                        "sha256": o.get("sha256"),
                        "path": o.get("path"),
                    }
                    for o in primary.get("outputs", [])
                ],
                "comparison_url": (
                    f"/api/outputs/{Path(primary['comparison']).name}"
                    if primary.get("comparison")
                    else None
                ),
                "json_url": f"/api/runs/{rid}",
            }

        return list(runs_dict.values())

    def get_run_record(self, run_id: str, wait_timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Retrieve full JSON record by run_id or job_id, waiting if job is active."""
        job = None
        with self._lock:
            actual_id = self.run_id_map.get(run_id, run_id)
            job = self.jobs.get(actual_id) or self.jobs.get(run_id)

        if job:
            if not job.is_done and wait_timeout > 0:
                job.done_event.wait(timeout=wait_timeout)
            if job.records:
                for r in job.records:
                    if r.get("run_id") == run_id:
                        return r
                return job.records[0]
            if job.primary_run_id and job.primary_run_id != run_id:
                disk_rec = self._load_disk_record(job.primary_run_id)
                if disk_rec:
                    return disk_rec
            if job.error:
                return {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "error",
                    "error": job.error,
                    "job_id": job.job_id,
                }

        disk_rec = self._load_disk_record(run_id)
        if disk_rec:
            return disk_rec

        # If run_id is a predicted_run_id, check for setup error record on disk
        session_prefix = run_id.rsplit("_run_", 1)[0].rsplit("_warmup_", 1)[0]
        setup_stem = f"{session_prefix}_setup_error"
        setup_rec = self._load_disk_record(setup_stem)
        if setup_rec:
            return setup_rec

        return None

    def get_output_file(self, filename: str) -> Optional[Path]:
        """Safely locate and return output file path, guarding against path traversal."""
        safe_name = Path(filename).name
        for od in self._get_search_output_dirs():
            candidate = (od / safe_name).resolve()
            try:
                if candidate.is_file() and candidate.is_relative_to(od.resolve()):
                    return candidate
            except (ValueError, RuntimeError):
                continue
        return None


# Global singleton instance
_bridge_instance: Optional[RunnerBridge] = None
_bridge_lock = threading.Lock()


def get_runner_bridge() -> RunnerBridge:
    global _bridge_instance
    with _bridge_lock:
        if _bridge_instance is None:
            _bridge_instance = RunnerBridge()
        return _bridge_instance


def shutdown_runner_bridge() -> None:
    """Shutdown and clear the process singleton without creating it."""
    global _bridge_instance
    with _bridge_lock:
        bridge = _bridge_instance
        _bridge_instance = None
    if bridge is not None:
        bridge.shutdown()
