"""Server output defaults agree across the browser, validation, jobs, and history."""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from ui.app import configure_app, parse_args
import ui.runner_bridge as bridge_module
import ui.server as server


@pytest.mark.parametrize("configuration", ["cli", "environment", "default"])
def test_output_directory_defaults_and_explicit_overrides(tmp_path, monkeypatch, configuration):
    bridge_module.shutdown_runner_bridge()
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path / "project")
    for field, variable in (("inputs_dir", "INPUTS_DIR"), ("models_dir", "MODELS_DIR"),
                            ("loras_dir", "LORAS_DIR"), ("outputs_dir", "OUTPUTS_DIR")):
        monkeypatch.setattr(server.app.state, field, None, raising=False)
        monkeypatch.setenv(variable, "")
    monkeypatch.setattr(server.app.state, "demo_mode", False)
    monkeypatch.setenv("DEMO_MODE", "")
    root = tmp_path / 'chosen " & <output>'
    flags = ["--inputs-dir", str(tmp_path / "inputs"), "--models-dir", str(tmp_path / "models"),
             "--loras-dir", str(tmp_path / "loras")]
    if configuration == "cli":
        flags += ["--outputs-dir", str(root)]
    elif configuration == "environment":
        monkeypatch.setenv("OUTPUTS_DIR", str(root))
    else:
        root = tmp_path / "project" / "outputs"
    configure_app(parse_args(flags))
    # State/CLI takes precedence over a conflicting environment root.
    ignored = tmp_path / "ignored-env"
    if configuration == "cli":
        monkeypatch.setenv("OUTPUTS_DIR", str(ignored))
    for folder, run_id in ((root, "configured_saved"), (working / "outputs", "unrelated_saved"),
                           (ignored, "ignored_saved")):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{run_id}.json").write_text(json.dumps({"run_id": run_id, "status": "success", "outputs": []}))
    image = tmp_path / "input.png"
    Image.new("RGB", (32, 32), "blue").save(image)
    payload = {"demo_mode": True, "generation": {"input_images": [str(image)], "reference_images": [],
               "steps": 1, "resolution": 32}, "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"}}
    default_jobs = []

    class OutputField(HTMLParser):
        attrs = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "input" and attrs.get("id") == "param-output-dir":
                self.attrs = attrs

    try:
        with TestClient(server.app) as client:
            parser = OutputField()
            response = client.get("/")
            assert response.status_code == 200
            parser.feed(response.text)
            assert parser.attrs["value"] == str(root)
            assert "__OUTPUTS_DIR__" not in response.text
            assert {run["run_id"] for run in client.get("/api/runs").json()["runs"]} == {"configured_saved"}
            bridge = bridge_module.get_runner_bridge()
            assert bridge.output_dir == root
            assert bridge._get_search_output_dirs() == [root]

            override = tmp_path / "override"
            for fields, expected in (({}, str(root)), ({"output_dir": ""}, str(root)),
                                     ({"output_dir": str(override)}, str(override)),
                                     ({"flat": str(override / "flat")}, str(override / "flat")),
                                     ({"output_dir": "outputs"}, "outputs")):
                request = {**payload, "runtime": {**payload["runtime"], **fields}}
                if "flat" in fields:
                    request["output_dir"] = request["runtime"].pop("flat")
                validation = client.post("/api/config/validate", json=request).json()
                assert validation["valid"], validation
                assert validation["config"]["runtime"]["output_dir"] == expected
                submitted = client.post("/api/run", json=request)
                assert submitted.status_code == 200, submitted.text
                run_id = submitted.json()["run_id"]
                job = bridge.jobs[run_id]
                assert job.done_event.wait(10), "Temporary demo job did not finish"
                record = client.get(f"/api/runs/{run_id}").json()
                assert record["status"] == "success", record
                assert record["parameters"]["runtime"]["output_dir"] == expected
                directory = Path(expected).resolve()
                assert (directory / f"{run_id}.json").is_file()
                output = Path(record["outputs"][0]["path"])
                assert output.parent == directory
                served = client.get(f"/api/outputs/{output.name}")
                assert served.status_code == 200
                assert hashlib.sha256(served.content).hexdigest() == record["outputs"][0]["sha256"]
                if expected == str(root):
                    default_jobs.append(run_id)
            for invalid in (None, False, [], "/etc",):
                request = {**payload, "runtime": {**payload["runtime"], "output_dir": invalid}}
                assert client.post("/api/config/validate", json=request).json()["valid"] is False
                assert client.post("/api/run", json=request).status_code == 400
            flat_unsafe = {**payload, "output_dir": "/etc"}
            assert client.post("/api/run", json=flat_unsafe).status_code == 400
        # A fresh singleton still reads the configured default's durable history.
        assert bridge_module._bridge_instance is None
        with TestClient(server.app) as client:
            history = {run["run_id"] for run in client.get("/api/runs").json()["runs"]}
            assert history == {"configured_saved", *default_jobs}
    finally:
        bridge_module.shutdown_runner_bridge()
