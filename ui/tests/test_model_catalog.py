"""Selected catalog model must remain the only source for web inference."""

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from ui.model_catalog import discover_models, resolve_selected_model
from ui.server import app


def make_pipeline(root: Path, name: str, pipeline_class="QwenImage21Pipeline") -> Path:
    target = root / name
    target.mkdir()
    (target / "model_index.json").write_text(json.dumps({"_class_name": pipeline_class}))
    for component in ("transformer", "text_encoder", "processor", "vae"):
        folder = target / component
        folder.mkdir()
        if component != "processor":
            (folder / "model.safetensors").write_bytes(b"test weights")
    (target / "transformer" / "config.json").write_text("{}")
    return target


def test_catalog_ids_are_stable_and_incompatible_models_are_visible():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        good = make_pipeline(root, "supported")
        make_pipeline(root, "older", "QwenImagePipeline")
        (root / "bad.gguf").write_bytes(b"GGUFfake")
        first = discover_models(root)
        second = discover_models(root)
        assert [(item["id"], item["compatible"]) for item in first] == [
            (item["id"], item["compatible"]) for item in second
        ]
        chosen = next(item for item in first if item["path"] == str(good))
        assert chosen["compatible"] is True
        assert resolve_selected_model(root, chosen["id"])["path"] == str(good)
        older = next(item for item in first if item["name"] == "older")
        assert older["compatible"] is False
        assert "QwenImage21Pipeline" in older["compatibility_reason"]
        assert next(item for item in first if item["name"] == "bad.gguf")["compatible"] is False


def test_selected_id_overrides_conflicting_source_and_rejects_stale_id():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        selected = make_pipeline(root, "chosen")
        wrong = make_pipeline(root, "wrong")
        selected_id = next(item["id"] for item in discover_models(root) if item["path"] == str(selected))
        image = root / "input.png"
        Image.new("RGB", (32, 32)).save(image)
        payload = {
            "selected_model_id": selected_id,
            "model": {"source": str(wrong), "base_model": str(wrong), "selected_model_id": "forged"},
            "generation": {"input_images": [str(image)], "reference_images": [], "steps": 1},
            "runtime": {"device": "cpu", "dtype": "float32", "offload": "none"},
        }
        app.state.models_dir = root
        try:
            client = TestClient(app)
            validation = client.post("/api/config/validate", json=payload)
            assert validation.status_code == 200
            assert validation.json()["valid"] is True
            resolved = validation.json()["config"]["model"]
            assert resolved["source"] == str(selected)
            assert resolved["base_model"] == str(selected)
            assert resolved["selected_model_id"] == selected_id

            fake_bridge = MagicMock()
            fake_bridge.submit_run.return_value.job_id = "selected_job"
            with patch("ui.server.get_runner_bridge", return_value=fake_bridge):
                response = client.post("/api/run", json=payload)
            assert response.status_code == 200
            submitted = fake_bridge.submit_run.call_args.kwargs["config"]
            assert submitted.model.source == str(selected)
            assert submitted.model.selected_model_id == selected_id

            payload["selected_model_id"] = "model_stale"
            rejected = client.post("/api/run", json=payload)
            assert rejected.status_code == 400
            assert "no longer available" in rejected.json()["detail"]
        finally:
            app.state.models_dir = None


def test_legacy_direct_source_and_incompatible_selection():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        older = make_pipeline(root, "older", "QwenImagePipeline")
        incompatible_id = next(item["id"] for item in discover_models(root) if item["path"] == str(older))
        app.state.models_dir = root
        try:
            client = TestClient(app)
            rejected = client.post("/api/config/validate", json={"selected_model_id": incompatible_id})
            assert rejected.json()["valid"] is False
            assert "incompatible" in rejected.json()["errors"][0]
            legacy = client.post("/api/config/validate", json={"model": {"source": "custom/model"}})
            assert legacy.json()["valid"] is True
            assert legacy.json()["config"]["model"]["source"] == "custom/model"
        finally:
            app.state.models_dir = None
