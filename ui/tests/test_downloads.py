"""Measured Hub download progress, cancellation, retry, and API contract."""

import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from qwen_runner.models import DownloadCancelled, ModelStore, parse_model_ref
from ui.download_jobs import DownloadJob
from ui.server import app, download_tasks, download_tasks_lock


def wait_for_status(client, task_id, wanted):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        payload = client.get(f"/api/models/download/progress/{task_id}").json()
        if payload["status"] == wanted:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"Download stayed at {payload['status']}, expected {wanted}")


def test_progress_is_measured_and_unknown_totals_stay_unknown():
    job = DownloadJob("dl_test", "owner/model", None, "main")
    assert job.snapshot()["percent"] is None
    job.started()
    job.apply({"event": "selection", "total_files": 2, "total_bytes": None})
    job.apply({"event": "file_start", "filename": "a.gguf", "file_total_bytes": None})
    job.apply({"event": "file_progress", "filename": "a.gguf", "file_bytes": 40, "file_total_bytes": 100})
    state = job.snapshot()
    assert state["downloaded_bytes"] == 40
    assert state["current_file"] == "a.gguf"
    assert state["percent"] is None
    assert state["speed_bytes_per_second"] > 0
    job.apply({"event": "file_complete", "filename": "a.gguf", "size": 100})
    assert job.snapshot()["completed_files"] == 1
    assert job.snapshot()["remaining_files"] == 1
    failed = job.finish("failed", error="connection closed")
    assert failed["percent"] is None
    assert failed["error"] == "connection closed"

    known = DownloadJob("dl_known", "owner/model", None, "main")
    known.apply({"event": "selection", "total_files": 2, "total_bytes": 200})
    known.apply({"event": "file_start", "filename": "a.gguf", "file_total_bytes": 100})
    known.apply({"event": "file_progress", "filename": "a.gguf", "file_bytes": 50, "file_total_bytes": 100})
    assert known.snapshot()["percent"] == 25.0
    assert known.snapshot()["eta_seconds"] is not None
    known.apply({"event": "file_complete", "filename": "a.gguf", "size": 100})
    assert known.snapshot()["percent"] == 50.0
    assert known.finish("completed", metadata={"downloaded_selection_bytes": 200})["percent"] == 100.0


def test_model_store_reports_file_progress_and_reuses_manifest():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        api = Mock()
        api.model_info.return_value = SimpleNamespace(
            sha="commit123", siblings=[
                SimpleNamespace(rfilename="model_index.json", size=40),
                SimpleNamespace(rfilename="transformer/model.safetensors", size=100),
            ],
        )

        def download(**options):
            path = root / "hub" / "snapshots" / options["revision"] / options["filename"]
            path.parent.mkdir(parents=True, exist_ok=True)
            content = (json.dumps({"_class_name": "QwenImage21Pipeline"}).encode()
                       if options["filename"] == "model_index.json" else b"w" * 100)
            path.write_bytes(content)
            bar = options["tqdm_class"](total=len(content), desc=options["filename"])
            bar.update(len(content))
            bar.close()
            return str(path)

        events = []
        store = ModelStore(root, api=api, downloader=download)
        ref = parse_model_ref("owner/model")
        path, metadata = store.fetch(ref, on_progress=events.append)
        assert path.is_dir()
        assert metadata["cache_hit"] is False
        assert events[0] == {"event": "selection", "total_files": 2, "total_bytes": 140}
        assert any(item["event"] == "file_progress" and item["file_bytes"] == 100 for item in events)
        assert events[-1]["event"] == "verifying"
        api.model_info.assert_called_once_with("owner/model", revision="main", files_metadata=True)
        api.reset_mock()
        events.clear()
        path_again, metadata = store.fetch(ref, on_progress=events.append)
        assert path_again == path and metadata["cache_hit"] is True
        api.model_info.assert_not_called()
        assert [item["event"] for item in events] == ["selection", "file_complete", "file_complete", "verifying"]


