"""LoRA deletion is confined and does not invalidate active work."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from qwen_runner.config import Config
from qwen_runner.resources import _PipelineSlot
from ui.runner_bridge import RunnerBridge
from ui.server import app


def test_lora_delete_rejects_active_job_and_unloads_idle_pipeline():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        loras = root / "loras"
        loras.mkdir()
        target = loras / "style.safetensors"
        target.write_bytes(b"placeholder")
        bridge = RunnerBridge(output_dir=str(root / "outputs"))
        app.state.loras_dir = loras
        client = TestClient(app)
        try:
            config = Config()
            config.model.lora_path = str(target)
            bridge.jobs["queued"] = SimpleNamespace(status="queued", config=config)
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                blocked = client.delete("/api/loras/style.safetensors")
                assert blocked.status_code == 409
                assert "queued" in blocked.json()["detail"]
                assert target.exists()

                bridge.jobs.clear()
                backend = SimpleNamespace(metadata={"lora": {"path": str(target)}}, unload=Mock())
                bridge.pipeline_manager._slots["cpu"] = _PipelineSlot(
                    device="cpu", backend=backend, state="ready",
                    model_request={"source": "owner/model"})
                deleted = client.delete("/api/loras/style.safetensors")
                assert deleted.status_code == 200
                assert deleted.json()["deleted"] is True
                assert not target.exists()
                backend.unload.assert_called_once()
                assert bridge.pipeline_manager.snapshot()["slots"][0]["state"] == "empty"
                assert client.delete("/api/loras/style.safetensors").status_code == 404
        finally:
            bridge.shutdown()
            app.state.loras_dir = None


def test_lora_delete_rejects_active_pipeline_symlink_and_traversal():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        loras = root / "loras"
        loras.mkdir()
        target = loras / "style.safetensors"
        target.write_bytes(b"placeholder")
        outside = root / "outside.safetensors"
        outside.write_bytes(b"keep")
        (loras / "link.safetensors").symlink_to(outside)
        bridge = RunnerBridge(output_dir=str(root / "outputs"))
        app.state.loras_dir = loras
        client = TestClient(app)
        try:
            backend = SimpleNamespace(metadata={"lora": {"path": str(target)}}, unload=Mock())
            bridge.pipeline_manager._slots["cpu"] = _PipelineSlot(
                device="cpu", backend=backend, active_leases=1, state="in_use")
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                names = {item["name"] for item in client.get("/api/loras").json()["loras"]}
                assert "link.safetensors" not in names
                assert client.delete("/api/loras/style.safetensors").status_code == 409
                assert target.exists()
                assert client.delete("/api/loras/link.safetensors").status_code == 400
                assert outside.read_bytes() == b"keep"
                assert client.delete("/api/loras/..%5Coutside.safetensors").status_code == 400
                assert client.delete("/api/loras/../outside.safetensors").status_code in {400, 404}
            bridge.pipeline_manager._slots["cpu"].active_leases = 0
        finally:
            bridge.shutdown()
            app.state.loras_dir = None
