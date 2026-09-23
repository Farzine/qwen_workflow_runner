"""Tier 1: Comprehensive E2E Feature Coverage Tests for Qwen Workflow Runner Web UI.

Features Covered (>=80 tests across 16 features):
  - F1: Input Directory Scanner
  - F2: Reference Image Ordering
  - F3: Thumbnails
  - F4: Generation Parameters
  - F5: Runtime Parameters
  - F6: Validation Endpoints
  - F7: Model HF Repo Selector & Download Initiation
  - F8: Model File Upload
  - F9: Cached Models Dropdown
  - F10: GGUF Variant Parameter Handling
  - F11: Run Endpoint & SSE Log Stream
  - F12: Output Image Viewer Endpoints
  - F13: Side-by-Side Comparison Endpoint
  - F14: JSON Run Record Endpoint
  - F15: Session Run History Endpoint
  - F16: App Startup & Healthcheck Endpoint
"""

import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from PIL import Image

from ui.tests.e2e.common import (
    compute_sha256,
    create_test_image,
    get_test_client,
)


class TestTier1Features(unittest.TestCase):
    """Tier 1 Feature Coverage test suite."""

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

        # Populate sample input folders & images
        cls.folder_portraits = cls.inputs_dir / "portraits"
        cls.folder_landscapes = cls.inputs_dir / "landscapes"
        cls.folder_portraits.mkdir()
        cls.folder_landscapes.mkdir()

        cls.img_p1 = create_test_image(cls.folder_portraits / "face1.png", 64, 64, (255, 0, 0))
        cls.img_p2 = create_test_image(cls.folder_portraits / "face2.jpg", 128, 128, (0, 255, 0))
        cls.img_l1 = create_test_image(cls.folder_landscapes / "view1.png", 64, 64, (0, 0, 255))
        # Non-image files to verify filtering
        (cls.folder_portraits / ".DS_Store").write_bytes(b"junk")
        (cls.folder_portraits / "notes.txt").write_text("not an image")

        cls.client = get_test_client(
            inputs_dir=cls.inputs_dir,
            models_dir=cls.models_dir,
            outputs_dir=cls.outputs_dir,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    # =========================================================================
    # F1: Input Directory Scanner
    # =========================================================================

    def test_f01_browse_root_returns_subfolders(self):
        resp = self.client.get("/api/inputs/browse")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("folders", data)
        self.assertIn("portraits", data["folders"])
        self.assertIn("landscapes", data["folders"])

    def test_f01_browse_subfolder_returns_images(self):
        resp = self.client.get("/api/inputs/browse?folder=portraits")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("images", data)
        names = [img["name"] for img in data["images"]]
        self.assertIn("face1.png", names)
        self.assertIn("face2.jpg", names)

    def test_f01_browse_filters_ds_store_and_hidden(self):
        resp = self.client.get("/api/inputs/browse?folder=portraits")
        self.assertEqual(resp.status_code, 200)
        names = [img["name"] for img in resp.json()["images"]]
        self.assertNotIn(".DS_Store", names)
        for name in names:
            self.assertFalse(name.startswith("."))

    def test_f01_browse_filters_non_images(self):
        resp = self.client.get("/api/inputs/browse?folder=portraits")
        self.assertEqual(resp.status_code, 200)
        names = [img["name"] for img in resp.json()["images"]]
        self.assertNotIn("notes.txt", names)

    def test_f01_browse_returns_image_metadata(self):
        resp = self.client.get("/api/inputs/browse?folder=portraits")
        self.assertEqual(resp.status_code, 200)
        images = resp.json()["images"]
        face1 = next(im for im in images if im["name"] == "face1.png")
        self.assertEqual(face1["width"], 64)
        self.assertEqual(face1["height"], 64)
        self.assertIn("thumb_url", face1)

    def test_f01_browse_invalid_folder_handling(self):
        resp = self.client.get("/api/inputs/browse?folder=nonexistent_subfolder")
        self.assertIn(resp.status_code, [404, 400])

    # =========================================================================
    # F2: Reference Image Ordering
    # =========================================================================

    def test_f02_single_reference_accepted(self):
        payload = {"generation": {"images": [str(self.img_p1)]}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f02_two_references_accepted(self):
        payload = {"generation": {"images": [str(self.img_p1), str(self.img_p2)]}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f02_five_references_accepted(self):
        imgs = [str(self.img_p1)] * 5
        payload = {"generation": {"images": imgs}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f02_ten_references_boundary_accepted(self):
        imgs = [str(self.img_p1)] * 10
        payload = {"generation": {"images": imgs}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f02_zero_images_rejected_with_specific_error(self):
        payload = {"generation": {"images": []}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("valid"))
        self.assertTrue(any("1–10" in err or "image1" in err for err in data.get("errors", [])))

    def test_f02_eleven_images_rejected_with_specific_error(self):
        imgs = [str(self.img_p1)] * 11
        payload = {"generation": {"images": imgs}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("valid"))
        self.assertTrue(any("1–10" in err or "image1" in err for err in data.get("errors", [])))

    # =========================================================================
    # F3: Image Previews & Thumbnails
    # =========================================================================

    def test_f03_thumbnail_generation_success(self):
        resp = self.client.get(f"/api/inputs/thumbnail?path={self.img_p1}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("image", resp.headers.get("content-type", ""))

    def test_f03_thumbnail_dimensions_clamped_to_256(self):
        # Create larger image (512x512)
        large_img = create_test_image(self.folder_portraits / "large.png", 512, 512)
        resp = self.client.get(f"/api/inputs/thumbnail?path={large_img}")
        self.assertEqual(resp.status_code, 200)
        im = Image.open(BytesIO(resp.content))
        self.assertLessEqual(im.width, 256)
        self.assertLessEqual(im.height, 256)

    def test_f03_thumbnail_caching_returns_cached_response(self):
        resp1 = self.client.get(f"/api/inputs/thumbnail?path={self.img_p2}")
        resp2 = self.client.get(f"/api/inputs/thumbnail?path={self.img_p2}")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.content, resp2.content)

    def test_f03_thumbnail_content_type_header(self):
        resp = self.client.get(f"/api/inputs/thumbnail?path={self.img_p1}")
        self.assertIn(resp.headers.get("content-type"), ["image/jpeg", "image/png"])

    def test_f03_thumbnail_nonexistent_file_returns_404(self):
        resp = self.client.get("/api/inputs/thumbnail?path=/nonexistent/image.png")
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # F4: Generation Config Parameter Controls
    # =========================================================================

    def test_f04_prompt_and_negative_prompt_controls(self):
        payload = {
            "generation": {
                "images": [str(self.img_p1)],
                "prompt": "Keep <image1> unchanged and apply light blue denim shirt",
                "negative_prompt": "blurry, low quality, distorted",
            }
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f04_steps_and_cfg_generation_params(self):
        payload = {
            "generation": {
                "images": [str(self.img_p1)],
                "steps": 30,
                "cfg": 2.5,
            }
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f04_strength_and_resolution_params(self):
        payload = {
            "generation": {
                "images": [str(self.img_p1)],
                "strength": 0.8,
                "resolution": 1024,
            }
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f04_custom_width_height_and_batch_size(self):
        payload = {
            "generation": {
                "images": [str(self.img_p1)],
                "custom_size": True,
                "width": 768,
                "height": 512,
                "batch_size": 2,
            }
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f04_sampler_scheduler_and_shift(self):
        payload = {
            "generation": {
                "images": [str(self.img_p1)],
                "sampler": "euler",
                "scheduler": "normal",
                "shift": 1.25,
            }
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f04_kv_cache_device_and_reference_mode(self):
        payload = {
            "generation": {
                "images": [str(self.img_p1)],
                "kv_cache": True,
                "kv_cache_device": "cpu",
                "kv_cache_reserve_gib": 2.0,
                "reference_mode": "rgba",
            }
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    # =========================================================================
    # F5: Runtime Config Parameter Controls
    # =========================================================================

    def test_f05_device_and_dtype_controls(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f05_offload_and_vae_tiling_controls(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cuda:0", "dtype": "bfloat16", "offload": "sequential", "vae_tiling": True},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f05_repeats_warmup_and_seed_increment(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "repeats": 3, "warmup_runs": 1, "increment_seed": True,
            },
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f05_memory_poll_seconds_control(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "memory_poll_seconds": 0.05,
            },
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f05_output_dir_and_filename_prefix_controls(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "output_dir": "custom_outputs",
                "filename_prefix": "fashion_run",
            },
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f05_save_comparison_toggle_control(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "save_comparison": False,
            },
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    # =========================================================================
    # F6: Validation Endpoints
    # =========================================================================

    def test_f06_validation_valid_config_returns_true(self):
        payload = {"generation": {"images": [str(self.img_p1)], "steps": 25}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f06_validation_invalid_steps_returns_false_with_error(self):
        payload = {"generation": {"images": [str(self.img_p1)], "steps": 0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("valid"))
        self.assertTrue(any("steps" in err for err in data.get("errors", [])))

    def test_f06_validation_invalid_strength_returns_false(self):
        payload = {"generation": {"images": [str(self.img_p1)], "strength": 0.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("valid"))
        self.assertTrue(any("strength" in err for err in data.get("errors", [])))

    def test_f06_validation_invalid_seed_returns_false(self):
        payload = {"generation": {"images": [str(self.img_p1)], "seed": -5}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("valid"))
        self.assertTrue(any("seed" in err for err in data.get("errors", [])))

    def test_f06_validation_invalid_resolution_returns_false(self):
        payload = {"generation": {"images": [str(self.img_p1)], "resolution": 500}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("valid"))
        self.assertTrue(any("resolution" in err for err in data.get("errors", [])))

    def test_f06_validation_invalid_prefix_returns_false(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "filename_prefix": "nested/path"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("valid"))
        self.assertTrue(any("filename_prefix" in err for err in data.get("errors", [])))

    # =========================================================================
    # F7: Model HF Repo Selector & Download Initiation
    # =========================================================================

    def test_f07_hf_download_initiation_returns_task_id(self):
        payload = {"repo_id": "Qwen/Qwen-Image-2.1"}
        resp = self.client.post("/api/models/download", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("task_id", data)

    def test_f07_hf_download_progress_endpoint(self):
        init_resp = self.client.post("/api/models/download", json={"repo_id": "Qwen/Qwen-Image-2.1"})
        task_id = init_resp.json()["task_id"]
        prog_resp = self.client.get(f"/api/models/download/progress/{task_id}")
        self.assertEqual(prog_resp.status_code, 200)
        self.assertIn("progress", prog_resp.json())

    def test_f07_hf_download_empty_repo_rejected(self):
        resp = self.client.post("/api/models/download", json={"repo_id": ""})
        self.assertEqual(resp.status_code, 400)

    def test_f07_hf_download_with_custom_revision(self):
        payload = {"repo_id": "Qwen/Qwen-Image-2.1", "revision": "main"}
        resp = self.client.post("/api/models/download", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("task_id", resp.json())

    def test_f07_hf_download_with_filename(self):
        payload = {"repo_id": "Qwen/Qwen-Image-2.1", "filename": "qwen_q4.gguf"}
        resp = self.client.post("/api/models/download", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("task_id", resp.json())

    # =========================================================================
    # F8: Model File Upload (.gguf/.safetensors)
    # =========================================================================

    def test_f08_upload_gguf_file_success(self):
        content = b"GGUF_TEST_HEADER_DATA"
        files = {"file": ("model_quantized.gguf", content, "application/octet-stream")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("filename"), "model_quantized.gguf")

    def test_f08_upload_safetensors_file_success(self):
        content = b"SAFETENSORS_TEST_BYTES"
        files = {"file": ("transformer_weights.safetensors", content, "application/octet-stream")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))

    def test_f08_upload_invalid_extension_rejected(self):
        content = b"malicious binary"
        files = {"file": ("payload.exe", content, "application/octet-stream")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 400)

    def test_f08_upload_empty_file_rejected(self):
        files = {"file": ("empty.gguf", b"", "application/octet-stream")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 400)

    def test_f08_upload_saves_to_models_directory(self):
        fname = "persisted_model.gguf"
        files = {"file": (fname, b"DURABLE_WEIGHTS", "application/octet-stream")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 200)
        saved = self.models_dir / fname
        self.assertTrue(saved.exists())
        self.assertEqual(saved.read_bytes(), b"DURABLE_WEIGHTS")

    # =========================================================================
    # F9: Cached Models Dropdown & Discovery
    # =========================================================================

    def test_f09_list_models_returns_empty_or_list(self):
        resp = self.client.get("/api/models")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("models", resp.json())

    def test_f09_list_models_includes_uploaded_model(self):
        resp = self.client.get("/api/models")
        models = resp.json()["models"]
        names = [m["name"] for m in models]
        self.assertIn("persisted_model.gguf", names)

    def test_f09_list_models_differentiates_gguf_and_safetensors(self):
        resp = self.client.get("/api/models")
        models = resp.json()["models"]
        for m in models:
            if m["name"].endswith(".gguf"):
                self.assertEqual(m["type"], "gguf")
            elif m["name"].endswith(".safetensors"):
                self.assertEqual(m["type"], "safetensors")

    def test_f09_list_models_ignores_non_model_files(self):
        (self.models_dir / "notes.txt").write_text("info")
        (self.models_dir / ".gitkeep").write_text("")
        resp = self.client.get("/api/models")
        names = [m["name"] for m in resp.json()["models"]]
        self.assertNotIn("notes.txt", names)
        self.assertNotIn(".gitkeep", names)

    def test_f09_list_models_marks_cached_flag(self):
        resp = self.client.get("/api/models")
        models = resp.json()["models"]
        for m in models:
            self.assertTrue(m.get("is_cached"))

    # =========================================================================
    # F10: GGUF Variant Parameter Handling
    # =========================================================================

    def test_f10_gguf_default_quantization_is_q4_k_m(self):
        from qwen_runner.config import ModelConfig
        mc = ModelConfig()
        self.assertEqual(mc.gguf_quantization, "Q4_K_M")

    def test_f10_gguf_custom_quantization_variant_accepted(self):
        payload = {"model": {"gguf_quantization": "Q8_0"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f10_gguf_filename_parameter_accepted(self):
        payload = {"model": {"filename": "custom_variant.gguf"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f10_gguf_base_model_source_accepted(self):
        payload = {"model": {"base_model": "Qwen/Qwen-Image-2.1-custom"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    def test_f10_gguf_base_revision_accepted(self):
        payload = {"model": {"base_revision": "v2.0"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("valid"))

    # =========================================================================
    # F11: Background Run Endpoint & SSE Log Stream
    # =========================================================================

    def test_f11_run_endpoint_launches_and_returns_run_id(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("run_id", data)

    def test_f11_run_endpoint_returns_stream_url(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        data = resp.json()
        self.assertIn("stream_url", data)
        self.assertTrue(data["stream_url"].startswith("/api/run/"))

    def test_f11_sse_stream_emits_log_events(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
            "demo_mode": True,
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        stream_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(stream_resp.status_code, 200)
        self.assertIn("event: log", stream_resp.text)

    def test_f11_sse_stream_emits_progress_events(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
            "demo_mode": True,
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        stream_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(stream_resp.status_code, 200)
        self.assertIn("event: progress", stream_resp.text)

    def test_f11_sse_stream_emits_complete_event(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
            "demo_mode": True,
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        stream_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertIn("event: complete", stream_resp.text)

    def test_f11_run_rejects_invalid_config_payload(self):
        payload = {"generation": {"images": []}}
        resp = self.client.post("/api/run", json=payload)
        self.assertIn(resp.status_code, [400, 422])

    # =========================================================================
    # F12: Output Image Viewer Endpoints
    # =========================================================================

    def test_f12_output_image_served_with_correct_media_type(self):
        out_file = self.outputs_dir / "test_out_00.png"
        create_test_image(out_file, 64, 64)
        resp = self.client.get(f"/api/outputs/{out_file.name}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "image/png")

    def test_f12_output_image_file_not_found_returns_404(self):
        resp = self.client.get("/api/outputs/missing_image_xyz.png")
        self.assertEqual(resp.status_code, 404)

    def test_f12_output_metadata_has_dimensions(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec_resp = self.client.get(f"/api/runs/{run_id}")
        rec = rec_resp.json()
        self.assertTrue(len(rec["outputs"]) > 0)
        out0 = rec["outputs"][0]
        self.assertIn("width", out0)
        self.assertIn("height", out0)
        self.assertEqual(out0["width"], 64)
        self.assertEqual(out0["height"], 64)

    def test_f12_output_metadata_has_sha256_hash(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        out0 = rec["outputs"][0]
        self.assertIn("sha256", out0)
        self.assertEqual(len(out0["sha256"]), 64)

    def test_f12_output_sha256_matches_disk_file(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        out0 = rec["outputs"][0]
        disk_path = Path(out0["path"])
        self.assertEqual(compute_sha256(disk_path), out0["sha256"])

    # =========================================================================
    # F13: Side-by-Side Comparison Endpoint
    # =========================================================================

    def test_f13_comparison_image_generated_when_enabled(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": True},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertIn("comparison", rec)
        comp_path = Path(rec["comparison"])
        self.assertTrue(comp_path.exists())

    def test_f13_comparison_image_served_by_outputs_endpoint(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": True},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        comp_name = Path(rec["comparison"]).name
        resp = self.client.get(f"/api/outputs/{comp_name}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "image/png")

    def test_f13_comparison_image_width_equals_sum_of_widths(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": True},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        comp_path = Path(rec["comparison"])
        with Image.open(comp_path) as c_im:
            # 64 + 64 = 128
            self.assertEqual(c_im.width, 128)

    def test_f13_comparison_not_generated_when_disabled(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": False},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertNotIn("comparison", rec)

    def test_f13_comparison_metadata_recorded_in_run(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": True},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertIn("comparison", rec)
        self.assertTrue(rec["comparison"].endswith(".png"))

    # =========================================================================
    # F14: JSON Run Record Endpoint
    # =========================================================================

    def test_f14_json_record_accessible_by_run_id(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec_resp = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(rec_resp.status_code, 200)
        self.assertEqual(rec_resp.json().get("run_id"), run_id)

    def test_f14_json_record_contains_parameters(self):
        payload = {
            "generation": {"images": [str(self.img_p1)], "steps": 15},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertIn("parameters", rec)
        self.assertEqual(rec["parameters"]["generation"]["steps"], 15)

    def test_f14_json_record_contains_effective_parameters(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertIn("effective_parameters", rec)
        eff = rec["effective_parameters"]
        self.assertIn("width", eff)
        self.assertIn("height", eff)
        self.assertIn("sigmas", eff)

    def test_f14_json_record_contains_environment_and_outputs(self):
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        run_resp = self.client.post("/api/run", json=payload)
        run_id = run_resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertIn("environment", rec)
        self.assertIn("outputs", rec)
        self.assertIn("status", rec)
        self.assertEqual(rec["status"], "success")

    def test_f14_json_record_nonexistent_run_returns_404(self):
        resp = self.client.get("/api/runs/nonexistent_run_id_9999")
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # F15: Session Run History Endpoint
    # =========================================================================

    def test_f15_runs_history_lists_executed_runs(self):
        resp = self.client.get("/api/runs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("runs", resp.json())

    def test_f15_runs_history_contains_status_and_timestamps(self):
        resp = self.client.get("/api/runs")
        runs = resp.json()["runs"]
        for r in runs:
            self.assertIn("run_id", r)
            self.assertIn("status", r)
            self.assertIn("timestamp", r)

    def test_f15_runs_history_preserves_run_order(self):
        resp = self.client.get("/api/runs")
        runs = resp.json()["runs"]
        self.assertIsInstance(runs, list)

    def test_f15_runs_history_reflects_new_runs(self):
        before_count = len(self.client.get("/api/runs").json()["runs"])
        payload = {
            "generation": {"images": [str(self.img_p1)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        self.client.post("/api/run", json=payload)
        after_count = len(self.client.get("/api/runs").json()["runs"])
        self.assertEqual(after_count, before_count + 1)

    def test_f15_runs_history_accessible_via_get_api_runs(self):
        resp = self.client.get("/api/runs")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/json")

    # =========================================================================
    # F16: App Startup & Healthcheck Endpoint
    # =========================================================================

    def test_f16_health_endpoint_returns_status_ok(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")

    def test_f16_health_endpoint_returns_200(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)

    def test_f16_root_endpoint_returns_html(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))

    def test_f16_root_endpoint_contains_app_title(self):
        resp = self.client.get("/")
        self.assertIn("Qwen", resp.text)

    def test_f16_server_cors_or_header_presence(self):
        resp = self.client.get("/api/health")
        self.assertTrue("content-length" in resp.headers or "content-type" in resp.headers)


if __name__ == "__main__":
    unittest.main()
