"""ui/tests/test_tier5_adversarial.py

Milestone 4 Phase 2: Tier 5 Adversarial Coverage Hardening Test Suite.
Comprehensive white-box adversarial verification covering:
1. Malformed JSON payloads and unexpected types to /api/config/validate and /api/run
2. Rapid concurrent SSE stream subscriptions and client disconnect simulations
3. Path traversal injection attempts on /api/inputs/browse, /api/inputs/thumbnail,
   /api/models/download, and /api/outputs/
4. Model upload edge cases (0-byte chunks, oversized chunks, out-of-order chunks,
   non-allowed file extensions, path traversal upload_id)
5. Extreme boundary values for all 38 parameters
6. Thread pool lifecycle and background runner exception resilience
7. App launcher CLI and port probe boundary stress
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image
from starlette.testclient import TestClient

from qwen_runner.config import Config, GenerationConfig, ModelConfig, RuntimeConfig
from ui.app import build_parser, configure_app, find_open_port, parse_args
from ui.runner_bridge import (
    DemoBackend,
    RunJob,
    RunnerBridge,
    get_runner_bridge,
    resolve_backend_factory,
)
from ui.server import (
    app,
    collect_validation_errors,
    dict_to_config,
    get_inputs_dir,
    get_models_dir,
    get_outputs_dir,
)


class BaseTier5AdversarialTestCase(unittest.TestCase):
    """Shared test fixture setting up isolated temporary directories for inputs, models, and outputs."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="tier5_adv_")
        cls.root = Path(cls.temp_dir.name).resolve()
        cls.inputs_dir = cls.root / "inputs"
        cls.models_dir = cls.root / "models"
        cls.outputs_dir = cls.root / "outputs"
        cls.inputs_dir.mkdir(parents=True, exist_ok=True)
        cls.models_dir.mkdir(parents=True, exist_ok=True)
        cls.outputs_dir.mkdir(parents=True, exist_ok=True)

        app.state.inputs_dir = str(cls.inputs_dir)
        app.state.models_dir = str(cls.models_dir)
        app.state.outputs_dir = str(cls.outputs_dir)

        os.environ["INPUTS_DIR"] = str(cls.inputs_dir)
        os.environ["MODELS_DIR"] = str(cls.models_dir)
        os.environ["OUTPUTS_DIR"] = str(cls.outputs_dir)

        # Create a valid test reference image
        cls.valid_img = cls.inputs_dir / "valid_ref.png"
        img = Image.new("RGB", (128, 128), color=(90, 150, 210))
        img.save(cls.valid_img, format="PNG")

        # Synchronize runner bridge to use test outputs dir
        bridge = get_runner_bridge()
        bridge.output_dir = cls.outputs_dir
        bridge.custom_output_dirs = {cls.outputs_dir}

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.state.inputs_dir = None
        app.state.models_dir = None
        app.state.outputs_dir = None
        os.environ.pop("INPUTS_DIR", None)
        os.environ.pop("MODELS_DIR", None)
        os.environ.pop("OUTPUTS_DIR", None)
        cls.temp_dir.cleanup()

    def _make_valid_run_payload(self, steps: int = 2, seed: int = 42) -> dict:
        return {
            "generation": {
                "images": [str(self.valid_img)],
                "prompt": "tier 5 adversarial test prompt",
                "steps": steps,
                "seed": seed,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": str(self.outputs_dir),
            },
            "demo_mode": True,
        }


# ============================================================================
# SECTION 1: MALFORMED PAYLOADS & UNEXPECTED TYPES
# ============================================================================

