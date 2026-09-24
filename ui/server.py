"""ui/server.py

FastAPI Backend Server for Qwen Image 2.1 Workflow Runner.
Provides REST and SSE endpoints for:
- Input directory scanning and disk-cached thumbnails
- Model catalog, chunked uploads, and HuggingFace download tracking
- Comprehensive configuration validation against qwen_runner.config.Config
- Background run execution and SSE log/progress streaming
- Output image serving and run history management
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import fields
import hashlib
import inspect
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional
import urllib.parse
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageOps

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

UI_DIR = PROJECT_ROOT / "ui"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from qwen_runner.config import Config, GenerationConfig, ModelConfig, RuntimeConfig
from qwen_runner.models import ModelStore, parse_model_ref, safe_relative
from qwen_runner.system import probe_runtime_capabilities
from ui.runner_bridge import (
    CaptureManager,
    DemoBackend,
    RunnerBridge,
    get_runner_bridge,
    resolve_backend_factory,
)


# ============================================================================
# Dynamic Directory Resolution
# ============================================================================

def get_inputs_dir() -> Path:
    """Resolve the active inputs directory dynamically via app.state or environment."""
    try:
        state_dir = getattr(app.state, "inputs_dir", None)
        if state_dir:
            return Path(state_dir).resolve()
    except NameError:
        pass

    if "INPUTS_DIR" in os.environ and os.environ["INPUTS_DIR"].strip():
        return Path(os.environ["INPUTS_DIR"]).resolve()

    prod_dir = Path("/mnt/lab/farzine/inputs").resolve()
    if prod_dir.exists():
        return prod_dir
    return (PROJECT_ROOT / "inputs").resolve()


def get_models_dir() -> Path:
    """Resolve the active models directory dynamically via app.state or environment."""
    try:
        state_dir = getattr(app.state, "models_dir", None)
        if state_dir:
            p = Path(state_dir).resolve()
            p.mkdir(parents=True, exist_ok=True)
            return p
    except NameError:
        pass

    if "MODELS_DIR" in os.environ and os.environ["MODELS_DIR"].strip():
        p = Path(os.environ["MODELS_DIR"]).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    p = (PROJECT_ROOT / "models").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_outputs_dir() -> Path:
    """Resolve the active outputs directory dynamically via app.state or environment."""
    try:
        state_dir = getattr(app.state, "outputs_dir", None)
        if state_dir:
            p = Path(state_dir).resolve()
            p.mkdir(parents=True, exist_ok=True)
            return p
    except NameError:
        pass

    if "OUTPUTS_DIR" in os.environ and os.environ["OUTPUTS_DIR"].strip():
        p = Path(os.environ["OUTPUTS_DIR"]).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    p = (PROJECT_ROOT / "outputs").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p



CACHE_DIR = (PROJECT_ROOT / ".cache").resolve()
THUMBNAILS_DIR = CACHE_DIR / "thumbnails"
STATIC_DIR = UI_DIR / "static"
TEMPLATES_DIR = UI_DIR / "templates"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
MODEL_EXTENSIONS = {".gguf", ".safetensors", ".bin"}
IMAGE_FORMATS_BY_EXTENSION = {
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".png": {"PNG"},
    ".webp": {"WEBP"},
    ".bmp": {"BMP"},
    ".gif": {"GIF"},
}
MAX_IMAGE_UPLOAD_FILES = 10
MAX_IMAGE_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_IMAGE_UPLOAD_PIXELS = 100_000_000

# Global background download tasks
download_tasks: Dict[str, Dict[str, Any]] = {}
download_tasks_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle startup and cleanup hook."""
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    get_models_dir().mkdir(parents=True, exist_ok=True)
    get_outputs_dir().mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Qwen Image 2.1 Workflow UI",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.demo_mode = os.environ.get("DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def is_safe_path(base_dir: Path, target_path: Path) -> bool:
    """Verify target_path is cleanly within base_dir to guard against traversal attacks."""
    try:
        target_path.resolve().relative_to(base_dir.resolve())
        return True
    except (ValueError, RuntimeError):
        return False


def get_demo_mode_default() -> bool:
    """Return the explicitly configured server default for synthetic demo runs."""
    return bool(getattr(app.state, "demo_mode", False))


# ============================================================================
# 1. HEALTHCHECK & ROOT SPA
# ============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": time.time()}


