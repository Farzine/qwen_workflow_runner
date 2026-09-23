"""Common test client fixtures, contract reference app, and test utilities.

Provides transparent fallback to contract-compliant ASGI app if ui.server is not yet implemented,
ensuring progressive testability and verification across all project milestones.
"""

from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

UI_DIR = REPO_ROOT / "ui"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from PIL import Image
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from qwen_runner.config import Config, GenerationConfig, ModelConfig, RuntimeConfig
from qwen_runner.runner import run as core_run


class DemoBackend:
    """Fast, deterministic backend for demo/test mode producing authentic PIL images."""

    def __init__(self, config):
        import torch

        self.config = config
        self.torch = torch
        self.metadata = {
            "model": {"repo_id": config.model.source, "mode": "demo"},
            "text_encoder": {"repo_id": config.model.text_encoder_source or config.model.source},
            "pipe": "WorkflowQwenImage21Pipeline[Demo]",
        }

    def load(self):
        return self

    def generate(self, images, canvas, seed):
        from PIL import ImageDraw

        outputs = []
        width, height = canvas
        for i in range(self.config.generation.batch_size):
            img = Image.new("RGB", (width, height), color=(30 + (seed + i) % 100, 50, 80))
            draw = ImageDraw.Draw(img)
            if images:
                ref0 = images[0].copy()
                ref0.thumbnail((max(32, width // 4), max(32, height // 4)))
                img.paste(ref0, (10, 10))
            draw.text((10, max(0, height - 30)), f"Demo #{i+1} Seed:{seed}", fill=(255, 255, 255))
            outputs.append(img)
        return outputs


def create_contract_app(inputs_dir: Path | None = None, models_dir: Path | None = None, outputs_dir: Path | None = None):
    """Create reference contract-compliant FastAPI app if ui.server is not yet built."""
    app = FastAPI(title="Qwen Workflow Runner Web UI (Contract Reference)")

    effective_inputs = Path(inputs_dir or "/mnt/lab/farzine/inputs")
    effective_models = Path(models_dir or REPO_ROOT / "models")
    effective_outputs = Path(outputs_dir or REPO_ROOT / "outputs")
    effective_models.mkdir(parents=True, exist_ok=True)
    effective_outputs.mkdir(parents=True, exist_ok=True)

    thumb_cache: dict[str, bytes] = {}
    active_runs: list[dict] = []
    download_tasks: dict[str, dict] = {}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return "<html><head><title>Qwen Workflow Runner</title></head><body><h1>Qwen Workflow Runner</h1></body></html>"

    @app.get("/api/health")
    def health():
        return {"status": "ok", "timestamp": time.time()}

    @app.get("/api/inputs/browse")
    def browse_inputs(folder: str | None = None):
        base = effective_inputs
        if folder:
            target = (base / folder).resolve()
            # Prevent directory traversal
            try:
                target.relative_to(base.resolve())
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid folder path")
            if not target.exists() or not target.is_dir():
                raise HTTPException(status_code=404, detail=f"Folder '{folder}' not found")
        else:
            target = base

        if not target.exists():
            return {"folders": [], "images": []}

        folders = []
        images = []
        valid_exts = {".png", ".jpg", ".jpeg", ".webp"}

        try:
            for item in sorted(target.iterdir()):
                if item.name.startswith(".") or item.name == ".DS_Store":
                    continue
                if item.is_dir():
                    folders.append(item.name)
                elif item.is_file() and item.suffix.lower() in valid_exts:
                    try:
                        with Image.open(item) as im:
                            w, h = im.size
                    except Exception:
                        w, h = 0, 0
                    images.append({
                        "name": item.name,
                        "path": str(item),
                        "width": w,
                        "height": h,
                        "thumb_url": f"/api/inputs/thumbnail?path={item}",
                    })
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {"folders": folders, "images": images}

    @app.get("/api/inputs/thumbnail")
    def get_thumbnail(path: str):
        file_path = Path(path).resolve()
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Image file not found")

        if path in thumb_cache:
            return Response(content=thumb_cache[path], media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

        try:
            with Image.open(file_path) as img:
                img = img.convert("RGB")
                img.thumbnail((256, 256))
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=85)
                data = buf.getvalue()
                thumb_cache[path] = data
                return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to generate thumbnail: {e}")

    @app.get("/api/models")
    def list_models():
        models = []
        valid_exts = {".gguf", ".safetensors"}
        if effective_models.exists():
            for item in sorted(effective_models.iterdir()):
                if item.name.startswith("."):
                    continue
                if item.is_file() and item.suffix.lower() in valid_exts:
                    m_type = "gguf" if item.suffix.lower() == ".gguf" else "safetensors"
                    models.append({
                        "name": item.name,
                        "path": str(item),
                        "type": m_type,
                        "is_cached": True,
                    })
        return {"models": models}

    @app.post("/api/models/download")
    def download_model(payload: dict):
        repo_id = payload.get("repo_id")
        if not repo_id or not isinstance(repo_id, str) or not repo_id.strip():
            raise HTTPException(status_code=400, detail="repo_id is required and cannot be empty")
        task_id = str(uuid.uuid4())
        download_tasks[task_id] = {
            "task_id": task_id,
            "repo_id": repo_id,
            "filename": payload.get("filename"),
            "status": "in_progress",
            "progress": 0.0,
        }
        return {"task_id": task_id}

    @app.get("/api/models/download/progress/{task_id}")
    def download_progress(task_id: str):
        if task_id not in download_tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        task = download_tasks[task_id]
        task["progress"] = 100.0
        task["status"] = "completed"
        return task

    @app.post("/api/models/upload")
    async def upload_model(file: UploadFile = File(...)):
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file selected")
        ext = Path(file.filename).suffix.lower()
        if ext not in {".gguf", ".safetensors"}:
            raise HTTPException(status_code=400, detail="Invalid model extension; only .gguf and .safetensors allowed")

        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="File is empty")

        save_path = effective_models / Path(file.filename).name
        save_path.write_bytes(content)
        return {"success": True, "filename": file.filename, "path": str(save_path)}

    from dataclasses import fields

    m_fields = {f.name for f in fields(ModelConfig)}
    g_fields = {f.name for f in fields(GenerationConfig)}
    r_fields = {f.name for f in fields(RuntimeConfig)}

    def build_config(payload: dict) -> Config:
        m = payload.get("model", {})
        g = payload.get("generation", {})
        r = payload.get("runtime", {})

        model_cfg = ModelConfig(**{k: v for k, v in m.items() if k in m_fields})
        gen_cfg = GenerationConfig(**{k: v for k, v in g.items() if k in g_fields})
        run_cfg = RuntimeConfig(**{k: v for k, v in r.items() if k in r_fields})
        return Config(model=model_cfg, generation=gen_cfg, runtime=run_cfg)

    @app.post("/api/config/validate")
    def validate_config(payload: dict):
        try:
            cfg = build_config(payload)
            cfg.validate(check_images=payload.get("check_images", False))
            return {"valid": True, "errors": []}
        except Exception as e:
            return {"valid": False, "errors": [str(e)]}

    @app.post("/api/run")
    def start_run(payload: dict):
        try:
            cfg = build_config(payload)
            cfg.validate(check_images=True)
        except Exception as e:
            return JSONResponse(status_code=400, content={"valid": False, "errors": [str(e)]})

        run_id = f"run_{datetime_id()}_{uuid.uuid4().hex[:6]}"
        is_demo = payload.get("demo_mode", True)

        # Execute demo run
        cfg.runtime.output_dir = str(effective_outputs)
        cfg.runtime.device = "cpu"
        cfg.runtime.dtype = "float32"
        cfg.runtime.offload = "none"

        try:
            records = core_run(cfg, backend_factory=DemoBackend)
            record = records[0] if records else {}
            actual_run_id = record.get("run_id", run_id)
            active_runs.append({
                "run_id": actual_run_id,
                "status": record.get("status", "success"),
                "timestamp": record.get("timestamp"),
                "outputs": record.get("outputs", []),
                "record": record,
            })
            return {"run_id": actual_run_id, "stream_url": f"/api/run/{actual_run_id}/stream"}
        except Exception as e:
            return JSONResponse(status_code=400, content={"valid": False, "errors": [str(e)]})

    @app.get("/api/run/{run_id}/stream")
    def run_stream(run_id: str):
        matching = next((r for r in active_runs if r["run_id"] == run_id), None)
        if not matching:
            # Check disk for json
            disk_json = effective_outputs / f"{run_id}.json"
            if not disk_json.exists():
                raise HTTPException(status_code=404, detail="Run not found")

        def event_generator():
            yield f"event: log\ndata: {json.dumps({'text': f'Starting run {run_id}'})}\n\n"
            yield f"event: progress\ndata: {json.dumps({'step': 1, 'total': 1})}\n\n"
            rec = matching["record"] if matching else {}
            yield f"event: complete\ndata: {json.dumps(rec)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/api/runs")
    def list_runs():
        runs = []
        for r in active_runs:
            runs.append({
                "run_id": r["run_id"],
                "status": r["status"],
                "timestamp": r.get("timestamp"),
                "outputs": r.get("outputs", []),
            })
        return {"runs": runs}

    @app.get("/api/runs/{run_id}")
    def get_run_record(run_id: str):
        matching = next((r for r in active_runs if r["run_id"] == run_id), None)
        if matching and "record" in matching:
            return matching["record"]
        disk_path = effective_outputs / f"{run_id}.json"
        if disk_path.exists():
            return json.loads(disk_path.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="Run record not found")

    @app.get("/api/outputs/{filename}")
    def get_output_file(filename: str):
        clean_name = Path(filename).name
        target = effective_outputs / clean_name
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail=f"Output file '{filename}' not found")
        content_type = "image/png" if target.suffix.lower() == ".png" else "application/octet-stream"
        return Response(content=target.read_bytes(), media_type=content_type)

    return app