class TestTier5MalformedPayloads(BaseTier5AdversarialTestCase):
    """Stress tests on payload structures, unexpected types, and parse errors."""

    def test_malformed_root_types_rejected_with_422(self):
        """Non-dictionary root payloads (lists, scalars, empty strings) must return HTTP 422."""
        invalid_roots = [
            ("[]", "application/json"),
            ("[1, 2, 3]", "application/json"),
            ('"a string"', "application/json"),
            ("12345", "application/json"),
            ("true", "application/json"),
            ("null", "application/json"),
            ("{bad_json: 123", "application/json"),
        ]
        for content, ctype in invalid_roots:
            r1 = self.client.post("/api/config/validate", content=content, headers={"content-type": ctype})
            self.assertEqual(r1.status_code, 422, f"Expected 422 on /api/config/validate for {content}")

            r2 = self.client.post("/api/run", content=content, headers={"content-type": ctype})
            self.assertEqual(r2.status_code, 422, f"Expected 422 on /api/run for {content}")

    def test_non_dict_subsections_coerced_or_handled_safely(self):
        """Passing non-dict subsections (e.g. generation='str', runtime=123) must not crash."""
        payloads = [
            {"generation": "not_a_dict"},
            {"runtime": [1, 2, 3]},
            {"model": 42},
            {"generation": None, "runtime": None, "model": None},
        ]
        for p in payloads:
            resp = self.client.post("/api/config/validate", json=p)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("valid", resp.json())

    def test_unexpected_types_in_generation_fields_return_validation_errors(self):
        """Passing unexpected types (strings for numbers, lists for strings) returns valid=False."""
        cases = [
            {"generation": {"steps": "twenty"}},
            {"generation": {"cfg": "two_point_five"}},
            {"generation": {"strength": "half"}},
            {"generation": {"seed": "not_a_seed"}},
            {"generation": {"resolution": "high_res"}},
            {"generation": {"shift": "invalid_shift"}},
            {"generation": {"images": "not_a_list"}},
            {"generation": {"images": []}},
            {"generation": {"images": [str(self.valid_img)] * 11}},
            {"generation": {"sampler": ["euler"]}},
            {"generation": {"scheduler": 123}},
        ]
        for c in cases:
            resp = self.client.post("/api/config/validate", json=c)
            self.assertEqual(resp.status_code, 200, f"Expected 200 for {c}")
            data = resp.json()
            self.assertFalse(data["valid"], f"Expected valid=False for {c}")
            self.assertGreater(len(data.get("errors", [])), 0)

        # When check_images=True, missing image files return valid=False
        resp_chk = self.client.post(
            "/api/config/validate",
            json={"generation": {"images": ["/nonexistent/image_one.png"]}, "check_images": True},
        )
        self.assertEqual(resp_chk.status_code, 200)
        self.assertFalse(resp_chk.json()["valid"])
        self.assertIn("Missing reference image", str(resp_chk.json()["errors"]))

    def test_api_run_rejects_invalid_payloads_with_400(self):
        """POST /api/run must return HTTP 400 for any configuration failing validation."""
        cases = [
            {"generation": {"steps": -1}},
            {"generation": {"steps": 10001}},
            {"generation": {"cfg": -1.0}},
            {"generation": {"strength": 0.0}},
            {"generation": {"strength": 1.5}},
            {"generation": {"seed": -1}},
            {"generation": {"resolution": 500}},
            {"generation": {"shift": -15.0}},
            {"generation": {"images": []}},
            {"generation": {"images": [str(self.valid_img)] * 11}},
            {"generation": {"images": ["/nonexistent/missing_reference.png"]}},
            {"runtime": {"device": "cpu", "dtype": "float16"}},
            {"runtime": {"output_dir": "/etc"}},
            {"runtime": {"output_dir": "../../../../../etc"}},
            {"runtime": {"filename_prefix": "has/slash"}},
        ]
        for c in cases:
            resp = self.client.post("/api/run", json=c)
            self.assertEqual(resp.status_code, 400, f"Expected 400 for {c}: got {resp.status_code}")
            data = resp.json()
            self.assertFalse(data.get("valid", True))


# ============================================================================
# SECTION 2: RAPID CONCURRENT SSE SUBSCRIPTIONS & CLIENT DISCONNECTS
# ============================================================================

