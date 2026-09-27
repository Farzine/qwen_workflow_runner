"""Confined, reference-aware removal of local model catalog entries."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from ui.model_catalog import discover_models


def _within(path: Path, root: Path) -> bool:
    return path.is_relative_to(root) and path.resolve().is_relative_to(root)


def _manifest_records(root: Path) -> list[tuple[Path, dict]]:
    records = []
    directory = root / "manifests"
    if not directory.exists():
        return records
    for path in directory.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Cannot delete model while a manifest is unsafe")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data["load_path"], str) or not isinstance(data["files"], list):
                raise ValueError("Invalid manifest fields")
            for item in data["files"]:
                if not isinstance(item["path"], str):
                    raise ValueError("Invalid manifest file")
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise RuntimeError(f"Cannot safely inspect manifest {path.name}: {error}") from error
        records.append((path, data))
    return records


def _prune_empty(directory: Path, stop: Path) -> None:
    while directory != stop and directory.is_relative_to(stop):
        try:
            directory.rmdir()
        except OSError:
            break
        directory = directory.parent


def delete_model_entry(root: Path, model_id: str) -> dict:
    """Delete one catalog item, preserving files referenced by other manifests.

    Hub content is only removed from the exact snapshot file paths in completed
    manifests. A blob is removed only when no snapshot symlink still points to it.
    """
    root = root.resolve()
    if not isinstance(model_id, str) or not model_id.startswith("model_"):
        raise ValueError("Select a model ID from the catalog")
    entry = next((item for item in discover_models(root) if item["id"] == model_id), None)
    if entry is None:
        raise FileNotFoundError("Model is no longer in the catalog; refresh the list")
    target = Path(entry["path"])
    if not _within(target, root):
        raise RuntimeError("Model path escapes configured storage")

    manifests = _manifest_records(root)
    selected = [(path, data) for path, data in manifests if Path(data["load_path"]).absolute() == target]
    if not selected:
        # Direct uploads and user-provided local models are top-level entries.
        if target.parent != root or target.is_symlink():
            raise RuntimeError("Model is not a removable local catalog entry")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        else:
            raise FileNotFoundError("Model file no longer exists")
        return entry

    hub = root / "hub"
    selected_names = {path for path, _ in selected}
    retained_paths = {Path(item["path"]).absolute() for path, data in manifests
                      if path not in selected_names for item in data["files"]}
    selected_paths = {Path(item["path"]).absolute() for _, data in selected for item in data["files"]}
    for path in selected_paths:
        parts = path.relative_to(hub).parts if path.is_relative_to(hub) else ()
        in_selected_snapshot = (path.is_relative_to(target) if target.is_dir() else path == target)
        if (not _within(path, hub) or len(parts) < 4 or parts[1] != "snapshots"
                or not in_selected_snapshot or not path.is_file()):
            raise RuntimeError("Manifest contains an unsafe or missing Hub snapshot file")
    for path in selected_names:
        if not _within(path, root / "manifests"):
            raise RuntimeError("Manifest path escapes configured storage")

    removable = sorted(selected_paths - retained_paths)
    blob_candidates = {path.resolve() for path in removable if path.is_symlink()}
    for path in selected_names:
        path.unlink()
    for path in removable:
        path.unlink()
        _prune_empty(path.parent, hub)

    # An incomplete or unmanifested download may still point at a shared blob.
    for blob in blob_candidates:
        if not _within(blob, hub) or not blob.is_file():
            continue
        repo_root = next((parent for parent in blob.parents if parent.parent == hub), None)
        if repo_root is None or blob.parent != repo_root / "blobs":
            continue
        snapshots = repo_root / "snapshots"
        still_used = any(path.is_symlink() and path.resolve() == blob
                         for path in snapshots.rglob("*") if path.is_file()) if snapshots.exists() else False
        if not still_used:
            blob.unlink()
            _prune_empty(blob.parent, hub)
    return entry
