from dataclasses import asdict, dataclass, field
from pathlib import Path
import math


@dataclass
class ModelConfig:
    source: str = "https://huggingface.co/Qwen/Qwen-Image-2.1"
    revision: str | None = None
    filename: str | None = None  # Choose one GGUF; default selects Q4_K_M only.
    gguf_quantization: str = "Q4_K_M"
    base_model: str = "Qwen/Qwen-Image-2.1"  # Companion components for GGUF/single-file DiT.
    base_revision: str | None = None
    text_encoder_source: str | None = None  # Diffusers-layout repo/local folder.
    cache_dir: str = "models"
    offline: bool = False


@dataclass
class GenerationConfig:
    images: list[str] = field(default_factory=lambda: [
        "inputs/portrait_model_denim.png", "inputs/clothing_light_blue_denim_shirt.png"])
    # Explicit batch contract. When input_images is provided it takes precedence
    # over the legacy combined images list. Each input is inferred independently
    # with the same ordered reference_images appended after it.
    input_images: list[str] | None = None
    reference_images: list[str] | None = None
    prompt: str = (
        "Keep the character and pose in <image1> unchanged, put this light blue denim shirt "
        "from <image2> on the character, preserve the original facial features, hair, body "
        "shape and pose, the denim shirt fits naturally on body, realistic denim fabric "
        "texture, natural clothing folds, keep the original background and original lighting, "
        "high fashion editorial photography, sharp details"
    )
    negative_prompt: str = ""
    steps: int = 25
    cfg: float = 1.0
    seed: int = 1070478148268574
    strength: float = 1.0  # KSampler denoise; NOT first-image latent blending.
    resolution: int = 0
    custom_size: bool = False
    width: int = 1024
    height: int = 1024
    batch_size: int = 1
    sampler: str = "euler"
    scheduler: str = "simple"  # Also: normal; deliberately reject unimplemented schedules.
    shift: float = 0.69
    kv_cache: bool = True
    kv_cache_device: str = "auto"  # auto | gpu | cpu; storage remains lossless.
    kv_cache_reserve_gib: float = 1.0  # auto leaves this much CUDA headroom.
    reference_mode: str = "rgb"  # LoadImage's connected IMAGE output is RGB.


@dataclass
class RuntimeConfig:
    device: str = "cuda:0"  # CPU works but is very slow; MPS has unverified operator coverage.
    dtype: str = "bfloat16"
    offload: str = "model"  # none | model | sequential
    vae_tiling: bool = False
    repeats: int = 1
    warmup_runs: int = 0
    increment_seed: bool = False
    memory_poll_seconds: float = 0.02
    output_dir: str = "outputs"
    filename_prefix: str = "Qwen_image_2.1"
    save_comparison: bool = True


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    def as_dict(self):
        result = asdict(self)
        if self.generation.input_images is not None or self.generation.reference_images is not None:
            # Do not serialize ignored default/legacy paths beside the active
            # explicit contract; this keeps API responses and run records clear.
            result['generation']['images'] = []
        return result

    def resolved_image_inputs(self):
        """Return ordered process inputs and shared references.

        The legacy ``images`` field remains a single conditioning sequence:
        its first item is the process input/canvas and the remaining items are
        references. Supplying either explicit field activates the new contract.
        """
        g = self.generation
        explicit = g.input_images is not None or g.reference_images is not None
        if explicit:
            inputs = g.input_images
            references = [] if g.reference_images is None else g.reference_images
            if not isinstance(inputs, list) or not 1 <= len(inputs) <= 10:
                raise ValueError("Provide 1–10 ordered input_images.")
            if not isinstance(references, list) or len(references) > 9:
                raise ValueError(
                    "Provide at most 9 ordered reference_images so each inference has at most 10 conditioning images."
                )
        else:
            if not isinstance(g.images, list) or not 1 <= len(g.images) <= 10:
                raise ValueError("Provide 1–10 ordered reference images; image1 is the output canvas.")
            inputs, references = g.images[:1], g.images[1:]

        if not all(isinstance(path, str) and path.strip() for path in [*inputs, *references]):
            raise ValueError("All image paths must be non-empty strings.")
        return list(inputs), list(references)

    def validate(self, check_images=True):
        g, r = self.generation, self.runtime
        input_images, reference_images = self.resolved_image_inputs()
        explicit_images = g.input_images is not None or g.reference_images is not None
        if check_images:
            for p in [*input_images, *reference_images]:
                if not Path(p).is_file():
                    label = "image" if explicit_images else "reference image"
                    raise FileNotFoundError(f"Missing {label}: {p}. Supply your images or run scripts/download_examples.py.")
        if g.steps < 1 or g.steps > 10000 or g.batch_size < 1:
            raise ValueError("steps must be 1–10000 and batch_size must be positive")
        if not math.isfinite(g.cfg) or g.cfg < 0:
            raise ValueError("cfg must be finite and >= 0")
        if not 0 < g.strength <= 1:
            raise ValueError("strength must be > 0 and <= 1; this is empty-latent KSampler denoise")
        if int(g.steps / g.strength) > 10000:
            raise ValueError("steps / strength exceeds the 10000-point training schedule")
        if not 0 <= g.seed <= 2**64 - 1:
            raise ValueError("seed must be an unsigned 64-bit integer")
        if g.resolution < 0 or g.resolution > 4096 or g.resolution % 32:
            raise ValueError("resolution must be 0 or a multiple of 32 through 4096")
        if g.custom_size and any(v < 32 or v % 32 for v in (g.width, g.height)):
            raise ValueError("custom width/height must be positive multiples of 32")
        if g.sampler != "euler" or g.scheduler not in {"simple", "normal"}:
            raise ValueError("Implemented sampling: euler with simple or normal; unsupported options are never ignored")
        if not math.isfinite(g.shift) or not -10 <= g.shift <= 10:
            raise ValueError("shift must be finite and between -10 and 10")
        if g.reference_mode not in {"rgb", "rgba"}:
            raise ValueError("reference_mode must be rgb or rgba")
        if g.kv_cache_device not in {"auto", "gpu", "cpu"} or not math.isfinite(g.kv_cache_reserve_gib) or g.kv_cache_reserve_gib < 0:
            raise ValueError("Invalid KV cache device or memory reserve")
        if r.dtype not in {"bfloat16", "float16", "float32"} or r.offload not in {"none", "model", "sequential"}:
            raise ValueError("Unsupported dtype or offload mode")
        if r.device == "cpu" and (r.dtype != "float32" or r.offload != "none"):
            raise ValueError("For CPU use dtype='float32', offload='none'")
        if r.device.startswith("mps") and r.offload != "none":
            raise ValueError("Use offload='none' on MPS")
        if r.repeats < 1 or r.warmup_runs < 0 or not 0.001 <= r.memory_poll_seconds <= 1:
            raise ValueError("Invalid repeat, warmup or memory polling settings")
        if not r.filename_prefix or Path(r.filename_prefix).name != r.filename_prefix or '/' in r.filename_prefix or '\\' in r.filename_prefix:
            raise ValueError("filename_prefix must be a filename, not a directory")