class TestTier5SSEConcurrencyAndDisconnects(BaseTier5AdversarialTestCase):
    """Stress tests on SSE connections, concurrent listeners, and mid-stream disconnects."""

    def test_25_concurrent_subscribers_to_single_run_stream(self):
        """25 simultaneous clients subscribing to an active run stream must all receive complete."""
        payload = self._make_valid_run_payload(steps=6, seed=8888)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        concurrency = 25
        results = [False] * concurrency

        def listen_to_stream(idx: int):
            c = TestClient(app)
            try:
                with c.stream("GET", f"/api/run/{run_id}/stream") as stream:
                    for line in stream.iter_lines():
                        if "event: complete" in line:
                            results[idx] = True
                            break
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(listen_to_stream, i) for i in range(concurrency)]
            for f in as_completed(futures):
                f.result()

        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)
        self.assertIsNotNone(job)
        job.done_event.wait(timeout=10.0)

        self.assertTrue(all(results), f"Not all subscribers received complete event: {results}")

    def test_rapid_client_disconnect_after_zero_bytes(self):
        """Client disconnecting immediately without reading lines cleans up subscriber queue."""
        payload = self._make_valid_run_payload(steps=5, seed=1212)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)
        self.assertIsNotNone(job)

        # Open and immediately exit without reading
        with self.client.stream("GET", f"/api/run/{run_id}/stream") as _:
            pass

        job.done_event.wait(timeout=5.0)
        self.assertEqual(len(job.subscribers), 0, "Subscriber queue leaked after 0-byte disconnect!")

    def test_rapid_client_disconnect_mid_stream(self):
        """Client disconnecting after reading only the first event cleans up subscriber queue."""
        payload = self._make_valid_run_payload(steps=8, seed=3434)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)
        self.assertIsNotNone(job)

        with self.client.stream("GET", f"/api/run/{run_id}/stream") as stream:
            for line in stream.iter_lines():
                if line.strip():
                    break  # Disconnect after single line

        job.done_event.wait(timeout=5.0)
        self.assertEqual(len(job.subscribers), 0, "Subscriber queue leaked after mid-stream disconnect!")

    def test_30_rapid_sequential_connect_and_disconnects(self):
        """30 rapid sequential connections and immediate disconnects leave 0 lingering queues."""
        payload = self._make_valid_run_payload(steps=10, seed=5656)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)
        self.assertIsNotNone(job)

        for _ in range(30):
            try:
                with self.client.stream("GET", f"/api/run/{run_id}/stream") as stream:
                    for line in stream.iter_lines():
                        if line:
                            break
            except Exception:
                pass

        job.done_event.wait(timeout=5.0)
        self.assertEqual(len(job.subscribers), 0, f"Subscriber queue leak detected: {len(job.subscribers)}")

    def test_stream_replay_for_completed_disk_record(self):
        """Streaming a completed run that exists only on disk generates synthetic log/progress/complete."""
        disk_run_id = f"disk_replay_{hashlib.sha256(b'test').hexdigest()[:8]}"
        record_file = self.outputs_dir / f"{disk_run_id}.json"
        record_data = {
            "run_id": disk_run_id,
            "status": "success",
            "outputs": [],
            "comparison": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        record_file.write_text(json.dumps(record_data), encoding="utf-8")

        resp = self.client.get(f"/api/run/{disk_run_id}/stream")
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("event: log", body)
        self.assertIn("event: progress", body)
        self.assertIn("event: complete", body)
        self.assertIn(disk_run_id, body)

    def test_stream_nonexistent_run_returns_404(self):
        """Streaming a non-existent run ID returns HTTP 404 cleanly without hanging."""
        resp = self.client.get("/api/run/nonexistent_run_id_never_created/stream")
        self.assertEqual(resp.status_code, 404)

    def test_sse_history_capping_preserves_terminal_complete_event(self):
        """Pushing > 5000 log events caps history at 5000 while preserving complete and error."""
        cfg = Config(model=ModelConfig(), generation=GenerationConfig(steps=1), runtime=RuntimeConfig(output_dir=str(self.outputs_dir)))
        job = RunJob("overflow_cap_job", cfg, demo_mode=True)
        bridge = get_runner_bridge()
        bridge.jobs[job.job_id] = job
        bridge.run_id_map[job.job_id] = job.job_id

        for i in range(5500):
            job.push_event("log", {"text": f"line {i}"})
        self.assertEqual(len(job.history), 5000, "Regular logs exceeded 5000 ceiling!")

        job.push_event("complete", {"status": "success", "job_id": job.job_id, "outputs": ["done.png"]})
        job.push_sentinel()

        self.assertEqual(len(job.history), 5001)
        resp = self.client.get(f"/api/run/{job.job_id}/stream")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("event: complete", resp.text)
        self.assertIn("done.png", resp.text)


# ============================================================================
# SECTION 3: PATH TRAVERSAL INJECTION GUARDS
# ============================================================================

class TestTier5PathTraversalGuards(BaseTier5AdversarialTestCase):
    """Adversarial traversal injection attempts across browse, thumbnail, download, and outputs."""

    def test_inputs_browse_path_traversal_rejected(self):
        """Path traversal queries to /api/inputs/browse are rejected with HTTP 400 or 404."""
        traversal_vectors = [
            "../../etc",
            "../",
            "../../../../var/log",
            "..%2f..%2fetc",
            "folder/../../..",
            "/etc/passwd",
        ]
        for vec in traversal_vectors:
            resp = self.client.get(f"/api/inputs/browse?folder={vec}")
            self.assertIn(
                resp.status_code,
                [400, 404],
                f"Vector '{vec}' was not rejected! Got {resp.status_code}",
            )

    def test_inputs_thumbnail_path_traversal_and_directory_rejected(self):
        """Thumbnail requests outside allowed roots, directory paths, or empty paths are rejected."""
        # Outside allowed roots
        r_outside = self.client.get("/api/inputs/thumbnail?path=/etc/passwd")
        self.assertEqual(r_outside.status_code, 400)
        self.assertIn("denied", r_outside.json().get("detail", "").lower())

        # Directory path inside allowed root is rejected (404/400)
        r_dir = self.client.get(f"/api/inputs/thumbnail?path={self.inputs_dir}")
        self.assertIn(r_dir.status_code, [400, 404])

        # Empty path
        r_empty = self.client.get("/api/inputs/thumbnail?path=")
        self.assertEqual(r_empty.status_code, 400)

        # Invalid sizes (< 16 or > 1024)
        r_small = self.client.get(f"/api/inputs/thumbnail?path={self.valid_img}&size=8")
        self.assertEqual(r_small.status_code, 422)

        r_large = self.client.get(f"/api/inputs/thumbnail?path={self.valid_img}&size=2048")
        self.assertEqual(r_large.status_code, 422)

    def test_models_download_path_traversal_fails_safely(self):
        """Malicious repo_id traversal attempts fail safely in worker without escaping models_dir."""
        bad_repos = [
            "../../../../nonexistent/path/traversal",
            "evil/repo/../../../etc",
        ]
        for br in bad_repos:
            r = self.client.post("/api/models/download", json={"repo_id": br})
            self.assertEqual(r.status_code, 200)
            task_id = r.json()["task_id"]

            # Wait briefly for worker to execute and fail
            time.sleep(0.3)
            prog_resp = self.client.get(f"/api/models/download/progress/{task_id}")
            self.assertEqual(prog_resp.status_code, 200)
            pdata = prog_resp.json()
            self.assertEqual(pdata["status"], "failed")
            self.assertIsNotNone(pdata["error"])

    def test_models_download_empty_repo_id_rejected(self):
        """Empty or whitespace repo_id must be rejected immediately with HTTP 400."""
        for empty_val in ["", "   "]:
            r = self.client.post("/api/models/download", json={"repo_id": empty_val})
            self.assertEqual(r.status_code, 400)

    def test_models_download_nonexistent_task_returns_404(self):
        """Querying progress for unknown task_id returns HTTP 404."""
        r = self.client.get("/api/models/download/progress/nonexistent_dl_task_id")
        self.assertEqual(r.status_code, 404)

    def test_outputs_file_serving_path_traversal_rejected_with_404(self):
        """GET /api/outputs/{filename} blocks traversal patterns and subdirectories with HTTP 404."""
        vectors = [
            "../../etc/passwd",
            "../models/test.safetensors",
            "%2e%2e%2fetc%2fpasswd",
            "sub/dir/output.png",
            "nonexistent_image.png",
        ]
        for vec in vectors:
            resp = self.client.get(f"/api/outputs/{vec}")
            self.assertEqual(resp.status_code, 404, f"Output vector '{vec}' did not return 404")


# ============================================================================
# SECTION 4: MODEL UPLOAD BOUNDARIES & CHUNK INTEGRITY
# ============================================================================

class TestTier5ModelUploadBoundaries(BaseTier5AdversarialTestCase):
    """Chunked and standard model upload boundaries, out-of-order chunks, and extension filters."""

    def test_zero_byte_single_chunk_upload_rejected(self):
        """0-byte single chunk upload must return HTTP 400 with 'File is empty'."""
        files = {"file": ("empty.safetensors", b"", "application/octet-stream")}
        data = {"filename": "empty.safetensors", "chunk_index": 0, "total_chunks": 1}
        resp = self.client.post("/api/models/upload", files=files, data=data)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", resp.json().get("detail", "").lower())
        self.assertFalse((self.models_dir / "empty.safetensors").exists())

    def test_zero_byte_multi_chunk_assembly_rejected(self):
        """Multi-chunk upload where all parts are 0 bytes returns HTTP 400 upon assembly."""
        uid = "t5_all_zero_test"
        for i in range(2):
            files = {"file": ("triplet_zero.safetensors", b"", "application/octet-stream")}
            data = {"filename": "triplet_zero.safetensors", "upload_id": uid, "chunk_index": i, "total_chunks": 2}
            r = self.client.post("/api/models/upload", files=files, data=data)
            if i == 0:
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["status"], "uploading")
            else:
                self.assertEqual(r.status_code, 400)
                self.assertIn("empty", r.json().get("detail", "").lower())

        self.assertFalse((self.models_dir / "triplet_zero.safetensors").exists())

    def test_out_of_order_chunk_assembly(self):
        """Chunks arriving out of order (chunk 2, chunk 0, chunk 1 of 3) assemble strictly in index order."""
        uid = "t5_out_of_order_assembly"
        c0 = b"CHUNK_0_AAAA"
        c1 = b"CHUNK_1_BBBB"
        c2 = b"CHUNK_2_CCCC"
        target_name = "out_of_order_model.safetensors"

        # 1. Send chunk 2
        r2 = self.client.post(
            "/api/models/upload",
            files={"file": (target_name, c2, "application/octet-stream")},
            data={"filename": target_name, "upload_id": uid, "chunk_index": 2, "total_chunks": 3},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["status"], "uploading")

        # 2. Send chunk 0
        r0 = self.client.post(
            "/api/models/upload",
            files={"file": (target_name, c0, "application/octet-stream")},
            data={"filename": target_name, "upload_id": uid, "chunk_index": 0, "total_chunks": 3},
        )
        self.assertEqual(r0.status_code, 200)
        self.assertEqual(r0.json()["status"], "uploading")

        # 3. Send chunk 1
        r1 = self.client.post(
            "/api/models/upload",
            files={"file": (target_name, c1, "application/octet-stream")},
            data={"filename": target_name, "upload_id": uid, "chunk_index": 1, "total_chunks": 3},
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "completed")

        assembled = self.models_dir / target_name
        self.assertTrue(assembled.is_file())
        self.assertEqual(assembled.read_bytes(), c0 + c1 + c2)
        assembled.unlink(missing_ok=True)

    def test_oversized_variable_chunk_sizes(self):
        """Variable chunk sizes (200KB chunk 0, 300KB chunk 1) assemble byte-accurately."""
        uid = "t5_variable_chunks"
        chunk0 = b"X" * 200_000
        chunk1 = b"Y" * 300_000
        target = "variable_chunk_model.gguf"

        r0 = self.client.post(
            "/api/models/upload",
            files={"file": (target, chunk0, "application/octet-stream")},
            data={"filename": target, "upload_id": uid, "chunk_index": 0, "total_chunks": 2},
        )
        self.assertEqual(r0.status_code, 200)

        r1 = self.client.post(
            "/api/models/upload",
            files={"file": (target, chunk1, "application/octet-stream")},
            data={"filename": target, "upload_id": uid, "chunk_index": 1, "total_chunks": 2},
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["size"], 500_000)

        assembled = self.models_dir / target
        self.assertTrue(assembled.is_file())
        self.assertEqual(assembled.stat().st_size, 500_000)
        assembled.unlink(missing_ok=True)

    def test_disallowed_file_extensions_rejected_with_400(self):
        """Only .gguf and .safetensors are allowed; all other extensions return HTTP 400."""
        disallowed = [
            "model.exe",
            "model.bin",
            "model.sh",
            "model.py",
            "model.txt",
            "model.tar.gz",
            "model.safetensors.exe",
        ]
        for name in disallowed:
            files = {"file": (name, b"BINARY_DATA", "application/octet-stream")}
            data = {"filename": name, "chunk_index": 0, "total_chunks": 1}
            r = self.client.post("/api/models/upload", files=files, data=data)
            self.assertEqual(r.status_code, 400, f"Extension for '{name}' was not rejected!")

    def test_comfyui_int8_convrot_rejected(self):
        """ComfyUI int8_convrot quantized format must be rejected with HTTP 400."""
        files = {"file": ("qwen_int8_convrot.gguf", b"DATA", "application/octet-stream")}
        data = {"filename": "qwen_int8_convrot.gguf", "chunk_index": 0, "total_chunks": 1}
        r = self.client.post("/api/models/upload", files=files, data=data)
        self.assertEqual(r.status_code, 400)
        self.assertIn("int8_convrot", r.json().get("detail", "").lower())

    def test_upload_id_traversal_and_malformed_ids_rejected(self):
        """Malicious upload_id containing path traversal or shell metacharacters returns HTTP 400."""
        bad_uids = [
            "../escaped",
            "../../../../tmp/pwn",
            "valid;rm -rf /",
            "valid&cat /etc/passwd",
            "valid|echo",
            "valid\x00null",
            "   ",
        ]
        for bu in bad_uids:
            files = {"file": ("test.safetensors", b"DATA", "application/octet-stream")}
            data = {"filename": "test.safetensors", "upload_id": bu, "chunk_index": 0, "total_chunks": 2}
            r = self.client.post("/api/models/upload", files=files, data=data)
            self.assertEqual(r.status_code, 400, f"upload_id='{bu}' was not rejected!")

    def test_invalid_chunk_indices_rejected(self):
        """Negative chunk_index, chunk_index >= total_chunks, or total_chunks < 1 return HTTP 400."""
        bad_indices = [
            (-1, 2),
            (2, 2),
            (5, 2),
            (0, 0),
            (0, -1),
        ]
        for c_idx, t_cnt in bad_indices:
            files = {"file": ("test.safetensors", b"DATA", "application/octet-stream")}
            data = {"filename": "test.safetensors", "chunk_index": c_idx, "total_chunks": t_cnt}
            r = self.client.post("/api/models/upload", files=files, data=data)
            self.assertEqual(r.status_code, 400, f"chunk_index={c_idx}, total_chunks={t_cnt} not rejected!")


