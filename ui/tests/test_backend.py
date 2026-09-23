"""ui/tests/test_backend.py

Unit and integration tests for RunnerBridge and backend API endpoints.
Verifies SSE stream termination, thread-safe dispatch, demo execution,
and error handling.
"""

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from qwen_runner.config import Config, GenerationConfig, ModelConfig, RuntimeConfig
from qwen_runner.backend import QwenBackend
from ui.runner_bridge import RunnerBridge, RunJob, resolve_backend_factory, DemoBackend
from ui.server import app


class TestBackendRunnerBridge(unittest.TestCase):
    """Test background runner bridge execution, SSE dispatch, and stream termination."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.outputs_dir = self.root / "outputs"
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        app.state.outputs_dir = self.outputs_dir
        os.environ["OUTPUTS_DIR"] = str(self.outputs_dir)
        self.bridge = RunnerBridge(output_dir=str(self.outputs_dir))
        self.client = TestClient(app)

    def tearDown(self):
        app.state.outputs_dir = None
        os.environ.pop("OUTPUTS_DIR", None)
        self.temp_dir.cleanup()

    def test_resolve_backend_factory_demo_mode(self):
        backend_cls = resolve_backend_factory(demo_mode=True)
        self.assertIs(backend_cls, DemoBackend)

    def test_resolve_backend_factory_real_mode_never_falls_back(self):
        with patch("ui.runner_bridge.torch.cuda.is_available", return_value=False):
            backend_cls = resolve_backend_factory(demo_mode=False)
        self.assertIs(backend_cls, QwenBackend)

    def test_system_capabilities_reports_selected_runtime(self):
        app.state.demo_mode = False
        response = self.client.get("/api/system?device=cpu&dtype=float32&offload=none")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selected_device"]["id"], "cpu")
        self.assertTrue(payload["production_backend"]["ready"])
        self.assertEqual(payload["backend"]["default_mode"], "production")
        self.assertTrue(payload["backend"]["demo_is_synthetic"])

    def test_run_without_mode_defaults_to_production(self):
        image_path = self.root / "production_default.png"
        from PIL import Image
        Image.new("RGB", (32, 32), color=(10, 20, 30)).save(image_path)

        payload = {
            "generation": {"images": [str(image_path)], "steps": 1},
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
            },
        }
        fake_bridge = MagicMock()
        fake_bridge.submit_run.return_value.job_id = "production_default_job"
        app.state.demo_mode = False

        with patch("ui.server.get_runner_bridge", return_value=fake_bridge):
            response = self.client.post("/api/run", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(fake_bridge.submit_run.call_args.kwargs["demo_mode"])

    def test_run_rejects_non_boolean_demo_mode(self):
        image_path = self.root / "invalid_mode.png"
        from PIL import Image
        Image.new("RGB", (32, 32), color=(10, 20, 30)).save(image_path)

        payload = {
            "generation": {"images": [str(image_path)], "steps": 1},
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
            },
            "demo_mode": "false",
        }
        response = self.client.post("/api/run", json=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("boolean", response.json()["detail"])

    def test_run_job_reentrant_lock_safe(self):
        cfg = Config(
            model=ModelConfig(),
            generation=GenerationConfig(steps=5),
            runtime=RuntimeConfig(output_dir=str(self.outputs_dir)),
        )
        job = RunJob(job_id="test_job_001", config=cfg, demo_mode=True)
        # Verify nested lock acquisition doesn't deadlock
        with job._lock:
            q = asyncio.Queue()
            job.add_subscriber(q)
            self.assertIn(q, job.subscribers)
            job.remove_subscriber(q)
            self.assertNotIn(q, job.subscribers)

    def test_sse_stream_terminates_on_complete(self):
        # Create a sample image for the run
        img_path = self.root / "input.png"
        from PIL import Image
        img = Image.new("RGB", (64, 64), color=(120, 180, 240))
        img.save(img_path)

        payload = {
            "generation": {"images": [str(img_path)], "steps": 5},
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        # Connect to stream - must terminate cleanly and include complete event
        stream_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(stream_resp.status_code, 200)
        self.assertIn("event: log", stream_resp.text)
        self.assertIn("event: progress", stream_resp.text)
        self.assertIn("event: complete", stream_resp.text)

    def test_stream_nonexistent_run_returns_404(self):
        resp = self.client.get("/api/run/definitely_nonexistent_run_id_99999/stream")
        self.assertEqual(resp.status_code, 404)

    def test_stream_replay_for_completed_disk_run(self):
        # Write a dummy record to disk
        run_id = "test_completed_run_disk_001"
        rec_path = self.outputs_dir / f"{run_id}.json"
        rec_data = {
            "run_id": run_id,
            "status": "success",
            "outputs": [],
            "timestamp": "2026-09-22T20:00:00Z",
        }
        import json
        rec_path.write_text(json.dumps(rec_data))

        resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("event: complete", stream_resp_text := resp.text)
        self.assertIn(run_id, stream_resp_text)

    def test_models_dir_isolation_with_adversarial_var_name(self):
        from ui.tests.e2e.common import get_test_client
        with tempfile.TemporaryDirectory() as my_empty_models:
            c = get_test_client(models_dir=Path(my_empty_models))
            resp = c.get("/api/models")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(len(resp.json()["models"]), 0)

    def test_upload_id_path_traversal_rejected(self):
        files = {"file": ("model.safetensors", b"dummy_content", "application/octet-stream")}
        data = {
            "filename": "model.safetensors",
            "upload_id": "../../../../../../tmp/evil_uid",
            "chunk_index": 0,
            "total_chunks": 2,
        }
        resp = self.client.post("/api/models/upload", files=files, data=data)
        self.assertEqual(resp.status_code, 400)
        evil_file = Path("/tmp/evil_uid_chunk_0000.part")
        self.assertFalse(evil_file.exists())

    def test_upload_id_invalid_characters_rejected(self):
        files = {"file": ("model.safetensors", b"dummy_content", "application/octet-stream")}
        data = {
            "filename": "model.safetensors",
            "upload_id": "invalid$upload;id",
            "chunk_index": 0,
            "total_chunks": 2,
        }
        resp = self.client.post("/api/models/upload", files=files, data=data)
        self.assertEqual(resp.status_code, 400)

    def test_chunked_upload_empty_file_rejected(self):
        models_dir = self.root / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        app.state.models_dir = models_dir
        os.environ["MODELS_DIR"] = str(models_dir)
        try:
            files0 = {"file": ("empty_assembled.safetensors", b"", "application/octet-stream")}
            d0 = {"filename": "empty_assembled.safetensors", "upload_id": "clean_zero_test", "chunk_index": 0, "total_chunks": 2}
            r0 = self.client.post("/api/models/upload", files=files0, data=d0)
            self.assertEqual(r0.status_code, 200)

            files1 = {"file": ("empty_assembled.safetensors", b"", "application/octet-stream")}
            d1 = {"filename": "empty_assembled.safetensors", "upload_id": "clean_zero_test", "chunk_index": 1, "total_chunks": 2}
            r1 = self.client.post("/api/models/upload", files=files1, data=d1)
            self.assertEqual(r1.status_code, 400)
            self.assertIn("File is empty", r1.text)
            target_file = models_dir / "empty_assembled.safetensors"
            self.assertFalse(target_file.exists())
        finally:
            app.state.models_dir = None
            os.environ.pop("MODELS_DIR", None)

    def test_run_output_dir_outside_allowed_boundaries_rejected(self):
        img_path = self.root / "input.png"
        from PIL import Image
        img = Image.new("RGB", (64, 64), color=(100, 100, 100))
        img.save(img_path)

        payload = {
            "generation": {"images": [str(img_path)], "steps": 1},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "output_dir": "/etc"},
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 400)
        resp_passwd = self.client.get("/api/outputs/passwd")
        self.assertEqual(resp_passwd.status_code, 404)

    def test_sse_subscriber_queue_disconnect_during_replay_cleaned(self):
        from unittest.mock import MagicMock
        cfg = Config(model=ModelConfig(), generation=GenerationConfig(steps=1), runtime=RuntimeConfig(output_dir=str(self.outputs_dir)))
        job = RunJob("leak_test_job", cfg, demo_mode=True)
        job.history.append({"event": "log", "data": {"text": "hello 1"}})
        job.history.append({"event": "log", "data": {"text": "hello 2"}})
        self.bridge.jobs["leak_test_job"] = job
        self.bridge.run_id_map["leak_test_job"] = "leak_test_job"

        async def check():
            gen = self.bridge.event_generator("leak_test_job", MagicMock())
            await gen.asend(None)
            await gen.aclose()
            self.assertEqual(len(job.subscribers), 0)

        asyncio.run(check())

    def test_history_overflow_preserves_terminal_events(self):
        cfg = Config(model=ModelConfig(), generation=GenerationConfig(steps=1), runtime=RuntimeConfig(output_dir=str(self.outputs_dir)))
        job = RunJob("overflow_test_job", cfg, demo_mode=True)
        for i in range(5500):
            job.push_event("log", {"text": f"line {i}"})
        self.assertEqual(len(job.history), 5000)

        # Pushing terminal complete event must NOT be dropped
        job.push_event("complete", {"status": "success", "outputs": []})
        self.assertEqual(len(job.history), 5001)
        self.assertEqual(job.history[-1]["event"], "complete")

    def test_setup_error_attribution_and_lookup_without_404(self):
        corrupt_img = self.root / "corrupt_backend.png"
        corrupt_img.write_bytes(b"NOT_A_PNG")

        payload = {
            "generation": {"images": [str(corrupt_img)], "steps": 2},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "output_dir": str(self.outputs_dir)},
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        predicted_run_id = resp.json()["run_id"]

        import time
        time.sleep(0.3)

        rec_resp = self.client.get(f"/api/runs/{predicted_run_id}")
        self.assertEqual(rec_resp.status_code, 200)
        rec_data = rec_resp.json()
        self.assertIn(rec_data.get("status"), ["error", "setup_error"])
        self.assertIn("error", rec_data)


if __name__ == "__main__":
    unittest.main()