def datetime_id():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def get_test_client(inputs_dir: Path | None = None, models_dir: Path | None = None, outputs_dir: Path | None = None) -> TestClient:
    """Get TestClient for ui.server if available, otherwise contract reference app."""
    try:
        from ui.server import app as server_app

        if inputs_dir is not None:
            resolved_in = Path(inputs_dir).resolve()
            server_app.state.inputs_dir = resolved_in
            os.environ["INPUTS_DIR"] = str(resolved_in)

        if models_dir is not None:
            resolved_mod = Path(models_dir).resolve()
            resolved_mod.mkdir(parents=True, exist_ok=True)
            server_app.state.models_dir = resolved_mod
            os.environ["MODELS_DIR"] = str(resolved_mod)

        if outputs_dir is not None:
            resolved_out = Path(outputs_dir).resolve()
            resolved_out.mkdir(parents=True, exist_ok=True)
            server_app.state.outputs_dir = resolved_out
            os.environ["OUTPUTS_DIR"] = str(resolved_out)

        return TestClient(server_app)
    except (ImportError, AttributeError):
        app = create_contract_app(inputs_dir=inputs_dir, models_dir=models_dir, outputs_dir=outputs_dir)
        return TestClient(app)



def create_test_image(path: Path, width: int = 64, height: int = 64, color: tuple = (200, 100, 50)) -> Path:
    """Create a valid PNG image file on disk for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, format="PNG")
    return path


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
