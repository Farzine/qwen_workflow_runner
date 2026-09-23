"""ui/tests/test_adversarial_stress.py

Adversarial stress and concurrency verification test suite for Milestone 1 Backend API & Runner Bridge.
Verifies:
1. Rapid concurrent requests to /api/run and /api/run/{run_id}/stream
2. Client mid-stream disconnects and server/thread-pool resilience
3. Stream replay on completed runs (in-memory and on-disk)
4. Boundary chunk uploads, path traversal defense, and malformed payloads
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from PIL import Image
from starlette.testclient import TestClient

from qwen_runner.config import Config, GenerationConfig, ModelConfig, RuntimeConfig
from ui.runner_bridge import RunnerBridge, RunJob, get_runner_bridge, resolve_backend_factory, DemoBackend
from ui.server import app, get_models_dir, get_outputs_dir, get_inputs_dir


class TestAdversarialStress(unittest.TestCase):
    """Adversarial stress and concurrency test suite for Milestone 1."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="adv_stress_")
        cls.root = Path(cls.temp_dir.name)
        cls.inputs_dir = cls.root / "inputs"
        cls.models_dir = cls.root / "models"
        cls.outputs_dir = cls.root / "outputs"
        cls.inputs_dir.mkdir(parents=True, exist_ok=True)
        cls.models_dir.mkdir(parents=True, exist_ok=True)
        cls.outputs_dir.mkdir(parents=True, exist_ok=True)

        app.state.inputs_dir = cls.inputs_dir
        app.state.models_dir = cls.models_dir
        app.state.outputs_dir = cls.outputs_dir

        os.environ["INPUTS_DIR"] = str(cls.inputs_dir)
        os.environ["MODELS_DIR"] = str(cls.models_dir)
        os.environ["OUTPUTS_DIR"] = str(cls.outputs_dir)

        # Create a sample input image
        cls.sample_img = cls.inputs_dir / "sample.png"
        img = Image.new("RGB", (128, 128), color=(80, 140, 200))
        img.save(cls.sample_img)

        # Re-initialize runner bridge pointing to test outputs
        bridge = get_runner_bridge()
        bridge.output_dir = cls.outputs_dir
        bridge.custom_output_dirs = {cls.outputs_dir}

    @classmethod
    def tearDownClass(cls):
        app.state.inputs_dir = None
        app.state.models_dir = None
        app.state.outputs_dir = None
        os.environ.pop("INPUTS_DIR", None)
        os.environ.pop("MODELS_DIR", None)
        os.environ.pop("OUTPUTS_DIR", None)
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client = TestClient(app)

    def _make_valid_run_payload(self, steps=5, seed=42):
        return {
            "generation": {
                "images": [str(self.sample_img)],
                "prompt": "test prompt",
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

    # ========================================================================
    # 1. RAPID CONCURRENT REQUESTS
    # ========================================================================

    def test_01_rapid_concurrent_run_submissions(self):
        """Submit 20 runs concurrently: assert unique run_ids, no deadlocks, all complete."""
        concurrency = 20
        payloads = [self._make_valid_run_payload(steps=2, seed=1000 + i) for i in range(concurrency)]

        results = []
        def submit(p):
            c = TestClient(app)
            return c.post("/api/run", json=p)

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(submit, p) for p in payloads]
            for f in as_completed(futures):
                results.append(f.result())
        submit_duration = time.time() - t0

        # Assert all submissions succeeded
        self.assertEqual(len(results), concurrency)
        run_ids = set()
        for r in results:
            self.assertEqual(r.status_code, 200, f"Submit failed: {r.text}")
            data = r.json()
            self.assertIn("run_id", data)
            self.assertIn("stream_url", data)
            self.assertNotIn(data["run_id"], run_ids, "Duplicate run_id generated!")
            run_ids.add(data["run_id"])

        self.assertEqual(len(run_ids), concurrency, "UUID collision under concurrent load!")

        # Wait for all background jobs in the executor to complete
        bridge = get_runner_bridge()
        wait_start = time.time()
        for rid in run_ids:
            job = bridge.jobs.get(rid)
            self.assertIsNotNone(job, f"Job {rid} missing from bridge")
            done = job.done_event.wait(timeout=10.0)
            self.assertTrue(done, f"Job {rid} timed out after 10s - possible deadlock!")
            self.assertEqual(job.status, "completed", f"Job {rid} failed with status {job.status}")

        total_duration = time.time() - t0
        print(f"\n[STRESS] 20 concurrent runs submitted in {submit_duration:.2f}s, all completed in {total_duration:.2f}s.")

    def test_02_concurrent_stream_readers_single_run(self):
        """Connect 10 concurrent stream readers to a single running job; verify all receive complete."""
        payload = self._make_valid_run_payload(steps=10, seed=5555)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        concurrency = 10
        stream_results = [None] * concurrency

        def read_stream(idx):
            c = TestClient(app)
            res = c.get(f"/api/run/{run_id}/stream")
            stream_results[idx] = res

        threads = []
        for i in range(concurrency):
            t = ThreadPoolExecutor(max_workers=1).submit(read_stream, i)
            threads.append(t)

        for t in threads:
            t.result(timeout=10.0)

        # Verify each reader received full stream including complete
        for idx, res in enumerate(stream_results):
            self.assertIsNotNone(res, f"Reader {idx} received no response")
            self.assertEqual(res.status_code, 200)
            text = res.text
            self.assertIn("event: complete", text, f"Reader {idx} did not receive complete event!")
            self.assertIn("event: progress", text, f"Reader {idx} did not receive progress event!")
            self.assertIn(run_id, text, f"Reader {idx} received mismatched payload!")

        # Verify no subscriber queue leak
        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)
        self.assertIsNotNone(job)
        self.assertEqual(len(job.subscribers), 0, "Subscriber queues were not cleaned up!")
        print(f"[STRESS] 10 concurrent stream readers on single run successfully received complete event.")

    # ========================================================================
    # 2. MID-STREAM CLIENT DISCONNECTS
    # ========================================================================

    def test_03_mid_stream_disconnect_resilience(self):
        """Client disconnects after reading 1 event; verify server survives and background run finishes."""
        payload = self._make_valid_run_payload(steps=15, seed=8888)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)
        self.assertIsNotNone(job)

        # Simulate client disconnect by closing the stream context early
        with self.client.stream("GET", f"/api/run/{run_id}/stream") as stream_resp:
            self.assertEqual(stream_resp.status_code, 200)
            for line in stream_resp.iter_lines():
                if line and "event:" in line:
                    break
            # Exiting the 'with' block forcefully terminates the client-side connection

        # Wait for the background job to finish
        finished = job.done_event.wait(timeout=5.0)
        self.assertTrue(finished, "Background job did not finish after client disconnected!")
        self.assertEqual(job.status, "completed", f"Job status was {job.status} after disconnect")

        # Verify subscriber was cleanly removed
        self.assertEqual(len(job.subscribers), 0, "Subscriber queue leaked after disconnect!")

        # Verify a new client can now replay the stream to completion
        new_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(new_resp.status_code, 200)
        self.assertIn("event: complete", new_resp.text)
        self.assertIn(run_id, new_resp.text)
        print(f"[STRESS] Mid-stream disconnect handled cleanly; job completed and full replay succeeded.")

    def test_04_rapid_disconnect_reconnect_cycling(self):
        """Rapidly connect and disconnect 10 times while run is executing."""
        payload = self._make_valid_run_payload(steps=20, seed=9999)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)

        # Cycle 10 connects and immediate disconnects
        for _ in range(10):
            try:
                with self.client.stream("GET", f"/api/run/{run_id}/stream") as s:
                    for line in s.iter_lines():
                        if line:
                            break
            except Exception:
                pass
            time.sleep(0.02)

        # Wait for job to complete
        finished = job.done_event.wait(timeout=5.0)
        self.assertTrue(finished, "Background job hung after rapid client disconnects!")
        self.assertEqual(job.status, "completed")
        self.assertEqual(len(job.subscribers), 0)

        # Verify final replay
        final_resp = self.client.get(f"/api/run/{run_id}/stream")
        self.assertEqual(final_resp.status_code, 200)
        self.assertIn("event: complete", final_resp.text)
        print(f"[STRESS] Rapid 10x disconnect-reconnect cycling passed with 0 queue leaks.")

    # ========================================================================
    # 3. STREAM REPLAY ON COMPLETED RUNS
    # ========================================================================

    def test_05_stream_replay_in_memory(self):
        """Replay completed in-memory run multiple times; verify identical complete payload."""
        payload = self._make_valid_run_payload(steps=3, seed=123)
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["run_id"]

        # Wait for completion
        job = get_runner_bridge().jobs.get(run_id)
        job.done_event.wait(timeout=5.0)

        # Replay 5 times sequentially
        for i in range(5):
            r = self.client.get(f"/api/run/{run_id}/stream")
            self.assertEqual(r.status_code, 200)
            self.assertIn("event: complete", r.text)
            self.assertIn(run_id, r.text)
            self.assertIn("outputs", r.text)
        print(f"[STRESS] In-memory stream replay verified across 5 sequential requests.")

    def test_06_stream_replay_from_disk_cold(self):
        """Replay a run that exists ONLY on disk (not in memory); verify complete SSE."""
        cold_run_id = "cold_disk_replay_test_001"
        rec_path = self.outputs_dir / f"{cold_run_id}.json"
        dummy_record = {
            "run_id": cold_run_id,
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "outputs": [
                {
                    "path": str(self.outputs_dir / "out_00.png"),
                    "width": 512,
                    "height": 512,
                    "sha256": "abcdef1234567890",
                }
            ],
            "comparison": str(self.outputs_dir / "comp.png"),
            "inference_time_seconds": 0.42,
            "error": None,
        }
        rec_path.write_text(json.dumps(dummy_record))

        # Request stream replay for cold run
        r = self.client.get(f"/api/run/{cold_run_id}/stream")
        self.assertEqual(r.status_code, 200)
        text = r.text
        self.assertIn("event: log", text)
        self.assertIn(f"Replaying finished run {cold_run_id}", text)
        self.assertIn("event: progress", text)
        self.assertIn("event: complete", text)
        self.assertIn("abcdef1234567890", text)
        print(f"[STRESS] Cold disk stream replay correctly reconstructed SSE stream.")

    def test_07_stream_replay_nonexistent_returns_404(self):
        """Request stream for nonexistent run ID; assert HTTP 404."""
        r = self.client.get("/api/run/nonexistent_phantom_run_id/stream")
        self.assertEqual(r.status_code, 404)
        self.assertIn("not found", r.json()["detail"].lower())

    def test_08_concurrent_stream_replay(self):
        """20 concurrent threads requesting stream replay on same completed run."""
        payload = self._make_valid_run_payload(steps=2, seed=777)
        resp = self.client.post("/api/run", json=payload)
        run_id = resp.json()["run_id"]
        job = get_runner_bridge().jobs.get(run_id)
        job.done_event.wait(timeout=5.0)

        concurrency = 20
        results = []
        def replay():
            c = TestClient(app)
            return c.get(f"/api/run/{run_id}/stream")

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(replay) for _ in range(concurrency)]
            for f in as_completed(futures):
                results.append(f.result())
        duration = time.time() - t0

        self.assertEqual(len(results), concurrency)
        for res in results:
            self.assertEqual(res.status_code, 200)
            self.assertIn("event: complete", res.text)
        print(f"[STRESS] 20 concurrent stream replays succeeded in {duration:.2f}s.")

    # ========================================================================
    # 4. BOUNDARY & MALFORMED PAYLOADS
    # ========================================================================

    def test_09_upload_empty_single_chunk_rejected(self):
        """Upload zero-byte file with total_chunks=1; assert HTTP 400."""
        files = {"file": ("empty.safetensors", b"", "application/octet-stream")}
        data = {"filename": "empty.safetensors", "total_chunks": 1, "chunk_index": 0}
        resp = self.client.post("/api/models/upload", files=files, data=data)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", resp.json()["detail"].lower())

    def test_10_upload_invalid_extension_rejected(self):
        """Upload files with forbidden extensions (.exe, .py, .txt); assert HTTP 400."""
        for bad_ext in ["virus.exe", "script.py", "readme.txt", "archive.tar.gz"]:
            files = {"file": (bad_ext, b"fake content", "application/octet-stream")}
            data = {"filename": bad_ext, "total_chunks": 1, "chunk_index": 0}
            resp = self.client.post("/api/models/upload", files=files, data=data)
            self.assertEqual(resp.status_code, 400)
            self.assertIn("invalid model extension", resp.json()["detail"].lower())

    def test_11_upload_comfyui_int8_convrot_rejected(self):
        """Upload ComfyUI int8_convrot format; assert HTTP 400 rejected."""
        files = {"file": ("model_int8_convrot.safetensors", b"dummy", "application/octet-stream")}
        data = {"filename": "model_int8_convrot.safetensors", "total_chunks": 1, "chunk_index": 0}
        resp = self.client.post("/api/models/upload", files=files, data=data)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("int8_convrot", resp.json()["detail"].lower())

    def test_12_upload_chunked_out_of_order_assembly(self):
        """Upload 3 chunks in reverse order (2, 0, 1); assert assembled correctly."""
        part0 = b"CHUNK_ZERO_"
        part1 = b"CHUNK_ONE_"
        part2 = b"CHUNK_TWO"
        expected_full = part0 + part1 + part2

        upload_id = "test_chunk_assembly_001"
        fname = "assembled_model.safetensors"

        # Send chunk 2
        resp2 = self.client.post(
            "/api/models/upload",
            files={"file": (fname, part2, "application/octet-stream")},
            data={"filename": fname, "upload_id": upload_id, "chunk_index": 2, "total_chunks": 3},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "uploading")

        # Send chunk 0
        resp0 = self.client.post(
            "/api/models/upload",
            files={"file": (fname, part0, "application/octet-stream")},
            data={"filename": fname, "upload_id": upload_id, "chunk_index": 0, "total_chunks": 3},
        )
        self.assertEqual(resp0.status_code, 200)
        self.assertEqual(resp0.json()["status"], "uploading")

        # Send chunk 1
        resp1 = self.client.post(
            "/api/models/upload",
            files={"file": (fname, part1, "application/octet-stream")},
            data={"filename": fname, "upload_id": upload_id, "chunk_index": 1, "total_chunks": 3},
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["status"], "completed")

        # Check assembled file on disk
        final_path = self.models_dir / fname
        self.assertTrue(final_path.is_file())
        self.assertEqual(final_path.read_bytes(), expected_full)
        print(f"[STRESS] Out-of-order chunk assembly (2, 0, 1) verified with exact byte integrity.")

    def test_13_upload_path_traversal_filename_defended(self):
        """Filename with path traversal '../../evil.safetensors' must be sanitized."""
        files = {"file": ("evil.safetensors", b"safetensors data", "application/octet-stream")}
        data = {"filename": "../../evil.safetensors", "total_chunks": 1, "chunk_index": 0}
        resp = self.client.post("/api/models/upload", files=files, data=data)
        self.assertEqual(resp.status_code, 200)
        # Should be saved inside models_dir as evil.safetensors, NOT in root
        self.assertTrue((self.models_dir / "evil.safetensors").is_file())
        self.assertFalse((self.root / "evil.safetensors").is_file())

    def test_14_config_validate_boundary_and_malformed(self):
        """Test config validation against adversarial boundary inputs."""
        # 1. Non-JSON string -> 422
        r1 = self.client.post("/api/config/validate", content="Not a JSON string", headers={"content-type": "application/json"})
        self.assertEqual(r1.status_code, 422)

        # 2. String instead of int for steps
        r2 = self.client.post("/api/config/validate", json={"generation": {"steps": "twenty"}})
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()["valid"])
        self.assertTrue(any("steps" in e.lower() for e in r2.json()["errors"]))

        # 3. Steps exceeding schedule (steps=6000, strength=0.5 -> steps/strength=12000 > 10000)
        r3 = self.client.post("/api/config/validate", json={"generation": {"steps": 6000, "strength": 0.5}})
        self.assertEqual(r3.status_code, 200)
        self.assertFalse(r3.json()["valid"])
        self.assertTrue(any("10000-point" in e for e in r3.json()["errors"]))

        # 4. Zero reference images
        r4 = self.client.post("/api/config/validate", json={"generation": {"images": []}})
        self.assertEqual(r4.status_code, 200)
        self.assertFalse(r4.json()["valid"])
        self.assertTrue(any("1–10" in e for e in r4.json()["errors"]))

        # 5. Eleven reference images (> 10)
        r5 = self.client.post("/api/config/validate", json={"generation": {"images": [f"img_{i}.png" for i in range(11)]}})
        self.assertEqual(r5.status_code, 200)
        self.assertFalse(r5.json()["valid"])
        self.assertTrue(any("1–10" in e for e in r5.json()["errors"]))

        # 6. Unsigned 64-bit seed overflow
        r6 = self.client.post("/api/config/validate", json={"generation": {"seed": 2**64 + 10}})
        self.assertEqual(r6.status_code, 200)
        self.assertFalse(r6.json()["valid"])
        self.assertTrue(any("seed" in e.lower() for e in r6.json()["errors"]))

    def test_15_run_malformed_config_rejected(self):
        """Invalid config submitted to /api/run must return HTTP 400 without crashing server."""
        bad_payload = {"generation": {"steps": -5, "strength": 2.0}}
        resp = self.client.post("/api/run", json=bad_payload)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["valid"])

    def test_16_directory_traversal_endpoints_defended(self):
        """Check traversal attacks on /api/inputs/browse, /api/inputs/thumbnail, /api/outputs/."""
        # 1. Inputs browse
        r1 = self.client.get("/api/inputs/browse?folder=../../")
        self.assertEqual(r1.status_code, 400)

        # 2. Thumbnail traversal
        r2 = self.client.get("/api/inputs/thumbnail?path=/etc/passwd")
        self.assertEqual(r2.status_code, 400)

        # 3. Output traversal
        r3 = self.client.get("/api/outputs/../../etc/passwd")
        self.assertEqual(r3.status_code, 404)

        # 4. Model download empty repo
        r4 = self.client.post("/api/models/download", json={"repo_id": "   "})
        self.assertEqual(r4.status_code, 400)

    # ========================================================================
    # 5. EMPIRICALLY CONFIRMED VULNERABILITIES & FAILURE MODES
    # ========================================================================
    # 5. EMPIRICALLY CONFIRMED REMEDIATIONS & ADVERSARIAL VERIFICATIONS
    # ========================================================================

    def test_17_upload_id_path_traversal_blocked(self):
        """VERIFIED FIX: upload_id with traversal sequences must be rejected with HTTP 400."""
        evil_chunk = self.models_dir / "evil_traversal_chunk_0000.part"
        if evil_chunk.exists():
            evil_chunk.unlink()

        for bad_uid in ["../evil_traversal", "../../tmp/escaped", "sub/dir", "a/b/c", "bad$uid", "uid;rm", "   "]:
            files = {"file": ("model.safetensors", b"TRAVERSAL_CONTENT", "application/octet-stream")}
            data = {
                "filename": "model.safetensors",
                "upload_id": bad_uid,
                "chunk_index": 0,
                "total_chunks": 2,
            }
            resp = self.client.post("/api/models/upload", files=files, data=data)
            self.assertEqual(resp.status_code, 400, f"Expected 400 for upload_id='{bad_uid}', got {resp.status_code}")
            self.assertFalse(evil_chunk.exists(), f"File escaped into models dir for upload_id='{bad_uid}'")

    def test_18_zero_byte_chunked_upload_rejected(self):
        """VERIFIED FIX: Multi-chunk upload of 0-byte chunks must be rejected on assembly with HTTP 400."""
        target_file = self.models_dir / "zero_assembled.safetensors"
        if target_file.exists():
            target_file.unlink()

        files0 = {"file": ("zero_assembled.safetensors", b"", "application/octet-stream")}
        d0 = {"filename": "zero_assembled.safetensors", "upload_id": "zero_bypass_fix", "chunk_index": 0, "total_chunks": 2}
        r0 = self.client.post("/api/models/upload", files=files0, data=d0)
        self.assertEqual(r0.status_code, 200)

        files1 = {"file": ("zero_assembled.safetensors", b"", "application/octet-stream")}
        d1 = {"filename": "zero_assembled.safetensors", "upload_id": "zero_bypass_fix", "chunk_index": 1, "total_chunks": 2}
        r1 = self.client.post("/api/models/upload", files=files1, data=d1)
        self.assertEqual(r1.status_code, 400, "Assembly of 0-byte file must be rejected with HTTP 400")
        self.assertIn("empty", r1.json()["detail"].lower())

        # Assert no empty file was created in models/
        self.assertFalse(target_file.exists(), "0-byte model file should not exist on disk!")

    def test_19_stream_history_overflow_preserves_complete(self):
        """VERIFIED FIX: 5000-event history cap must NEVER drop complete/terminal events."""
        bridge = get_runner_bridge()
        cfg = Config(model=ModelConfig(), generation=GenerationConfig(steps=5), runtime=RuntimeConfig(output_dir=str(self.outputs_dir)))
        job = RunJob("overflow_job_test_fix_001", cfg, demo_mode=True)
        bridge.jobs[job.job_id] = job
        bridge.run_id_map[job.job_id] = job.job_id

        # Fill history beyond 5000 events
        for i in range(5200):
            job.push_event("log", {"text": f"step log {i}"})

        # History should be capped at 5000 for regular logs
        self.assertEqual(len(job.history), 5000)

        # Push terminal complete event
        job.push_event("complete", {"status": "success", "job_id": job.job_id, "run_id": job.job_id, "outputs": []})
        job.push_sentinel()

        # Terminal event should be preserved
        self.assertEqual(len(job.history), 5001)
        self.assertEqual(job.history[-1]["event"], "complete")

        # Connect to stream replay
        resp = self.client.get(f"/api/run/{job.job_id}/stream")
        self.assertEqual(resp.status_code, 200)

        # Verify complete event is delivered in SSE stream
        self.assertIn("event: complete", resp.text)
        self.assertIn("overflow_job_test_fix_001", resp.text)

    def test_20_output_dir_confinement_blocks_arbitrary_system_paths(self):
        """VERIFIED FIX: runtime.output_dir set to /etc or /root must be rejected with HTTP 400."""
        for forbidden_dir in ["/etc", "/root", "/var", "/etc/passwd"]:
            payload = self._make_valid_run_payload(steps=1)
            payload["runtime"]["output_dir"] = forbidden_dir
            resp = self.client.post("/api/run", json=payload)
            self.assertEqual(resp.status_code, 400, f"Expected 400 for output_dir='{forbidden_dir}'")
            self.assertIn("outside allowed boundaries", resp.json().get("detail", ""))

            # Also check /api/config/validate
            v_resp = self.client.post("/api/config/validate", json={"runtime": {"output_dir": forbidden_dir}})
            self.assertEqual(v_resp.status_code, 200)
            self.assertFalse(v_resp.json()["valid"])
            self.assertTrue(any("must be within project root or temp" in err for err in v_resp.json()["errors"]))

    def test_21_event_loop_burst_submission_non_blocking(self):
        """VERIFIED FIX: Burst of 30 run submissions executes in sub-second time without blocking event loop."""
        payloads = [self._make_valid_run_payload(steps=1, seed=2000 + i) for i in range(30)]
        t0 = time.time()
        for p in payloads:
            r = self.client.post("/api/run", json=p)
            self.assertEqual(r.status_code, 200)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 2.0, f"30 submissions took {elapsed:.2f}s, indicating event loop blocking!")


if __name__ == "__main__":
    unittest.main()

