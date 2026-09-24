"""Thread-safe ownership and lifecycle management for heavyweight pipelines."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import gc
import threading
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _factory_name(factory: Callable[..., Any]) -> str:
    module = getattr(factory, "__module__", type(factory).__module__)
    name = getattr(factory, "__qualname__", type(factory).__qualname__)
    return f"{module}.{name}"


def normalize_device_id(device: Any) -> str:
    """Collapse aliases that address the same physical cache slot."""
    value = str(device).strip().lower()
    return "cuda:0" if value == "cuda" else value


def pipeline_compatibility_key(config: Any, factory: Callable[..., Any]) -> tuple[Any, ...]:
    """Return fields that require rebuilding or moving a loaded pipeline."""
    model = config.model
    runtime = config.runtime
    return (
        _factory_name(factory),
        model.source,
        model.revision,
        model.filename,
        model.gguf_quantization,
        model.base_model,
        model.base_revision,
        model.text_encoder_source,
        str(model.cache_dir),
        normalize_device_id(runtime.device),
        runtime.dtype,
        runtime.offload,
        bool(runtime.vae_tiling),
    )


@dataclass
class _PipelineSlot:
    device: str
    backend: Any | None = None
    key: tuple[Any, ...] | None = None
    active_leases: int = 0
    state: str = "empty"
    load_count: int = 0
    reuse_count: int = 0
    loaded_at: str | None = None
    last_used_at: str | None = None
    last_error: str | None = None
    model_request: dict[str, Any] = field(default_factory=dict)


class PipelineLease:
    """Exclusive access to one cached backend for the duration of a job."""

    def __init__(self, manager: "PipelineManager", device: str, backend: Any, reused: bool):
        self._manager = manager
        self.device = device
        self.backend = backend
        self.reused = reused
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._manager._release(self.device)

    def __enter__(self) -> "PipelineLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class PipelineManager:
    """Keep at most one compatible production pipeline loaded per device.

    A lease is exclusive and spans a complete job. This makes model and LoRA
    replacement safe even if the runner later gains more worker threads.
    """

    def __init__(self):
        self._condition = threading.Condition(threading.RLock())
        self._slots: dict[str, _PipelineSlot] = {}
        self._accepting = True

    def acquire(self, config: Any, factory: Callable[[Any], Any]) -> PipelineLease:
        device = normalize_device_id(config.runtime.device)
        key = pipeline_compatibility_key(config, factory)
        with self._condition:
            if not self._accepting:
                raise RuntimeError("Pipeline manager is shutting down and cannot accept new jobs")
            slot = self._slots.setdefault(device, _PipelineSlot(device=device))
            while slot.active_leases:
                self._condition.wait()
                if not self._accepting:
                    raise RuntimeError("Pipeline manager is shutting down and cannot accept new jobs")
            slot.active_leases = 1
            slot.state = "preparing"
            slot.last_error = None

        reused = slot.backend is not None and slot.key == key
        try:
            if reused:
                backend = slot.backend
                prepare = getattr(backend, "prepare_for_config", None)
                if callable(prepare):
                    prepare(config)
                else:
                    backend.config = config
            else:
                old_backend = slot.backend
                with self._condition:
                    slot.backend = None
                    slot.key = None
                if old_backend is not None:
                    self._unload_backend(old_backend, device)
                backend = factory(config).load()

            with self._condition:
                slot.backend = backend
                slot.key = key
                if reused:
                    slot.reuse_count += 1
                else:
                    slot.load_count += 1
                    slot.loaded_at = _now()
                slot.last_used_at = _now()
                slot.model_request = {
                    "source": config.model.source,
                    "revision": config.model.revision,
                    "filename": config.model.filename,
                }
                slot.state = "in_use"
                cache_metadata = {
                    "device": device,
                    "reused": reused,
                    "load_count": slot.load_count,
                    "reuse_count": slot.reuse_count,
                    "loaded_at": slot.loaded_at,
                }
            if hasattr(backend, "metadata"):
                backend.metadata["resource_cache"] = cache_metadata
            return PipelineLease(self, device, backend, reused)
        except BaseException as error:
            with self._condition:
                slot.active_leases = 0
                slot.state = "error"
                slot.last_error = f"{type(error).__name__}: {error}"
                self._condition.notify_all()
            raise

    def _release(self, device: str) -> None:
        with self._condition:
            slot = self._slots.get(device)
            if slot is None or slot.active_leases == 0:
                return
            slot.active_leases = 0
            slot.state = "ready" if slot.backend is not None else "empty"
            slot.last_used_at = _now()
            self._condition.notify_all()

    @staticmethod
    def _unload_backend(backend: Any, device: str) -> None:
        unload_error = None
        unload = getattr(backend, "unload", None)
        try:
            if callable(unload):
                unload()
        except BaseException as error:
            unload_error = error
        finally:
            del backend
            gc.collect()
            if device.startswith("cuda"):
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.synchronize(device)
                        torch.cuda.empty_cache()
                        if hasattr(torch.cuda, "ipc_collect"):
                            torch.cuda.ipc_collect()
                except Exception:
                    # CUDA may already be unavailable during process teardown.
                    pass
        if unload_error is not None:
            raise unload_error

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            slots = []
            for device, slot in sorted(self._slots.items()):
                backend_metadata = deepcopy(getattr(slot.backend, "metadata", {})) if slot.backend else {}
                slots.append({
                    "device": device,
                    "state": slot.state,
                    "active_leases": slot.active_leases,
                    "model": deepcopy(slot.model_request),
                    "lora": backend_metadata.get("lora", {}),
                    "pipeline": backend_metadata.get("pipeline"),
                    "load_count": slot.load_count,
                    "reuse_count": slot.reuse_count,
                    "loaded_at": slot.loaded_at,
                    "last_used_at": slot.last_used_at,
                    "last_error": slot.last_error,
                })
            return {
                "accepting_jobs": self._accepting,
                "policy": "one_pipeline_per_device",
                "slots": slots,
            }

    def unload_device(self, device: str) -> bool:
        normalized_device = normalize_device_id(device)
        with self._condition:
            slot = self._slots.get(normalized_device)
            if slot is None:
                return False
            if slot.active_leases:
                raise RuntimeError(f"Cannot unload {normalized_device}: a pipeline lease is active")
            backend = slot.backend
            slot.backend = None
            slot.key = None
            slot.state = "empty"
            slot.model_request = {}
        if backend is not None:
            self._unload_backend(backend, normalized_device)
        return backend is not None

    def shutdown(self) -> None:
        with self._condition:
            self._accepting = False
            while any(slot.active_leases for slot in self._slots.values()):
                self._condition.wait()
            pending = [(device, slot.backend) for device, slot in self._slots.items() if slot.backend]
            for slot in self._slots.values():
                slot.backend = None
                slot.key = None
                slot.state = "empty"
                slot.model_request = {}
        for device, backend in pending:
            try:
                self._unload_backend(backend, device)
            except BaseException as error:
                with self._condition:
                    slot = self._slots[device]
                    slot.state = "error"
                    slot.last_error = f"{type(error).__name__}: {error}"
