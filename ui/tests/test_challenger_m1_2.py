"""ui/tests/test_challenger_m1_2.py

Milestone 1 Challenger 2 Adversarial Verification Suite.
Thoroughly stress-tests DemoBackend, runner_bridge.py, server.py, output images,
byte-accurate SHA-256 hashes, side-by-side comparison images, {run_id}.json schema compliance,
and error propagation under hostile conditions.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
from starlette.testclient import TestClient

from qwen_runner.config import Config, GenerationConfig, ModelConfig, RuntimeConfig
from qwen_runner.images import load_references, reference_size, save_comparison
from ui.runner_bridge import DemoBackend, RunJob, RunnerBridge, get_runner_bridge, resolve_backend_factory
from ui.server import app, dict_to_config, get_outputs_dir


class TestChallengerM12ExecutionIntegrity(unittest.TestCase):
    """Empirical adversarial verification of DemoBackend and RunnerBridge execution integrity."""

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

        # Helper test images
        cls.img_64 = cls.root / "img_64x64.png"
        Image.new("RGB", (64, 64), color=(200, 100, 50)).save(cls.img_64, format="PNG")

        cls.img_wide = cls.root / "img_wide.png"
        Image.new("RGB", (320, 160), color=(50, 150, 200)).save(cls.img_wide, format="PNG")

        cls.img_tall = cls.root / "img_tall.png"
        Image.new("RGB", (160, 480), color=(100, 200, 50)).save(cls.img_tall, format="PNG")

        cls.img_large = cls.root / "img_large.png"
        Image.new("RGB", (1600, 1200), color=(180, 70, 140)).save(cls.img_large, format="PNG")

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("INPUTS_DIR", None)
        os.environ.pop("OUTPUTS_DIR", None)
        os.environ.pop("MODELS_DIR", None)
        cls.temp_dir.cleanup()

    def _wait_for_job(self, run_id: str, timeout: float = 5.0) -> dict:
        """Poll get_run_record or stream until completed."""
        start = time.time()
        bridge = get_runner_bridge()
        while time.time() - start < timeout:
            rec = bridge.get_run_record(run_id, wait_timeout=0.2)
            if rec and rec.get("status") in ("success", "error"):
                return rec
            time.sleep(0.05)
        raise TimeoutError(f"Job {run_id} did not finish within {timeout}s")

    # =========================================================================
    # 1. Output Image Dimensions & PNG Validity (DemoBackend & Pipeline)
    # =========================================================================

    def test_01_standard_canvas_dimensions_and_png_magic_bytes(self):
        """Verify standard canvas output is valid PNG with exact dimensions and magic bytes."""
        cfg = Config(
            model=ModelConfig(),
            generation=GenerationConfig(
                images=[str(self.img_wide)],
                steps=5,
                custom_size=True,
                width=512,
                height=256,
            ),
            runtime=RuntimeConfig(output_dir=str(self.outputs_dir)),
        )
        backend = DemoBackend(cfg).load()
        images, canvas, _ = load_references(cfg.generation)
        self.assertEqual(canvas, (512, 256))

        results = backend.generate(images, canvas, seed=12345)
        self.assertEqual(len(results), 1)
        out_img = results[0]

        # In-memory dimension check
        self.assertEqual((out_img.width, out_img.height), (512, 256))

        # Save to disk as PNG
        out_path = self.outputs_dir / "test_std_canvas.png"
        out_img.save(out_path, format="PNG")

        # Byte inspection: PNG magic bytes
        file_bytes = out_path.read_bytes()
        self.assertTrue(file_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # Reload with PIL and inspect dimensions
        with Image.open(out_path) as reloaded:
            self.assertEqual(reloaded.format, "PNG")
            self.assertEqual(reloaded.size, (512, 256))
            self.assertEqual(reloaded.mode, "RGB")

    def test_02_boundary_minimum_custom_dimensions(self):
        """Stress-test minimum valid 32-pixel increments: (32, 32), (64, 32), (32, 64)."""
        test_dimensions = [(32, 32), (64, 32), (32, 64), (64, 64)]
        for w, h in test_dimensions:
            cfg = Config(
                model=ModelConfig(),
                generation=GenerationConfig(
                    images=[str(self.img_64)],
                    steps=2,
                    custom_size=True,
                    width=w,
                    height=h,
                ),
                runtime=RuntimeConfig(output_dir=str(self.outputs_dir)),
            )
            backend = DemoBackend(cfg).load()
            images, canvas, _ = load_references(cfg.generation)
            self.assertEqual(canvas, (w, h))

            results = backend.generate(images, canvas, seed=999)
            self.assertEqual(len(results), 1)
            out_img = results[0]
            self.assertEqual((out_img.width, out_img.height), (w, h))

            out_file = self.outputs_dir / f"boundary_{w}x{h}.png"
            out_img.save(out_file, format="PNG")
            with Image.open(out_file) as reloaded:
                self.assertEqual(reloaded.size, (w, h))
                self.assertEqual(reloaded.format, "PNG")

    def test_03_asymmetric_and_large_dimensions(self):
        """Stress-test extreme aspect ratios and large dimensions: (1024, 64), (64, 1024), (1536, 1536)."""
        asym_dims = [(1024, 64), (64, 1024), (1536, 1536)]
        for w, h in asym_dims:
            cfg = Config(
                model=ModelConfig(),
                generation=GenerationConfig(
                    images=[str(self.img_wide)],
                    steps=3,
                    custom_size=True,
                    width=w,
                    height=h,
                ),
                runtime=RuntimeConfig(output_dir=str(self.outputs_dir)),
            )
            backend = DemoBackend(cfg).load()
            images, canvas, _ = load_references(cfg.generation)
            results = backend.generate(images, canvas, seed=42)
            self.assertEqual((results[0].width, results[0].height), (w, h))

    def test_04_batch_generation_exact_dimensions(self):
        """Verify batch generation (batch_size=3) produces exact count and dimensions."""
        batch_count = 3
        cfg = Config(
            model=ModelConfig(),
            generation=GenerationConfig(
                images=[str(self.img_64)],
                batch_size=batch_count,
                custom_size=True,
                width=128,
                height=128,
            ),
            runtime=RuntimeConfig(output_dir=str(self.outputs_dir)),
        )
        backend = DemoBackend(cfg).load()
        images, canvas, _ = load_references(cfg.generation)
        results = backend.generate(images, canvas, seed=777)
        self.assertEqual(len(results), batch_count)
        for i, img in enumerate(results):
            self.assertEqual(img.size, (128, 128))

    def test_05_ordered_references_up_to_10_images(self):
        """Verify handling of up to 10 ordered reference images with canvas set by slot 1."""
        ref_paths = []
        for i in range(10):
            p = self.root / f"ref_{i:02d}.png"
            Image.new("RGB", (64 + i * 32, 64 + i * 32), color=(i * 20, 100, 200 - i * 15)).save(p, format="PNG")
            ref_paths.append(str(p))

        cfg = Config(
            model=ModelConfig(),
            generation=GenerationConfig(
                images=ref_paths,
                steps=5,
                custom_size=False,  # Canvas dictated by image 1 (ref_paths[0])
            ),
            runtime=RuntimeConfig(output_dir=str(self.outputs_dir)),
        )
        images, canvas, metadata = load_references(cfg.generation)
        self.assertEqual(len(images), 10)
        self.assertEqual(len(metadata), 10)
        # First image is 64x64
        self.assertEqual(canvas, (64, 64))

        backend = DemoBackend(cfg).load()
        results = backend.generate(images, canvas, seed=100)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].size, (64, 64))

    # =========================================================================
    # 2. Byte-Accurate SHA-256 Hash Matching
    # =========================================================================

    def test_06_byte_accurate_sha256_disk_and_api(self):
        """Verify SHA-256 reported in JSON, SSE stream, and API matches exact file bytes on disk."""
        payload = {
            "generation": {
                "images": [str(self.img_wide)],
                "steps": 5,
                "custom_size": True,
                "width": 256,
                "height": 128,
                "seed": 424242,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
                "filename_prefix": "sha_verify",
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        # Read SSE stream
        stream_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(stream_resp.status_code, 200)
        stream_text = stream_resp.text
        self.assertIn("event: complete", stream_text)

        # Parse complete event data
        complete_data = None
        for chunk in stream_text.split("\n\n"):
            if "event: complete" in chunk:
                for line in chunk.split("\n"):
                    if line.startswith("data: "):
                        complete_data = json.loads(line[6:])
                        break
        self.assertIsNotNone(complete_data)
        self.assertEqual(complete_data["status"], "success")
        self.assertGreater(len(complete_data["outputs"]), 0)

        # 1. Inspect output item in SSE
        out_info = complete_data["outputs"][0]
        reported_sha256 = out_info["sha256"]
        out_filename = out_info["filename"]
        out_url = out_info["url"]

        # 2. Inspect file on disk
        disk_file = self.outputs_dir / out_filename
        self.assertTrue(disk_file.is_file(), f"Expected file {disk_file} to exist on disk")
        computed_disk_sha256 = hashlib.sha256(disk_file.read_bytes()).hexdigest()
        self.assertEqual(reported_sha256, computed_disk_sha256)

        # 3. Inspect served HTTP bytes via /api/outputs/{filename}
        out_resp = self.client.get(out_url)
        self.assertEqual(out_resp.status_code, 200)
        computed_http_sha256 = hashlib.sha256(out_resp.content).hexdigest()
        self.assertEqual(reported_sha256, computed_http_sha256)

        # 4. Inspect {run_id}.json record on disk
        actual_run_id = complete_data["run_id"]
        json_file = self.outputs_dir / f"{actual_run_id}.json"
        self.assertTrue(json_file.is_file(), f"Expected record {json_file} on disk")
        disk_record = json.loads(json_file.read_text(encoding="utf-8"))
        self.assertEqual(disk_record["outputs"][0]["sha256"], computed_disk_sha256)

        # 5. Inspect GET /api/runs/{run_id}
        api_rec_resp = self.client.get(f"/api/runs/{actual_run_id}")
        self.assertEqual(api_rec_resp.status_code, 200)
        api_record = api_rec_resp.json()
        self.assertEqual(api_record["outputs"][0]["sha256"], computed_disk_sha256)

    def test_07_batch_outputs_unique_and_accurate_hashes(self):
        """Verify batch generation creates unique files with accurate SHA-256 for every element."""
        payload = {
            "generation": {
                "images": [str(self.img_64)],
                "batch_size": 3,
                "custom_size": True,
                "width": 64,
                "height": 64,
                "seed": 10001,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
                "filename_prefix": "batch_sha",
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]
        rec = self._wait_for_job(run_id)

        self.assertEqual(len(rec["outputs"]), 3)
        hashes = [o["sha256"] for o in rec["outputs"]]
        # All batch element hashes must be unique (different seeds / batch indicators)
        self.assertEqual(len(set(hashes)), 3)

        # Verify each hash matches disk and HTTP
        for o in rec["outputs"]:
            disk_p = Path(o["path"])
            self.assertTrue(disk_p.is_file())
            disk_sha = hashlib.sha256(disk_p.read_bytes()).hexdigest()
            self.assertEqual(o["sha256"], disk_sha)

            http_resp = self.client.get(f"/api/outputs/{disk_p.name}")
            self.assertEqual(http_resp.status_code, 200)
            self.assertEqual(hashlib.sha256(http_resp.content).hexdigest(), disk_sha)

    # =========================================================================
    # 3. Side-by-Side Comparison Image Verification
    # =========================================================================

    def test_08_save_comparison_true_generates_valid_image_and_serves(self):
        """Verify save_comparison=True produces {run_id}_comparison.png with height <= 1024."""
        payload = {
            "generation": {
                "images": [str(self.img_tall)],  # 160x480
                "custom_size": True,
                "width": 256,
                "height": 256,
                "steps": 4,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
                "save_comparison": True,
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]
        rec = self._wait_for_job(run_id)

        self.assertIn("comparison", rec)
        comp_path = Path(rec["comparison"])
        self.assertTrue(comp_path.is_file())
        self.assertTrue(comp_path.name.endswith("_comparison.png"))

        # Open and inspect comparison image
        with Image.open(comp_path) as comp_img:
            self.assertEqual(comp_img.format, "PNG")
            self.assertLessEqual(comp_img.height, 1024)
            # Source height: 480, Output height: 256 -> max = 480 <= 1024
            self.assertEqual(comp_img.height, 480)
            # Width = round(160 * 480 / 480) + round(256 * 480 / 256) = 160 + 480 = 640
            self.assertEqual(comp_img.width, 640)

        # Verify serving via /api/outputs/
        comp_url = f"/api/outputs/{comp_path.name}"
        comp_resp = self.client.get(comp_url)
        self.assertEqual(comp_resp.status_code, 200)
        self.assertEqual(comp_resp.headers["content-type"], "image/png")
        self.assertEqual(
            hashlib.sha256(comp_resp.content).hexdigest(),
            hashlib.sha256(comp_path.read_bytes()).hexdigest(),
        )

    def test_09_save_comparison_height_clamped_to_1024(self):
        """Verify comparison image clamps height to 1024 when source height exceeds 1024."""
        # Source image is 1600x1200
        payload = {
            "generation": {
                "images": [str(self.img_large)],
                "custom_size": True,
                "width": 512,
                "height": 512,
                "steps": 2,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
                "save_comparison": True,
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]
        rec = self._wait_for_job(run_id)

        comp_path = Path(rec["comparison"])
        with Image.open(comp_path) as comp_img:
            self.assertEqual(comp_img.height, 1024)
            self.assertLessEqual(comp_img.height, 1024)

    def test_10_save_comparison_false_omits_comparison(self):
        """Verify save_comparison=False does not create comparison image or comparison_url."""
        payload = {
            "generation": {
                "images": [str(self.img_64)],
                "steps": 2,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
                "save_comparison": False,
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]
        rec = self._wait_for_job(run_id)

        self.assertIsNone(rec.get("comparison"))

        # Verify no _comparison.png exists for this run
        actual_rid = rec["run_id"]
        comp_file = self.outputs_dir / f"{actual_rid}_comparison.png"
        self.assertFalse(comp_file.exists())

        # Requesting /api/outputs/{run_id}_comparison.png returns 404
        bad_resp = self.client.get(f"/api/outputs/{actual_rid}_comparison.png")
        self.assertEqual(bad_resp.status_code, 404)

    # =========================================================================
    # 4. JSON Run Record Schema Compliance
    # =========================================================================

    def test_11_json_run_record_complete_schema_and_types(self):
        """Verify all schema fields, types, and constraints in {run_id}.json."""
        seed_val = 987654321
        payload = {
            "generation": {
                "images": [str(self.img_64)],
                "prompt": "Cyberpunk city in rain with neon reflections",
                "negative_prompt": "blurry, low quality",
                "steps": 8,
                "cfg": 3.5,
                "seed": seed_val,
                "strength": 0.8,
                "sampler": "euler",
                "scheduler": "simple",
                "shift": 1.2,
                "custom_size": True,
                "width": 128,
                "height": 128,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
                "filename_prefix": "schema_test",
                "save_comparison": True,
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]
        rec = self._wait_for_job(run_id)

        # 1. Top-level keys
        required_keys = [
            "schema_version", "run_id", "status", "timestamp", "is_warmup",
            "model", "text_encoder", "backend", "parameters", "effective_parameters",
            "setup_seconds", "setup_shared_across_runs", "environment",
            "inference_time_seconds", "outputs", "finished_at",
            "run_wall_seconds_including_output_save",
        ]
        for key in required_keys:
            self.assertIn(key, rec, f"Missing required key: {key}")

        # 2. Value checks
        self.assertEqual(rec["schema_version"], 1)
        self.assertEqual(rec["status"], "success")
        self.assertFalse(rec["is_warmup"])

        # 3. ISO timestamps
        t_start = datetime.fromisoformat(rec["timestamp"])
        t_finish = datetime.fromisoformat(rec["finished_at"])
        self.assertGreaterEqual(t_finish, t_start)

        # 4. Parameters fidelity
        params = rec["parameters"]
        self.assertEqual(params["generation"]["prompt"], "Cyberpunk city in rain with neon reflections")
        self.assertEqual(params["generation"]["steps"], 8)
        self.assertEqual(params["generation"]["cfg"], 3.5)
        self.assertEqual(params["generation"]["seed"], seed_val)
        self.assertEqual(params["generation"]["strength"], 0.8)
        self.assertEqual(params["generation"]["shift"], 1.2)

        # 5. Effective parameters
        eff = rec["effective_parameters"]
        self.assertEqual(eff["width"], 128)
        self.assertEqual(eff["height"], 128)
        self.assertTrue(eff["negative_prompt_active"])  # cfg = 3.5 != 1
        self.assertEqual(eff["noise_device"], "cpu")
        self.assertEqual(eff["noise_dtype"], "float32")
        self.assertEqual(len(eff["sigmas"]), 8 + 1)
        self.assertEqual(eff["sigmas"][-1], 0.0)

        # 6. Environment
        env = rec["environment"]
        self.assertIn("python", env)
        self.assertIn("platform", env)
        self.assertIn("packages", env)

        # 7. Outputs schema
        self.assertGreater(len(rec["outputs"]), 0)
        out0 = rec["outputs"][0]
        self.assertEqual(out0["width"], 128)
        self.assertEqual(out0["height"], 128)
        self.assertEqual(out0["mode"], "RGB")
        self.assertEqual(len(out0["sha256"]), 64)

    def test_12_seed_progression_across_repeats(self):
        """Verify increment_seed=True increments seed sequentially across repeats."""
        base_seed = 5000
        payload = {
            "generation": {
                "images": [str(self.img_64)],
                "steps": 2,
                "seed": base_seed,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "repeats": 3,
                "increment_seed": True,
                "output_dir": str(self.outputs_dir),
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]
        bridge = get_runner_bridge()

        # Wait for all 3 repeats to complete
        job = bridge.jobs.get(run_id)
        self.assertIsNotNone(job)
        job.done_event.wait(timeout=5.0)
        self.assertEqual(len(job.records), 3)

        for idx, r in enumerate(job.records):
            expected_seed = base_seed + idx
            self.assertEqual(r["parameters"]["generation"]["seed"], expected_seed)
            self.assertEqual(r["run_id"].endswith(f"_{idx:03d}"), True)

    # =========================================================================
    # 5. Error Propagation & Failure Resilience
    # =========================================================================

    def test_13_missing_reference_image_returns_400_cleanly(self):
        """Verify submitting nonexistent reference image fails validation with HTTP 400."""
        payload = {
            "generation": {
                "images": ["/tmp/nonexistent_phantom_image_12345.png"],
                "steps": 5,
            },
            "runtime": {
                "output_dir": str(self.outputs_dir),
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get("valid", True))
        self.assertTrue(any("Missing reference image" in e for e in data.get("errors", [])))

    def test_14_corrupted_image_writes_setup_error_json_and_propagates_cleanly(self):
        """Verify corrupted image file triggers setup_error JSON and clean SSE error event."""
        # Use an isolated output directory to prevent cross-test interference
        isolated_out = self.root / "outputs_test_14"
        isolated_out.mkdir(parents=True, exist_ok=True)

        corrupt_img = self.root / "corrupt.png"
        corrupt_img.write_bytes(b"NOT A REAL PNG IMAGE FILE CORRUPTED DATA")

        payload = {
            "generation": {
                "images": [str(corrupt_img)],
                "steps": 4,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(isolated_out),
            },
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        # Connect to stream
        stream_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(stream_resp.status_code, 200)
        stream_text = stream_resp.text
        self.assertIn("event: complete", stream_text)

        # Parse complete event
        complete_data = None
        for chunk in stream_text.split("\n\n"):
            if "event: complete" in chunk:
                for line in chunk.split("\n"):
                    if line.startswith("data: "):
                        complete_data = json.loads(line[6:])
                        break
        self.assertIsNotNone(complete_data)
        self.assertEqual(complete_data["status"], "error")
        self.assertIsNotNone(complete_data["error"])
        self.assertIn("UnidentifiedImageError", complete_data["error"]["type"])

        # Verify *_setup_error.json was written to disk
        setup_errors = list(isolated_out.glob("*_setup_error.json"))
        self.assertGreater(len(setup_errors), 0)
        err_file = setup_errors[0]
        err_content = json.loads(err_file.read_text(encoding="utf-8"))
        self.assertEqual(err_content["status"], "setup_error")
        self.assertIn("UnidentifiedImageError", err_content["error"]["type"])

    def test_15_backend_runtime_exception_isolated(self):
        """Verify backend exception in clean environment produces error status record without crashing."""
        isolated_out = self.root / "outputs_test_15"
        isolated_out.mkdir(parents=True, exist_ok=True)

        class ExplodingBackend(DemoBackend):
            def generate(self, images, canvas, seed):
                raise RuntimeError("Deliberate simulated backend failure in diffusion loop")

        cfg = Config(
            model=ModelConfig(),
            generation=GenerationConfig(images=[str(self.img_64)], steps=3),
            runtime=RuntimeConfig(
                device="cpu",
                dtype="float32",
                offload="none",
                output_dir=str(isolated_out),
            ),
        )

        with patch("ui.runner_bridge.resolve_backend_factory", return_value=ExplodingBackend):
            bridge = get_runner_bridge()
            job = bridge.submit_run(config=cfg, demo_mode=True)
            job.done_event.wait(timeout=5.0)

            self.assertEqual(job.status, "error")
            self.assertIsNotNone(job.error)
            self.assertEqual(job.error["type"], "RuntimeError")
            self.assertIn("Deliberate simulated backend failure", job.error["message"])

            # Check record written to disk
            actual_rid = job.primary_run_id or job.job_id
            err_json = isolated_out / f"{actual_rid}.json"
            self.assertTrue(err_json.is_file())
            rec = json.loads(err_json.read_text())
            self.assertEqual(rec["status"], "error")
            self.assertEqual(rec["error"]["type"], "RuntimeError")

    def test_15_backend_runtime_exception_writes_error_record_and_recovers(self):
        """Verify runtime exception produces error record and system cleanly recovers on next run."""
        recov_out = self.root / "outputs_test_15_recov"
        recov_out.mkdir(parents=True, exist_ok=True)

        class ExplodingBackend(DemoBackend):
            def generate(self, images, canvas, seed):
                raise RuntimeError("Deliberate runtime crash in backend generation")

        # 1. First run crashes during generation
        with patch("ui.runner_bridge.resolve_backend_factory", return_value=ExplodingBackend):
            payload_crash = {
                "generation": {"images": [str(self.img_64)], "steps": 2},
                "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "output_dir": str(recov_out)},
                "demo_mode": True,
            }
            resp_crash = self.client.post("/api/run", json=payload_crash)
            self.assertEqual(resp_crash.status_code, 200)
            rid_crash = resp_crash.json()["run_id"]
            time.sleep(0.4)

            rec_crash = self.client.get(f"/api/runs/{rid_crash}")
            self.assertEqual(rec_crash.status_code, 200)
            crash_data = rec_crash.json()
            self.assertEqual(crash_data["status"], "error")
            self.assertEqual(crash_data["error"]["type"], "RuntimeError")

        # 2. Subsequent run with normal DemoBackend succeeds and recovers
        payload_ok = {
            "generation": {"images": [str(self.img_64)], "steps": 2},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "output_dir": str(recov_out)},
            "demo_mode": True,
        }
        resp_ok = self.client.post("/api/run", json=payload_ok)
        self.assertEqual(resp_ok.status_code, 200)
        rid_ok = resp_ok.json()["run_id"]
        time.sleep(0.4)

        rec_ok = self.client.get(f"/api/runs/{rid_ok}")
        self.assertEqual(rec_ok.status_code, 200)
        ok_data = rec_ok.json()
        self.assertEqual(ok_data["status"], "success")
        self.assertEqual(len(ok_data.get("outputs", [])), 1)

    def test_16_cross_job_error_leakage_adversarial_empirical_demonstration(self):
        """EMPIRICAL ADVERSARIAL VERIFICATION:
        Verify that ui/runner_bridge.py does NOT leak setup errors across jobs!
        When Job A experiences a setup error, a subsequent Job B (failing with RuntimeError in generate())
        must retain its own RuntimeError error details and MUST NOT be hijacked by Job A's setup error JSON.
        """
        shared_out = self.root / "outputs_shared_adversarial"
        shared_out.mkdir(parents=True, exist_ok=True)

        # 1. Job A: Trigger setup error with corrupted image
        corrupt_img = self.root / "corrupt_shared.png"
        corrupt_img.write_bytes(b"CORRUPTED BYTES")

        payload_a = {
            "generation": {"images": [str(corrupt_img)], "steps": 2},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "output_dir": str(shared_out)},
            "demo_mode": True,
        }
        resp_a = self.client.post("/api/run", json=payload_a)
        run_id_a = resp_a.json()["run_id"]
        stream_a = self.client.get(f"/api/run/{run_id_a}/stream")
        self.assertIn("UnidentifiedImageError", stream_a.text)

        # 2. Job B: Submitted immediately afterwards (<15s) with VALID image, but backend generates RuntimeError
        class InferenceExplodingBackend(DemoBackend):
            def generate(self, images, canvas, seed):
                raise RuntimeError("InferenceFailed: Out of CUDA memory")

        cfg_b = Config(
            model=ModelConfig(),
            generation=GenerationConfig(images=[str(self.img_64)], steps=3),
            runtime=RuntimeConfig(device="cpu", dtype="float32", offload="none", output_dir=str(shared_out)),
        )

        with patch("ui.runner_bridge.resolve_backend_factory", return_value=InferenceExplodingBackend):
            bridge = get_runner_bridge()
            job_b = bridge.submit_run(config=cfg_b, demo_mode=True)
            job_b.done_event.wait(timeout=5.0)

            # Strictly verify that error attribution is correct:
            self.assertEqual(job_b.error["type"], "RuntimeError")
            self.assertIn("InferenceFailed: Out of CUDA memory", job_b.error["message"])
            self.assertFalse(job_b.primary_run_id.endswith("_setup_error"))
            self.assertNotIn("setup_error_json", job_b.error)

            # Verify GET /api/runs for both runs
            rec_a = self.client.get(f"/api/runs/{run_id_a}")
            self.assertEqual(rec_a.status_code, 200)
            self.assertEqual(rec_a.json()["status"], "setup_error")

            rec_b = self.client.get(f"/api/runs/{job_b.job_id}")
            self.assertEqual(rec_b.status_code, 200)
            self.assertEqual(rec_b.json()["status"], "error")
            self.assertEqual(rec_b.json()["error"]["type"], "RuntimeError")

    def test_17_setup_error_predicted_run_id_lookup_bug_demonstration(self):
        """EMPIRICAL ADVERSARIAL VERIFICATION:
        When a run fails during setup, POST /api/run returns {run_id: predicted_run_id}.
        Calling GET /api/runs/{predicted_run_id} MUST return HTTP 200 (not 404),
        containing the full setup error record.
        """
        isolated_out = self.root / "outputs_test_17"
        isolated_out.mkdir(parents=True, exist_ok=True)
        corrupt_img = self.root / "corrupt_17.png"
        corrupt_img.write_bytes(b"INVALID_IMAGE_BYTES")

        payload = {
            "generation": {"images": [str(corrupt_img)], "steps": 2},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "output_dir": str(isolated_out)},
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        returned_run_id = resp.json()["run_id"]

        # Wait for failure
        time.sleep(0.4)

        # Query GET /api/runs/{returned_run_id}
        rec_resp = self.client.get(f"/api/runs/{returned_run_id}")
        self.assertEqual(rec_resp.status_code, 200, f"Expected 200 for failed setup run, got {rec_resp.status_code}")
        rec_data = rec_resp.json()
        self.assertEqual(rec_data["status"], "setup_error")
        self.assertEqual(rec_data["error"]["type"], "UnidentifiedImageError")

    def test_18_path_traversal_attacks_on_outputs_endpoint(self):
        """Verify directory traversal attempts on /api/outputs/{filename} return 404."""
        attack_paths = [
            "..%2fserver.py",
            "....//....//etc/passwd",
            "/etc/passwd",
            "../PROJECT.md",
            "subdir/../../app.py",
        ]
        for p in attack_paths:
            resp = self.client.get(f"/api/outputs/{p}")
            self.assertIn(resp.status_code, (404, 400), f"Path {p} returned unexpected {resp.status_code}")


if __name__ == "__main__":
    unittest.main()