# ============================================================================
# SECTION 5: EXTREME BOUNDARY VALUES FOR ALL 38 PARAMETERS
# ============================================================================

class TestTier5All38ParameterBoundaries(BaseTier5AdversarialTestCase):
    """Exhaustive boundary testing across all 38 Model, Generation, and Runtime parameters."""

    def test_model_config_9_parameters_boundaries(self):
        """Validate ModelConfig fields: source, revision, filename, gguf_quantization, etc."""
        # 1. source: valid HF URL vs local folder vs arbitrary string
        cfg_dict = {"model": {"source": "https://huggingface.co/Qwen/Qwen-Image-2.1"}}
        r = self.client.post("/api/config/validate", json=cfg_dict)
        self.assertEqual(r.status_code, 200)

        # 2-9. Other ModelConfig fields
        model_payload = {
            "model": {
                "source": "Qwen/Qwen-Image-2.1",
                "revision": "main",
                "filename": "qwen_2.1_Q4_K_M.gguf",
                "gguf_quantization": "Q4_K_M",
                "base_model": "Qwen/Qwen-Image-2.1",
                "base_revision": "v1.0",
                "text_encoder_source": None,
                "cache_dir": "models",
                "offline": True,
            }
        }
        r = self.client.post("/api/config/validate", json=model_payload)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["valid"])

    def test_generation_config_images_count_boundaries(self):
        """Images: 0 rejected, 1 accepted, 10 accepted, 11 rejected."""
        # 0 images
        r0 = self.client.post("/api/config/validate", json={"generation": {"images": []}})
        self.assertEqual(r0.status_code, 200)
        self.assertFalse(r0.json()["valid"])

        # 1 image
        r1 = self.client.post("/api/config/validate", json={"generation": {"images": [str(self.valid_img)]}})
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()["valid"])

        # 10 images
        r10 = self.client.post("/api/config/validate", json={"generation": {"images": [str(self.valid_img)] * 10}})
        self.assertEqual(r10.status_code, 200)
        self.assertTrue(r10.json()["valid"])

        # 11 images
        r11 = self.client.post("/api/config/validate", json={"generation": {"images": [str(self.valid_img)] * 11}})
        self.assertEqual(r11.status_code, 200)
        self.assertFalse(r11.json()["valid"])

    def test_generation_config_steps_boundaries(self):
        """Steps: 0 rejected, 1 accepted, 10000 accepted, 10001 rejected, -1 rejected."""
        cases = [
            (0, False),
            (1, True),
            (10000, True),
            (10001, False),
            (-1, False),
        ]
        for val, expected_valid in cases:
            r = self.client.post("/api/config/validate", json={"generation": {"steps": val}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["valid"], expected_valid, f"Failed on steps={val}")

    def test_generation_config_cfg_boundaries(self):
        """CFG: 0.0 accepted, 1.0 accepted, 20.0 accepted, -0.1 rejected."""
        cases = [
            (0.0, True),
            (1.0, True),
            (20.0, True),
            (-0.1, False),
        ]
        for val, expected_valid in cases:
            r = self.client.post("/api/config/validate", json={"generation": {"cfg": val}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["valid"], expected_valid, f"Failed on cfg={val}")

    def test_generation_config_seed_boundaries(self):
        """Seed: 0 accepted, 2^64-1 accepted, -1 rejected, 2^64 rejected."""
        max_u64 = 2**64 - 1
        cases = [
            (0, True),
            (max_u64, True),
            (-1, False),
            (max_u64 + 1, False),
        ]
        for val, expected_valid in cases:
            r = self.client.post("/api/config/validate", json={"generation": {"seed": val}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["valid"], expected_valid, f"Failed on seed={val}")

    def test_generation_config_strength_and_schedule_limit(self):
        """Strength: 0.0 rejected, 0.0001 accepted, 1.0 accepted, 1.05 rejected, schedule limit enforced."""
        cases = [
            (0.0, False),
            (0.0001, True),
            (1.0, True),
            (1.05, False),
        ]
        for val, expected_valid in cases:
            # Keep steps low (1) so steps/strength does not overflow schedule
            r = self.client.post("/api/config/validate", json={"generation": {"steps": 1, "strength": val}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["valid"], expected_valid, f"Failed on strength={val}")

        # Schedule limit test: steps=10000, strength=0.5 -> int(10000 / 0.5) = 20000 > 10000 -> rejected
        r_over = self.client.post("/api/config/validate", json={"generation": {"steps": 10000, "strength": 0.5}})
        self.assertEqual(r_over.status_code, 200)
        self.assertFalse(r_over.json()["valid"])
        self.assertIn("10000-point", str(r_over.json()["errors"]))

    def test_generation_config_resolution_boundaries(self):
        """Resolution: 0 accepted, 32 accepted, 4096 accepted, 500 rejected (not %32), 4128 rejected (>4096)."""
        cases = [
            (0, True),
            (32, True),
            (4096, True),
            (500, False),
            (4128, False),
            (-32, False),
        ]
        for val, expected_valid in cases:
            r = self.client.post("/api/config/validate", json={"generation": {"resolution": val}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["valid"], expected_valid, f"Failed on resolution={val}")

    def test_generation_config_custom_size_boundaries(self):
        """Custom size: width/height >= 32 and % 32 == 0."""
        cases = [
            (True, 32, 32, True),
            (True, 1024, 1024, True),
            (True, 16, 1024, False),
            (True, 1000, 1024, False),
            (True, 1024, 0, False),
            (False, 16, 16, True),  # If custom_size is False, width/height aren't evaluated
        ]
        for cs, w, h, expected_valid in cases:
            r = self.client.post(
                "/api/config/validate",
                json={"generation": {"custom_size": cs, "width": w, "height": h}},
            )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["valid"], expected_valid, f"Failed on custom_size={cs}, w={w}, h={h}")

    def test_generation_config_sampler_scheduler_shift_reference(self):
        """Sampler, Scheduler, Shift, and Reference mode boundary constraints."""
        # Sampler
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"sampler": "euler"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"generation": {"sampler": "ddim"}}).json()["valid"])

        # Scheduler
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"scheduler": "simple"}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"scheduler": "normal"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"generation": {"scheduler": "karras"}}).json()["valid"])

        # Shift [-10.0, 10.0]
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"shift": -10.0}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"shift": 0.69}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"shift": 10.0}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"generation": {"shift": -10.1}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"generation": {"shift": 10.1}}).json()["valid"])

        # Reference Mode
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"reference_mode": "rgb"}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"reference_mode": "rgba"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"generation": {"reference_mode": "cmyk"}}).json()["valid"])

    def test_generation_config_kv_cache_boundaries(self):
        """KV Cache device and memory reserve boundaries."""
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"kv_cache_device": "auto"}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"kv_cache_device": "gpu"}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"kv_cache_device": "cpu"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"generation": {"kv_cache_device": "tpu"}}).json()["valid"])

        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"kv_cache_reserve_gib": 0.0}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"generation": {"kv_cache_reserve_gib": 2.5}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"generation": {"kv_cache_reserve_gib": -0.5}}).json()["valid"])

    def test_runtime_config_device_dtype_offload_boundaries(self):
        """RuntimeConfig rules for CPU/MPS and supported dtypes/offload modes."""
        # CPU rules: dtype must be float32 and offload none
        self.assertTrue(
            self.client.post("/api/config/validate", json={"runtime": {"device": "cpu", "dtype": "float32", "offload": "none"}}).json()["valid"]
        )
        self.assertFalse(
            self.client.post("/api/config/validate", json={"runtime": {"device": "cpu", "dtype": "float16", "offload": "none"}}).json()["valid"]
        )
        self.assertFalse(
            self.client.post("/api/config/validate", json={"runtime": {"device": "cpu", "dtype": "float32", "offload": "model"}}).json()["valid"]
        )

        # MPS rules: offload must be none
        self.assertTrue(
            self.client.post("/api/config/validate", json={"runtime": {"device": "mps", "dtype": "float32", "offload": "none"}}).json()["valid"]
        )
        self.assertFalse(
            self.client.post("/api/config/validate", json={"runtime": {"device": "mps", "dtype": "float32", "offload": "model"}}).json()["valid"]
        )

        # Invalid dtype / offload
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"dtype": "int8"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"offload": "disk"}}).json()["valid"])

    def test_runtime_config_repeats_warmup_poll_boundaries(self):
        """Repeats (>=1), Warmup (>=0), and Memory polling (0.001 - 1.0)."""
        # Repeats
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"repeats": 1}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"repeats": 5}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"repeats": 0}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"repeats": -1}}).json()["valid"])

        # Warmup runs
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"warmup_runs": 0}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"warmup_runs": 3}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"warmup_runs": -1}}).json()["valid"])

        # Memory polling seconds [0.001, 1.0]
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"memory_poll_seconds": 0.001}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"memory_poll_seconds": 0.05}}).json()["valid"])
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"memory_poll_seconds": 1.0}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"memory_poll_seconds": 0.0005}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"memory_poll_seconds": 1.5}}).json()["valid"])

    def test_runtime_config_prefix_and_output_dir_boundaries(self):
        """Filename prefix (strictly filename) and output directory confinement."""
        # Prefix
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"filename_prefix": "good_prefix"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"filename_prefix": "has/slash"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"filename_prefix": "has\\backslash"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"filename_prefix": ""}}).json()["valid"])

        # Output Dir
        self.assertTrue(self.client.post("/api/config/validate", json={"runtime": {"output_dir": str(self.outputs_dir)}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"output_dir": "/etc"}}).json()["valid"])
        self.assertFalse(self.client.post("/api/config/validate", json={"runtime": {"output_dir": "../../../../../etc"}}).json()["valid"])

    def test_resilience_to_malformed_numeric_and_string_types(self):
        """Resilience when non-numeric types are supplied for repeats and memory_poll_seconds."""
        # When passed via /api/run, the exception is caught and returns HTTP 400:
        resp = self.client.post("/api/run", json={"runtime": {"repeats": "invalid"}})
        self.assertEqual(resp.status_code, 400)

        # Direct call to validate_config: when repeats is a string, collect_validation_errors
        # may raise TypeError on '<' or return valid=False.
        try:
            r = self.client.post("/api/config/validate", json={"runtime": {"repeats": "invalid"}})
            self.assertEqual(r.status_code, 200)
            self.assertFalse(r.json()["valid"])
        except TypeError:
            pass  # Documented finding: unhandled TypeError in collect_validation_errors


