"""Finished run deletion keeps shared files and rejects unsafe or active work."""

import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from qwen_runner.config import Config
from ui.runner_bridge import RunJob, RunnerBridge
from ui.server import app


def _record(root: Path, run_id: str, outputs=(), comparison=None):
    record = {"run_id": run_id, "status": "success", "outputs":
              [{"path": str(path)} for path in outputs]}
    if comparison:
        record["comparison"] = str(comparison)
    (root / f"{run_id}.json").write_text(json.dumps(record))
    return record


def test_delete_run_preserves_shared_output_and_evicts_completed_job():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shared, own, comparison = (root / name for name in ("shared.png", "own.png", "comparison.png"))
        for path in (shared, own, comparison):
            path.write_bytes(b"image")
        first = _record(root, "first_run", [shared, own], comparison)
        _record(root, "second_run", [shared])
        bridge = RunnerBridge(output_dir=str(root))
        job = RunJob("first_run", Config(), demo_mode=True)
        job.status = "completed"
        job.is_done = True
        job.records = [first, {"run_id": "second_run", "outputs": [{"path": str(shared)}]}]
        bridge.jobs[job.job_id] = job
        bridge.run_id_map["second_run"] = job.job_id
        app.state.outputs_dir = root
        client = TestClient(app)
        try:
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                response = client.delete("/api/runs/first_run")
                assert response.status_code == 200, response.text
                assert response.json()["deleted_artifacts"] == 2
                assert response.json()["preserved_shared_artifacts"] == 1
                assert shared.exists() and not own.exists() and not comparison.exists()
                assert not (root / "first_run.json").exists()
                assert bridge.jobs == {} and bridge.run_id_map == {}
                assert client.get("/api/runs/first_run").status_code == 404
                assert client.get("/api/runs/second_run").status_code == 200
                ids = {item["run_id"] for item in client.get("/api/runs").json()["runs"]}
                assert ids == {"second_run"}
        finally:
            bridge.shutdown()
            app.state.outputs_dir = None


def test_delete_run_blocks_active_work_and_unsafe_paths():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        # Keep the external target within the temporary tree, outside output storage.
        outputs = root / "outputs"
        outputs.mkdir()
        outside = root / "outside.png"
        outside.write_bytes(b"keep")
        _record(outputs, "unsafe_run", [outside])
        missing = outputs / "missing.png"
        _record(outputs, "missing_run", [missing])
        bridge = RunnerBridge(output_dir=str(outputs))
        job = RunJob("active_run", Config(), demo_mode=True)
        bridge.jobs[job.job_id] = job
        app.state.outputs_dir = outputs
        client = TestClient(app)
        try:
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                assert client.delete("/api/runs/missing_run").status_code == 409
                bridge.jobs.clear()
                assert client.delete("/api/runs/unsafe_run").status_code == 409
                assert outside.read_bytes() == b"keep"
                assert (outputs / "unsafe_run.json").exists()
                assert client.delete("/api/runs/..%5Coutside").status_code == 400
                assert client.delete("/api/runs/unknown_run").status_code == 404
                deleted = client.delete("/api/runs/missing_run")
                assert deleted.status_code == 200
                assert deleted.json()["deleted_artifacts"] == 0
                assert not (outputs / "missing_run.json").exists()
        finally:
            bridge.shutdown()
            app.state.outputs_dir = None


def test_delete_run_rejects_linked_record_and_artifact():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        outputs = root / "outputs"
        outputs.mkdir()
        outside = root / "outside.png"
        outside.write_bytes(b"keep")
        linked = outputs / "linked.png"
        linked.symlink_to(outside)
        _record(outputs, "linked_artifact", [linked])
        (outputs / "linked_record.json").symlink_to(outputs / "linked_artifact.json")
        bridge = RunnerBridge(output_dir=str(outputs))
        app.state.outputs_dir = outputs
        client = TestClient(app)
        try:
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                assert client.delete("/api/runs/linked_artifact").status_code == 409
                assert client.delete("/api/runs/linked_record").status_code == 409
                assert outside.read_bytes() == b"keep"
        finally:
            bridge.shutdown()
            app.state.outputs_dir = None


def test_delete_run_handles_registered_custom_directory_and_duplicate_ids():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        default = root / "default"
        custom = root / "custom"
        default.mkdir()
        custom.mkdir()
        output = custom / "custom.png"
        output.write_bytes(b"image")
        _record(custom, "custom_run", [output])
        _record(default, "duplicate_run")
        _record(custom, "duplicate_run")
        bridge = RunnerBridge(output_dir=str(default))
        bridge.custom_output_dirs.add(custom)
        app.state.outputs_dir = default
        client = TestClient(app)
        try:
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                assert client.delete("/api/runs/duplicate_run").status_code == 409
                response = client.delete("/api/runs/custom_run")
                assert response.status_code == 200, response.text
                assert not output.exists() and not (custom / "custom_run.json").exists()
                assert (default / "duplicate_run.json").exists()
                assert (custom / "duplicate_run.json").exists()
        finally:
            bridge.shutdown()
            app.state.outputs_dir = None
