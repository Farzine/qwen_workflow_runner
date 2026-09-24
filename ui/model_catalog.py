"""Local model inventory and conservative Qwen Image 2.1 compatibility checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _identity(path: Path) -> str:
    return "model_" + hashlib.sha256(str(path.absolute()).encode()).hexdigest()[:20]


def _inspect_directory(path: Path) -> tuple[bool, str | None]:
    try:
        index = json.loads((path / "model_index.json").read_text(encoding="utf-8"))
        if index.get("_class_name") != "QwenImage21Pipeline":
            return False, "This workflow requires QwenImage21Pipeline."
        missing = [name for name in ("transformer", "text_encoder", "processor", "vae") if not (path / name).is_dir()]
        if missing:
            return False, "Missing pipeline components: " + ", ".join(missing)
        transformer_config = path / "transformer" / "config.json"
        if not transformer_config.is_file():
            return False, "Missing transformer configuration."
        for component in ("transformer", "text_encoder", "vae"):
            if not any((path / component).glob("*.safetensors")) and not any((path / component).glob("*.bin")):
                if not any((path / component).glob("*.safetensors.index.json")):
                    return False, f"Missing {component} weight files."
        transformer = json.loads(transformer_config.read_text(encoding="utf-8"))
        if transformer.get("quantization_config"):
            return False, "This quantized Diffusers transformer requires a loader unavailable in this workflow."
        return True, None
    except (OSError, ValueError, KeyError) as error:
        return False, f"Cannot inspect pipeline metadata: {error}"


def _inspect_transformer_file(path: Path) -> tuple[bool, str | None]:
    try:
        size = path.stat().st_size
    except OSError as error:
        return False, f"Cannot inspect model file: {error}"
    if size < 1024 * 1024:
        return False, "Model file is too small to contain Qwen Image 2.1 transformer weights."
    if path.suffix.lower() == ".gguf":
        try:
            with path.open("rb") as handle:
                if handle.read(4) != b"GGUF":
                    return False, "Invalid GGUF file header."
            import gguf
            reader = gguf.GGUFReader(str(path))
            architecture = reader.get_field("general.architecture")
            if architecture is None or architecture.contents() != "qwen_image21":
                return False, "GGUF architecture is not qwen_image21."
            if len(reader.tensors) < 100:
                return False, "GGUF does not contain a complete Qwen Image 2.1 transformer."
        except Exception as error:
            return False, f"Invalid GGUF checkpoint: {error}"
        return True, None  # Exact names and shapes are checked by the loader.
    if path.suffix.lower() != ".safetensors":
        return False, "Unsupported single-file checkpoint format."
    if "convrot" in path.name.lower():
        return False, "Comfy int8_convrot checkpoints are unsupported."
    try:
        from safetensors import safe_open
        with safe_open(str(path), framework="pt", device="cpu") as handle:
            keys = handle.keys()
            if not any("transformer_blocks." in key for key in keys):
                return False, "No Qwen Image transformer block tensors were found."
    except Exception as error:
        return False, f"Invalid SafeTensors checkpoint: {error}"
    return True, None


def discover_models(root: Path) -> list[dict]:
    """Inventory only configured local storage, without loading model tensors."""
    root = root.resolve()
    candidates: dict[Path, dict] = {}
    if root.is_dir():
        for path in sorted(root.iterdir()):
            if path.name.startswith(".") or path.name in {"manifests", "hub", "loras"}:
                continue
            if path.is_file() and path.suffix.lower() in {".gguf", ".safetensors", ".bin"}:
                kind = "gguf" if path.suffix.lower() == ".gguf" else path.suffix.lower()[1:]
                candidates[path.resolve()] = {"name": path.name, "repo_id": None, "type": kind,
                                              "filename": path.name, "size": path.stat().st_size}
            elif path.is_dir() and (path / "model_index.json").is_file():
                candidates[path.resolve()] = {"name": path.name, "repo_id": None, "type": "diffusers",
                                              "filename": None, "size": None}

    manifests = root / "manifests"
    if manifests.is_dir():
        for manifest in sorted(manifests.glob("*.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                path = Path(data["load_path"]).absolute()
                if not path.resolve().is_relative_to(root) or not path.exists():
                    continue
                files = data.get("files", [])
                if not files or not all(
                    Path(item["path"]).is_file() and Path(item["path"]).stat().st_size == item["size"] > 0
                    and Path(item["path"]).resolve().is_relative_to(root)
                    for item in files
                ):
                    continue
                meta = data.get("metadata", {})
                entry = {"name": meta.get("repo_id") or path.name, "repo_id": meta.get("repo_id"),
                         "type": meta.get("format", "hub"), "filename": meta.get("filename"),
                         "size": meta.get("downloaded_selection_bytes"),
                         "revision": meta.get("resolved_revision"),
                         "requested_revision": meta.get("requested_revision")}
                prior = candidates.get(path)
                if prior is None or (entry["size"] or 0) > (prior.get("size") or 0):
                    candidates[path] = entry
            except (OSError, ValueError, KeyError, TypeError):
                continue

    complete = {path: _inspect_directory(path) for path, entry in candidates.items()
                if path.is_dir() and entry["type"] == "diffusers"}
    companions = [path for path, (supported, _) in complete.items() if supported]
    result = []
    for path, entry in sorted(candidates.items(), key=lambda pair: (pair[1]["name"].lower(), str(pair[0]))):
        kind = entry["type"]
        companion = None
        if kind == "diffusers":
            compatible, reason = complete[path]
        elif kind in {"gguf", "safetensors", "single_file"}:
            compatible, reason = _inspect_transformer_file(path)
            if compatible and len(companions) != 1:
                compatible, reason = False, "A single-file transformer requires exactly one compatible local Qwen Image 2.1 companion pipeline."
            elif compatible:
                companion = str(companions[0])
        else:
            compatible, reason = False, "Unsupported model format."
        result.append({**entry, "id": _identity(path), "path": str(path), "is_cached": True,
                       "compatible": compatible, "compatibility_reason": reason,
                       "companion_path": companion})
    return result


def resolve_selected_model(root: Path, model_id: str) -> dict:
    if not isinstance(model_id, str) or not model_id.startswith("model_"):
        raise ValueError("Select a downloaded model from the catalog")
    entry = next((item for item in discover_models(root) if item["id"] == model_id), None)
    if entry is None:
        raise ValueError("Selected model is no longer available; refresh the model catalog")
    if not entry["compatible"]:
        raise ValueError(f"Selected model is incompatible: {entry['compatibility_reason']}")
    return entry
