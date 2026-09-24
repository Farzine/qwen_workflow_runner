# Porting decisions

## The connected graph controls the result

Top-level node 459 instantiates the `Image Edit (Qwen Image 2.1)` subgraph.
Its exposed widget values override the inner widgets. In particular, the inner
text-encoding node shows resolution 1024, but the connected subgraph input
supplies **0**. The effective prompt, seed and other parameters also come from
the outer instance, not the empty inner prompt or inner seed 0.

The `ComfySwitchNode` selects the encoder's first-reference-sized empty latent
because `custom_size` is false. Therefore the connected ResolutionSelector's
square dimensions are **inactive**, even though its node is present. The
provided width/height defaults remain 1024 for explicit custom-size use. This
runner exposes width/height directly rather than implementing the unused
ResolutionSelector widget UI.

Both reference images are conditioning inputs. Neither is the sampler's initial
image latent. This is why traditional image-to-image strength blending would
reproduce the wrong graph.

## Native implementation

The dedicated Qwen 2.1 Diffusers architecture supplies the Qwen3-VL encoder,
single-stream transformer, reference latent insertion, block-causal attention,
prefix KV caching and RGBA VAE. The pipeline source is pinned and attributed.
This runner modifies its input sizing to match the graph, uses the first image
as the output canvas, retains FP32 sampler latents, and maps CFG faithfully.

The runner supplies Comfy-style, already-shifted sigmas to an unshifted Euler
flow scheduler. Passing those sigmas to a dynamically shifted scheduler would
apply the shift twice. The fixed shift is 0.69; no canvas-dependent dynamic
shift is applied. The simple schedule samples the same 10,000-point training
grid. Reduced denoise selects the final requested steps and scales starting
noise by the first selected sigma. The VAE encodes references with its latent
mode, not a random sample.

Noise is generated on CPU in float32 from a per-run generator. It is packed
into the model's spatial-token representation, and only transformer inputs are
cast to model precision during Euler accumulation.

## Explicit differences and bounds

1. **Weights:** the graph names a Comfy `int8_convrot` transformer. The native
   default uses the official Diffusers BF16 weights. GGUF is a separately
   selected quantization. The code rejects `int8_convrot` rather than pretending
   it is an ordinary safetensors checkpoint. Comparing these runs measures
   both format/precision and backend differences.
2. **Cache transport:** cache contents are lossless. Auto placement uses a
   configurable CUDA reserve, with synchronous CPU transfers. Comfy's dynamic
   VRAM decisions and asynchronous prefetch implementation are not reproduced.
   Int8/int4 KV-cache storage is not implemented. The original graph uses
   default, lossless storage.
3. **Numeric details:** kernel selection, prompt/vision preprocessing details
   inside each framework, sigma rounding and floating-point accumulation can
   differ. Equal seeds do not guarantee identical output pixels across engines,
   hardware, software versions, offload configurations or weight quantizations.
4. **Seed controls:** Comfy's UI randomize-after-generation behavior does not
   represent a second sampling operation. Here the provided seed is fixed;
   optional incrementing is explicit and logged.
5. **ImageSave/ImageCompare:** outputs use Pillow PNG saving and an optional
   side-by-side comparison. Comfy's embedded PNG workflow metadata, live slider,
   and custom color-profile UI are not recreated. The full run metadata is
   stored in JSON. Outputs are ordinary 8-bit PNGs.
6. **Architecture scope:** this is the Qwen Image 2.1 graph. Earlier Qwen Image
   and Qwen Image Edit architectures, masks and unrelated custom nodes are not
   silently accepted. One compatible Qwen Image 2.1 transformer LoRA can be
   applied through Diffusers/PEFT. One to ten ordered references are supported.

These bounds are recorded or explained so a successful load is not mistaken
for a demonstrated pixel-for-pixel reproduction. `original.json` remains the
authoritative submitted graph; `source_manifest.json` records source hashes.