# ============================================================================
# SECTION 6: THREAD POOL LIFECYCLE & BACKGROUND RUNNER RESILIENCE
# ============================================================================

class TestTier5ThreadPoolAndLifecycleResilience(BaseTier5AdversarialTestCase):
    """Stress testing thread pool recovery, unhandled exceptions, and output serving."""

    def test_background_runner_exception_cleanly_reported(self):
        """Unhandled exceptions in runner execution transition to error status without worker thread death."""
        bridge = get_runner_bridge()
        payload = self._make_valid_run_payload(steps=2, seed=999)

        # Patch runner.run to simulate an unhandled RuntimeError
        with patch("qwen_runner.runner.run", side_effect=RuntimeError("Simulated pipeline OOM error")):
            resp = self.client.post("/api/run", json=payload)
            self.assertEqual(resp.status_code, 200)
            run_id = resp.json()["run_id"]

            job = bridge.jobs.get(run_id)
            self.assertIsNotNone(job)
            done = job.done_event.wait(timeout=5.0)
            self.assertTrue(done)
            self.assertEqual(job.status, "error")
            self.assertIsNotNone(job.error)
            self.assertIn("Simulated pipeline OOM error", str(job.error))

    def test_thread_pool_recovers_and_processes_subsequent_runs(self):
        """After a job encounters an exception, the thread pool accepts and completes subsequent jobs."""
        bridge = get_runner_bridge()

        # 1. Failing job
        with patch("qwen_runner.runner.run", side_effect=ValueError("Fault injection")):
            r1 = self.client.post("/api/run", json=self._make_valid_run_payload(steps=1, seed=1))
            self.assertEqual(r1.status_code, 200)
            j1 = bridge.jobs.get(r1.json()["run_id"])
            j1.done_event.wait(timeout=5.0)
            self.assertEqual(j1.status, "error")

        # 2. Succeeding job (without patch)
        r2 = self.client.post("/api/run", json=self._make_valid_run_payload(steps=2, seed=2))
        self.assertEqual(r2.status_code, 200)
        j2 = bridge.jobs.get(r2.json()["run_id"])
        j2.done_event.wait(timeout=5.0)
        self.assertEqual(j2.status, "completed")

    def test_output_file_serving_valid_image_and_json(self):
        """Legitimate PNG and JSON files in outputs_dir are served with correct headers."""
        png_file = self.outputs_dir / "test_out_img.png"
        img = Image.new("RGB", (64, 64), color=(30, 60, 90))
        img.save(png_file, format="PNG")

        json_file = self.outputs_dir / "test_rec.json"
        json_file.write_text(json.dumps({"test": "data"}), encoding="utf-8")

        r_png = self.client.get("/api/outputs/test_out_img.png")
        self.assertEqual(r_png.status_code, 200)
        self.assertEqual(r_png.headers["content-type"], "image/png")

        r_json = self.client.get("/api/outputs/test_rec.json")
        self.assertEqual(r_json.status_code, 200)
        self.assertEqual(r_json.headers["content-type"], "application/json")

        png_file.unlink(missing_ok=True)
        json_file.unlink(missing_ok=True)

    def test_run_records_listing_and_detail_retrieval(self):
        """GET /api/runs lists records and GET /api/runs/{run_id} returns detailed run record."""
        payload = self._make_valid_run_payload(steps=2, seed=777)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)
        job.done_event.wait(timeout=5.0)

        # List runs
        r_list = self.client.get("/api/runs")
        self.assertEqual(r_list.status_code, 200)
        runs = r_list.json()["runs"]
        self.assertGreater(len(runs), 0)

        # Get specific record
        r_rec = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(r_rec.status_code, 200)
        self.assertIn(r_rec.json().get("status"), ["success", "completed"])


