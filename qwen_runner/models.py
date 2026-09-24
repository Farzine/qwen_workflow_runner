"""Deterministic file selection and disk-first, complete-manifest model reuse."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse
import fnmatch
import hashlib
import json
import os


class DownloadCancelled(Exception):
    """A cooperative cancellation requested between Hub file operations."""


class _DiscardProgressOutput:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def _observed_tqdm(filename, callback):
    """Adapt Hub HTTP/Xet per-file bars to byte events without terminal output."""
    from tqdm.auto import tqdm

    class ObservedTqdm(tqdm):
        def __init__(self, *args, **kwargs):
            self._transfer_bar = "downloading bytes" in str(kwargs.get("desc", "")).lower()
            kwargs["file"] = _DiscardProgressOutput()
            kwargs["disable"] = False
            super().__init__(*args, **kwargs)

        def update(self, amount=1):
            result = super().update(amount)
            if not self._transfer_bar:
                callback({"event": "file_progress", "filename": filename,
                          "file_bytes": max(0, int(self.n)),
                          "file_total_bytes": int(self.total) if self.total else None})
            return result

    return ObservedTqdm


@dataclass(frozen=True)
class ModelRef:
    source: str
    repo_id: str | None = None
    revision: str = "main"
    filename: str | None = None
    local: str | None = None


def safe_relative(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or any(x in {"..", "."} for x in p.parts) or "\\" in value:
        raise ValueError(f"Unsafe repository path: {value!r}")
    return value


def parse_model_ref(source, revision=None, filename=None):
    expanded = Path(source).expanduser()
    if expanded.exists():
        return ModelRef(source, local=str(expanded.resolve()), filename=filename)
    if source.startswith(("http://", "https://")):
        u = urlparse(source)
        if u.scheme != "https" or u.hostname not in {"huggingface.co", "www.huggingface.co"}:
            raise ValueError("Use an HTTPS huggingface.co model link or a local path")
        parts = [unquote(x) for x in u.path.strip("/").split("/")]
        if len(parts) < 2:
            raise ValueError("Model link must contain owner/repository")
        repo = "/".join(parts[:2])
        if len(parts) > 2:
            if len(parts) < 4 or parts[2] not in {"tree", "blob", "resolve"}:
                raise ValueError("Expected a repo, /tree/revision, or /resolve/revision/file link")
            revision = revision or parts[3]
            suffix = "/".join(parts[4:])
            if parts[2] == "tree" and suffix:
                raise ValueError("Use the repository root, not a tree subdirectory; select filename separately")
            if parts[2] != "tree":
                filename = filename or safe_relative(suffix)
    else:
        if source.startswith(("/", ".", "~")) or ":" in source or len(source.split("/")) != 2:
            raise ValueError(f"Not an existing local model or owner/repository ID: {source}")
        repo = source
    safe_relative(repo)
    if filename: safe_relative(filename)
    return ModelRef(source, repo_id=repo, revision=revision or "main", filename=filename)


def select_gguf(files, quantization, explicit=None):
    if explicit:
        if explicit not in files:
            raise ValueError(f"Requested model file not found: {explicit}")
        return explicit
    candidates = [x for x in files if x.lower().endswith('.gguf') and quantization.lower() in Path(x).stem.lower()
                  and not any(s in x.lower() for s in ('mmproj', 'text_encoder', 'vae/'))]
    if len(candidates) != 1:
        raise ValueError(f"Expected exactly one {quantization} transformer GGUF; found {candidates}. Set model.filename explicitly.")
    return candidates[0]


class ModelStore:
    def __init__(self, root, offline=False, api=None, downloader=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.offline, self._api, self._downloader = offline, api, downloader

    def _clients(self):
        if self._api is None or self._downloader is None:
            from huggingface_hub import HfApi, hf_hub_download
            self._api = self._api or HfApi()
            self._downloader = self._downloader or hf_hub_download
        return self._api, self._downloader

    def fetch(self, ref, purpose="pipeline", quantization="Q4_K_M", on_progress=None, should_cancel=None):
        def check_cancel():
            if should_cancel is not None and should_cancel():
                raise DownloadCancelled("Download cancelled before completion")

        check_cancel()
        if ref.local:
            p = Path(ref.local)
            if ref.filename: p = p / ref.filename
            if not p.exists(): raise FileNotFoundError(p)
            return p, {"source": ref.source, "local_path": str(p), "cache_hit": True, "revision": None}
        key = hashlib.sha256(json.dumps([ref.repo_id, ref.revision, ref.filename, purpose, quantization]).encode()).hexdigest()[:20]
        manifest = self.root / "manifests" / f"{key}.json"
        if manifest.exists():
            data = json.loads(manifest.read_text())
            if all(Path(f["path"]).is_file() and Path(f["path"]).stat().st_size == f["size"] and f["size"] > 0 for f in data["files"]):
                if on_progress:
                    on_progress({"event": "selection", "total_files": len(data["files"]),
                                 "total_bytes": sum(item["size"] for item in data["files"])})
                    for item in data["files"]:
                        on_progress({"event": "file_complete", "filename": item["filename"],
                                     "size": item["size"]})
                    on_progress({"event": "verifying"})
                return Path(data["load_path"]), {**data["metadata"], "cache_hit": True}
        if self.offline:
            raise FileNotFoundError(f"No complete cached {purpose} for {ref.repo_id}@{ref.revision}. Download once online or point source to a complete local folder.")
        api, download = self._clients()
        info = api.model_info(ref.repo_id, revision=ref.revision, **({"files_metadata": True} if on_progress else {}))
        check_cancel()
        commit = info.sha
        files = [x.rfilename for x in info.siblings]
        kind = "diffusers"
        if ref.filename or (purpose == "pipeline" and "model_index.json" not in files and any(f.endswith('.gguf') for f in files)):
            selected = [select_gguf(files, quantization, ref.filename)]
            kind = "gguf" if selected[0].endswith('.gguf') else "single_file"
        elif purpose == "pipeline":
            if "model_index.json" not in files:
                raise ValueError("Repository has no model_index.json or selectable GGUF. For a single-file DiT set filename; Comfy int8_convrot is unsupported by this native backend.")
            selected = [f for f in files if f == 'model_index.json' or f.startswith(('transformer/', 'text_encoder/', 'vae/', 'processor/', 'scheduler/'))]
        elif purpose == "companions":
            selected = [f for f in files if f in {'model_index.json', 'transformer/config.json'} or f.startswith(('text_encoder/', 'vae/', 'processor/', 'scheduler/'))]
        elif purpose == "text_encoder":
            selected = [f for f in files if f.startswith(('text_encoder/', 'processor/'))]
        else:
            raise ValueError(f"Unknown download purpose: {purpose}")
        selected = [safe_relative(f) for f in selected if not any(fnmatch.fnmatch(f, p) for p in ('*.bin','*.msgpack','*.onnx','*.h5'))]
        if not selected: raise ValueError(f"No compatible {purpose} files in {ref.repo_id}")
        selected.sort(key=lambda name: name != 'model_index.json')
        sizes = {item.rfilename: getattr(item, "size", None) for item in info.siblings}
        known_sizes = [sizes.get(name) for name in selected]
        total_bytes = sum(known_sizes) if all(isinstance(size, int) and size > 0 for size in known_sizes) else None
        if on_progress:
            on_progress({"event": "selection", "total_files": len(selected), "total_bytes": total_bytes})
        records, snapshot = [], None
        for name in selected:
            check_cancel()
            if on_progress:
                on_progress({"event": "file_start", "filename": name,
                             "file_total_bytes": sizes.get(name)})
            options = {"tqdm_class": _observed_tqdm(name, on_progress)} if on_progress else {}
            p = Path(download(repo_id=ref.repo_id, filename=name, revision=commit,
                              cache_dir=str(self.root / 'hub'), local_files_only=False, **options))
            check_cancel()
            if name == 'model_index.json':
                declared_class = json.loads(p.read_text()).get('_class_name')
                if declared_class != 'QwenImage21Pipeline':
                    raise ValueError(f'Unsupported pipeline {declared_class!r}; this workflow requires QwenImage21Pipeline. Stopped before downloading weights.')
            records.append({"path": str(p), "size": p.stat().st_size, "filename": name})
            if on_progress:
                on_progress({"event": "file_complete", "filename": name, "size": p.stat().st_size})
            # hf_hub_download paths are snapshot/<commit>/<relative filename>.
            root = p
            for _ in PurePosixPath(name).parts: root = root.parent
            snapshot = root
        load_path = Path(records[0]['path']) if kind != 'diffusers' else snapshot
        metadata = {"source": ref.source, "repo_id": ref.repo_id, "requested_revision": ref.revision,
                    "resolved_revision": commit, "format": kind, "filename": selected[0] if kind != 'diffusers' else None,
                    "local_path": str(load_path), "cache_hit": False, "downloaded_selection_bytes": sum(x['size'] for x in records)}
        if on_progress:
            on_progress({"event": "verifying"})
        check_cancel()
        manifest.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest.with_suffix(f'.{os.getpid()}.tmp')
        temporary.write_text(json.dumps({"metadata": metadata, "load_path": str(load_path), "files": records}, indent=2))
        temporary.replace(manifest)
        return load_path, metadata
