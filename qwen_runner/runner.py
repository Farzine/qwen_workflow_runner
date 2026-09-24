from copy import deepcopy
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
import hashlib
import json
import os
import platform
import time
import traceback
import uuid
from .images import load_references, save_comparison
from .metrics import InferenceMetrics
from .sampling import sigma_schedule


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temp = path.with_suffix(f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')
    temp.replace(path)


def environment(torch=None, device=None):
    packages = {}
    for name in ('torch', 'diffusers', 'transformers', 'accelerate', 'gguf', 'huggingface_hub', 'Pillow', 'psutil'):
        try:
            dist = metadata.distribution(name)
            packages[name] = {"version": dist.version}
            direct = dist.read_text('direct_url.json')
            if direct:
                provenance = json.loads(direct)
                packages[name]['source_commit'] = provenance.get('vcs_info', {}).get('commit_id')
        except metadata.PackageNotFoundError:
            packages[name] = {"version": None}
    result = {"python": platform.python_version(), "platform": platform.platform(), "packages": packages}
    if torch:
        result['cuda_runtime'] = torch.version.cuda
        if device and str(device).startswith('cuda') and torch.cuda.is_available():
            props = torch.cuda.get_device_properties(device)
            result['gpu'] = {"name": props.name, "total_memory_bytes": props.total_memory,
                             "compute_capability": f'{props.major}.{props.minor}'}
    return result


def run(config, backend_factory=None):
    """Load once, then write one durable JSON record per input attempt.

    CPU image I/O and weight download/loading are outside inference_seconds.
    Prompt/image encoding, noise creation, denoising, VAE decode and device sync are inside.

    Legacy ``generation.images`` is one conditioning sequence. The explicit
    batch contract runs each ``input_images`` item independently with the same
    ordered ``reference_images``. Seeds advance per repeat, not per input, so
    all inputs in a repeat use the same seed.
    """
    from .backend import QwenBackend
    root = Path(config.runtime.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    session_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:10]
    setup_start = time.perf_counter()
    backend = None
    explicit_batch = config.generation.input_images is not None or config.generation.reference_images is not None
    legacy_loaded_images = None
    try:
        config.validate()
        input_paths, reference_paths = config.resolved_image_inputs()
        # Preserve the legacy lifecycle: decode its single conditioning set
        # during setup, before model loading. Explicit batches decode per input
        # so one corrupt source does not prevent later inputs from running.
        if not explicit_batch:
            legacy_loaded_images = load_references(config.generation)
        backend = (backend_factory or QwenBackend)(config).load()
        setup_seconds = time.perf_counter() - setup_start
    except Exception as error:
        path = root / f'{session_id}_setup_error.json'
        atomic_json(path, {"schema_version": 1, "status": "setup_error", "timestamp": timestamp(),
                           "parameters": config.as_dict(), "model": config.model.source,
                           "inference_time_seconds": None, "peak_memory_usage": None,
                           "setup_seconds": time.perf_counter() - setup_start,
                           "environment": environment(), "error": {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}})
        print(f'Setup failed; details: {path}')
        raise
    runtime_environment = environment(backend.torch, config.runtime.device)
    workflow = Path(__file__).resolve().parent.parent / 'workflow' / 'original.json'
    workflow_hash = hashlib.sha256(workflow.read_bytes()).hexdigest() if workflow.exists() else None
    records = []
    input_count = len(input_paths)
    phases = ((True, config.runtime.warmup_runs), (False, config.runtime.repeats))
    for is_warmup, phase_repeats in phases:
        for repeat_index in range(phase_repeats):
            seed = config.generation.seed
            if config.runtime.increment_seed and not is_warmup:
                seed = (seed + repeat_index) % 2**64
            for input_index, input_path in enumerate(input_paths):
                attempt_index = repeat_index * input_count + input_index
                run_id = f'{session_id}_{"warmup" if is_warmup else "run"}_{attempt_index:03d}'
                log_path = root / f'{run_id}.json'
                parameters = deepcopy(config.as_dict())
                parameters['generation']['seed'] = seed
                conditioning_paths = [input_path, *reference_paths]
                task_config = deepcopy(config)
                task_config.generation.images = conditioning_paths
                task_config.generation.input_images = None
                task_config.generation.reference_images = None
                record = {
                    "schema_version": 1, "run_id": run_id, "status": "started", "timestamp": timestamp(),
                    "is_warmup": is_warmup, "repeat_index": repeat_index,
                    "input_index": input_index, "input_image": str(Path(input_path).resolve()),
                    "model": backend.metadata.get('model', {}),
                    "text_encoder": backend.metadata.get('text_encoder', {}), "backend": backend.metadata,
                    "parameters": parameters,
                    "effective_parameters": {
                        "conditioning_image_paths": [str(Path(path).resolve()) for path in conditioning_paths],
                        "sigmas": sigma_schedule(config.generation.steps, config.generation.strength, config.generation.shift, config.generation.scheduler) + [0.0],
                        "negative_prompt_active": config.generation.cfg != 1,
                        "noise_device": "cpu", "noise_dtype": "float32",
                    },
                    "setup_seconds": setup_seconds, "setup_shared_across_runs": True,
                    "environment": runtime_environment, "workflow_sha256": workflow_hash,
                    "inference_time_seconds": None, "peak_memory_usage": None,
                    "outputs": [],
                }
                atomic_json(log_path, record)
                meter = None
                start = time.perf_counter()
                pending_error = None
                try:
                    preprocess_start = time.perf_counter()
                    if legacy_loaded_images is None:
                        images, canvas, image_metadata = load_references(task_config.generation)
                    else:
                        images, canvas, image_metadata = legacy_loaded_images
                    record['preprocessing_seconds'] = time.perf_counter() - preprocess_start
                    record['effective_parameters'].update({
                        "width": canvas[0], "height": canvas[1],
                        # Retained for record compatibility: this is the complete
                        # ordered conditioning sequence, including the input first.
                        "reference_images": image_metadata,
                        "conditioning_images": image_metadata,
                        "process_input": image_metadata[0],
                        "additional_reference_images": image_metadata[1:],
                    })
                    backend.config = task_config
                    meter = InferenceMetrics(backend.torch, config.runtime.device, config.runtime.memory_poll_seconds)
                    with meter:
                        generated = backend.generate(images, canvas, seed)
                    for n, image in enumerate(generated):
                        out = root / f'{config.runtime.filename_prefix}_{run_id}_{n:02d}.png'
                        image.save(out, format='PNG')
                        record['outputs'].append({"path": str(out.resolve()), "width": image.width, "height": image.height,
                                                  "mode": image.mode, "sha256": hashlib.sha256(out.read_bytes()).hexdigest()})
                    if config.runtime.save_comparison and generated:
                        comparison = root / f'{run_id}_comparison.png'
                        save_comparison(images[0], generated[0], comparison)
                        record['comparison'] = str(comparison.resolve())
                    record['status'] = 'success'
                except BaseException as error:
                    record['status'] = 'interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'error'
                    record['error'] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
                    pending_error = error
                finally:
                    record['finished_at'] = timestamp()
                    record['run_wall_seconds_including_output_save'] = time.perf_counter() - start
                    if meter and meter.result:
                        record['inference_time_seconds'] = meter.result['inference_seconds']
                        record['peak_memory_usage'] = {k: v for k, v in meter.result.items() if k != 'inference_seconds'}
                    atomic_json(log_path, record)
                    records.append(record)
                    print(f"{run_id}: {record['status']}; inference={record['inference_time_seconds']} s; log={log_path}")
                if pending_error is not None:
                    if not isinstance(pending_error, Exception) or not explicit_batch or input_count == 1:
                        raise pending_error
                    # Explicit multi-input jobs isolate ordinary per-input failures.
                    continue
    backend.config = config
    return records
