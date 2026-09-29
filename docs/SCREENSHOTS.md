# Screenshot and Sample Provenance

These assets were captured on **2026-09-29** from the running production web
application. They are actual browser screenshots, not mockups. Inputs are original
geometric robot illustrations and a four-color reference created locally for this
repository. Existing personal input images and outputs were not used.

## Capture settings

| Setting | Value |
| --- | --- |
| Model | Qwen/Qwen-Image-2.1, full Diffusers pipeline |
| Model revision | `790c92633540aa0cb11d9abf19eb46d861714758` |
| Backend | `WorkflowQwenImage21Pipeline`; demo disabled |
| Device | `cuda:1`, NVIDIA RTX A6000 |
| Precision / offload | BF16 / model offload |
| Inputs | Two independent 512 × 512 robot illustrations |
| Shared reference | One 512 × 512 color-palette image |
| Output size | 384 × 384 |
| Steps / CFG | 4 / 1.0 |
| Seed | `1070478148268574`, identical across input attempts |
| Runs | Two baseline outputs, then two LoRA-enabled outputs |
| LoRA | `bfs_head_v1.1_qwen_2.1.safetensors`, strength 0.8 |
| Browser | Headless Google Chrome, native DevTools protocol |
| Screenshots | 1440 × 1100 desktop; Models 1440 × 1600; mobile width 390, height 844 |

The mobile screenshot includes content beyond the initial viewport. Desktop
screenshots show the visible app viewport; scrollable panels may contain further
controls. `inference-ready.png` precedes the baseline job; the other published
screenshots show the LoRA-enabled job or its results, except Models and parameter
help, captured in a second production UI session without loading weights. That
pass shows the complete download/upload controls and genuine help popover. UI inventory includes
pre-existing catalog entries, including incompatible test files; their presence
is not a claim that they can perform inference.

## Validation

All four attempts succeeded and produced saved, served PNGs with verified SHA-256
hashes. Records confirm the selected model, `cuda:1`, ordered conditioning
`[current_input, color_reference]`, and actual adapter application for the second
job. Outputs differ from resized inputs; the baseline and adapter outputs also
differ. These are functional smoke samples, not a model-quality or head-swap
benchmark. Four steps and geometric references are intentionally modest; the
baseline visibly carries reference shapes into the result.

The base pipeline loaded once and was reused once for the next job. Navigation
checks passed for all eight pages at widths 1440, 900, and 390, including recovery
from a browser-injected status-fetch error. Owned server/browser processes exited
cleanly. Shutdown reported no active leases and empty resource slots; the process
still held about 9.6 MB allocated / 29.4 MB reserved before exiting, rather than
claiming zero memory while its CUDA context was alive.

Machine-readable facts and artifact hashes: [capture-evidence.json](assets/capture-evidence.json).
Detailed run records and temporary browser tooling were retained locally at
`/tmp/qwen-docs-4ap3gcp7`; that directory is disposable and is not required to
view the committed assets.

## Sample files

| Input | Baseline output | LoRA-enabled output |
| --- | --- | --- |
| [Gold robot](assets/samples/1-robot-gold.png) | [Baseline](assets/samples/baseline-robot-1.png) | [Adapter applied](assets/samples/lora-robot-1.png) |
| [Teal robot](assets/samples/2-robot-teal.png) | [Baseline](assets/samples/baseline-robot-2.png) | [Adapter applied](assets/samples/lora-robot-2.png) |

[Shared color reference](assets/samples/3-color-reference.png).

Prompt:

> Transform the toy robot in &lt;image1&gt; into a charming watercolor illustration
> on textured paper. Use the blue, teal, gold and coral palette in &lt;image2&gt;.
> Preserve the robot silhouette and friendly expression. Soft brushwork,
> detailed hand-painted finish, no text.

## Updating the screenshots

Start the UI with temporary input/output directories and the intended compatible
model catalog. Copy these sample inputs into the temporary input folder. Select
two process inputs and the shared reference, apply the documented device/settings,
and run real inference. Capture each task page after its content loads and capture
Batch while generation is genuinely active. Save comparison/details screenshots
after completion, then check narrower viewports.

Use the existing [browser validation script](../scripts/validate_browser_production.js)
for navigation or real inference checks. Its full inference mode expects three
images in a `Child` input subfolder; settings and flags are described in the script.
For an update, change the evidence and captions alongside the screenshots. Demo
captures must be explicitly labeled synthetic. Do not redistribute weights or
adapters with the documentation.

Original drawn inputs are covered by the repository license. Generated samples
remain subject to the model/adapter terms. Screenshots contain ordinary local
runtime identifiers and paths, but no authentication tokens or personal portraits.
