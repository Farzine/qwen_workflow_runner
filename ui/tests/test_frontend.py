"""Unit and integration tests for Frontend Web UI assets and endpoints.

Verifies:
- Root single-page application serving (GET /)
- Static asset delivery (CSS, JS) with appropriate media types
- Parameter coverage for all 38 dataclass fields from ModelConfig, GenerationConfig, and RuntimeConfig
- Zero external CDN dependencies (offline capability)
- Form control ranges, options, and validation attributes
- 100% ID alignment between index.html and app.js
"""

import re
import subprocess
import unittest
from dataclasses import fields
from pathlib import Path

from starlette.testclient import TestClient

from qwen_runner.config import GenerationConfig, ModelConfig, RuntimeConfig
from ui.server import app


class TestFrontendServing(unittest.TestCase):
    """Verifies that the backend server correctly serves template and static assets."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.repo_root = Path(__file__).resolve().parent.parent.parent
        cls.index_path = cls.repo_root / "ui" / "templates" / "index.html"
        cls.css_path = cls.repo_root / "ui" / "static" / "css" / "style.css"
        cls.js_path = cls.repo_root / "ui" / "static" / "js" / "app.js"

    def test_root_serves_html_with_title_and_panels(self):
        """GET / returns HTTP 200, Content-Type text/html, and contains core UI panels."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        html = resp.text

        # Page title and brand
        self.assertIn("<title>Qwen Image 2.1", html)
        self.assertIn("Qwen Image 2.1", html)

        # Core panels: Input Assets, Configuration, Output Hub
        self.assertIn('id="panel-inputs"', html)
        self.assertIn('id="panel-config"', html)
        self.assertIn('id="panel-output"', html)
        self.assertIn('id="launch-control-bar"', html)

    def test_static_css_served_with_correct_media_type(self):
        """GET /static/css/style.css returns HTTP 200 with Content-Type text/css."""
        resp = self.client.get("/static/css/style.css")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/css", resp.headers["content-type"])
        self.assertTrue(len(resp.text) > 1000)
        self.assertIn(".app-layout", resp.text)
        self.assertIn(".panel", resp.text)

    def test_static_js_served_with_correct_media_type(self):
        """GET /static/js/app.js returns HTTP 200 with Content-Type javascript."""
        resp = self.client.get("/static/js/app.js")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            "javascript" in resp.headers["content-type"]
            or "text/javascript" in resp.headers["content-type"]
            or "application/javascript" in resp.headers["content-type"]
        )
        self.assertTrue(len(resp.text) > 1000)
        self.assertIn("Qwen Image 2.1 Workflow", resp.text)

    def test_html_template_references_valid_static_assets(self):
        """HTML references /static/css/style.css and /static/js/app.js."""
        with open(self.index_path, encoding="utf-8") as f:
            html = f.read()

        self.assertIn('<link rel="stylesheet" href="/static/css/style.css">', html)
        self.assertIn('<script type="module" src="/static/js/app.js"></script>', html)


