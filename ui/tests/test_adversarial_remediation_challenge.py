"""ui/tests/test_adversarial_remediation_challenge.py

Comprehensive Adversarial Stress & Exploit Verification Harness for Milestone 1 Re-Gating.
Written by Challenger 1 to empirically verify:
1. upload_id path traversal rejection & boundary confinement.
2. 0-byte chunk uploads and assembly empty-file rejection.
3. output_dir confinement (/etc, traversal, symlinks) and secure file serving.
4. SSE disconnect cleanup (replay, live, rapid cycling) and terminal event preservation.
5. Setup error attribution and predicted run_id resolution.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from PIL import Image
from starlette.testclient import TestClient

from qwen_runner.config import Config, GenerationConfig, ModelConfig, RuntimeConfig
from ui.runner_bridge import RunnerBridge, RunJob, get_runner_bridge
from ui.server import app, get_models_dir, get_outputs_dir, get_inputs_dir


class TestAdversarialRemediationChallenge(unittest.TestCase):
    """Deep adversarial probes against Milestone 1 remediation fixes."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="adv_rem_challenge_")
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

        # Create valid input image
        cls.valid_img = cls.inputs_dir / "valid_input.png"
        img = Image.new("RGB", (64, 64), color=(50, 100, 150))
        img.save(cls.valid_img)

        # Sync bridge
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

    def _make_payload(self, steps=2, seed=42, output_dir=None):
        return {
            "generation": {
                "images": [str(self.valid_img)],
                "prompt": "adversarial test prompt",
                "steps": steps,
                "seed": seed,
            },
            "runtime": {
                "device": "cpu",
                "dtype": "float32",
                "offload": "none",
                "output_dir": output_dir or str(self.outputs_dir),
            },
            "demo_mode": True,
        }

    # ========================================================================
    # SECTION 1: UPLOAD_ID PATH TRAVERSAL & BOUNDARY CONFINEMENT
    # ========================================================================

    def test_adv_upload_id_traversal_payloads(self):
        """Probe upload_id with extensive traversal and injection payloads."""
        malicious_ids = [
            "../escaped",
            "../../escaped",
            "../../../tmp/escaped",
            "../../../../../../../../tmp/pwn",
            "..\\win_escaped",
            "dir/sub",
            "dir/../sub",
            "valid;rm -rf /",
            "valid&cat /etc/passwd",
            "valid|echo",
            "valid$VAR",
            "valid`id`",
            "valid\x00null",
            "valid\nnewline",
            "   ",
            "\t\t",
            "foo bar",
            "foo.bar",
            "../",
            "/absolute/path",
        ]

        for bad_id in malicious_ids:
            files = {"file": ("test.safetensors", b"PAYLOAD", "application/octet-stream")}
            data = {
                "filename": "test.safetensors",
                "upload_id": bad_id,
                "chunk_index": 0,
                "total_chunks": 2,
            }
            resp = self.client.post("/api/models/upload", files=files, data=data)
            self.assertEqual(
                resp.status_code,
                400,
                f"Malicious upload_id='{repr(bad_id)}' was not rejected with HTTP 400! Got {resp.status_code}",
            )
            # Confirm no file was created in /tmp or root
            escaped_tmp = Path("/tmp/pwn_chunk_0000.part")
            self.assertFalse(escaped_tmp.exists(), f"File escaped into /tmp for bad_id={bad_id}!")
            escaped_in_models = self.models_dir / "escaped_chunk_0000.part"
            self.assertFalse(escaped_in_models.exists(), f"File escaped into models_dir for bad_id={bad_id}!")

    def test_adv_upload_id_legitimate_alphanumeric(self):
        """Legitimate upload_id containing alphanumeric, hyphens, and underscores must work."""
        valid_uid = "Valid-Upload_ID-2026_09"
        part0 = b"CHUNK_0_BYTES"
        part1 = b"CHUNK_1_BYTES"

        r0 = self.client.post(
            "/api/models/upload",
            files={"file": ("legit.safetensors", part0, "application/octet-stream")},
            data={"filename": "legit.safetensors", "upload_id": valid_uid, "chunk_index": 0, "total_chunks": 2},
        )
        self.assertEqual(r0.status_code, 200)
        self.assertEqual(r0.json()["status"], "uploading")

        r1 = self.client.post(
            "/api/models/upload",
            files={"file": ("legit.safetensors", part1, "application/octet-stream")},
            data={"filename": "legit.safetensors", "upload_id": valid_uid, "chunk_index": 1, "total_chunks": 2},
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "completed")

        assembled = self.models_dir / "legit.safetensors"
        self.assertTrue(assembled.is_file())
        self.assertEqual(assembled.read_bytes(), part0 + part1)
        assembled.unlink(missing_ok=True)

    def test_adv_upload_invalid_chunk_indices(self):
        """Negative chunk_index or chunk_index >= total_chunks or total_chunks < 1 must be rejected."""
        cases = [
            (-1, 2),
            (2, 2),
            (5, 2),
            (0, 0),
            (0, -1),
            (-2, -5),
        ]
        for c_idx, t_chunks in cases:
            files = {"file": ("chunk_bounds.safetensors", b"DATA", "application/octet-stream")}
            data = {"filename": "chunk_bounds.safetensors", "chunk_index": c_idx, "total_chunks": t_chunks}
            resp = self.client.post("/api/models/upload", files=files, data=data)
            self.assertEqual(resp.status_code, 400, f"Expected 400 for chunk_index={c_idx}, total_chunks={t_chunks}")

    # ========================================================================
    # SECTION 2: 0-BYTE CHUNK UPLOADS & EMPTY MODEL FILE DEFENSE
    # ========================================================================

    def test_adv_zero_byte_single_chunk_upload(self):
        """Single-chunk 0-byte upload must be rejected with HTTP 400 and deleted."""
        files = {"file": ("empty_single.safetensors", b"", "application/octet-stream")}
        data = {"filename": "empty_single.safetensors", "total_chunks": 1, "chunk_index": 0}
        resp = self.client.post("/api/models/upload", files=files, data=data)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", resp.json()["detail"].lower())
        self.assertFalse((self.models_dir / "empty_single.safetensors").exists())

    def test_adv_zero_byte_multi_chunk_assembly(self):
        """Multi-chunk upload with 3 empty chunks must be rejected on assembly with HTTP 400."""
        target = self.models_dir / "empty_triplet.safetensors"
        target.unlink(missing_ok=True)

        uid = "triplet_zero_test"
        for i in range(3):
            files = {"file": ("empty_triplet.safetensors", b"", "application/octet-stream")}
            data = {"filename": "empty_triplet.safetensors", "upload_id": uid, "chunk_index": i, "total_chunks": 3}
            resp = self.client.post("/api/models/upload", files=files, data=data)
            if i < 2:
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["status"], "uploading")
            else:
                self.assertEqual(resp.status_code, 400)
                self.assertIn("empty", resp.json()["detail"].lower())

        # Assert no file exists in models directory and no parts linger
        self.assertFalse(target.exists(), "0-byte model file was assembled in models_dir!")
        uploads_dir = self.models_dir / ".uploads"
        parts_remaining = list(uploads_dir.glob(f"{uid}*.part"))
        self.assertEqual(len(parts_remaining), 0, f"Lingering part files after empty rejection: {parts_remaining}")

    def test_adv_multi_chunk_one_nonempty_chunk_succeeds(self):
        """Multi-chunk upload where chunk 0 has 10 bytes and chunk 1 has 0 bytes must assemble 10 bytes."""
        target = self.models_dir / "partial_empty.safetensors"
        target.unlink(missing_ok=True)

        uid = "partial_zero_ok"
        files0 = {"file": ("partial_empty.safetensors", b"TEN_BYTES!", "application/octet-stream")}
        d0 = {"filename": "partial_empty.safetensors", "upload_id": uid, "chunk_index": 0, "total_chunks": 2}
        r0 = self.client.post("/api/models/upload", files=files0, data=d0)
        self.assertEqual(r0.status_code, 200)

        files1 = {"file": ("partial_empty.safetensors", b"", "application/octet-stream")}
        d1 = {"filename": "partial_empty.safetensors", "upload_id": uid, "chunk_index": 1, "total_chunks": 2}
        r1 = self.client.post("/api/models/upload", files=files1, data=d1)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "completed")
        self.assertEqual(r1.json()["size"], 10)

        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), b"TEN_BYTES!")
        target.unlink(missing_ok=True)

    # ========================================================================
    # SECTION 3: OUTPUT DIR CONFINEMENT & SERVING ATTACKS
    # ========================================================================

    def test_adv_output_dir_confinement_arbitrary_paths(self):
        """Attempts to register /etc, /root, /var/log, or ../ traversals must be rejected."""
        targets = ["/etc", "/root", "/var/log", "/usr", "../../../etc"]
        for t in targets:
            payload = self._make_payload(output_dir=t)
            resp = self.client.post("/api/run", json=payload)
            self.assertEqual(resp.status_code, 400, f"output_dir='{t}' was not blocked in /api/run!")
            self.assertIn("outside allowed boundaries", resp.json().get("detail", ""))

    def test_adv_output_file_serving_path_traversal(self):
        """GET /api/outputs/{filename} must block all traversal vectors."""
        traversal_requests = [
            "../../etc/passwd",
            "../etc/shadow",
            "....//etc/passwd",
            "%2e%2e%2fetc%2fpasswd",
            "sub/dir/output.png",
            "passwd",
        ]
        for tr in traversal_requests:
            resp = self.client.get(f"/api/outputs/{tr}")
            self.assertEqual(resp.status_code, 404, f"Traversal '{tr}' did not return 404! Got {resp.status_code}")

    def test_adv_output_file_serving_symlink_defense(self):
        """Symlink in output_dir pointing outside to /etc/passwd must be blocked by resolve().is_relative_to()."""
        symlink_path = self.outputs_dir / "evil_symlink.json"
        try:
            symlink_path.symlink_to("/etc/passwd")
        except OSError:
            self.skipTest("Symlinks not permitted in test environment")

        try:
            resp = self.client.get("/api/outputs/evil_symlink.json")
            self.assertEqual(resp.status_code, 404, "Symlink pointing to /etc/passwd returned non-404!")
        finally:
            symlink_path.unlink(missing_ok=True)

    def test_adv_output_file_serving_legitimate_file(self):
        """Legitimate file inside output_dir must be served with correct content-type."""
        legit_file = self.outputs_dir / "legit_test_result.png"
        img = Image.new("RGB", (32, 32), color=(200, 100, 50))
        img.save(legit_file)

        resp = self.client.get("/api/outputs/legit_test_result.png")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "image/png")
        self.assertEqual(len(resp.content), legit_file.stat().st_size)
        legit_file.unlink(missing_ok=True)

    # ========================================================================
    # SECTION 4: SSE DISCONNECT CLEANUP & TERMINAL EVENT PRESERVATION
    # ========================================================================

    def test_adv_sse_disconnect_during_history_replay_cleans_subscribers(self):
        """Client disconnect during historical replay must clean up subscriber queue immediately."""
        bridge = get_runner_bridge()
        cfg = Config(model=ModelConfig(), generation=GenerationConfig(steps=1), runtime=RuntimeConfig(output_dir=str(self.outputs_dir)))
        job = RunJob("replay_disc_test", cfg, demo_mode=True)
        for i in range(50):
            job.history.append({"event": "log", "data": {"text": f"historical log {i}"}})
        bridge.jobs[job.job_id] = job
        bridge.run_id_map[job.job_id] = job.job_id

        async def run_disconnect():
            gen = bridge.event_generator(job.job_id, MagicMock())
            # Read first event from history
            first = await gen.asend(None)
            self.assertIn("historical log 0", first)
            # Force disconnect during replay
            await gen.aclose()
            # Queue must be removed
            self.assertEqual(len(job.subscribers), 0, "Subscriber queue leaked after disconnect during replay!")

        asyncio.run(run_disconnect())

    def test_adv_sse_50_rapid_disconnect_stress(self):
        """50 rapid sequential connections and immediate disconnects must leave 0 subscriber queues."""
        payload = self._make_payload(steps=10, seed=3333)
        r = self.client.post("/api/run", json=payload)
        self.assertEqual(r.status_code, 200)
        run_id = r.json()["run_id"]

        bridge = get_runner_bridge()
        job = bridge.jobs.get(run_id)
        self.assertIsNotNone(job)

        for _ in range(50):
            try:
                with self.client.stream("GET", f"/api/run/{run_id}/stream") as stream:
                    for line in stream.iter_lines():
                        if line:
                            break
            except Exception:
                pass

        job.done_event.wait(timeout=5.0)
        self.assertEqual(len(job.subscribers), 0, f"Subscriber queue leak detected! Count: {len(job.subscribers)}")

    def test_adv_history_overflow_preserves_complete_and_error(self):
        """Pushing 6000 events must cap logs at 5000 and reliably preserve terminal complete and error."""
        cfg = Config(model=ModelConfig(), generation=GenerationConfig(steps=1), runtime=RuntimeConfig(output_dir=str(self.outputs_dir)))
        job = RunJob("overflow_stress_job", cfg, demo_mode=True)
        bridge = get_runner_bridge()
        bridge.jobs[job.job_id] = job
        bridge.run_id_map[job.job_id] = job.job_id

        # 6000 log events
        for i in range(6000):
            job.push_event("log", {"text": f"log {i}"})
        self.assertEqual(len(job.history), 5000, "Regular logs exceeded 5000 cap!")

        # Push terminal status and complete
        job.push_event("status", {"status": "success", "job_id": job.job_id})
        job.push_event("complete", {"status": "success", "job_id": job.job_id, "outputs": ["out1.png"]})
        job.push_sentinel()

        # Both must be preserved
        self.assertEqual(len(job.history), 5002)
        events_in_history = [e["event"] for e in job.history]
        self.assertIn("status", events_in_history)
        self.assertIn("complete", events_in_history)

        # Stream replay must deliver the complete event
        resp = self.client.get(f"/api/run/{job.job_id}/stream")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("event: complete", resp.text)
        self.assertIn("out1.png", resp.text)

    # ========================================================================
    # SECTION 5: SETUP ERROR ATTRIBUTION & PREDICTED RUN_ID RESOLUTION
    # ========================================================================

    def test_adv_setup_error_attribution_and_no_404(self):
        """Failed setup must map to predicted run_id, return HTTP 200 on /api/runs/{run_id}, not 404."""
        bad_img = self.root / "corrupted_input.png"
        bad_img.write_bytes(b"NOT_A_VALID_IMAGE_HEADER")

        payload = {
            "generation": {"images": [str(bad_img)], "steps": 1},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none", "output_dir": str(self.outputs_dir)},
            "demo_mode": True,
        }
        resp = self.client.post("/api/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        predicted_run_id = resp.json()["run_id"]

        time.sleep(0.3)

        rec_resp = self.client.get(f"/api/runs/{predicted_run_id}")
        self.assertEqual(rec_resp.status_code, 200, f"Expected 200 for setup error run, got {rec_resp.status_code}")
        data = rec_resp.json()
        self.assertIn(data.get("status"), ["error", "setup_error"])
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
