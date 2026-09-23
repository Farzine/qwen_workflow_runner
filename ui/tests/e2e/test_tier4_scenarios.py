"""Tier 4: Real-World End-to-End Application Scenario Workflows for Qwen Workflow Runner Web UI.

Contains >=8 complete real-world scenarios:
  1. Single-Reference Casual Edit (F1, F2, F3, F4, F5, F11, F12, F14)
  2. Multi-Reference Complex Composition (5 images) (F1, F2, F3, F4, F5, F6, F11, F12, F13, F14)
  3. Boundary Image Count (10 reference images max) (F1, F2, F3, F4, F8, F11, F12, F13, F14, F15)
  4. Custom Resolution & Aspect Ratio Editing (F1, F2, F4, F5, F6, F11, F12, F14)
  5. GGUF Quantization Model Switch & Run (F7, F8, F9, F10, F11, F12, F14, F15)
  6. Repeats & Seed Incrementation with Comparison (F1, F2, F4, F5, F11, F12, F13, F14, F15)
  7. Graceful Validation Recovery & Resubmission (F4, F5, F6, F11, F12, F14)
  8. Large File Upload (.gguf) & Immediate Inference (F8, F9, F10, F11, F12, F14)
"""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from ui.tests.e2e.common import (
    compute_sha256,
    create_test_image,
    get_test_client,
)


