"""Tier 3: Pairwise Combinatorial Feature Testing for Qwen Workflow Runner Web UI.

Contains >=16 pairwise combination tests combining orthogonal parameter spaces:
  - Custom size vs resolution
  - KV cache device vs offload mode
  - Comparison saving vs repeats
  - Scheduler vs flow shift & CFG
  - Reference mode vs batch size
  - Seed incrementation vs repeats
  - VAE tiling vs custom aspect ratios
  - GGUF variant options vs base model configurations
  - Memory polling frequency vs repeats
  - Multi-image reference counts vs output comparisons
"""

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


class TestTier3Pairwise(unittest.TestCase):
    """Tier 3 Pairwise Combinatorial Tests."""

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

        cls.sample_folder = cls.inputs_dir / "pairwise_samples"
        cls.sample_folder.mkdir()
        cls.ref_images = [
            create_test_image(cls.sample_folder / f"ref_{i:02d}.png", 64, 64, (50 + i * 20, 100, 150))
            for i in range(10)
        ]

        cls.client = get_test_client(
            inputs_dir=cls.inputs_dir,
            models_dir=cls.models_dir,
            outputs_dir=cls.outputs_dir,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_pair01_custom_size_overrides_resolution_zero(self):
        """Pair 1: custom_size=True (1024x768) + resolution=0."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "custom_size": True,
                "width": 1024,
                "height": 768,
                "resolution": 0,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        eff = rec["effective_parameters"]
        self.assertEqual(eff["width"], 1024)
        self.assertEqual(eff["height"], 768)

    def test_pair02_standard_resolution_with_custom_size_false(self):
        """Pair 2: custom_size=False + resolution=512."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "custom_size": False,
                "resolution": 512,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(rec["parameters"]["generation"]["resolution"], 512)

    def test_pair03_kv_cache_cpu_with_offload_none(self):
        """Pair 3: kv_cache=True, kv_cache_device='cpu' + offload='none'."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "kv_cache": True,
                "kv_cache_device": "cpu",
                "kv_cache_reserve_gib": 2.0,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(rec["parameters"]["generation"]["kv_cache_device"], "cpu")
        self.assertEqual(rec["parameters"]["runtime"]["offload"], "none")

    def test_pair04_kv_cache_disabled_with_custom_reserve(self):
        """Pair 4: kv_cache=False + kv_cache_reserve_gib=0.0."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "kv_cache": False,
                "kv_cache_reserve_gib": 0.0,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        val_resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(val_resp.json()["valid"])
        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)

    def test_pair05_save_comparison_true_with_repeats_two(self):
        """Pair 5: save_comparison=True + repeats=2."""
        payload = {
            "generation": {"images": [str(self.ref_images[0])]},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "save_comparison": True, "repeats": 2,
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertIn("comparison", rec)
        self.assertTrue(Path(rec["comparison"]).exists())

    def test_pair06_save_comparison_false_with_warmup_and_repeat(self):
        """Pair 6: save_comparison=False + warmup_runs=1 + repeats=1."""
        payload = {
            "generation": {"images": [str(self.ref_images[0])]},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "save_comparison": False, "warmup_runs": 1, "repeats": 1,
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertNotIn("comparison", rec)

    def test_pair07_scheduler_normal_with_positive_shift_and_cfg_half(self):
        """Pair 7: scheduler='normal' + shift=2.5 + cfg=0.5."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "scheduler": "normal",
                "shift": 2.5,
                "cfg": 0.5,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(rec["parameters"]["generation"]["scheduler"], "normal")
        self.assertEqual(rec["parameters"]["generation"]["shift"], 2.5)
        self.assertEqual(rec["parameters"]["generation"]["cfg"], 0.5)

    def test_pair08_scheduler_simple_with_negative_shift_and_high_cfg(self):
        """Pair 8: scheduler='simple' + shift=-4.0 + cfg=8.0."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "scheduler": "simple",
                "shift": -4.0,
                "cfg": 8.0,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(rec["parameters"]["generation"]["scheduler"], "simple")
        self.assertEqual(rec["parameters"]["generation"]["shift"], -4.0)

    def test_pair09_reference_mode_rgba_with_batch_size_two(self):
        """Pair 9: reference_mode='rgba' + batch_size=2."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "reference_mode": "rgba",
                "batch_size": 2,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(len(rec["outputs"]), 2)
        self.assertEqual(rec["parameters"]["generation"]["reference_mode"], "rgba")

    def test_pair10_reference_mode_rgb_with_seed_zero(self):
        """Pair 10: reference_mode='rgb' + seed=0."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "reference_mode": "rgb",
                "seed": 0,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(rec["parameters"]["generation"]["seed"], 0)

    def test_pair11_increment_seed_true_with_repeats_three(self):
        """Pair 11: increment_seed=True + repeats=3."""
        payload = {
            "generation": {"images": [str(self.ref_images[0])], "seed": 42},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "increment_seed": True, "repeats": 3,
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertTrue(rec["parameters"]["runtime"]["increment_seed"])

    def test_pair12_increment_seed_false_with_repeats_two(self):
        """Pair 12: increment_seed=False + repeats=2."""
        payload = {
            "generation": {"images": [str(self.ref_images[0])], "seed": 12345},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "increment_seed": False, "repeats": 2,
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertFalse(rec["parameters"]["runtime"]["increment_seed"])
        self.assertEqual(rec["parameters"]["generation"]["seed"], 12345)

    def test_pair13_vae_tiling_true_with_wide_aspect_ratio(self):
        """Pair 13: vae_tiling=True + custom_size (768x256)."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "custom_size": True,
                "width": 768,
                "height": 256,
            },
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "vae_tiling": True,
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertTrue(rec["parameters"]["runtime"]["vae_tiling"])
        self.assertEqual(rec["effective_parameters"]["width"], 768)
        self.assertEqual(rec["effective_parameters"]["height"], 256)

    def test_pair14_cfg_one_disables_negative_prompt(self):
        """Pair 14: cfg=1.0 with non-empty negative_prompt."""
        payload = {
            "generation": {
                "images": [str(self.ref_images[0])],
                "cfg": 1.0,
                "negative_prompt": "blurry, lowres",
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        eff = rec["effective_parameters"]
        # CFG 1.0 sets negative_prompt_active to False
        self.assertFalse(eff["negative_prompt_active"])

    def test_pair15_gguf_quant_q8_with_custom_filename_and_text_encoder(self):
        """Pair 15: gguf_quantization='Q8_0' + filename + text_encoder_source."""
        payload = {
            "model": {
                "gguf_quantization": "Q8_0",
                "filename": "qwen_q8.gguf",
                "text_encoder_source": "custom/text_encoder",
            },
            "generation": {"images": [str(self.ref_images[0])]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        val_resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(val_resp.json()["valid"])
        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{run_resp.json()['run_id']}").json()
        self.assertEqual(rec["parameters"]["model"]["gguf_quantization"], "Q8_0")
        self.assertEqual(rec["parameters"]["model"]["filename"], "qwen_q8.gguf")

    def test_pair16_gguf_base_model_with_base_revision(self):
        """Pair 16: base_model='Qwen/Qwen-Image-2.1' + base_revision='v1.2'."""
        payload = {
            "model": {
                "base_model": "Qwen/Qwen-Image-2.1",
                "base_revision": "v1.2",
            },
            "generation": {"images": [str(self.ref_images[0])]},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        val_resp = self.client.post("/api/config/validate", json=payload)
        self.assertTrue(val_resp.json()["valid"])
        run_resp = self.client.post("/api/run", json=payload)
        self.assertEqual(run_resp.status_code, 200)

    def test_pair17_high_frequency_memory_polling_with_repeats(self):
        """Pair 17: memory_poll_seconds=0.005 + repeats=2."""
        payload = {
            "generation": {"images": [str(self.ref_images[0])]},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "memory_poll_seconds": 0.005, "repeats": 2,
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(rec["parameters"]["runtime"]["memory_poll_seconds"], 0.005)

    def test_pair18_custom_filename_prefix_and_output_dir(self):
        """Pair 18: filename_prefix='batch_run_alpha' + output_dir."""
        custom_out = self.root / "batch_out"
        payload = {
            "generation": {"images": [str(self.ref_images[0])]},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "filename_prefix": "batch_run_alpha",
                "output_dir": str(custom_out),
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(rec["parameters"]["runtime"]["filename_prefix"], "batch_run_alpha")

    def test_pair19_multi_references_five_with_side_by_side_comparison(self):
        """Pair 19: 5 reference images + save_comparison=True."""
        five_imgs = [str(p) for p in self.ref_images[:5]]
        payload = {
            "generation": {"images": five_imgs},
            "runtime": {
                "device": "cpu", "dtype": "float32", "offload": "none",
                "save_comparison": True,
            },
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(len(rec["effective_parameters"]["reference_images"]), 5)
        self.assertIn("comparison", rec)

    def test_pair20_boundary_ten_references_with_batch_size_two(self):
        """Pair 20: 10 reference images + batch_size=2 + custom_size (64x64)."""
        ten_imgs = [str(p) for p in self.ref_images[:10]]
        payload = {
            "generation": {
                "images": ten_imgs,
                "batch_size": 2,
                "custom_size": True,
                "width": 64,
                "height": 64,
            },
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        rec = self.client.get(f"/api/runs/{resp.json()['run_id']}").json()
        self.assertEqual(len(rec["effective_parameters"]["reference_images"]), 10)
        self.assertEqual(len(rec["outputs"]), 2)


if __name__ == "__main__":
    unittest.main()
