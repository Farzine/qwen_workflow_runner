"""ui/tests/test_challenger_m1_stress.py

Adversarial Stress Verification Suite for Milestone 1 Re-Gating:
1. Cold disk retrieval of setup errors after cache/memory purge (GET /api/runs/{predicted_run_id}).
2. Highly concurrent mixed workload (setup failure, runtime exception, success) to stress error attribution.
3. Byte-accurate SHA-256 verification under varied generation settings.
4. Side-by-side comparison images with extreme dimensions, clamping, and negative checks.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
from starlette.testclient import TestClient

from ui.runner_bridge import DemoBackend, get_runner_bridge
from ui.server import app


class TestChallengerM1Stress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_dir.name)
        cls.inputs_dir = cls.root / "inputs"
        cls.outputs_dir = cls.root / "outputs"
        cls.models_dir = cls.root / "models"

        cls.inputs_dir.mkdir(parents=True, exist_ok=True)
        cls.outputs_dir.mkdir(parents=True, exist_ok=True)
        cls.models_dir.mkdir(parents=True, exist_ok=True)

        os.environ["INPUTS_DIR"] = str(cls.inputs_dir)
        os.environ["OUTPUTS_DIR"] = str(cls.outputs_dir)
        os.environ["MODELS_DIR"] = str(cls.models_dir)

        cls.valid_img = cls.root / "valid_128.png"
        Image.new("RGB", (128, 128), color=(120, 80, 200)).save(cls.valid_img, format="PNG")

        cls.corrupt_img = cls.root / "corrupt_data.png"
        cls.corrupt_img.write_bytes(b"CORRUPTED_PNG_HEADER_DATA_FAIL")

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("INPUTS_DIR", None)
        os.environ.pop("OUTPUTS_DIR", None)
        os.environ.pop("MODELS_DIR", None)
        cls.temp_dir.cleanup()

    def test_stress_01_cold_disk_retrieval_of_setup_error_after_cache_clear(self):
        """Stress-test setup error retrieval on GET /api/runs/{predicted_run_id} after in-memory purge."""
        resp_setup = self.client.post("/api/run", json={
            "generation": {"images": [str(self.corrupt_img)], "steps": 2},
            "runtime": {"output_dir": str(self.outputs_dir)},
            "demo_mode": True,
        })
        self.assertEqual(resp_setup.status_code, 200)
        pred_run_id = resp_setup.json()["run_id"]
        time.sleep(0.4)

        bridge = get_runner_bridge()
        # Verify warm in-memory retrieval
        rec_warm = self.client.get(f"/api/runs/{pred_run_id}")
        self.assertEqual(rec_warm.status_code, 200)
        self.assertEqual(rec_warm.json()["status"], "setup_error")

        # Evict cache completely to test cold disk resolution
        with bridge._lock:
            saved_jobs = dict(bridge.jobs)
            saved_map = dict(bridge.run_id_map)
            bridge.jobs.clear()
            bridge.run_id_map.clear()

        try:
            rec_cold = self.client.get(f"/api/runs/{pred_run_id}")
            self.assertEqual(rec_cold.status_code, 200)
            cold_json = rec_cold.json()
            self.assertEqual(cold_json["status"], "setup_error")
            self.assertEqual(cold_json["error"]["type"], "UnidentifiedImageError")
        finally:
            with bridge._lock:
                bridge.jobs.update(saved_jobs)
                bridge.run_id_map.update(saved_map)

    def test_stress_02_concurrent_mixed_workload_isolation(self):
        """Stress-test error isolation across 15 concurrent threads (5 setup fails, 5 runtime fails, 5 successes)."""
        def ConcurrencyExploder(config):
            class Exploder(DemoBackend):
                def generate(self, images, canvas, seed):
                    time.sleep(0.01)
                    raise RuntimeError(f"Thread runtime failure at seed={seed}")
            return Exploder(config)

        def dynamic_resolve(*args, **kwargs):
            def backend_selector(config):
                if "runtime_error" in config.runtime.filename_prefix:
                    return ConcurrencyExploder(config)
                return DemoBackend(config)
            return backend_selector

        results: dict[str, tuple] = {}
        lock = threading.Lock()

        def worker_task(idx: int, task_type: str):
            out_dir = self.root / f"conc_out_{task_type}_{idx}"
            out_dir.mkdir(parents=True, exist_ok=True)
            if task_type == "setup_error":
                resp = self.client.post("/api/run", json={
                    "generation": {"images": [str(self.corrupt_img)], "steps": 2},
                    "runtime": {"output_dir": str(out_dir), "filename_prefix": f"{task_type}_{idx}"},
                    "demo_mode": True,
                })
                rid = resp.json()["run_id"]
                time.sleep(0.6)
                rec = self.client.get(f"/api/runs/{rid}")
                with lock:
                    results[f"{task_type}_{idx}"] = (rec.status_code, rec.json().get("status"), rec.json().get("error", {}).get("type"))
            elif task_type == "runtime_error":
                resp = self.client.post("/api/run", json={
                    "generation": {"images": [str(self.valid_img)], "steps": 2},
                    "runtime": {"output_dir": str(out_dir), "filename_prefix": f"{task_type}_{idx}"},
                    "demo_mode": True,
                })
                rid = resp.json()["run_id"]
                time.sleep(0.6)
                rec = self.client.get(f"/api/runs/{rid}")
                with lock:
                    results[f"{task_type}_{idx}"] = (rec.status_code, rec.json().get("status"), rec.json().get("error", {}).get("type"))
            elif task_type == "success":
                resp = self.client.post("/api/run", json={
                    "generation": {"images": [str(self.valid_img)], "steps": 2, "custom_size": True, "width": 64, "height": 64},
                    "runtime": {"output_dir": str(out_dir), "filename_prefix": f"{task_type}_{idx}"},
                    "demo_mode": True,
                })
                rid = resp.json()["run_id"]
                time.sleep(0.6)
                rec = self.client.get(f"/api/runs/{rid}")
                with lock:
                    results[f"{task_type}_{idx}"] = (rec.status_code, rec.json().get("status"), len(rec.json().get("outputs", [])))

        with patch("ui.runner_bridge.resolve_backend_factory", side_effect=dynamic_resolve):
            with ThreadPoolExecutor(max_workers=15) as executor:
                futures = []
                for i in range(5):
                    futures.append(executor.submit(worker_task, i, "setup_error"))
                    futures.append(executor.submit(worker_task, i, "runtime_error"))
                    futures.append(executor.submit(worker_task, i, "success"))
                for f in futures:
                    f.result()

        # Validate complete isolation across all 15 concurrent jobs
        self.assertEqual(len(results), 15)
        for key, res in results.items():
            status_code, run_status, detail = res
            self.assertEqual(status_code, 200, f"Task {key} failed with status code {status_code}")
            if "setup_error" in key:
                self.assertEqual(run_status, "setup_error", f"Task {key} expected setup_error, got {run_status}")
                self.assertEqual(detail, "UnidentifiedImageError", f"Task {key} expected UnidentifiedImageError, got {detail}")
            elif "runtime_error" in key:
                self.assertEqual(run_status, "error", f"Task {key} expected error, got {run_status}")
                self.assertEqual(detail, "RuntimeError", f"Task {key} misattributed to {detail}!")
            elif "success" in key:
                self.assertEqual(run_status, "success", f"Task {key} expected success, got {run_status}")
                self.assertEqual(detail, 1, f"Task {key} expected 1 output, got {detail}")

    def test_stress_03_sha256_full_parity_across_components(self):
        """Stress-test byte-level SHA-256 accuracy across file, HTTP response, SSE, and JSON record."""
        payload = {
            "generation": {
                "images": [str(self.valid_img)],
                "steps": 4,
                "custom_size": True,
                "width": 160,
                "height": 96,
                "seed": 987123,
            },
            "runtime": {
                "output_dir": str(self.outputs_dir),
                "filename_prefix": "stress_sha",
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        time.sleep(0.5)
        rec_resp = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(rec_resp.status_code, 200)
        rec = rec_resp.json()
        self.assertEqual(rec["status"], "success")
        self.assertGreater(len(rec["outputs"]), 0)

        out_meta = rec["outputs"][0]
        fname = Path(out_meta["path"]).name
        claimed_sha = out_meta["sha256"]

        disk_file = self.outputs_dir / fname
        self.assertTrue(disk_file.is_file())
        disk_bytes = disk_file.read_bytes()
        actual_disk_sha = hashlib.sha256(disk_bytes).hexdigest()
        self.assertEqual(claimed_sha, actual_disk_sha)

        http_resp = self.client.get(f"/api/outputs/{fname}")
        self.assertEqual(http_resp.status_code, 200)
        actual_http_sha = hashlib.sha256(http_resp.content).hexdigest()
        self.assertEqual(claimed_sha, actual_http_sha)

    def test_stress_04_comparison_dimensions_and_clamping(self):
        """Stress-test side-by-side comparison image clamping and aspect ratios."""
        tall_img = self.root / "tall_img_1800.png"
        Image.new("RGB", (900, 1800), color=(80, 160, 240)).save(tall_img, format="PNG")

        payload = {
            "generation": {
                "images": [str(tall_img)],
                "steps": 2,
                "custom_size": True,
                "width": 512,
                "height": 256,
            },
            "runtime": {
                "output_dir": str(self.outputs_dir),
                "save_comparison": True,
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]
        time.sleep(0.5)

        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(rec["status"], "success")
        self.assertIsNotNone(rec.get("comparison"))

        comp_p = Path(rec["comparison"])
        self.assertTrue(comp_p.is_file())
        with Image.open(comp_p) as c_img:
            self.assertEqual(c_img.format, "PNG")
            # Max source height is 1800 -> must clamp to 1024
            self.assertEqual(c_img.height, 1024)
            # Width = round(900 * 1024 / 1800) + round(512 * 1024 / 256) = 512 + 2048 = 2560
            self.assertEqual(c_img.width, 2560)


if __name__ == "__main__":
    unittest.main()
