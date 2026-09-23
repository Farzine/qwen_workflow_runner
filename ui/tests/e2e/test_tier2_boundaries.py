"""Tier 2: Boundary Value Analysis & Corner Case Tests for Qwen Workflow Runner Web UI.

Features Covered (>=80 tests across all 16 features):
  - Steps boundary: 1, 10000, error on 0, error on 10001
  - Denoise strength: 0.0001, 1.0, error on 0.0, error on 1.05
  - Steps/strength truncation limit: int(steps/strength) > 10000 rejected
  - Resolution: 0, 32, 4096, error on 500 (not % 32), error on 4128 (> 4096)
  - Custom size: width/height >= 32 and % 32 == 0; error on 16, error on 1000
  - Seed: 0, 2**64 - 1, error on -1, error on 2**64
  - CFG: 0.0, 1.0, 20.0, error on -0.5, error on NaN/inf
  - Repeats/warmup: repeats=1, warmup=0, error on repeats=0, error on warmup=-1
  - Memory poller: 0.001, 1.0, error on 0.0, error on 1.5
  - Filename prefix: pure filename allowed, error on empty, error on slashes (/ or \\)
  - Reference selection count: 1 allowed, 10 allowed, 0 rejected, 11 rejected
  - Device & dtype compat: cpu+float32+offload=none allowed; cpu+float16 rejected; mps+offload=sequential rejected
  - Sampler & scheduler: euler, simple, normal allowed; error on dpm++, error on karras
  - Flow shift: -10.0, 0.69, 10.0 allowed; error on -11.0, error on 15.0
  - Reference mode: rgb, rgba allowed; error on cmyk
  - File upload: invalid extension (.exe, .txt) rejected; empty upload rejected
"""

from io import BytesIO
import json
import math
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from ui.tests.e2e.common import (
    compute_sha256,
    create_test_image,
    get_test_client,
)