class TestTier4Scenarios(unittest.TestCase):
    """Tier 4 Real-World Application Scenario Tests."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_dir.name)
        cls.inputs_dir = cls.root / "inputs"
        cls.models_dir = cls.root / "models"
        cls.outputs_dir = cls.root / "outputs"

        cls.inputs_dir.mkdir(parents=True, exist_ok=True)
        cls.models_dir.mkdir(parents=True, exist_ok=True)
        cls.outputs_dir.mkdir(parents=True, exist_ok=True)

        cls.fashion_dir = cls.inputs_dir / "fashion"
        cls.fashion_dir.mkdir()
        cls.images = [
            create_test_image(cls.fashion_dir / f"model_{i:02d}.png", 128, 128, (40 + i * 15, 80, 120))
            for i in range(12)
        ]

        cls.client = get_test_client(
            inputs_dir=cls.inputs_dir,
            models_dir=cls.models_dir,
            outputs_dir=cls.outputs_dir,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_scenario_01_single_reference_casual_edit(self):
        """Scenario 1: Single-Reference Casual Edit (F1, F2, F3, F4, F5, F11, F12, F14)."""
        # Step 1: Browse inputs to select photo
        browse_resp = self.client.get("/api/inputs/browse?folder=fashion")
        self.assertEqual(browse_resp.status_code, 200)
        img_meta = browse_resp.json()["images"][0]
        chosen_path = img_meta["path"]

        # Step 2: Fetch thumbnail preview
        thumb_resp = self.client.get(f"/api/inputs/thumbnail?path={chosen_path}")
        self.assertEqual(thumb_resp.status_code, 200)

        # Step 3 & 4: Configure and launch run
        payload = {
            "generation": {
                "images": [chosen_path],
                "prompt": "Apply summer lighting and subtle smile to <image1>",
                "steps": 20,
                "cfg": 2.0,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
            "demo_mode": True,
        }
        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)
        run_id = run_resp.json()["run_id"]

        # Step 5: Follow SSE log stream
        stream_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(stream_resp.status_code, 200)
        self.assertIn("event: complete", stream_resp.text)

        # Step 6: Inspect JSON record
        rec_resp = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(rec_resp.status_code, 200)
        rec = rec_resp.json()
        self.assertEqual(rec["status"], "success")

        # Step 7: View generated image
        out_filename = Path(rec["outputs"][0]["path"]).name
        img_resp = self.client.get(f"/api/outputs/{out_filename}")
        self.assertEqual(img_resp.status_code, 200)
        self.assertEqual(img_resp.headers["content-type"], "image/png")

    def test_scenario_02_multi_reference_complex_composition(self):
        """Scenario 2: Multi-Reference Composition with 5 images (F1-F6, F11-F14)."""
        # Step 1: Select 5 reference images
        selected = [str(self.images[i]) for i in range(5)]

        # Step 2: Preview thumbnails
        for p in selected:
            t = self.client.get(f"/api/inputs/thumbnail?path={p}")
            self.assertEqual(t.status_code, 200)

        # Step 3: Configure multi-ref prompt and comparison
        payload = {
            "generation": {
                "images": selected,
                "prompt": "Keep person from <image1>, apply shirt from <image2>, jacket from <image3>, background from <image4>, hat from <image5>",
                "steps": 30,
                "strength": 0.85,
            },
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "save_comparison": True,
            },
        }

        # Step 4: Validate config
        val = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(val.json()["valid"])

        # Step 5: Execute run
        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)
        run_id = run_resp.json()["run_id"]

        # Step 6: Verify comparison image
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertIn("comparison", rec)
        comp_file = Path(rec["comparison"]).name
        comp_resp = self.client.get(f"/api/outputs/{comp_file}")
        self.assertEqual(comp_resp.status_code, 200)
        self.assertEqual(len(rec["effective_parameters"]["reference_images"]), 5)

    def test_scenario_03_boundary_image_count_ten_references(self):
        """Scenario 3: Boundary Image Count (10 reference images max) (F1-F4, F8, F11-F15)."""
        # Select 10 reference images
        ten_refs = [str(self.images[i]) for i in range(10)]
        payload = {
            "generation": {"images": ten_refs, "steps": 15},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }

        # Validate
        v = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(v.json()["valid"])

        # Run
        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)
        run_id = run_resp.json()["run_id"]

        # Check run history
        hist = self.client.get("/api/runs").json()["runs"]
        self.assertTrue(any(r["run_id"] == run_id for r in hist))

    def test_scenario_04_custom_resolution_and_aspect_ratio(self):
        """Scenario 4: Custom Resolution & Aspect Ratio Editing (F1, F2, F4-F6, F11, F12, F14)."""
        payload = {
            "generation": {
                "images": [str(self.images[0])],
                "custom_size": True,
                "width": 768,
                "height": 512,
                "steps": 25,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        val = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(val.json()["valid"])

        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{run_resp.json()['run_id']}").json()
        out0 = rec["outputs"][0]
        self.assertEqual(out0["width"], 768)
        self.assertEqual(out0["height"], 512)

    def test_scenario_05_gguf_quantization_model_switch_and_run(self):
        """Scenario 5: GGUF Quantization Model Switch & Run (F7-F12, F14, F15)."""
        # Step 1: List models
        m_list = self.client.get("/api/models").json()["models"]

        # Step 2: Download task
        dl = self.client.post("/api/models/download", json={"repo_id": "Qwen/Qwen-Image-2.1-GGUF"}).json()
        task_id = dl["task_id"]

        # Step 3: Check progress
        prog = self.client.get(f"/api/models/download/progress/{task_id}").json()
        self.assertIn("progress", prog)

        # Step 4: Upload GGUF variant
        files = {"file": ("qwen_q5_k_m.gguf", b"GGUF_V5_MOCK", "application/octet-stream")}
        up = self.client.post("/api/models/upload", files=files).json()
        self.assertTrue(up["success"])

        # Step 5: Run with uploaded GGUF model
        payload = {
            "model": {"filename": "qwen_q5_k_m.gguf", "gguf_quantization": "Q5_K_M"},
            "generation": {"images": [str(self.images[0])]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)

    def test_scenario_06_repeats_seed_increment_with_comparison(self):
        """Scenario 6: Repeats & Seed Incrementation with Comparison (F1, F2, F4, F5, F11-F15)."""
        payload = {
            "generation": {"images": [str(self.images[0])], "seed": 777},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "repeats": 2, "increment_seed": True, "save_comparison": True,
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertTrue(rec["parameters"]["runtime"]["increment_seed"])
        self.assertIn("comparison", rec)

    def test_scenario_07_graceful_validation_recovery_and_resubmission(self):
        """Scenario 7: Graceful Validation Recovery & Resubmission (F4-F6, F11, F12, F14)."""
        # Step 1: Submit invalid config (steps=0, strength=2.0)
        invalid_payload = {
            "generation": {"images": [str(self.images[0])], "steps": 0, "strength": 2.0},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        val1 = self.client.post("/api/config/validate", json=invalid_payload).json()
        self.assertFalse(val1["valid"])
        self.assertGreaterEqual(len(val1["errors"]), 1)

        # Server is alive and responsive
        h = self.client.get("/api/health")
        self.assertEqual(h.status_code, 200)

        # Step 2: Correct config and resubmit
        valid_payload = {
            "generation": {"images": [str(self.images[0])], "steps": 25, "strength": 0.9},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        val2 = self.client.post("/api/config/validate", json=valid_payload).json()
        self.assertTrue(val2["valid"])

        # Step 3: Run succeeds
        run_resp = self.client.post("/api/run", json=valid_payload)
        self.assertEqual(run_resp.status_code, 200)

    def test_scenario_08_large_file_upload_and_immediate_inference(self):
        """Scenario 8: File Upload (.safetensors) and Immediate Selection (F8-F12, F14)."""
        # Upload new safetensors model weights
        file_bytes = b"SAFETENSORS_PAYLOAD_" * 50
        files = {"file": ("custom_finetune.safetensors", file_bytes, "application/octet-stream")}
        up = self.client.post("/api/models/upload", files=files).json()
        self.assertTrue(up["success"])

        # Check models endpoint immediately lists it
        m_names = [m["name"] for m in self.client.get("/api/models").json()["models"]]
        self.assertIn("custom_finetune.safetensors", m_names)

        # Run immediately using uploaded weights
        payload = {
            "model": {"source": str(self.models_dir / "custom_finetune.safetensors")},
            "generation": {"images": [str(self.images[0])]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{run_resp.json()['run_id']}").json()
        self.assertEqual(rec["status"], "success")


if __name__ == "__main__":
    unittest.main()
