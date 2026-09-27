"""Model deletion uses catalog IDs and preserves shared Hub cache content."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import pytest

from qwen_runner.config import Config
from qwen_runner.resources import _PipelineSlot
from ui.model_catalog import discover_models
from ui.runner_bridge import RunnerBridge
from ui.server import app, download_tasks, download_tasks_lock


def _manifest(root: Path, name: str, load_path: Path, files: list[Path]) -> None:
    directory = root / "manifests"
    directory.mkdir(exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps({
        "load_path": str(load_path),
        "files": [{"path": str(path), "size": path.stat().st_size, "filename": path.name} for path in files],
        "metadata": {"repo_id": "owner/repo", "format": "gguf", "filename": load_path.name,
                     "resolved_revision": name, "downloaded_selection_bytes": sum(p.stat().st_size for p in files)},
    }))


def test_direct_model_delete_blocks_active_use_and_unloads_idle_pipeline():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "model.safetensors"
        target.write_bytes(b"placeholder")
        entry = discover_models(root)[0]
        bridge = RunnerBridge(output_dir=str(root / "outputs"))
        app.state.models_dir = root
        client = TestClient(app)
        try:
            config = Config()
            config.model.selected_model_id = entry["id"]
            bridge.jobs["queued"] = SimpleNamespace(status="queued", config=config)
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                assert client.delete(f"/api/models/catalog/{entry['id']}").status_code == 409
                assert target.exists()
                config.model.selected_model_id = None
                config.model.source = "other/model"
                config.model.base_model = str(target)
                assert client.delete(f"/api/models/catalog/{entry['id']}").status_code == 409
                bridge.jobs.clear()
                backend = SimpleNamespace(metadata={}, unload=Mock())
                bridge.pipeline_manager._slots["cpu"] = _PipelineSlot(
                    device="cpu", backend=backend, state="ready", model_request={"base_model": str(target)})
                response = client.delete(f"/api/models/catalog/{entry['id']}")
                assert response.status_code == 200, response.text
                assert not target.exists()
                backend.unload.assert_called_once()
                assert client.delete(f"/api/models/catalog/{entry['id']}").status_code == 404
                config.model.selected_model_id = entry["id"]
                config.model.cache_dir = str(root)
                with pytest.raises(ValueError, match="no longer available"):
                    bridge.submit_run(config)
        finally:
            bridge.shutdown()
            app.state.models_dir = None


def test_hub_model_delete_preserves_shared_blob_and_other_selection():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        hub_repo = root / "hub" / "models--owner--repo"
        blob = hub_repo / "blobs" / "shared"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"GGUFshared")
        first = hub_repo / "snapshots" / "rev1" / "first.gguf"
        second = hub_repo / "snapshots" / "rev2" / "second.gguf"
        for path in (first, second):
            path.parent.mkdir(parents=True)
            path.symlink_to(blob)
        _manifest(root, "first", first, [first])
        _manifest(root, "second", second, [second])
        entry = next(item for item in discover_models(root) if item["path"] == str(first))
        bridge = RunnerBridge(output_dir=str(root / "outputs"))
        app.state.models_dir = root
        client = TestClient(app)
        try:
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                response = client.delete(f"/api/models/catalog/{entry['id']}")
                assert response.status_code == 200, response.text
                assert not first.exists()
                assert not (root / "manifests" / "first.json").exists()
                assert second.is_file() and blob.is_file()
                assert (root / "manifests" / "second.json").exists()
                other = next(item for item in discover_models(root) if item["path"] == str(second))
                assert client.delete(f"/api/models/catalog/{other['id']}").status_code == 200
                assert not blob.exists()
        finally:
            bridge.shutdown()
            app.state.models_dir = None


def test_delete_rejects_active_download_pipeline_and_unknown_id():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        model = root / "model.safetensors"
        model.write_bytes(b"placeholder")
        entry = discover_models(root)[0]
        bridge = RunnerBridge(output_dir=str(root / "outputs"))
        app.state.models_dir = root
        client = TestClient(app)
        try:
            backend = SimpleNamespace(metadata={}, unload=Mock())
            bridge.pipeline_manager._slots["cpu"] = _PipelineSlot(
                device="cpu", backend=backend, state="in_use", active_leases=1,
                model_request={"source": str(model)})
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                assert client.delete(f"/api/models/catalog/{entry['id']}").status_code == 409
                assert model.exists()
                assert client.delete("/api/models/catalog/model_unknown").status_code == 400
                assert client.delete("/api/models/catalog/model_" + "0" * 20).status_code == 404
            bridge.pipeline_manager._slots["cpu"].active_leases = 0
            symlink = root / "link.safetensors"
            symlink.symlink_to(model)
            assert all(item["path"] != str(symlink) for item in discover_models(root))
        finally:
            bridge.shutdown()
            app.state.models_dir = None


def test_hub_delete_rejects_matching_active_download():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        snapshot = root / "hub" / "models--owner--repo" / "snapshots" / "rev1" / "one.gguf"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_bytes(b"GGUFfile")
        _manifest(root, "first", snapshot, [snapshot])
        entry = discover_models(root)[0]
        bridge = RunnerBridge(output_dir=str(root / "outputs"))
        app.state.models_dir = root
        job = SimpleNamespace(data={"repo_id": "owner/repo"}, snapshot=lambda: {"status": "downloading"})
        client = TestClient(app)
        try:
            with download_tasks_lock:
                download_tasks["test_deletion"] = job
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                response = client.delete(f"/api/models/catalog/{entry['id']}")
                assert response.status_code == 409
                assert snapshot.exists()
        finally:
            with download_tasks_lock:
                download_tasks.pop("test_deletion", None)
            bridge.shutdown()
            app.state.models_dir = None


def test_direct_pipeline_directory_delete_is_confined_to_selected_entry():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        pipeline = root / "old_pipeline"
        pipeline.mkdir()
        (pipeline / "model_index.json").write_text('{"_class_name":"QwenImage21Pipeline"}')
        (pipeline / "weights.bin").write_bytes(b"placeholder")
        keep = root / "keep.safetensors"
        keep.write_bytes(b"keep")
        entry = next(item for item in discover_models(root) if item["path"] == str(pipeline))
        bridge = RunnerBridge(output_dir=str(root / "outputs"))
        app.state.models_dir = root
        client = TestClient(app)
        try:
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                response = client.delete(f"/api/models/catalog/{entry['id']}")
                assert response.status_code == 200, response.text
                assert not pipeline.exists()
                assert keep.read_bytes() == b"keep"
        finally:
            bridge.shutdown()
            app.state.models_dir = None