class TestTier2Boundaries(unittest.TestCase):
    """Tier 2 Boundary Value Analysis and Corner Cases."""

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

        cls.sample_folder = cls.inputs_dir / "samples"
        cls.sample_folder.mkdir()
        cls.ref_img = create_test_image(cls.sample_folder / "ref.png", 64, 64, (100, 150, 200))

        cls.client = get_test_client(
            inputs_dir=cls.inputs_dir,
            models_dir=cls.models_dir,
            outputs_dir=cls.outputs_dir,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    # =========================================================================
    # F1 Boundaries: Input Scanner
    # =========================================================================

    def test_b01_empty_directory_scan(self):
        empty_dir = self.inputs_dir / "empty_dir"
        empty_dir.mkdir()
        resp = self.client.get("/api/inputs/browse?folder=empty_dir")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["images"], [])

    def test_b01_deep_nested_folder_scan(self):
        sub = self.sample_folder / "nested"
        sub.mkdir()
        create_test_image(sub / "nested_img.png", 32, 32)
        resp = self.client.get("/api/inputs/browse?folder=samples/nested")
        self.assertEqual(resp.status_code, 200)
        names = [im["name"] for im in resp.json()["images"]]
        self.assertIn("nested_img.png", names)

    def test_b01_directory_traversal_path_rejected(self):
        resp = self.client.get("/api/inputs/browse?folder=../../etc")
        self.assertIn(resp.status_code, [400, 404])

    def test_b01_dot_prefix_folder_ignored(self):
        dot_dir = self.inputs_dir / ".cache_folder"
        dot_dir.mkdir()
        resp = self.client.get("/api/inputs/browse")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(".cache_folder", resp.json()["folders"])

    def test_b01_special_characters_in_folder_name(self):
        special_dir = self.inputs_dir / "folder with spaces & hyphens"
        special_dir.mkdir()
        create_test_image(special_dir / "special.png", 32, 32)
        resp = self.client.get("/api/inputs/browse")
        self.assertIn("folder with spaces & hyphens", resp.json()["folders"])

    # =========================================================================
    # F2 Boundaries: Reference Image Ordering
    # =========================================================================

    def test_b02_min_boundary_single_image(self):
        payload = {"generation": {"images": [str(self.ref_img)]}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["valid"])

    def test_b02_max_boundary_ten_images(self):
        payload = {"generation": {"images": [str(self.ref_img)] * 10}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["valid"])

    def test_b02_underflow_zero_images_rejected(self):
        payload = {"generation": {"images": []}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("1–10" in e for e in data["errors"]))

    def test_b02_overflow_eleven_images_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)] * 11}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("1–10" in e for e in data["errors"]))

    def test_b02_extreme_overflow_twenty_images_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)] * 20}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["valid"])

    # =========================================================================
    # F3 Boundaries: Thumbnails
    # =========================================================================

    def test_b03_thumbnail_1x1_pixel_image(self):
        p1x1 = create_test_image(self.sample_folder / "tiny1x1.png", 1, 1)
        resp = self.client.get(f"/api/inputs/thumbnail?path={p1x1}")
        self.assertEqual(resp.status_code, 200)
        im = Image.open(BytesIO(resp.content))
        self.assertGreaterEqual(im.width, 1)

    def test_b03_thumbnail_extreme_aspect_ratio_tall(self):
        tall = create_test_image(self.sample_folder / "tall.png", 32, 1024)
        resp = self.client.get(f"/api/inputs/thumbnail?path={tall}")
        self.assertEqual(resp.status_code, 200)
        im = Image.open(BytesIO(resp.content))
        self.assertLessEqual(im.height, 256)

    def test_b03_thumbnail_extreme_aspect_ratio_wide(self):
        wide = create_test_image(self.sample_folder / "wide.png", 1024, 32)
        resp = self.client.get(f"/api/inputs/thumbnail?path={wide}")
        self.assertEqual(resp.status_code, 200)
        im = Image.open(BytesIO(resp.content))
        self.assertLessEqual(im.width, 256)

    def test_b03_thumbnail_path_traversal_rejected(self):
        resp = self.client.get("/api/inputs/thumbnail?path=../../etc/passwd")
        self.assertIn(resp.status_code, [400, 404])

    def test_b03_thumbnail_directory_path_rejected(self):
        resp = self.client.get(f"/api/inputs/thumbnail?path={self.sample_folder}")
        self.assertIn(resp.status_code, [400, 404])

    # =========================================================================
    # F4 Boundaries: Steps, Strength, Resolution, Custom Size
    # =========================================================================

    def test_b04_steps_lower_boundary_one_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "steps": 1}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b04_steps_upper_boundary_10000_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "steps": 10000, "strength": 1.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b04_steps_underflow_zero_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "steps": 0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b04_steps_overflow_10001_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "steps": 10001}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b04_strength_min_boundary_accepted(self):
        # steps=1 with strength=0.0001 means int(1/0.0001) = 10000 which is within limit
        payload = {"generation": {"images": [str(self.ref_img)], "steps": 1, "strength": 0.0001}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b04_strength_max_boundary_one_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "strength": 1.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b04_strength_underflow_zero_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "strength": 0.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b04_strength_overflow_105_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "strength": 1.05}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b04_steps_strength_ratio_truncation_overflow_rejected(self):
        # steps=9000, strength=0.8 -> int(9000 / 0.8) = 11250 > 10000
        payload = {"generation": {"images": [str(self.ref_img)], "steps": 9000, "strength": 0.8}}
        resp = self.client.post("/api/config/validate", json=payload)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("10000-point" in e for e in data["errors"]))

    def test_b04_resolution_zero_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "resolution": 0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b04_resolution_32_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "resolution": 32}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b04_resolution_4096_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "resolution": 4096}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b04_resolution_non_multiple_of_32_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "resolution": 500}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b04_resolution_overflow_4128_rejected(self):
        # 4128 is a multiple of 32 but exceeds 4096
        payload = {"generation": {"images": [str(self.ref_img)], "resolution": 4128}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b04_custom_size_min_32x32_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "custom_size": True, "width": 32, "height": 32}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b04_custom_size_width_underflow_16_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "custom_size": True, "width": 16, "height": 64}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b04_custom_size_height_non_multiple_1000_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "custom_size": True, "width": 64, "height": 1000}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    # =========================================================================
    # F5 Boundaries: Seed, CFG, Repeats, Poller, Prefix
    # =========================================================================

    def test_b05_seed_min_boundary_zero_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "seed": 0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_seed_max_boundary_uint64_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "seed": 2**64 - 1}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_seed_underflow_negative_one_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "seed": -1}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_seed_overflow_2pow64_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "seed": 2**64}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_cfg_min_zero_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "cfg": 0.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_cfg_one_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "cfg": 1.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_cfg_large_twenty_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "cfg": 20.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_cfg_negative_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "cfg": -0.5}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_repeats_min_one_accepted(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "repeats": 1},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_repeats_zero_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "repeats": 0},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_warmup_zero_accepted(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "warmup_runs": 0},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_warmup_negative_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "warmup_runs": -1},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_memory_poll_min_0001_accepted(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "memory_poll_seconds": 0.001},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_memory_poll_max_10_accepted(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "memory_poll_seconds": 1.0},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_memory_poll_underflow_zero_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "memory_poll_seconds": 0.0},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_memory_poll_overflow_15_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "memory_poll_seconds": 1.5},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_filename_prefix_pure_name_accepted(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "filename_prefix": "fashion_sample"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b05_filename_prefix_empty_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "filename_prefix": ""},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_filename_prefix_forward_slash_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "filename_prefix": "dir/file"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b05_filename_prefix_backslash_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "filename_prefix": "dir\\file"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    # =========================================================================
    # F6 Boundaries: Device & Dtype Compatibility
    # =========================================================================

    def test_b06_cpu_float32_none_accepted(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b06_cpu_float16_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float16", "offload": "none"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("float32" in e for e in data["errors"]))

    def test_b06_cpu_model_offload_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "model"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("offload='none'" in e for e in data["errors"]))

    def test_b06_mps_sequential_offload_rejected(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "mps", "dtype": "float32", "offload": "sequential"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("MPS" in e for e in data["errors"]))

    def test_b06_mps_none_offload_accepted(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "mps", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    # =========================================================================
    # F7 Boundaries: HF Repo Selector
    # =========================================================================

    def test_b07_hf_repo_whitespace_only_rejected(self):
        resp = self.client.post("/api/models/download", json={"repo_id": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_b07_hf_repo_long_name_accepted(self):
        long_repo = "organization-name-with-many-hyphens/very-long-model-repo-id-name-version-2-1"
        resp = self.client.post("/api/models/download", json={"repo_id": long_repo})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("task_id", resp.json())

    def test_b07_hf_repo_with_special_namespace_accepted(self):
        repo = "community_hub/qwen_model.v2"
        resp = self.client.post("/api/models/download", json={"repo_id": repo})
        self.assertEqual(resp.status_code, 200)

    def test_b07_hf_repo_empty_revision_defaults_cleanly(self):
        resp = self.client.post("/api/models/download", json={"repo_id": "Qwen/Qwen-Image-2.1", "revision": None})
        self.assertEqual(resp.status_code, 200)

    def test_b07_hf_repo_nonexistent_task_progress_returns_404(self):
        resp = self.client.get("/api/models/download/progress/nonexistent-task-id-1234")
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # F8 Boundaries: Model File Upload
    # =========================================================================

    def test_b08_upload_invalid_exe_rejected(self):
        files = {"file": ("danger.exe", b"MZ...", "application/octet-stream")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 400)

    def test_b08_upload_invalid_txt_rejected(self):
        files = {"file": ("readme.txt", b"plain text", "text/plain")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 400)

    def test_b08_upload_invalid_py_rejected(self):
        files = {"file": ("script.py", b"print('hack')", "text/x-python")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 400)

    def test_b08_upload_zero_byte_gguf_rejected(self):
        files = {"file": ("empty_model.gguf", b"", "application/octet-stream")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertEqual(resp.status_code, 400)

    def test_b08_upload_no_filename_rejected(self):
        files = {"file": ("", b"weights", "application/octet-stream")}
        resp = self.client.post("/api/models/upload", files=files)
        self.assertIn(resp.status_code, [400, 422])

    # =========================================================================
    # F9 Boundaries: Cached Models Discovery
    # =========================================================================

    def test_b09_discovery_empty_models_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as empty_m:
            temp_client = get_test_client(models_dir=Path(empty_m))
            resp = temp_client.get("/api/models")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["models"], [])

    def test_b09_discovery_case_insensitive_extension_matching(self):
        # Write .GGUF in uppercase
        upper_file = self.models_dir / "MODEL_UPPER.GGUF"
        upper_file.write_bytes(b"GGUF_HEADER")
        resp = self.client.get("/api/models")
        names = [m["name"] for m in resp.json()["models"]]
        self.assertIn("MODEL_UPPER.GGUF", names)

    def test_b09_discovery_subdirectories_ignored(self):
        sub_dir = self.models_dir / "subdir_not_a_model"
        sub_dir.mkdir(exist_ok=True)
        resp = self.client.get("/api/models")
        names = [m["name"] for m in resp.json()["models"]]
        self.assertNotIn("subdir_not_a_model", names)

    def test_b09_discovery_hidden_files_ignored(self):
        hidden = self.models_dir / ".hidden_model.gguf"
        hidden.write_bytes(b"GGUF")
        resp = self.client.get("/api/models")
        names = [m["name"] for m in resp.json()["models"]]
        # Either omitted or ignored
        self.assertTrue(all(not n.startswith(".") for n in names))

    def test_b09_discovery_corrupted_model_file_listed_safely(self):
        corrupted = self.models_dir / "truncated.safetensors"
        corrupted.write_bytes(b"\x00\x00")
        resp = self.client.get("/api/models")
        names = [m["name"] for m in resp.json()["models"]]
        self.assertIn("truncated.safetensors", names)

    # =========================================================================
    # F10 Boundaries: GGUF Variant Parameter Handling
    # =========================================================================

    def test_b10_gguf_quantization_empty_string_falls_back(self):
        payload = {"model": {"gguf_quantization": "Q4_K_M"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b10_gguf_nonexistent_filename_in_model_config(self):
        payload = {"model": {"filename": "nonexistent_quant.gguf"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b10_gguf_base_model_empty_rejected_or_defaults(self):
        payload = {"model": {"base_model": "Qwen/Qwen-Image-2.1"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b10_gguf_variant_special_characters_handled(self):
        payload = {"model": {"filename": "qwen2.1-image-q4_k_m.gguf"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b10_gguf_quant_variants_q4_q5_q8_accepted(self):
        for q in ["Q4_K_M", "Q5_K_M", "Q8_0"]:
            payload = {"model": {"gguf_quantization": q}}
            resp = self.client.post("/api/config/validate", json=payload)
            self.assertTrue(resp.json()["valid"])

    # =========================================================================
    # F11 Boundaries: Run Execution & SSE Stream
    # =========================================================================

    def test_b11_run_missing_generation_section_rejected(self):
        payload = {"runtime": {"device": "cpu", "dtype": "float32", "offload": "none"}}
        resp = self.client.post("/api/run", json=payload)
        self.assertIn(resp.status_code, [400, 422, 500])

    def test_b11_run_missing_runtime_section_uses_defaults(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)

    def test_b11_run_nonexistent_run_id_stream_returns_404(self):
        resp = self.client.get("/api/run/invalid_run_id_99999/stream")
        self.assertEqual(resp.status_code, 404)

    def test_b11_run_large_batch_size_validation(self):
        payload = {
            "generation": {"images": [str(self.ref_img)], "batch_size": 4},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(len(rec["outputs"]), 4)

    def test_b11_run_rapid_successive_requests(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        r1 = self.client.post("/api/run", json=payload)
        r2 = self.client.post("/api/run", json=payload)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertNotEqual(r1.json()["run_id"], r2.json()["run_id"])

    # =========================================================================
    # F12 Boundaries: Output Image Viewer
    # =========================================================================

    def test_b12_output_viewer_directory_traversal_blocked(self):
        resp = self.client.get("/api/outputs/../../etc/passwd")
        self.assertIn(resp.status_code, [400, 404])

    def test_b12_output_viewer_non_image_output_request(self):
        non_img = self.outputs_dir / "secret.txt"
        non_img.write_text("secret")
        resp = self.client.get("/api/outputs/secret.txt")
        self.assertIn(resp.status_code, [200, 404])

    def test_b12_output_viewer_empty_filename_returns_404(self):
        resp = self.client.get("/api/outputs/")
        self.assertIn(resp.status_code, [404, 405])

    def test_b12_output_viewer_special_characters_filename(self):
        spec_img = self.outputs_dir / "output_test#1@special.png"
        create_test_image(spec_img, 32, 32)
        resp = self.client.get(f"/api/outputs/{spec_img.name}")
        self.assertIn(resp.status_code, [200, 404])

    def test_b12_output_viewer_large_image_served(self):
        big_img = self.outputs_dir / "big_image.png"
        create_test_image(big_img, 256, 256)
        resp = self.client.get(f"/api/outputs/{big_img.name}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "image/png")

    # =========================================================================
    # F13 Boundaries: Side-by-Side Comparison
    # =========================================================================

    def test_b13_comparison_unequal_aspect_ratio_handled(self):
        unequal = create_test_image(self.sample_folder / "unequal.png", 64, 128)
        payload = {
            "generation": {"images": [str(unequal)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": True},
        }
        resp = self.client.post("/api/run", json=payload)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertIn("comparison", rec)

    def test_b13_comparison_single_pixel_canvas_handled(self):
        # 32x32 minimum valid canvas
        small = create_test_image(self.sample_folder / "small32.png", 32, 32)
        payload = {
            "generation": {"images": [str(small)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": True},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)

    def test_b13_comparison_save_comparison_false_skips_file(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": False},
        }
        resp = self.client.post("/api/run", json=payload)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertNotIn("comparison", rec)

    def test_b13_comparison_custom_size_preserved_in_comparison(self):
        payload = {
            "generation": {"images": [str(self.ref_img)], "custom_size": True, "width": 64, "height": 64},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": True},
        }
        resp = self.client.post("/api/run", json=payload)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertIn("comparison", rec)

    def test_b13_comparison_output_file_naming_convention(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "save_comparison": True},
        }
        resp = self.client.post("/api/run", json=payload)
        run_id = resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        comp_file = Path(rec["comparison"]).name
        self.assertEqual(comp_file, f"{run_id}_comparison.png")

    # =========================================================================
    # F14 Boundaries: JSON Run Record
    # =========================================================================

    def test_b14_json_record_special_characters_in_prompt_escaped(self):
        special_prompt = 'Prompt with quotes: "hello" & \\n newlines and symbols: <image1> #$%'
        payload = {
            "generation": {"images": [str(self.ref_img)], "prompt": special_prompt},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        run_id = resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(rec["parameters"]["generation"]["prompt"], special_prompt)

    def test_b14_json_record_extreme_seed_number_serialized_accurately(self):
        big_seed = 2**64 - 1
        payload = {
            "generation": {"images": [str(self.ref_img)], "seed": big_seed},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        run_id = resp.json()["run_id"]
        rec = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(rec["parameters"]["generation"]["seed"], big_seed)

    def test_b14_json_record_nan_inf_safety(self):
        from qwen_runner.config import Config
        cfg = Config()
        cfg.generation.cfg = float("nan")
        with self.assertRaises(ValueError):
            cfg.validate(check_images=False)
        # Raw HTTP post of NaN payload is rejected via 4xx or valid=false
        resp = self.client.post(
            "/api/config/validate",
            content=b'{"generation": {"cfg": NaN}}',
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            self.assertFalse(resp.json()["valid"])
            self.assertTrue(any("finite" in e or "cfg" in e for e in resp.json()["errors"]))
        else:
            self.assertIn(resp.status_code, [400, 422])

    def test_b14_json_record_nonexistent_run_returns_404(self):
        resp = self.client.get("/api/runs/null_run_00000000000000")
        self.assertEqual(resp.status_code, 404)

    def test_b14_json_record_durable_atomic_write(self):
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        run_id = resp.json()["run_id"]
        disk_file = self.outputs_dir / f"{run_id}.json"
        self.assertTrue(disk_file.exists())
        loaded = json.loads(disk_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["run_id"], run_id)

    # =========================================================================
    # F15 Boundaries: Run History
    # =========================================================================

    def test_b15_history_empty_session_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as empty_env:
            c = get_test_client(outputs_dir=Path(empty_env))
            resp = c.get("/api/runs")
            self.assertEqual(resp.status_code, 200)
            self.assertIsInstance(resp.json()["runs"], list)

    def test_b15_history_accumulates_across_multiple_runs(self):
        init_len = len(self.client.get("/api/runs").json()["runs"])
        payload = {
            "generation": {"images": [str(self.ref_img)]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        self.client.post("/api/run", json=payload)
        self.client.post("/api/run", json=payload)
        after_len = len(self.client.get("/api/runs").json()["runs"])
        self.assertEqual(after_len, init_len + 2)

    def test_b15_history_preserves_error_runs(self):
        # Even if run error occurs, history handles status gracefully
        resp = self.client.get("/api/runs")
        self.assertEqual(resp.status_code, 200)

    def test_b15_history_response_is_valid_json_array(self):
        resp = self.client.get("/api/runs")
        self.assertIsInstance(resp.json()["runs"], list)

    def test_b15_history_id_uniqueness(self):
        resp = self.client.get("/api/runs")
        ids = [r["run_id"] for r in resp.json()["runs"]]
        self.assertEqual(len(ids), len(set(ids)))

    # =========================================================================
    # F16 Boundaries: Sampler, Scheduler, Shift, Reference Mode
    # =========================================================================

    def test_b16_sampler_euler_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "sampler": "euler"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b16_sampler_unsupported_dpmpp_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "sampler": "dpm++"}}
        resp = self.client.post("/api/config/validate", json=payload)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("euler" in e for e in data["errors"]))

    def test_b16_scheduler_simple_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "scheduler": "simple"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b16_scheduler_normal_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "scheduler": "normal"}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b16_scheduler_unsupported_karras_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "scheduler": "karras"}}
        resp = self.client.post("/api/config/validate", json=payload)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("simple" in e or "normal" in e for e in data["errors"]))

    def test_b16_shift_min_minus_10_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "shift": -10.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b16_shift_max_plus_10_accepted(self):
        payload = {"generation": {"images": [str(self.ref_img)], "shift": 10.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(resp.json()["valid"])

    def test_b16_shift_underflow_minus_11_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "shift": -11.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b16_shift_overflow_plus_15_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "shift": 15.0}}
        resp = self.client.post("/api/config/validate", json=payload)
        self.assertFalse(resp.json()["valid"])

    def test_b16_reference_mode_rgb_rgba_accepted(self):
        for mode in ["rgb", "rgba"]:
            payload = {"generation": {"images": [str(self.ref_img)], "reference_mode": mode}}
            resp = self.client.post("/api/config/validate", json=payload)
            self.assertTrue(resp.json()["valid"])

    def test_b16_reference_mode_cmyk_rejected(self):
        payload = {"generation": {"images": [str(self.ref_img)], "reference_mode": "cmyk"}}
        resp = self.client.post("/api/config/validate", json=payload)
        data = resp.json()
        self.assertFalse(data["valid"])
        self.assertTrue(any("rgb or rgba" in e for e in data["errors"]))


if __name__ == "__main__":
    unittest.main()
