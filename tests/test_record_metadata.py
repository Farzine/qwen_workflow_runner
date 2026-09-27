"""Human-readable record facts are derived, never guessed."""

from pathlib import Path
import tempfile
from unittest.mock import patch

from PIL import Image

from qwen_runner.record_metadata import summarize_record


def test_success_summary_uses_real_file_and_record_facts():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source, reference, output = (root / name for name in ("input.png", "reference.webp", "output.png"))
        Image.new("RGB", (120, 80)).save(source)
        Image.new("RGB", (32, 64)).save(reference)
        Image.new("RGB", (64, 64)).save(output)
        adapter = root / "style.safetensors"
        adapter.write_bytes(b"adapter")
        record = {
            "run_id": "run_1", "status": "success", "input_image": str(source), "input_index": 0,
            "model": {"repo_id": "owner/model", "downloaded_selection_bytes": 1234},
            "backend": {"pipeline": "WorkflowQwenImage21Pipeline", "device": "cuda:1"},
            "parameters": {"generation": {"input_images": [str(source)], "reference_images": [str(reference)],
                                          "steps": 12, "cfg": 1.5, "seed": 9}},
            "effective_parameters": {"conditioning_images": [
                {"path": str(source), "original_size": [120, 80]},
                {"path": str(reference), "original_size": [32, 64]}],
                "lora": {"path": str(adapter), "applied": True, "scale": 0.7},
                "width": 64, "height": 64},
            "inference_time_seconds": 2.5,
            "peak_memory_usage": {"gpu_peak_allocated_bytes": 2**30},
            "outputs": [{"path": str(output), "width": 64, "height": 64}],
        }
        summary = summarize_record(record)
        assert summary["summary_version"] == 1
        assert summary["input"]["aspect_ratio"] == "3:2"
        assert summary["input"]["file_type"] == "PNG"
        assert summary["input"]["size_bytes"] == source.stat().st_size
        assert summary["references"][0]["aspect_ratio"] == "1:2"
        assert summary["model"] == {"name": "owner/model", "source": "owner/model",
                                    "size_bytes": 1234, "parameters_billion": None}
        assert summary["lora"]["size_bytes"] == adapter.stat().st_size
        assert summary["generation"]["peak_gpu_allocated_bytes"] == 2**30
        assert summary["outputs"][0]["filename"] == "output.png"


def test_setup_error_and_legacy_missing_files_show_unavailable_facts():
    missing = "/missing/input.png"
    record = {"status": "setup_error", "schema_version": 1,
              "model": "legacy-model", "parameters": {"generation": {"images": [missing],
                                                                      "steps": 4, "cfg": 1.0, "seed": 7},
                                                     "model": {"source": "legacy-model"}},
              "error": {"type": "FileNotFoundError", "message": "missing input"}}
    summary = summarize_record(record)
    assert summary["input"]["filename"] == "input.png"
    assert summary["input"]["size_bytes"] is None
    assert summary["input"]["file_type"] is None
    assert summary["model"]["parameters_billion"] is None
    assert summary["lora"] is None
    assert summary["generation"]["duration_seconds"] is None
    assert summary["error"]["message"] == "missing input"


def test_unreadable_image_metadata_does_not_block_record_summary():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "input.png"
        source.write_bytes(b"not an image")
        with patch("qwen_runner.record_metadata.Image.open",
                   side_effect=Image.DecompressionBombError("too large")):
            summary = summarize_record({"input_image": str(source)})
        assert summary["input"]["filename"] == "input.png"
        assert summary["input"]["size_bytes"] == source.stat().st_size
        assert summary["input"]["file_type"] is None
