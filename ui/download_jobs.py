"""Thread-safe, truthful progress state for background model downloads."""

from __future__ import annotations

import threading
import time


TERMINAL_STATES = {"completed", "failed", "cancelled"}


class DownloadJob:
    def __init__(self, task_id: str, repo_id: str, filename: str | None, revision: str):
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self._clock = time.monotonic
        self._transfer_started: float | None = None
        self._transferred_bytes = 0
        self._completed_bytes = 0
        self.data = {
            "task_id": task_id,
            "repo_id": repo_id,
            "filename": filename,
            "revision": revision,
            "status": "queued",
            "progress": None,  # Legacy alias; unknown totals must not display 0%.
            "percent": None,
            "downloaded_bytes": 0,
            "total_bytes": None,
            "completed_files": 0,
            "total_files": None,
            "remaining_files": None,
            "current_file": None,
            "current_file_bytes": 0,
            "current_file_total_bytes": None,
            "speed_bytes_per_second": None,
            "eta_seconds": None,
            "error": None,
            "path": None,
            "metadata": None,
            "start_time": time.time(),
        }

    def snapshot(self) -> dict:
        with self.lock:
            return self.data.copy()

    def cancel(self) -> dict | None:
        with self.lock:
            if self.data["status"] in TERMINAL_STATES:
                return None
            self.cancel_event.set()
            self.data["status"] = "cancelling"
            return self.data.copy()

    def started(self) -> None:
        with self.lock:
            if not self.cancel_event.is_set():
                self.data["status"] = "preparing"

    def apply(self, event: dict) -> None:
        with self.lock:
            data = self.data
            kind = event["event"]
            if kind == "selection":
                count = event["total_files"]
                total = event.get("total_bytes")
                data["total_files"] = count
                data["total_bytes"] = total if isinstance(total, int) and total > 0 else None
            elif kind == "file_start":
                data["current_file"] = event["filename"]
                data["current_file_bytes"] = 0
                data["current_file_total_bytes"] = event.get("file_total_bytes")
                if self._transfer_started is None:
                    self._transfer_started = self._clock()
                if not self.cancel_event.is_set():
                    data["status"] = "downloading"
            elif kind == "file_progress":
                current = max(0, int(event["file_bytes"]))
                size = event.get("file_total_bytes") or data["current_file_total_bytes"]
                if size is not None:
                    current = min(current, size)
                    data["current_file_total_bytes"] = size
                previous = data["current_file_bytes"]
                data["current_file_bytes"] = current
                delta = max(0, current - previous)
                if delta:
                    self._transferred_bytes += delta
            elif kind == "file_complete":
                self._completed_bytes += event["size"]
                data["completed_files"] += 1
                data["current_file"] = None
                data["current_file_bytes"] = 0
                data["current_file_total_bytes"] = None
            elif kind == "verifying":
                data["current_file"] = None
                if not self.cancel_event.is_set():
                    data["status"] = "verifying"
            else:
                raise ValueError(f"Unknown download progress event: {kind}")

            if kind in {"selection", "file_progress", "file_complete"}:
                self._recalculate()

    def _recalculate(self) -> None:
        data = self.data
        count = data["total_files"]
        data["remaining_files"] = max(0, count - data["completed_files"]) if count is not None else None
        done = self._completed_bytes + data["current_file_bytes"]
        data["downloaded_bytes"] = done
        total = data["total_bytes"]
        percent = round(min(99.9, 100 * done / total), 1) if total else None
        data["percent"] = data["progress"] = percent
        if self._transferred_bytes and self._transfer_started is not None:
            elapsed = max(0.001, self._clock() - self._transfer_started)
            speed = self._transferred_bytes / elapsed
            data["speed_bytes_per_second"] = round(speed, 1)
            data["eta_seconds"] = round(max(0, total - done) / speed, 1) if total and speed > 0 else None

    def finish(self, status: str, *, path=None, metadata=None, error=None) -> dict:
        if status not in TERMINAL_STATES:
            raise ValueError(f"Invalid download terminal status: {status}")
        with self.lock:
            if status == "completed" and self.cancel_event.is_set():
                status, path, metadata = "cancelled", None, None
            data = self.data
            data["status"] = status
            data["current_file"] = None
            data["current_file_bytes"] = 0
            data["current_file_total_bytes"] = None
            data["speed_bytes_per_second"] = None
            data["eta_seconds"] = None
            data["error"] = error
            data["path"] = str(path) if path is not None else None
            data["metadata"] = metadata
            if status == "completed":
                if metadata and data["total_bytes"] is None:
                    data["total_bytes"] = metadata.get("downloaded_selection_bytes")
                if data["total_bytes"] is not None:
                    data["downloaded_bytes"] = data["total_bytes"]
                if data["total_files"] is not None:
                    data["completed_files"] = data["total_files"]
                    data["remaining_files"] = 0
                data["percent"] = data["progress"] = 100.0
            return data.copy()
