"""Runtime capability inspection shared by the API and future system UI."""

from __future__ import annotations

import platform
import sys
import warnings
from typing import Any


SUPPORTED_DTYPES = {"bfloat16", "float16", "float32"}
SUPPORTED_OFFLOAD_MODES = {"none", "model", "sequential"}


def _unavailable_report(device: str, dtype: str, offload: str, message: str) -> dict[str, Any]:
    selected = {
        "id": device,
        "type": "unknown",
        "name": device,
        "available": False,
        "ready": False,
        "message": message,
    }
    return {
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "platform": platform.platform(),
        "torch": {"version": None, "cuda_runtime": None},
        "cuda": {"available": False, "device_count": 0, "devices": [], "diagnostics": []},
        "mps": {"available": False},
        "devices": [{"id": "cpu", "type": "cpu", "name": "CPU", "available": True}],
        "selected_device": selected,
        "requested": {"device": device, "dtype": dtype, "offload": offload},
        "production_backend": {"name": "QwenBackend", "ready": False, "message": message},
    }


def probe_runtime_capabilities(
    device: str = "cuda:0",
    dtype: str = "bfloat16",
    offload: str = "model",
    *,
    torch_module: Any = None,
) -> dict[str, Any]:
    """Return JSON-safe runtime and selected-device readiness information.

    Importing and probing PyTorch is intentionally contained here so callers can
    report driver/runtime failures without loading model weights. ``torch_module``
    exists to keep the probe independently testable.
    """

    try:
        torch = torch_module
        if torch is None:
            import torch as imported_torch

            torch = imported_torch
    except Exception as error:
        return _unavailable_report(
            device,
            dtype,
            offload,
            f"PyTorch could not be imported: {type(error).__name__}: {error}",
        )

    diagnostics: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cuda_available = bool(torch.cuda.is_available())
            cuda_count = int(torch.cuda.device_count()) if cuda_available else 0
        diagnostics.extend(str(item.message) for item in caught)
    except Exception as error:
        cuda_available = False
        cuda_count = 0
        diagnostics.append(f"CUDA probe failed: {type(error).__name__}: {error}")

    cuda_devices: list[dict[str, Any]] = []
    if cuda_available:
        for index in range(cuda_count):
            try:
                props = torch.cuda.get_device_properties(index)
                cuda_devices.append(
                    {
                        "id": f"cuda:{index}",
                        "type": "cuda",
                        "index": index,
                        "name": props.name,
                        "total_memory_bytes": int(props.total_memory),
                        "compute_capability": f"{props.major}.{props.minor}",
                        "available": True,
                    }
                )
            except Exception as error:
                diagnostics.append(
                    f"Could not inspect cuda:{index}: {type(error).__name__}: {error}"
                )

    try:
        mps_available = bool(
            hasattr(torch, "backends")
            and hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        )
    except Exception as error:
        mps_available = False
        diagnostics.append(f"MPS probe failed: {type(error).__name__}: {error}")

    devices: list[dict[str, Any]] = [
        {"id": "cpu", "type": "cpu", "name": "CPU", "available": True}
    ]
    devices.extend(cuda_devices)
    if mps_available:
        devices.append({"id": "mps", "type": "mps", "name": "Apple MPS", "available": True})

    selected_type = "unknown"
    selected_name = device
    selected_available = False
    message = ""

    try:
        parsed_device = torch.device(device)
        selected_type = parsed_device.type
    except Exception as error:
        message = f"Invalid device '{device}': {error}"
    else:
        if dtype not in SUPPORTED_DTYPES:
            message = f"Unsupported dtype '{dtype}'. Choose bfloat16, float16, or float32."
        elif offload not in SUPPORTED_OFFLOAD_MODES:
            message = f"Unsupported offload mode '{offload}'. Choose none, model, or sequential."
        elif selected_type == "cpu":
            selected_name = "CPU"
            selected_available = True
            if dtype != "float32" or offload != "none":
                message = "CPU inference requires dtype=float32 and offload=none."
            else:
                message = "CPU is available; full Qwen Image inference may be extremely slow and memory intensive."
        elif selected_type == "cuda":
            index = parsed_device.index if parsed_device.index is not None else 0
            selected_name = f"CUDA GPU {index}"
            if not cuda_available:
                message = (
                    f"CUDA is unavailable to PyTorch for cuda:{index}. Install a PyTorch build "
                    "compatible with the NVIDIA driver, or update the driver."
                )
            elif index < 0 or index >= cuda_count:
                message = f"cuda:{index} was requested, but only {cuda_count} CUDA device(s) are available."
            else:
                selected_available = True
                match = next((item for item in cuda_devices if item["index"] == index), None)
                if match:
                    selected_name = match["name"]
                if dtype == "bfloat16":
                    try:
                        if not torch.cuda.is_bf16_supported():
                            message = f"{device} does not support bfloat16; choose float16 or float32."
                    except Exception as error:
                        message = f"Could not verify bfloat16 support on {device}: {error}"
                if not message:
                    message = f"{device} is available for production inference."
        elif selected_type == "mps":
            selected_name = "Apple MPS"
            selected_available = mps_available
            if not mps_available:
                message = "MPS is unavailable on this machine."
            elif offload != "none":
                message = "MPS inference requires offload=none."
            else:
                message = "MPS is available; Qwen operator coverage remains environment dependent."
        else:
            message = f"Device type '{selected_type}' is not supported by this runner."

    ready = bool(selected_available and not (
        (selected_type == "cpu" and (dtype != "float32" or offload != "none"))
        or (selected_type == "mps" and offload != "none")
        or (selected_type == "cuda" and message and "available for production" not in message)
    ))

    selected = {
        "id": device,
        "type": selected_type,
        "name": selected_name,
        "available": selected_available,
        "ready": ready,
        "message": message,
    }

    return {
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "platform": platform.platform(),
        "torch": {
            "version": str(getattr(torch, "__version__", "unknown")),
            "cuda_runtime": getattr(getattr(torch, "version", None), "cuda", None),
        },
        "cuda": {
            "available": cuda_available,
            "device_count": cuda_count,
            "devices": cuda_devices,
            "diagnostics": diagnostics,
        },
        "mps": {"available": mps_available},
        "devices": devices,
        "selected_device": selected,
        "requested": {"device": device, "dtype": dtype, "offload": offload},
        "production_backend": {"name": "QwenBackend", "ready": ready, "message": message},
    }
