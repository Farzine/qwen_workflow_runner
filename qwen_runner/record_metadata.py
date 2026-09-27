"""Versioned, human-readable facts derived from existing run records."""

from __future__ import annotations

from math import gcd
from pathlib import Path

from PIL import Image


def _object(value):
    return value if isinstance(value, dict) else {}


def _file(path, dimensions=None):
    if not isinstance(path, str) or not path:
        return None
    file = Path(path)
    width, height = (dimensions[:2] if isinstance(dimensions, (list, tuple)) and len(dimensions) >= 2
                     else (None, None))
    size = kind = None
    try:
        size = file.stat().st_size
        with Image.open(file) as image:
            width = width or image.width
            height = height or image.height
            kind = image.format
    except (OSError, ValueError, Image.DecompressionBombError):
        pass
    ratio = None
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        divisor = gcd(width, height)
        ratio = f"{width // divisor}:{height // divisor}"
    return {"filename": file.name, "path": str(file), "file_type": kind,
            "width": width, "height": height, "aspect_ratio": ratio, "size_bytes": size}


def summarize_record(record: dict) -> dict:
    """Project both current and legacy success/error records without guessing missing facts."""
    parameters = _object(record.get("parameters"))
    generation = _object(parameters.get("generation"))
    runtime = _object(parameters.get("runtime"))
    model_config = _object(parameters.get("model"))
    effective = _object(record.get("effective_parameters"))
    backend = _object(record.get("backend"))
    model = _object(record.get("model") or backend.get("model"))
    image_meta = effective.get("conditioning_images") or effective.get("reference_images") or []
    image_meta = image_meta if isinstance(image_meta, list) else []
    input_index = record.get("input_index") or 0
    inputs = generation.get("input_images") or []
    legacy_images = generation.get("images") or []
    legacy_images = legacy_images if isinstance(legacy_images, list) else []
    input_path = record.get("input_image") or (inputs[input_index] if isinstance(inputs, list) and
                                                 isinstance(input_index, int) and 0 <= input_index < len(inputs)
                                                 else None) or (legacy_images[0] if legacy_images else None)
    input_meta = next((item for item in image_meta if isinstance(item, dict) and item.get("path") == input_path), {})
    reference_meta = image_meta[1:] if image_meta else []
    reference_paths = generation.get("reference_images")
    if not isinstance(reference_paths, list):
        reference_paths = legacy_images[1:] if isinstance(legacy_images, list) else []
    reference_meta = [item for item in reference_meta if isinstance(item, dict)]
    if not reference_meta:
        reference_meta = [{"path": path} for path in reference_paths]

    source = model.get("repo_id") or model.get("local_path") or model_config.get("source")
    model_name = model.get("repo_id") or (Path(str(source)).name if source else None)
    model_size = model.get("downloaded_selection_bytes")
    if model_size is None and model.get("local_path"):
        try:
            path = Path(model["local_path"])
            model_size = path.stat().st_size if path.is_file() else None
        except OSError:
            pass
    lora_meta = _object(effective.get("lora") or backend.get("lora"))
    lora_path = lora_meta.get("path") or model_config.get("lora_path")
    lora = None
    if lora_path:
        try:
            lora_size = Path(lora_path).stat().st_size
        except OSError:
            lora_size = None
        lora = {"name": Path(lora_path).name, "path": lora_path, "size_bytes": lora_size,
                "applied": lora_meta.get("applied"), "scale": lora_meta.get("scale", model_config.get("lora_scale"))}

    peak = _object(record.get("peak_memory_usage")).get("gpu_peak_allocated_bytes")
    outputs = [item for item in (record.get("outputs") or []) if isinstance(item, dict)]
    error = _object(record.get("error"))
    return {
        "summary_version": 1,
        "run_id": record.get("run_id"), "status": record.get("status"),
        "timestamp": record.get("timestamp"), "finished_at": record.get("finished_at"),
        "input": _file(input_path, input_meta.get("original_size")),
        "references": [_file(item.get("path"), item.get("original_size")) for item in reference_meta
                       if isinstance(item, dict) and item.get("path")],
        "model": {"name": model_name, "source": source, "size_bytes": model_size,
                  "parameters_billion": model.get("parameters_billion")},
        "lora": lora,
        "generation": {"duration_seconds": record.get("inference_time_seconds"),
                       "wall_seconds": record.get("run_wall_seconds_including_output_save"),
                       "steps": generation.get("steps"), "guidance_scale": generation.get("cfg"),
                       "seed": generation.get("seed"), "width": effective.get("width"),
                       "height": effective.get("height"),
                       "requested_width": generation.get("width") if generation.get("custom_size") else None,
                       "requested_height": generation.get("height") if generation.get("custom_size") else None,
                       "device": backend.get("device") or runtime.get("device"),
                       "pipeline": backend.get("pipeline"), "peak_gpu_allocated_bytes": peak},
        "outputs": [_file(item.get("path"), [item.get("width"), item.get("height")])
                    for item in outputs if item.get("path")],
        "error": {"type": error.get("type"), "message": error.get("message")} if error else None,
    }