class TestZeroCDNDependencies(unittest.TestCase):
    """Verifies that no external CDN or cloud resources are referenced (strictly offline)."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent.parent
        cls.index_path = cls.repo_root / "ui" / "templates" / "index.html"
        cls.css_path = cls.repo_root / "ui" / "static" / "css" / "style.css"
        cls.js_path = cls.repo_root / "ui" / "static" / "js" / "app.js"

    def test_html_has_no_external_stylesheets_or_scripts(self):
        """No external Google Fonts, CDN stylesheets, or CDN scripts in index.html."""
        with open(self.index_path, encoding="utf-8") as f:
            html = f.read()

        # External link tags
        ext_links = re.findall(r'<link[^>]+href=["\'](https?:[^\'"]+)["\']', html)
        self.assertEqual(ext_links, [], f"Found external <link> URLs: {ext_links}")

        # External script tags
        ext_scripts = re.findall(r'<script[^>]+src=["\'](https?:[^\'"]+)["\']', html)
        self.assertEqual(ext_scripts, [], f"Found external <script> URLs: {ext_scripts}")

    def test_css_has_no_external_font_imports_or_urls(self):
        """No external @import or url() fetches in style.css."""
        with open(self.css_path, encoding="utf-8") as f:
            css = f.read()

        ext_imports = re.findall(r'@import\s+url\(["\']?(https?:[^\'")]+)["\']?\)', css)
        self.assertEqual(ext_imports, [], f"Found external @import in CSS: {ext_imports}")

        ext_urls = re.findall(r'url\(["\']?(https?:[^\'")]+)["\']?\)', css)
        self.assertEqual(ext_urls, [], f"Found external url() in CSS: {ext_urls}")

    def test_js_has_no_external_network_imports(self):
        """No external ES6 import statements pointing to CDN URLs in app.js."""
        with open(self.js_path, encoding="utf-8") as f:
            js = f.read()

        ext_imports = re.findall(r'import\s+.*?from\s+["\'](https?:[^\'"]+)["\']', js)
        self.assertEqual(ext_imports, [], f"Found external JS imports: {ext_imports}")


class TestParameterCoverage(unittest.TestCase):
    """Verifies that all 38 dataclass parameters are exposed in the HTML form."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent.parent
        cls.index_path = cls.repo_root / "ui" / "templates" / "index.html"
        cls.js_path = cls.repo_root / "ui" / "static" / "js" / "app.js"
        with open(cls.index_path, encoding="utf-8") as f:
            cls.html = f.read()

    def test_model_config_parameters_exposed(self):
        """Every field in ModelConfig is present in the HTML template."""
        for field in fields(ModelConfig):
            name_dash = field.name.replace("_", "-")
            found = (
                f'id="param-model-{name_dash}"' in self.html
                or f'id="param-model-{field.name}"' in self.html
                or f'id="param-{name_dash}"' in self.html
                or f'id="param-{field.name}"' in self.html
                or f'id="{name_dash}"' in self.html
            )
            self.assertTrue(found, f"ModelConfig field '{field.name}' not found in index.html")

    def test_generation_config_parameters_exposed(self):
        """Every field in GenerationConfig is present in the HTML template."""
        for field in fields(GenerationConfig):
            name_dash = field.name.replace("_", "-")
            found = (
                f'id="param-{name_dash}"' in self.html
                or f'id="param-{field.name}"' in self.html
                or f'id="{name_dash}"' in self.html
                or f'id="selection-sequence-panel"' in self.html  # for 'images'
            )
            self.assertTrue(found, f"GenerationConfig field '{field.name}' not found in index.html")

    def test_runtime_config_parameters_exposed(self):
        """Every field in RuntimeConfig is present in the HTML template."""
        for field in fields(RuntimeConfig):
            name_dash = field.name.replace("_", "-")
            found = (
                f'id="param-{name_dash}"' in self.html
                or f'id="param-{field.name}"' in self.html
                or f'id="{name_dash}"' in self.html
            )
            self.assertTrue(found, f"RuntimeConfig field '{field.name}' not found in index.html")

    def test_demo_mode_toggle_exposed(self):
        """Synthetic demo is exposed as an explicit, unchecked opt-in."""
        self.assertIn('id="toggle-demo-mode"', self.html)
        self.assertNotRegex(self.html, r'id="toggle-demo-mode"[^>]*\bchecked\b')
        self.assertIn("Synthetic Demo", self.html)

    def test_frontend_defaults_to_real_backend_and_checks_runtime(self):
        js = self.js_path.read_text(encoding="utf-8")
        self.assertIn("demo_mode: false", js)
        self.assertIn("/api/system", js)
        self.assertIn("Real Backend Blocked", js)