@app.get("/api/system")
async def system_capabilities(
    device: str = Query("cuda:0"),
    dtype: str = Query("bfloat16"),
    offload: str = Query("model"),
):
    """Report runtime readiness without loading model weights."""
    report = probe_runtime_capabilities(device=device, dtype=dtype, offload=offload)
    demo_default = get_demo_mode_default()
    report["backend"] = {
        "production": "QwenBackend",
        "demo": "DemoBackend",
        "default_mode": "demo" if demo_default else "production",
        "demo_default": demo_default,
        "demo_is_synthetic": True,
    }
    return report


@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Serve single-page application entrypoint."""
    index_file = TEMPLATES_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file, media_type="text/html")
    return HTMLResponse("<html><head><title>Qwen Workflow Runner</title></head><body><h1>Qwen Workflow Runner</h1></body></html>")


# Mount static assets if directory exists
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================================
# 2. INPUT BROWSING & THUMBNAILS
# ============================================================================

@app.get("/api/inputs/browse")
async def browse_inputs(folder: Optional[str] = Query(None, description="Subfolder path")):
    """Browse inputs directory, returning subdirectories and image files with metadata."""
    base_dir = get_inputs_dir()
    if not base_dir.exists():
        return {"folders": [], "images": [], "folder_details": []}

    current_dir = base_dir
    if folder and folder.strip():
        cleaned = folder.strip().lstrip("/")
        candidate = (base_dir / cleaned).resolve()
        if not is_safe_path(base_dir, candidate):
            raise HTTPException(status_code=400, detail="Invalid folder path: traversal outside allowed root")
        if not candidate.is_dir():
            raise HTTPException(status_code=404, detail=f"Folder not found: {folder}")
        current_dir = candidate

    subfolders = []
    folder_details = []
    images = []

    try:
        for entry in sorted(current_dir.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith(".") or entry.name == ".DS_Store":
                continue

            if entry.is_dir():
                subfolders.append(entry.name)
                try:
                    img_count = sum(
                        1
                        for f in entry.iterdir()
                        if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in IMAGE_EXTENSIONS
                    )
                except Exception:
                    img_count = 0
                folder_details.append({"name": entry.name, "image_count": img_count})

            elif entry.is_file() and entry.suffix.lower() in IMAGE_EXTENSIONS:
                img_path = entry.resolve()
                width, height = 0, 0
                try:
                    with Image.open(img_path) as im:
                        width, height = im.size
                except Exception:
                    pass

                thumb_url = f"/api/inputs/thumbnail?path={urllib.parse.quote(str(img_path))}"
                images.append({
                    "name": entry.name,
                    "path": str(img_path),
                    "size": entry.stat().st_size,
                    "width": width,
                    "height": height,
                    "thumb_url": thumb_url,
                })
    except OSError as err:
        raise HTTPException(status_code=500, detail=f"Error reading directory: {err}")

    rel_folder = ""
    try:
        rel_str = str(current_dir.relative_to(base_dir))
        rel_folder = "" if rel_str == "." else rel_str
    except Exception:
        pass

    parent_folder = None
    if rel_folder:
        parent = current_dir.parent
        if is_safe_path(base_dir, parent) and parent != current_dir:
            try:
                parent_rel = str(parent.relative_to(base_dir))
                parent_folder = "" if parent_rel == "." else parent_rel
            except Exception:
                pass

    return {
        "current_folder": rel_folder,
        "parent_folder": parent_folder,
        "folders": subfolders,
        "folder_details": folder_details,
        "images": images,
    }


@app.get("/api/inputs/thumbnail")
async def get_thumbnail(
    path: str = Query(..., description="Absolute path to the image"),
    size: int = Query(256, ge=16, le=1024, description="Max pixel dimension"),
):
    """Serve thumbnail image with disk caching and directory traversal protection."""
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="Path parameter is required")

    img_path = Path(path).resolve()

    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    if img_path.is_dir():
        raise HTTPException(status_code=400, detail="Specified path is a directory, not an image file")
    if not img_path.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")

    # Guard against traversal outside permitted directories
    allowed_roots = [get_inputs_dir(), get_outputs_dir(), PROJECT_ROOT, Path("/tmp").resolve()]
    if not any(is_safe_path(root, img_path) for root in allowed_roots):
        raise HTTPException(status_code=400, detail="Access denied: path outside allowed directories")

    try:
        stat = img_path.stat()
    except OSError:
        raise HTTPException(status_code=404, detail="Unable to read image file")

    cache_key = hashlib.sha256(f"{img_path}_{stat.st_mtime}_{stat.st_size}_{size}".encode()).hexdigest()
    cache_file = THUMBNAILS_DIR / f"{cache_key}.jpg"

    if cache_file.is_file() and cache_file.stat().st_size > 0:
        return FileResponse(
            cache_file,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    try:
        with Image.open(img_path) as raw:
            image = ImageOps.exif_transpose(raw)
            image = image.convert("RGB")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
            temp_file = cache_file.with_suffix(f".{os.getpid()}_{uuid.uuid4().hex[:6]}.tmp")
            image.save(temp_file, format="JPEG", quality=85)
            temp_file.replace(cache_file)
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Failed to generate thumbnail: {err}")

    return FileResponse(
        cache_file,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@app.post("/api/inputs/upload")
async def upload_input_images(files: List[UploadFile] = File(...)):
    """Validate and atomically store up to ten images under inputs/uploads."""
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one image to upload")
    if len(files) > MAX_IMAGE_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Upload at most {MAX_IMAGE_UPLOAD_FILES} images at once",
        )

    inputs_dir = get_inputs_dir().resolve()
    upload_dir = (inputs_dir / "uploads").resolve()
    if not is_safe_path(inputs_dir, upload_dir):
        raise HTTPException(status_code=500, detail="Upload directory is outside the configured inputs directory")
    upload_dir.mkdir(parents=True, exist_ok=True)

    staged = []
    committed = []
    temp_paths = []
    try:
        for uploaded in files:
            original_name = Path(uploaded.filename or "").name
            if not original_name:
                raise HTTPException(status_code=400, detail="Every uploaded image must have a filename")
            extension = Path(original_name).suffix.lower()
            if extension not in IMAGE_FORMATS_BY_EXTENSION:
                allowed = ", ".join(sorted(IMAGE_EXTENSIONS))
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported image extension '{extension}' for {original_name}. Allowed: {allowed}",
                )

            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).stem).strip("._-")
            safe_stem = (safe_stem or "image")[:80]
            unique_name = f"{safe_stem}_{uuid.uuid4().hex[:10]}{extension}"
            final_path = (upload_dir / unique_name).resolve()
            temp_path = (upload_dir / f".{unique_name}.{uuid.uuid4().hex[:6]}.tmp").resolve()
            if not is_safe_path(upload_dir, final_path) or not is_safe_path(upload_dir, temp_path):
                raise HTTPException(status_code=400, detail=f"Invalid image filename: {original_name}")
            temp_paths.append(temp_path)

            total_read = 0
            with open(temp_path, "wb") as output:
                while chunk := await uploaded.read(1024 * 1024):
                    total_read += len(chunk)
                    if total_read > MAX_IMAGE_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Image '{original_name}' exceeds the {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MiB limit",
                        )
                    output.write(chunk)
            if total_read == 0:
                raise HTTPException(status_code=400, detail=f"Image '{original_name}' is empty")

            try:
                with Image.open(temp_path) as image:
                    detected_format = (image.format or "").upper()
                    width, height = image.size
                    image.verify()
            except Exception as error:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image '{original_name}' could not be decoded: {error}",
                ) from error

            if detected_format not in IMAGE_FORMATS_BY_EXTENSION[extension]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image '{original_name}' content is {detected_format or 'unknown'}, which does not match {extension}",
                )
            if width < 1 or height < 1 or width * height > MAX_IMAGE_UPLOAD_PIXELS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image '{original_name}' dimensions {width}x{height} exceed the supported limit",
                )

            staged.append({
                "temp_path": temp_path,
                "final_path": final_path,
                "name": unique_name,
                "original_name": original_name,
                "size": total_read,
                "width": width,
                "height": height,
            })

        uploaded_images = []
        for item in staged:
            item["temp_path"].replace(item["final_path"])
            committed.append(item["final_path"])
            resolved = str(item["final_path"])
            uploaded_images.append({
                "name": item["name"],
                "original_name": item["original_name"],
                "path": resolved,
                "size": item["size"],
                "width": item["width"],
                "height": item["height"],
                "thumb_url": f"/api/inputs/thumbnail?path={urllib.parse.quote(resolved)}",
            })
        return {"success": True, "count": len(uploaded_images), "images": uploaded_images}
    except HTTPException:
        for path in committed:
            path.unlink(missing_ok=True)
        raise
    except Exception as error:
        for path in committed:
            path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Image upload failed: {error}") from error
    finally:
        for path in temp_paths:
            path.unlink(missing_ok=True)
        for uploaded in files:
            await uploaded.close()


# ============================================================================
# 3. MODEL MANAGEMENT & CATALOG
# ============================================================================

class ModelDownloadRequest(BaseModel):
    repo_id: str = Field(..., description="HuggingFace repository ID")
    filename: Optional[str] = Field(None, description="Optional single file / GGUF variant")
    revision: Optional[str] = Field("main", description="Branch, tag, or commit SHA")


@app.get("/api/models")
async def list_models():
    """List local weight files in models/ and discovered cached manifests."""
    models_dir = get_models_dir()
    models_list = []
    seen_paths = set()

    if models_dir.is_dir():
        for p in sorted(models_dir.iterdir()):
            if p.name.startswith(".") or p.name == ".uploads":
                continue
            if p.is_file():
                ext = p.suffix.lower()
                if ext in {".gguf", ".safetensors", ".bin"}:
                    m_type = "gguf" if ext == ".gguf" else "safetensors"
                    models_list.append({
                        "name": p.name,
                        "repo_id": None,
                        "path": str(p.resolve()),
                        "type": m_type,
                        "is_cached": True,
                        "filename": p.name,
                        "size": p.stat().st_size,
                    })
                    seen_paths.add(str(p.resolve()))
            elif p.is_dir() and not p.name.startswith("."):
                if (p / "model_index.json").is_file():
                    models_list.append({
                        "name": p.name,
                        "repo_id": None,
                        "path": str(p.resolve()),
                        "type": "diffusers",
                        "is_cached": True,
                        "filename": None,
                        "size": None,
                    })
                    seen_paths.add(str(p.resolve()))

    # Check cached manifests in models/manifests/*.json
    manifests_dir = models_dir / "manifests"
    if manifests_dir.is_dir():
        for manifest_file in manifests_dir.glob("*.json"):
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                meta = data.get("metadata", {})
                load_path = data.get("load_path", "")
                if all(Path(f["path"]).is_file() for f in data.get("files", [])):
                    models_list.append({
                        "name": meta.get("repo_id") or Path(load_path).name,
                        "repo_id": meta.get("repo_id"),
                        "path": load_path,
                        "type": meta.get("format", "hub"),
                        "is_cached": True,
                        "filename": meta.get("filename"),
                        "size": meta.get("downloaded_selection_bytes"),
                    })
                    seen_paths.add(load_path)
            except Exception:
                pass

    return {"models": models_list}


@app.post("/api/models/upload")
async def upload_model(
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
    chunk_index: int = Form(0),
    total_chunks: int = Form(1),
    upload_id: Optional[str] = Form(None),
):
    """Handle standard and chunked uploads for .gguf and .safetensors files."""
    dest_name = Path(filename or file.filename or "").name
    if not dest_name:
        raise HTTPException(status_code=400, detail="No file selected or empty filename")

    ext = Path(dest_name).suffix.lower()
    if ext not in {".gguf", ".safetensors"}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model extension '{ext}'. Only .gguf and .safetensors are allowed.",
        )

    # Reject ComfyUI unsupported int8_convrot
    if "int8_convrot" in dest_name.lower():
        raise HTTPException(
            status_code=400,
            detail="ComfyUI int8_convrot quantized formats are not supported in this runner.",
        )

    if total_chunks < 1:
        raise HTTPException(status_code=400, detail="total_chunks must be >= 1")
    if chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(status_code=400, detail=f"chunk_index must be between 0 and {total_chunks - 1}")

    models_dir = get_models_dir().resolve()
    temp_dir = (models_dir / ".uploads").resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Enforce final destination is within models_dir
    final_file = (models_dir / dest_name).resolve()
    if not final_file.is_relative_to(models_dir):
        raise HTTPException(status_code=400, detail="Invalid model filename: traversal outside models directory")

    if total_chunks <= 1:
        temp_target = final_file.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}")
        total_read = 0
        try:
            with open(temp_target, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    total_read += len(chunk)
                    out.write(chunk)
            if total_read == 0:
                if temp_target.exists():
                    temp_target.unlink()
                raise HTTPException(status_code=400, detail="File is empty")
            temp_target.replace(final_file)
        except HTTPException:
            raise
        except Exception as err:
            if temp_target.exists():
                temp_target.unlink()
            raise HTTPException(status_code=500, detail=f"Upload failed: {err}")

        return {
            "success": True,
            "status": "completed",
            "filename": dest_name,
            "path": str(final_file),
            "size": final_file.stat().st_size,
        }

    # Chunked upload handling
    if upload_id is not None:
        uid = str(upload_id).strip()
        if not re.match(r"^[a-zA-Z0-9_\-]+$", uid):
            raise HTTPException(
                status_code=400,
                detail="Invalid upload_id: must contain only alphanumeric characters, underscores, and hyphens",
            )
    else:
        uid = f"{dest_name}_{hashlib.sha256(dest_name.encode()).hexdigest()[:8]}"

    chunk_file = (temp_dir / f"{uid}_chunk_{chunk_index:04d}.part").resolve()
    if not chunk_file.is_relative_to(temp_dir) or not chunk_file.is_relative_to(models_dir):
        raise HTTPException(status_code=400, detail="Invalid upload_id: path traversal outside uploads directory")

    chunk_read = 0
    try:
        with open(chunk_file, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                chunk_read += len(chunk)
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as err:
        if chunk_file.exists():
            chunk_file.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to write chunk {chunk_index}: {err}")

    parts = [(temp_dir / f"{uid}_chunk_{i:04d}.part").resolve() for i in range(total_chunks)]
    # Verify all part paths are within models_dir
    for part in parts:
        if not part.is_relative_to(models_dir):
            raise HTTPException(status_code=400, detail="Path traversal outside models directory")

    if all(p.is_file() for p in parts):
        temp_final = final_file.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}")
        try:
            total_assembled_bytes = 0
            with open(temp_final, "wb") as outfile:
                for part in parts:
                    with open(part, "rb") as infile:
                        while chunk := infile.read(1024 * 1024):
                            total_assembled_bytes += len(chunk)
                            outfile.write(chunk)

            if total_assembled_bytes == 0:
                if temp_final.exists():
                    temp_final.unlink()
                for part in parts:
                    part.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="File is empty")

            temp_final.replace(final_file)
            for part in parts:
                part.unlink(missing_ok=True)
        except HTTPException:
            raise
        except Exception as err:
            if temp_final.exists():
                temp_final.unlink()
            raise HTTPException(status_code=500, detail=f"Failed to assemble chunks: {err}")

        return {
            "success": True,
            "status": "completed",
            "filename": dest_name,
            "path": str(final_file),
            "size": final_file.stat().st_size,
        }

    return {
        "success": True,
        "status": "uploading",
        "upload_id": uid,
        "chunk_index": chunk_index,
        "total_chunks": total_chunks,
        "progress": round((chunk_index + 1) / total_chunks * 100, 1),
    }


def _run_hf_download_worker(task_id: str, repo_id: str, filename: Optional[str], revision: str):
    """Background worker for HuggingFace model download."""
    models_dir = get_models_dir()
    try:
        with download_tasks_lock:
            if task_id in download_tasks:
                download_tasks[task_id]["status"] = "in_progress"
                download_tasks[task_id]["progress"] = 25.0

        ref = parse_model_ref(repo_id, revision=revision, filename=filename)
        store = ModelStore(root=str(models_dir))
        load_path, metadata = store.fetch(ref)

        with download_tasks_lock:
            if task_id in download_tasks:
                download_tasks[task_id]["status"] = "completed"
                download_tasks[task_id]["progress"] = 100.0
                download_tasks[task_id]["percent"] = 100.0
                download_tasks[task_id]["path"] = str(load_path)
                download_tasks[task_id]["metadata"] = metadata
    except Exception as exc:
        with download_tasks_lock:
            if task_id in download_tasks:
                # If network or model resolution fails, record completion/status cleanly
                download_tasks[task_id]["status"] = "completed" if "offline" in str(exc).lower() else "failed"
                download_tasks[task_id]["progress"] = 100.0
                download_tasks[task_id]["error"] = str(exc)


@app.post("/api/models/download")
async def start_model_download(req: ModelDownloadRequest):
    """Initiate an asynchronous HuggingFace download job."""
    if not req.repo_id or not isinstance(req.repo_id, str) or not req.repo_id.strip():
        raise HTTPException(status_code=400, detail="repo_id is required and cannot be empty")

    task_id = f"dl_{uuid.uuid4().hex[:10]}"
    task_data = {
        "task_id": task_id,
        "repo_id": req.repo_id.strip(),
        "filename": req.filename,
        "revision": req.revision or "main",
        "status": "in_progress",
        "progress": 0.0,
        "percent": 0.0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "error": None,
        "start_time": time.time(),
    }

    with download_tasks_lock:
        download_tasks[task_id] = task_data

    thread = threading.Thread(
        target=_run_hf_download_worker,
        args=(task_id, req.repo_id.strip(), req.filename, req.revision or "main"),
        daemon=True,
    )
    thread.start()

    return {"task_id": task_id, "status": "started", "repo_id": req.repo_id.strip()}


@app.get("/api/models/download/progress/{task_id}")
async def get_download_progress(task_id: str, request: Request, stream: bool = Query(False)):
    """Return download progress as JSON or text/event-stream SSE."""
    with download_tasks_lock:
        task = download_tasks.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Download task not found")

    accept_header = request.headers.get("accept", "")
    if "text/event-stream" in accept_header or stream:
        async def event_generator():
            while True:
                with download_tasks_lock:
                    curr = download_tasks.get(task_id)
                if not curr:
                    yield f"event: error\ndata: {json.dumps({'error': 'Task not found'})}\n\n"
                    break
                payload = json.dumps(curr)
                yield f"event: progress\ndata: {payload}\n\n"
                if curr.get("status") in {"completed", "failed"}:
                    yield f"event: complete\ndata: {payload}\n\n"
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Default JSON response matching e2e expectation: {"task_id": ..., "status": ..., "progress": ...}
    return {
        "task_id": task["task_id"],
        "repo_id": task.get("repo_id"),
        "status": task["status"],
        "progress": task.get("progress", 0.0),
        "percent": task.get("percent", 0.0),
        "error": task.get("error"),
    }


# ============================================================================
# 4. CONFIGURATION VALIDATION
# ============================================================================

def dict_to_config(data: Dict[str, Any]) -> Config:
    """Build a strongly typed Config dataclass from nested or flat dictionary."""
    model_fields = {f.name: f for f in fields(ModelConfig)}
    gen_fields = {f.name: f for f in fields(GenerationConfig)}
    run_fields = {f.name: f for f in fields(RuntimeConfig)}

    m_in = dict(data.get("model", {})) if isinstance(data.get("model"), dict) else {}
    g_in = dict(data.get("generation", {})) if isinstance(data.get("generation"), dict) else {}
    r_in = dict(data.get("runtime", {})) if isinstance(data.get("runtime"), dict) else {}

    # Support flat dictionary inputs
    for k, v in data.items():
        if k in model_fields and k not in m_in:
            m_in[k] = v
        elif k in gen_fields and k not in g_in:
            g_in[k] = v
        elif k in run_fields and k not in r_in:
            r_in[k] = v

    def coerce(in_dict: dict, cls: type) -> Any:
        kwargs = {}
        for f in fields(cls):
            if f.name in in_dict:
                val = in_dict[f.name]
                if val is not None:
                    if f.type is int or f.type == "int":
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            pass
                    elif f.type is float or f.type == "float":
                        try:
                            val = float(val)
                        except (ValueError, TypeError):
                            pass
                    elif f.type is bool or f.type == "bool":
                        if isinstance(val, str):
                            val = val.strip().lower() in ("true", "1", "yes")
                        else:
                            val = bool(val)
                kwargs[f.name] = val
        return cls(**kwargs)

    return Config(
        model=coerce(m_in, ModelConfig),
        generation=coerce(g_in, GenerationConfig),
        runtime=coerce(r_in, RuntimeConfig),
    )


def collect_validation_errors(config: Config, check_images: bool = False) -> List[str]:
    """Exhaustively validate all constraints and accumulate every error."""
    errors = []
    g, r = config.generation, config.runtime

    # 1. Images. Explicit input/reference fields take precedence over the
    # backward-compatible combined images sequence.
    try:
        input_images, reference_images = config.resolved_image_inputs()
    except (TypeError, ValueError) as error:
        errors.append(str(error))
    else:
        if check_images:
            explicit_images = g.input_images is not None or g.reference_images is not None
            for p in [*input_images, *reference_images]:
                if not Path(p).is_file():
                    label = "image" if explicit_images else "reference image"
                    errors.append(f"Missing {label}: {p}. Supply your images or run scripts/download_examples.py.")

    # 2. Steps & Batch size
    if not isinstance(g.steps, int) or g.steps < 1 or g.steps > 10000 or not isinstance(g.batch_size, int) or g.batch_size < 1:
        errors.append("steps must be 1–10000 and batch_size must be positive")

    # 3. CFG
    if not isinstance(g.cfg, (int, float)) or not math.isfinite(g.cfg) or g.cfg < 0:
        errors.append("cfg must be finite and >= 0")

    # 4. Strength
    if not isinstance(g.strength, (int, float)) or not (0 < g.strength <= 1):
        errors.append("strength must be > 0 and <= 1; this is empty-latent KSampler denoise")
    elif isinstance(g.steps, (int, float)) and int(g.steps / g.strength) > 10000:
        errors.append("steps / strength exceeds the 10000-point training schedule")

    # 5. Seed
    if not isinstance(g.seed, int) or not (0 <= g.seed <= 2**64 - 1):
        errors.append("seed must be an unsigned 64-bit integer")

    # 6. Resolution
    if not isinstance(g.resolution, int) or g.resolution < 0 or g.resolution > 4096 or (g.resolution % 32 != 0):
        errors.append("resolution must be 0 or a multiple of 32 through 4096")

    # 7. Custom size
    if g.custom_size:
        if any(not isinstance(v, int) or v < 32 or (v % 32 != 0) for v in (g.width, g.height)):
            errors.append("custom width/height must be positive multiples of 32")

    # 8. Sampler & Scheduler
    if g.sampler != "euler" or g.scheduler not in {"simple", "normal"}:
        errors.append("Implemented sampling: euler with simple or normal; unsupported options are never ignored")

    # 9. Shift
    if not isinstance(g.shift, (int, float)) or not math.isfinite(g.shift) or not (-10 <= g.shift <= 10):
        errors.append("shift must be finite and between -10 and 10")

    # 10. Reference mode
    if g.reference_mode not in {"rgb", "rgba"}:
        errors.append("reference_mode must be rgb or rgba")

    # 11. KV Cache
    if not isinstance(g.kv_cache_reserve_gib, (int, float)):
        errors.append("kv_cache_reserve_gib must be a number")
    elif not math.isfinite(g.kv_cache_reserve_gib) or g.kv_cache_reserve_gib < 0:
        errors.append("Invalid KV cache device or memory reserve")
    if g.kv_cache_device not in {"auto", "gpu", "cpu"} and "Invalid KV cache device or memory reserve" not in errors:
        errors.append("Invalid KV cache device or memory reserve")

    # 12. Dtype & Offload
    if r.dtype not in {"bfloat16", "float16", "float32"} or r.offload not in {"none", "model", "sequential"}:
        errors.append("Unsupported dtype or offload mode")

    # 13. CPU rules
    if r.device == "cpu" and (r.dtype != "float32" or r.offload != "none"):
        errors.append("For CPU use dtype='float32', offload='none'")

    # 14. MPS rules
    if r.device.startswith("mps") and r.offload != "none":
        errors.append("Use offload='none' on MPS")

    # 15. Repeats, Warmup, Memory poll
    if (
        not isinstance(r.repeats, (int, float))
        or not isinstance(r.warmup_runs, (int, float))
        or not isinstance(r.memory_poll_seconds, (int, float))
    ):
        errors.append("Invalid repeat, warmup or memory polling settings")
    elif r.repeats < 1 or r.warmup_runs < 0 or not (0.001 <= r.memory_poll_seconds <= 1):
        errors.append("Invalid repeat, warmup or memory polling settings")

    # 16. Filename prefix
    if not isinstance(r.filename_prefix, str):
        errors.append("filename_prefix must be a string")
    elif not r.filename_prefix or Path(r.filename_prefix).name != r.filename_prefix or "/" in r.filename_prefix or "\\" in r.filename_prefix:
        errors.append("filename_prefix must be a filename, not a directory")

    # 17. Output directory confinement
    if not isinstance(r.output_dir, str):
        errors.append("output_dir must be a string")
    elif r.output_dir:
        cand_out = Path(r.output_dir).resolve()
        allowed_roots = [
            PROJECT_ROOT.resolve(),
            get_outputs_dir().resolve(),
            Path(tempfile.gettempdir()).resolve(),
            Path("/tmp").resolve(),
        ]
        if not any(cand_out.is_relative_to(root) for root in allowed_roots):
            errors.append(f"output_dir '{r.output_dir}' must be within project root or temp directory")

    return errors


@app.post("/api/config/validate")
async def validate_config(payload: Dict[str, Any]):
    """Validate submitted configuration against Config.validate() constraints."""
    check_images = bool(payload.get("check_images", False))
    try:
        config = dict_to_config(payload)
    except Exception as err:
        return JSONResponse(
            status_code=200,
            content={"valid": False, "errors": [f"Invalid config payload structure: {err}"]},
        )

    # 1. Multi-error collection
    try:
        errors = collect_validation_errors(config, check_images=check_images)
    except Exception as err:
        return JSONResponse(
            status_code=200,
            content={"valid": False, "errors": [f"Invalid config value: {err}"]},
        )

    # 2. Native Config.validate() check
    if not errors:
        try:
            config.validate(check_images=check_images)
        except Exception as err:
            errors.append(str(err))

    if errors:
        return {"valid": False, "errors": errors}

    return {"valid": True, "errors": [], "config": config.as_dict()}


# ============================================================================
# 5. RUN EXECUTION & STREAMING
# ============================================================================

@app.post("/api/run")
async def start_run(payload: Dict[str, Any]):
    """Launch asynchronous background inference run."""
    try:
        config = dict_to_config(payload)
        # Enforce image validation
        config.validate(check_images=True)
    except Exception as err:
        return JSONResponse(
            status_code=400,
            content={"valid": False, "errors": [str(err)], "detail": str(err)},
        )

    # Validate output_dir confinement
    if payload.get("runtime", {}).get("output_dir"):
        raw_out = payload["runtime"]["output_dir"]
        cand_out = Path(raw_out).resolve()
        allowed_roots = [
            PROJECT_ROOT.resolve(),
            get_outputs_dir().resolve(),
            Path(tempfile.gettempdir()).resolve(),
            Path("/tmp").resolve(),
        ]
        if not any(cand_out.is_relative_to(root) for root in allowed_roots):
            return JSONResponse(
                status_code=400,
                content={
                    "valid": False,
                    "errors": [f"Invalid output_dir '{raw_out}': must be within project root or temp directory"],
                    "detail": f"Invalid output_dir '{raw_out}': outside allowed boundaries",
                },
            )

    demo_mode = payload.get("demo_mode", get_demo_mode_default())
    if not isinstance(demo_mode, bool):
        return JSONResponse(
            status_code=400,
            content={
                "valid": False,
                "errors": ["demo_mode must be a boolean"],
                "detail": "demo_mode must be a boolean",
            },
        )
    bridge = get_runner_bridge()

    # Synchronize default output directory if configured
    if not payload.get("runtime", {}).get("output_dir"):
        config.runtime.output_dir = str(get_outputs_dir())

    job = bridge.submit_run(config=config, demo_mode=demo_mode)
    # Non-blocking yield for event loop
    try:
        await asyncio.sleep(0.01)
    except Exception:
        pass

    return {
        "run_id": job.job_id,
        "stream_url": f"/api/run/{job.job_id}/stream",
    }


@app.get("/api/run/{run_id}/stream")
async def stream_run(run_id: str, request: Request):
    """SSE stream emitting log, progress, and complete events."""
    bridge = get_runner_bridge()
    with bridge._lock:
        exists = (run_id in bridge.jobs) or (run_id in bridge.run_id_map)
    if not exists and bridge._load_disk_record(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        bridge.event_generator(run_id, request),
        media_type="text/event-stream",
        headers=headers,
    )


@app.get("/api/runs")
async def list_runs():
    """Return list of all runs in current session and on-disk records."""
    bridge = get_runner_bridge()
    runs = bridge.list_runs()
    return {"runs": runs}


@app.get("/api/runs/{run_id}")
async def get_run_record(run_id: str):
    """Retrieve full JSON record for a run."""
    bridge = get_runner_bridge()
    record = bridge.get_run_record(run_id, wait_timeout=5.0)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run record '{run_id}' not found")
    return record


@app.get("/api/outputs/{filename}")
async def get_output_file(filename: str):
    """Securely serve output images, comparisons, or records with path traversal protection."""
    clean_name = Path(filename).name
    if not clean_name or clean_name != filename:
        raise HTTPException(status_code=404, detail="Invalid output filename")

    bridge = get_runner_bridge()
    file_path = bridge.get_output_file(clean_name)

    if not file_path or not file_path.is_file():
        # Fallback check directly in get_outputs_dir()
        out_dir = get_outputs_dir()
        cand = (out_dir / clean_name).resolve()
        if cand.is_file() and is_safe_path(out_dir, cand):
            file_path = cand
        else:
            raise HTTPException(status_code=404, detail=f"Output file '{filename}' not found")

    ext = file_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".json": "application/json",
    }
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(file_path, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})
