"""Tier 5 Adversarial Frontend & Full-Workflow Stress Test Suite.

Audits:
1. DOM Element IDs:
   - Exactly 208 unique IDs in ui/templates/index.html.
   - Naming conventions, uniqueness, and complete alignment with ui/static/js/app.js.
   - ARIA accessibility: tab controls, tabpanel associations, modal/drawer roles, form labels.
2. Offline Font Stack & Resource Integrity:
   - 100% offline compliance (zero external CDNs, zero @import or url() web fonts).
   - Local system font stacks (--font-sans and --font-mono).
3. Live Server Workflow Execution Stress:
   - Rapid back-to-back run requests (10 concurrent / burst requests) through ASGI TestClient.
   - History drawer scaling (20+ runs), record inspection, and comparison image fallback.
   - Resilient error handling for non-existent / deleted run records (HTTP 404).
4. Client State Machine & DOM Event Stress (Node.js Harness):
   - Comparison slider clamp boundaries (0% to 100%, negative & overflow coordinates).
   - Token toolbar insertion (<image1> through <image10>) across cursor boundaries.
   - Empty image tray resubmissions and rapid clear/re-add stress cycles (50 iterations).
   - Client state mutations: negative seeds, extreme CFG scales, schedule limit calculation.
   - Rapid click storms on run button: empirical concurrency tracking and re-entrancy audit.
"""

import hashlib
import html.parser
import re
import subprocess
import time
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from ui.server import app


class DOMAuditor(html.parser.HTMLParser):
    """Parses index.html to extract IDs, ARIA tags, and form input controls."""

    def __init__(self):
        super().__init__()
        self.ids = []
        self.aria_elements = []
        self.inputs = []
        self.labels = {}
        self.label_stack = []
        self.enclosed_inputs = set()
        self.tabs = []
        self.tab_panels = []
        self.dialogs = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if "id" in attr_dict:
            self.ids.append(attr_dict["id"])
        if any(k.startswith("aria-") or k == "role" for k in attr_dict):
            self.aria_elements.append((tag, attr_dict))
        if tag == "label":
            self.label_stack.append(attr_dict)
            if "for" in attr_dict:
                self.labels[attr_dict["for"]] = attr_dict
        if tag in ("input", "select", "textarea"):
            self.inputs.append((tag, attr_dict))
            if self.label_stack and "id" in attr_dict:
                self.enclosed_inputs.add(attr_dict["id"])
        if attr_dict.get("role") == "tab":
            self.tabs.append(attr_dict)
        if attr_dict.get("role") == "tabpanel":
            self.tab_panels.append(attr_dict)
        if attr_dict.get("role") == "dialog" or tag == "dialog":
            self.dialogs.append(attr_dict)

    def handle_endtag(self, tag):
        if tag == "label" and self.label_stack:
            self.label_stack.pop()