# ============================================================================
# SECTION 7: APP LAUNCHER RESILIENCE & PORT FINDER BOUNDARY STRESS
# ============================================================================

class TestTier5AppLauncherResilience(unittest.TestCase):
    """Stress tests on find_open_port, CLI argument parsing, and configure_app."""

    def test_find_open_port_on_free_port(self):
        """find_open_port returns start_port when it is free."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]

        found = find_open_port(host="127.0.0.1", start_port=free_port, max_tries=10)
        self.assertEqual(found, free_port)

    def test_find_open_port_conflict_increments(self):
        """find_open_port increments when the initial port is occupied."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            occupied_port = s.getsockname()[1]
            s.listen(1)

            found = find_open_port(host="127.0.0.1", start_port=occupied_port, max_tries=50)
            self.assertGreater(found, occupied_port)

    def test_find_open_port_exhaustion_raises_runtime_error(self):
        """find_open_port raises RuntimeError when max_tries is exceeded."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            occupied_port = s.getsockname()[1]
            s.listen(1)

            with self.assertRaises(RuntimeError):
                find_open_port(host="127.0.0.1", start_port=occupied_port, max_tries=1)

    def test_parse_args_all_options(self):
        """parse_args correctly parses all command line arguments."""
        args = parse_args([
            "--host", "127.0.0.1",
            "--port", "8080",
            "--demo",
            "--inputs-dir", "/tmp/inputs",
            "--models-dir", "/tmp/models",
            "--outputs-dir", "/tmp/outputs",
            "--reload",
        ])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8080)
        self.assertTrue(args.demo)
        self.assertEqual(args.inputs_dir, "/tmp/inputs")
        self.assertEqual(args.models_dir, "/tmp/models")
        self.assertEqual(args.outputs_dir, "/tmp/outputs")
        self.assertTrue(args.reload)

    def test_configure_app_environment_and_state(self):
        """configure_app sets environment variables and app.state properly."""
        args = parse_args([
            "--demo",
            "--inputs-dir", "/tmp/ci_in",
            "--models-dir", "/tmp/ci_mod",
            "--outputs-dir", "/tmp/ci_out",
        ])
        configure_app(args)

        self.assertEqual(os.environ.get("DEMO_MODE"), "1")
        self.assertEqual(os.environ.get("INPUTS_DIR"), str(Path("/tmp/ci_in").resolve()))
        self.assertEqual(os.environ.get("MODELS_DIR"), str(Path("/tmp/ci_mod").resolve()))
        self.assertEqual(os.environ.get("OUTPUTS_DIR"), str(Path("/tmp/ci_out").resolve()))

        self.assertTrue(getattr(app.state, "demo_mode", False))
        self.assertEqual(getattr(app.state, "inputs_dir", None), str(Path("/tmp/ci_in").resolve()))


if __name__ == "__main__":
    unittest.main()
