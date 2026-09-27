"""Legacy records gain the same summary through history and detail APIs."""

import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from ui.runner_bridge import RunnerBridge
from ui.server import app


def test_history_and_detail_project_legacy_records_without_rewriting_them():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.png"
        output = root / "result.png"
        Image.new("RGB", (60, 40)).save(source)
        Image.new("RGB", (64, 64)).save(output)
        legacy = {"schema_version": 1, "run_id": "legacy_run", "status": "success",
                  "input_image": str(source), "model": {"repo_id": "owner/model"},
                  "parameters": {"generation": {"steps": 4, "cfg": 1.0, "seed": 7}},
                  "outputs": [{"path": str(output), "width": 64, "height": 64}]}
        saved = root / "legacy_run.json"
        saved.write_text(json.dumps(legacy))
        bridge = RunnerBridge(output_dir=str(root))
        app.state.outputs_dir = root
        client = TestClient(app)
        try:
            with patch("ui.server.get_runner_bridge", return_value=bridge):
                listing = client.get("/api/runs")
                assert listing.status_code == 200
                summary = next(item["summary"] for item in listing.json()["runs"]
                               if item["run_id"] == "legacy_run")
                assert summary["input"]["aspect_ratio"] == "3:2"
                assert summary["model"]["parameters_billion"] is None
                detail = client.get("/api/runs/legacy_run")
                assert detail.status_code == 200
                assert detail.json()["summary"]["outputs"][0]["filename"] == "result.png"
                assert "summary" not in json.loads(saved.read_text())
        finally:
            bridge.shutdown()
            app.state.outputs_dir = None