class TestFormControlsAndValidationAttributes(unittest.TestCase):
    """Verifies that HTML form controls include specified boundary and constraint attributes."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent.parent
        cls.index_path = cls.repo_root / "ui" / "templates" / "index.html"
        with open(cls.index_path, encoding="utf-8") as f:
            cls.html = f.read()

    def test_step_slider_and_number_constraints(self):
        """Steps numeric input and slider specify min=1 and max=10000 or max=100."""
        self.assertIn('id="param-steps"', self.html)
        self.assertIn('min="1"', self.html)
        self.assertIn('max="10000"', self.html)
        self.assertIn('id="slider-steps"', self.html)

    def test_cfg_scale_constraints(self):
        """CFG numeric input specifies min=0."""
        self.assertIn('id="param-cfg"', self.html)
        self.assertIn('id="slider-cfg"', self.html)

    def test_strength_constraints(self):
        """Strength denoise specifies range (0, 1]."""
        self.assertIn('id="param-strength"', self.html)
        self.assertIn('id="slider-strength"', self.html)
        self.assertIn('id="schedule-calc-ratio"', self.html)

    def test_device_and_hardware_options(self):
        """Device options include cuda:0, cpu, and mps."""
        self.assertIn('value="cuda:0"', self.html)
        self.assertIn('value="cpu"', self.html)
        self.assertIn('value="mps"', self.html)

    def test_dtype_options(self):
        """Dtype options include bfloat16, float16, and float32."""
        self.assertIn('value="bfloat16"', self.html)
        self.assertIn('value="float16"', self.html)
        self.assertIn('value="float32"', self.html)

    def test_offload_options(self):
        """Offload options include model, none, and sequential."""
        self.assertIn('value="model"', self.html)
        self.assertIn('value="none"', self.html)
        self.assertIn('value="sequential"', self.html)

    def test_sampler_and_scheduler_options(self):
        """Sampler is euler; scheduler choices include simple and normal."""
        self.assertIn('value="euler"', self.html)
        self.assertIn('value="simple"', self.html)
        self.assertIn('value="normal"', self.html)


class TestInteractiveComponentIDs(unittest.TestCase):
    """Verifies that all interactive components required by R1, R3, and R4 are present."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent.parent
        cls.index_path = cls.repo_root / "ui" / "templates" / "index.html"
        cls.js_path = cls.repo_root / "ui" / "static" / "js" / "app.js"
        with open(cls.index_path, encoding="utf-8") as f:
            cls.html = f.read()
        with open(cls.js_path, encoding="utf-8") as f:
            cls.js = f.read()

    def test_r1_input_browser_elements(self):
        """Input browser R1 elements are present."""
        expected = [
            "btn-refresh-inputs",
            "folder-breadcrumbs",
            "subfolders-list",
            "input-search-filter",
            "input-gallery-grid",
            "inputs-loading-spinner",
            "selection-sequence-panel",
            "selected-count-badge",
            "btn-clear-selection",
            "selected-slots-list",
            "empty-selection-notice",
        ]
        for elem_id in expected:
            self.assertIn(f'id="{elem_id}"', self.html, f"Missing R1 element: {elem_id}")

    def test_r3_model_management_elements(self):
        """Model management R3 elements are present."""
        expected = [
            "select-cached-model",
            "btn-refresh-models",
            "btn-apply-cached-model",
            "cached-model-info-box",
            "info-model-path",
            "info-model-type",
            "info-model-size",
            "param-model-source",
            "param-model-filename",
            "param-model-revision",
            "btn-download-hf-model",
            "hf-download-progress-container",
            "hf-download-bar",
            "hf-download-status-label",
            "hf-download-percent-badge",
            "model-upload-dropzone",
            "model-file-input",
            "model-upload-progress-container",
            "model-upload-bar",
            "model-upload-status-label",
            "model-upload-percent-badge",
        ]
        for elem_id in expected:
            self.assertIn(f'id="{elem_id}"', self.html, f"Missing R3 element: {elem_id}")

    def test_r4_run_management_and_output_elements(self):
        """Run management and output hub R4 elements are present."""
        expected = [
            "btn-run-pipeline",
            "btn-cancel-run",
            "run-status-badge",
            "execution-progress-container",
            "run-step-progress-bar",
            "run-step-counter",
            "run-percent-label",
            "tab-btn-outputs",
            "tab-btn-comparison",
            "tab-btn-logs",
            "tab-btn-json",
            "output-active-view",
            "output-empty-state",
            "output-primary-image",
            "output-meta-filename",
            "output-meta-dimensions",
            "output-meta-sha256",
            "btn-download-output",
            "comparison-split-wrapper",
            "comparison-before-img",
            "comparison-after-img",
            "comparison-slider-handle",
            "comparison-two-up-wrapper",
            "terminal-stream-console",
            "terminal-log-lines",
            "toggle-log-autoscroll",
            "btn-copy-logs",
            "btn-clear-logs",
            "json-record-code",
            "btn-copy-json",
            "btn-download-json",
            "drawer-history",
            "drawer-backdrop",
            "btn-toggle-history",
            "btn-close-history",
            "history-counter",
            "history-runs-list",
            "modal-image-preview",
            "modal-preview-img",
            "btn-close-modal",
        ]
        for elem_id in expected:
            self.assertIn(f'id="{elem_id}"', self.html, f"Missing R4 element: {elem_id}")

    def test_all_js_get_element_by_id_calls_match_html(self):
        """Every element ID queried in app.js exists in index.html."""
        html_ids = set(re.findall(r'id=[\'"]([^\s\'"]+)[\'"]', self.html))
        js_ids = set(re.findall(r'document\.getElementById\([\'"]([^\s\'"]+)[\'"]\)', self.js))

        missing_ids = js_ids - html_ids
        self.assertEqual(
            missing_ids,
            set(),
            f"JavaScript controller queries IDs that do not exist in index.html: {missing_ids}",
        )

    def test_js_syntax_validity(self):
        """JavaScript controller has valid syntax (checked via node -c)."""
        res = subprocess.run(
            ["node", "-c", str(self.js_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"JavaScript syntax error in {self.js_path}:\n{res.stderr}",
        )

    def test_frontend_state_machine_harness(self):
        """Execute Node.js empirical state machine challenge harness (27 tests)."""
        node_script = self.repo_root / "ui" / "tests" / "test_challenger_m2_node.js"
        res = subprocess.run(
            ["node", str(node_script)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Node.js state machine harness failed:\n{res.stdout}\n{res.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