def test_cancellation_between_files_does_not_publish_a_complete_manifest():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        api = Mock()
        api.model_info.return_value = SimpleNamespace(
            sha="commit123", siblings=[
                SimpleNamespace(rfilename="model_index.json", size=39),
                SimpleNamespace(rfilename="transformer/model.safetensors", size=100),
            ],
        )
        downloaded = []
        cancelled = False

        def download(**options):
            downloaded.append(options["filename"])
            path = root / "hub" / "snapshots" / options["revision"] / options["filename"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"_class_name": "QwenImage21Pipeline"}))
            return str(path)

        def observe(event):
            nonlocal cancelled
            if event["event"] == "file_complete":
                cancelled = True

        store = ModelStore(root, api=api, downloader=download)
        with pytest.raises(DownloadCancelled):
            store.fetch(parse_model_ref("owner/model"), on_progress=observe,
                        should_cancel=lambda: cancelled)
        assert downloaded == ["model_index.json"]
        assert not list((root / "manifests").glob("*.json"))


def test_download_api_cancel_retry_and_terminal_sse():
    with tempfile.TemporaryDirectory() as directory:
        entered = threading.Event()
        release = threading.Event()
        attempts = []

        class FakeStore:
            def __init__(self, root):
                self.root = root

            def fetch(self, ref, on_progress, should_cancel):
                attempts.append(ref)
                on_progress({"event": "selection", "total_files": 1, "total_bytes": 100})
                on_progress({"event": "file_start", "filename": "weights.gguf", "file_total_bytes": 100})
                if len(attempts) == 1:
                    entered.set()
                    assert release.wait(2)
                    if should_cancel():
                        raise DownloadCancelled()
                on_progress({"event": "file_progress", "filename": "weights.gguf", "file_bytes": 100,
                             "file_total_bytes": 100})
                on_progress({"event": "file_complete", "filename": "weights.gguf", "size": 100})
                on_progress({"event": "verifying"})
                return Path(self.root) / "weights.gguf", {"downloaded_selection_bytes": 100}

        app.state.models_dir = Path(directory)
        client = TestClient(app)
        with patch("ui.server.ModelStore", FakeStore):
            response = client.post("/api/models/download", json={"repo_id": "owner/model"})
            task_id = response.json()["task_id"]
            assert entered.wait(2)
            before = client.get(f"/api/models/download/progress/{task_id}").json()
            assert before["status"] == "downloading"
            assert before["percent"] == 0.0
            cancelling = client.post(f"/api/models/download/{task_id}/cancel").json()
            assert cancelling["status"] == "cancelling"
            release.set()
            assert wait_for_status(client, task_id, "cancelled")["percent"] == 0.0
            assert client.post(f"/api/models/download/{task_id}/cancel").status_code == 409
            retried = client.post(f"/api/models/download/{task_id}/retry")
            assert retried.status_code == 200
            next_id = retried.json()["task_id"]
            completed = wait_for_status(client, next_id, "completed")
            assert completed["percent"] == 100.0
            assert completed["completed_files"] == 1
            assert len(attempts) == 2
            stream = client.get(f"/api/models/download/progress/{next_id}?stream=true")
            assert "event: complete" in stream.text
            assert client.post(f"/api/models/download/{next_id}/retry").status_code == 409
        app.state.models_dir = None
        with download_tasks_lock:
            download_tasks.pop(task_id, None)
            download_tasks.pop(next_id, None)


def test_offline_error_is_failed_not_completed():
    class OfflineStore:
        def __init__(self, root):
            pass

        def fetch(self, ref, on_progress, should_cancel):
            raise FileNotFoundError("offline cache is incomplete")

    with tempfile.TemporaryDirectory() as directory:
        app.state.models_dir = Path(directory)
        client = TestClient(app)
        with patch("ui.server.ModelStore", OfflineStore):
            task_id = client.post("/api/models/download", json={"repo_id": "owner/model"}).json()["task_id"]
            result = wait_for_status(client, task_id, "failed")
            assert result["percent"] is None
            assert "offline cache" in result["error"]
        app.state.models_dir = None
        with download_tasks_lock:
            download_tasks.pop(task_id, None)
