#!/usr/bin/env python3
"""Opt-in live Hub/API smoke check: pinned small files, isolated storage, no inference.

Run with host network/loopback access: timeout 120 .venv/bin/python scripts/validate_hub_download.py
Requires the existing UI/test dependencies. Evidence remains in a printed /tmp directory.
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES = [
    ("hf-internal-testing/tiny-random-GPT2Model", "d6694b0d8fe17978761c9305dc151780506b192e", "tokenizer.json"),
    ("hf-internal-testing/tiny-random-gpt2", "71034c5d8bde858ff824298bdedc65515b97d2b9", "model.safetensors"),
]


def main():
    root = Path(tempfile.mkdtemp(prefix="qwen-hub-validation-"))
    print(f"Evidence: {root}", flush=True)
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_XET_CACHE"] = str(root / "xet")
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "10"
    from huggingface_hub import HfApi, file_download
    from fastapi.testclient import TestClient
    from ui.download_jobs import DownloadJob, TERMINAL_STATES
    from ui.server import app

    specs = []
    for repo, revision, filename in FIXTURES:
        info = HfApi(token=False).model_info(repo, revision=revision, files_metadata=True, timeout=10)
        item = next(s for s in info.siblings if s.rfilename == filename)
        assert info.sha == revision and 0 < item.size <= 1024 * 1024
        specs.append({"repo_id": repo, "revision": revision, "filename": filename,
                      "size": item.size, "blob_id": item.blob_id,
                      "lfs_sha256": item.lfs.sha256 if item.lfs else None})
    assert sum(s["size"] for s in specs) <= 1024 * 1024

    lock = threading.Lock()
    observations, results = [], {}
    cancel_on_progress = False
    cancelled_ids = set()
    original_apply = DownloadJob.apply
    previous_models_dir = getattr(app.state, "models_dir", None)
    app.state.models_dir = root / "models"

    with TestClient(app) as client:
        def observe(job, event):
            original_apply(job, event)
            sample = {"event": event, "state": job.snapshot()}
            with lock:
                observations.append(sample)
                with (root / "events.jsonl").open("a") as handle:
                    handle.write(json.dumps(sample) + "\n")
            # Request real API cancellation after a real byte callback; no fabricated progress/delay.
            if cancel_on_progress and event["event"] == "file_progress" and event["file_bytes"] > 0:
                if job.data["task_id"] not in cancelled_ids:
                    cancelled_ids.add(job.data["task_id"])
                    response = client.post(f"/api/models/download/{job.data['task_id']}/cancel")
                    assert response.status_code == 200

        def post(path, payload=None):
            response = client.post(path, json=payload)
            assert response.status_code == 200, response.text
            return response.json()

        def wait(task_id, expected):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                response = client.get(f"/api/models/download/progress/{task_id}")
                assert response.status_code == 200
                state = response.json()
                if state["status"] in TERMINAL_STATES:
                    assert state["status"] == expected, state
                    stream = client.get(f"/api/models/download/progress/{task_id}?stream=true")
                    assert stream.status_code == 200 and "event: complete" in stream.text
                    results[task_id] = state
                    return state
                time.sleep(0.02)
            client.post(f"/api/models/download/{task_id}/cancel")
            raise AssertionError(f"Download timeout: {state}")

        try:
            with patch.object(DownloadJob, "apply", observe), \
                 patch.object(file_download, "http_get", wraps=file_download.http_get) as http, \
                 patch.object(file_download, "xet_get", wraps=file_download.xet_get) as xet:
                for index, spec in enumerate(specs):
                    cancel_on_progress = index == 1
                    task_id = post("/api/models/download", {k: spec[k] for k in ("repo_id", "revision", "filename")})["task_id"]
                    state = wait(task_id, "cancelled" if cancel_on_progress else "completed")
                    progress = [s for s in observations if s["state"]["task_id"] == task_id and s["event"]["event"] == "file_progress"]
                    assert progress and max(s["event"]["file_bytes"] for s in progress) == spec["size"]
                    assert any(s["state"]["speed_bytes_per_second"] > 0 for s in progress)
                    assert all(s["state"]["percent"] < 100 for s in progress)
                    if cancel_on_progress:
                        assert state["percent"] < 100 and state["path"] is None
                        assert len(list((root / "models/manifests").glob("*.json"))) == 1
                        cancel_on_progress = False
                        retry = post(f"/api/models/download/{task_id}/retry")
                        assert retry["task_id"] != task_id and retry["retry_of"] == task_id
                        state = wait(retry["task_id"], "completed")
                    assert state["metadata"]["cache_hit"] is False and state["percent"] == 100
                    path = Path(state["path"])
                    assert path.stat().st_size == spec["size"]
                    content = path.read_bytes()
                    digest = hashlib.sha256(content).hexdigest()
                    if spec["lfs_sha256"]:
                        assert digest == spec["lfs_sha256"]
                    else:
                        assert hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest() == spec["blob_id"]
                    spec["saved_sha256"] = digest
                    transfers_before_cache = (http.call_count, xet.call_count)
                    cached_id = post("/api/models/download", {k: spec[k] for k in ("repo_id", "revision", "filename")})["task_id"]
                    cached = wait(cached_id, "completed")
                    assert cached["metadata"]["cache_hit"] is True and cached["speed_bytes_per_second"] is None
                    assert transfers_before_cache == (http.call_count, xet.call_count)

                bad = post("/api/models/download", {"repo_id": specs[0]["repo_id"], "revision": specs[0]["revision"], "filename": "missing-diagnostic-file.safetensors"})
                failed = wait(bad["task_id"], "failed")
                assert failed["percent"] is None and "not found" in failed["error"]
                retried = post(f"/api/models/download/{bad['task_id']}/retry")
                assert retried["task_id"] != bad["task_id"]
                wait(retried["task_id"], "failed")
                catalog = client.get("/api/models").json()["models"]
                assert len(catalog) == 2 and all(not m["compatible"] for m in catalog)
                assert {m["filename"] for m in catalog} == {s["filename"] for s in specs}
                assert http.call_count > 0 and xet.call_count > 0, "Both real transfer paths must run"
                evidence = {"fixtures": specs, "results": results, "catalog": catalog,
                            "http_calls": http.call_count, "xet_calls": xet.call_count,
                            "scope": "Download/API only; incompatible tiny fixtures, no model inference. Speed measures reconstructed bytes."}
                (root / "evidence.json").write_text(json.dumps(evidence, indent=2))
                print(json.dumps({"evidence": str(root), "http_calls": http.call_count,
                                  "xet_calls": xet.call_count, "statuses": [s["status"] for s in results.values()]}))
        finally:
            app.state.models_dir = previous_models_dir


if __name__ == "__main__":
    main()