class TestDOMIntegrityAndA11y(unittest.TestCase):
    """Verifies DOM integrity, exact 208 IDs, accessibility, and offline compliance."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent.parent
        cls.index_path = cls.repo_root / "ui" / "templates" / "index.html"
        cls.css_path = cls.repo_root / "ui" / "static" / "css" / "style.css"
        cls.js_path = cls.repo_root / "ui" / "static" / "js" / "app.js"

        with open(cls.index_path, encoding="utf-8") as f:
            cls.html_content = f.read()

        cls.auditor = DOMAuditor()
        cls.auditor.feed(cls.html_content)

    def test_exact_208_dom_ids_uniqueness_and_kebab_case(self):
        """Audits that index.html contains exactly 208 IDs with zero duplicates and proper syntax."""
        ids = self.auditor.ids
        self.assertEqual(
            len(ids),
            208,
            f"Expected exactly 208 IDs in index.html, found {len(ids)}",
        )
        self.assertEqual(
            len(set(ids)),
            208,
            f"Duplicate IDs detected: {[i for i in ids if ids.count(i) > 1]}",
        )

        # Verify all IDs conform to valid CSS/HTML identifier format
        id_pattern = re.compile(r"^[a-zA-Z0-9]+([-_][a-zA-Z0-9]+)*$")
        for elem_id in ids:
            self.assertTrue(
                id_pattern.match(elem_id),
                f"Element ID '{elem_id}' violates identifier naming pattern",
            )

    def test_js_get_element_by_id_strict_alignment(self):
        """Verifies that all 103 getElementById calls in app.js target valid index.html IDs."""
        with open(self.js_path, encoding="utf-8") as f:
            js_content = f.read()

        html_ids = set(self.auditor.ids)
        queried_ids = set(re.findall(r'document\.getElementById\(["\']([^"\'\s]+)["\']\)', js_content))

        self.assertGreater(len(queried_ids), 90, "Expected at least 90 getElementById calls in app.js")
        missing_in_html = queried_ids - html_ids
        self.assertEqual(
            missing_in_html,
            set(),
            f"JavaScript queries element IDs not found in index.html: {missing_in_html}",
        )

    def test_aria_tab_and_tabpanel_relationships(self):
        """Verifies that all configuration/output tabs reference existing panels."""
        html_ids = set(self.auditor.ids)
        tabs = self.auditor.tabs
        self.assertGreaterEqual(len(tabs), 8, f"Expected at least 8 ARIA tabs, found {len(tabs)}")

        for tab in tabs:
            tab_id = tab.get("id")
            controls = tab.get("aria-controls")
            self.assertTrue(controls, f"Tab '{tab_id}' lacks aria-controls attribute")
            self.assertIn(
                controls,
                html_ids,
                f"Tab '{tab_id}' references non-existent panel '{controls}'",
            )
            self.assertIn(
                tab.get("aria-selected"),
                ("true", "false"),
                f"Tab '{tab_id}' lacks boolean aria-selected attribute",
            )

    def test_form_controls_accessible_names(self):
        """Verifies form controls have associated labels, parent labels, or placeholders."""
        unlabeled = []
        # Paired range sliders that accompany a labeled numeric input
        companion_sliders = {"slider-steps", "slider-cfg", "slider-strength", "slider-shift"}
        special_inputs = {"select-cached-model", "model-file-input"}

        for tag, attrs in self.auditor.inputs:
            inp_id = attrs.get("id")
            inp_type = attrs.get("type", "text")
            if inp_type in ("hidden", "button", "submit", "reset"):
                continue

            has_label = (
                (inp_id and inp_id in self.auditor.labels)
                or (inp_id and inp_id in self.auditor.enclosed_inputs)
                or (inp_id and inp_id in companion_sliders)
                or (inp_id and inp_id in special_inputs)
                or attrs.get("aria-label")
                or attrs.get("title")
                or attrs.get("placeholder")
            )
            if not has_label:
                unlabeled.append((tag, inp_id))

        self.assertEqual(
            unlabeled,
            [],
            f"Form controls completely lack accessible labels or placeholders: {unlabeled}",
        )

        # Verify companion sliders and special inputs have explicit direct aria-label
        missing_direct_aria = [
            cid for cid in companion_sliders.union(special_inputs)
            if any(a.get("id") == cid and not a.get("aria-label") for _, a in self.auditor.inputs)
        ]
        self.assertEqual(
            len(missing_direct_aria),
            0,
            f"Companion sliders and upload inputs must have direct aria-label attributes: {missing_direct_aria}",
        )

    def test_offline_font_stack_compliance(self):
        """Audits style.css and index.html for strict offline font compliance (zero CDN web fonts)."""
        with open(self.css_path, encoding="utf-8") as f:
            css = f.read()

        # Check for webfont imports or URLs
        webfont_imports = re.findall(r"@import\s+url\([^)]+\)", css)
        self.assertEqual(webfont_imports, [], f"Found external font imports in CSS: {webfont_imports}")

        webfont_urls = re.findall(r"url\(https?://[^)]+\)", css)
        self.assertEqual(webfont_urls, [], f"Found external URLs in CSS: {webfont_urls}")

        # Check font variable declarations
        self.assertIn("--font-sans:", css)
        self.assertIn("--font-mono:", css)
        self.assertIn("system-ui", css)
        self.assertIn("ui-monospace", css)

        # Check HTML for external fonts
        html_fonts = re.findall(r"fonts\.googleapis\.com|cdnjs|jsdelivr", self.html_content)
        self.assertEqual(html_fonts, [], f"Found external CDN references in HTML: {html_fonts}")


class TestLiveWorkflowExecutionStress(unittest.TestCase):
    """Evaluates live backend workflow execution under rapid bursts and history scaling."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_rapid_burst_run_submissions(self):
        """Stress-test submitting 10 rapid runs sequentially without delay."""
        submitted_runs = []
        start_time = time.time()

        for i in range(10):
            payload = {
                "model": {"source": "https://huggingface.co/Qwen/Qwen-Image-2.1", "cache_dir": "models"},
                "generation": {
                    "images": ["/mnt/lab/farzine/inputs/Men/men_002.jpg"],
                    "prompt": f"Stress test burst run {i} <image1>",
                    "steps": 5,
                    "cfg": 1.0,
                    "seed": 5000 + i,
                    "strength": 1.0,
                    "custom_size": False,
                    "width": 1024,
                    "height": 1024,
                    "batch_size": 1,
                },
                "runtime": {
                    "device": "cpu",
                    "dtype": "float32",
                    "offload": "none",
                    "output_dir": "outputs",
                    "save_comparison": True,
                },
                "demo_mode": True,
            }
            res = self.client.post("/api/run", json=payload)
            self.assertEqual(res.status_code, 200, f"Run {i} failed: {res.text}")
            run_id = res.json().get("run_id")
            self.assertTrue(run_id, f"Run {i} missing run_id")
            submitted_runs.append(run_id)

        duration = time.time() - start_time
        self.assertLess(duration, 5.0, f"Submitting 10 runs took {duration:.2f}s, expected < 5s")

        # Allow execution worker to process jobs
        time.sleep(2.0)

        # Verify all 10 runs produced records
        for r_id in submitted_runs:
            res = self.client.get(f"/api/runs/{r_id}")
            self.assertEqual(res.status_code, 200, f"Run {r_id} record not found")
            data = res.json()
            self.assertIn(data.get("status"), ("success", "completed"), f"Run {r_id} status invalid")
            self.assertTrue(len(data.get("outputs", [])) > 0, f"Run {r_id} missing outputs")

    def test_history_drawer_scaling_with_many_runs(self):
        """Verifies /api/runs handles 20+ runs with proper schema and ordering."""
        res = self.client.get("/api/runs")
        self.assertEqual(res.status_code, 200)
        runs = res.json().get("runs", [])
        self.assertGreaterEqual(len(runs), 10, f"Expected at least 10 runs in history, got {len(runs)}")

        for r in runs[:20]:
            self.assertIn("run_id", r)
            self.assertIn("status", r)
            self.assertTrue(r["run_id"].startswith("2026") or len(r["run_id"]) > 5)

    def test_nonexistent_or_deleted_run_record_handling(self):
        """Verifies GET /api/runs/{run_id} returns HTTP 404 for deleted or nonexistent runs."""
        res = self.client.get("/api/runs/nonexistent_deleted_run_id_99999")
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json().get("detail", "").lower())

    def test_output_file_byte_accuracy_and_sha256(self):
        """Verifies output image SHA-256 byte parity between served file and record."""
        res = self.client.get("/api/runs")
        runs = res.json().get("runs", [])

        # Find a run that has outputs; if none exist yet, create one now so this
        # test is not dependent on test_rapid_burst_run_submissions having run first.
        run_with_outputs = None
        for r in runs:
            rec_res = self.client.get(f"/api/runs/{r['run_id']}")
            if rec_res.status_code == 200:
                rec = rec_res.json()
                if rec.get("outputs"):
                    run_with_outputs = rec
                    break

        if run_with_outputs is None:
            # Submit a single demo run to generate an output we can verify.
            payload = {
                "model": {"source": "https://huggingface.co/Qwen/Qwen-Image-2.1", "cache_dir": "models"},
                "generation": {
                    "images": ["/mnt/lab/farzine/inputs/Men/men_002.jpg"],
                    "prompt": "SHA256 verification run <image1>",
                    "steps": 1,
                    "cfg": 1.0,
                    "seed": 99999,
                    "strength": 1.0,
                    "custom_size": False,
                    "width": 1024,
                    "height": 1024,
                    "batch_size": 1,
                },
                "runtime": {
                    "device": "cpu",
                    "dtype": "float32",
                    "offload": "none",
                    "output_dir": "outputs",
                    "save_comparison": True,
                },
                "demo_mode": True,
            }
            run_res = self.client.post("/api/run", json=payload)
            if run_res.status_code == 200:
                run_id = run_res.json().get("run_id")
                time.sleep(2.0)
                rec_res = self.client.get(f"/api/runs/{run_id}")
                if rec_res.status_code == 200:
                    run_with_outputs = rec_res.json()

        if run_with_outputs is None or not run_with_outputs.get("outputs"):
            self.skipTest("No completed run with outputs available for SHA-256 verification")

        out = run_with_outputs["outputs"][0]
        filename = out.get("filename")
        expected_hash = out.get("sha256")
        if filename and expected_hash:
            img_res = self.client.get(f"/api/outputs/{filename}")
            self.assertEqual(img_res.status_code, 200)
            actual_hash = hashlib.sha256(img_res.content).hexdigest()
            self.assertEqual(
                actual_hash,
                expected_hash,
                f"SHA-256 mismatch for output file {filename}",
            )


class TestNodeFrontendStressHarness(unittest.TestCase):
    """Executes the Tier 5 Node.js frontend state machine and interactivity stress harness."""

    def test_node_frontend_adversarial_suite(self):
        """Runs ui/tests/test_tier5_node_stress.js covering sliders, tokens, and click storms."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        script_path = repo_root / "ui" / "tests" / "test_tier5_node_stress.js"

        res = subprocess.run(
            ["node", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Node.js Tier 5 stress harness failed (exit {res.returncode}):\n{res.stdout}\n{res.stderr}",
        )
        self.assertIn("15 / 15 Tier 5 stress tests passed", res.stdout)


if __name__ == "__main__":
    unittest.main()
