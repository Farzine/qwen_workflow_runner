"""ui/tests/test_app.py

Unit tests for Web UI entrypoint, CLI argument parsing, port probe fallback, and configuration.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

UI_DIR = PROJECT_ROOT / "ui"
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from ui.app import (
    build_parser,
    configure_app,
    find_open_port,
    parse_args,
)
from ui.server import app


class TestFindOpenPort(unittest.TestCase):
    """Test automatic TCP port probing and conflict resolution."""

    def _get_ephemeral_port(self) -> int:
        """Helper to find an available port to use as a starting point."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_find_open_port_when_free(self):
        """When the requested port is free, find_open_port returns it directly."""
        port = self._get_ephemeral_port()
        found = find_open_port(host="127.0.0.1", start_port=port, max_tries=50)
        self.assertEqual(found, port)

    def test_find_open_port_increments_when_occupied(self):
        """When the requested port is occupied, find_open_port increments to the next free port."""
        port = self._get_ephemeral_port()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        try:
            found = find_open_port(host="127.0.0.1", start_port=port, max_tries=50)
            self.assertGreater(found, port)
        finally:
            sock.close()

    def test_find_open_port_multiple_occupied(self):
        """When multiple sequential ports are occupied, find_open_port probes past all of them."""
        port = self._get_ephemeral_port()
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock1.bind(("127.0.0.1", port))
        sock1.listen(1)

        sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock2.bind(("127.0.0.1", port + 1))
            sock2.listen(1)
            two_bound = True
        except OSError:
            two_bound = False

        try:
            found = find_open_port(host="127.0.0.1", start_port=port, max_tries=50)
            if two_bound:
                self.assertGreaterEqual(found, port + 2)
            else:
                self.assertGreaterEqual(found, port + 1)
        finally:
            sock1.close()
            sock2.close()

    def test_find_open_port_exhaustion_raises(self):
        """When all probed ports are occupied within max_tries, RuntimeError is raised."""
        port = self._get_ephemeral_port()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                find_open_port(host="127.0.0.1", start_port=port, max_tries=1)
            self.assertIn("Could not find an available port", str(ctx.exception))
        finally:
            sock.close()


class TestCLIArgumentParsing(unittest.TestCase):
    """Test CLI argument parsing and default configurations."""

    def test_default_arguments(self):
        """Default arguments match specification."""
        args = parse_args([])
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 7878)
        self.assertFalse(args.demo)
        self.assertIsNone(args.inputs_dir)
        self.assertIsNone(args.models_dir)
        self.assertIsNone(args.outputs_dir)
        self.assertFalse(args.reload)

    def test_custom_host_and_port(self):
        """Custom --host and --port flags are parsed correctly."""
        args = parse_args(["--host", "127.0.0.1", "--port", "9090"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 9090)

    def test_demo_flag(self):
        """The --demo flag enables demo mode."""
        args = parse_args(["--demo"])
        self.assertTrue(args.demo)

    def test_reload_flag(self):
        """The --reload flag enables development reload."""
        args = parse_args(["--reload"])
        self.assertTrue(args.reload)

    def test_directories_overrides(self):
        """Custom directory paths are parsed cleanly."""
        args = parse_args([
            "--inputs-dir", "/tmp/custom_inputs",
            "--models-dir", "/tmp/custom_models",
            "--outputs-dir", "/tmp/custom_outputs",
        ])
        self.assertEqual(args.inputs_dir, "/tmp/custom_inputs")
        self.assertEqual(args.models_dir, "/tmp/custom_models")
        self.assertEqual(args.outputs_dir, "/tmp/custom_outputs")

    def test_all_flags_combined(self):
        """All CLI arguments work harmoniously when provided together."""
        args = parse_args([
            "--host", "192.168.1.100",
            "--port", "8888",
            "--demo",
            "--reload",
            "--inputs-dir", "/data/inputs",
            "--models-dir", "/data/models",
            "--outputs-dir", "/data/outputs",
        ])
        self.assertEqual(args.host, "192.168.1.100")
        self.assertEqual(args.port, 8888)
        self.assertTrue(args.demo)
        self.assertTrue(args.reload)
        self.assertEqual(args.inputs_dir, "/data/inputs")
        self.assertEqual(args.models_dir, "/data/models")
        self.assertEqual(args.outputs_dir, "/data/outputs")


class TestAppConfiguration(unittest.TestCase):
    """Test configure_app propagation to os.environ and FastAPI app.state."""

    def setUp(self):
        self._saved_env = {
            "DEMO_MODE": os.environ.get("DEMO_MODE"),
            "INPUTS_DIR": os.environ.get("INPUTS_DIR"),
            "MODELS_DIR": os.environ.get("MODELS_DIR"),
            "OUTPUTS_DIR": os.environ.get("OUTPUTS_DIR"),
        }

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_configure_app_demo_mode(self):
        """configure_app sets DEMO_MODE in environment and app.state."""
        args = parse_args(["--demo"])
        configure_app(args)
        self.assertEqual(os.environ.get("DEMO_MODE"), "1")
        self.assertTrue(getattr(app.state, "demo_mode", False))

    def test_configure_app_directories(self):
        """configure_app sets environment and state for directory overrides."""
        args = parse_args([
            "--inputs-dir", "/tmp/test_inputs",
            "--models-dir", "/tmp/test_models",
            "--outputs-dir", "/tmp/test_outputs",
        ])
        configure_app(args)
        self.assertEqual(os.environ.get("INPUTS_DIR"), str(Path("/tmp/test_inputs").resolve()))
        self.assertEqual(getattr(app.state, "inputs_dir", None), str(Path("/tmp/test_inputs").resolve()))

        self.assertEqual(os.environ.get("MODELS_DIR"), str(Path("/tmp/test_models").resolve()))
        self.assertEqual(getattr(app.state, "models_dir", None), str(Path("/tmp/test_models").resolve()))

        self.assertEqual(os.environ.get("OUTPUTS_DIR"), str(Path("/tmp/test_outputs").resolve()))
        self.assertEqual(getattr(app.state, "outputs_dir", None), str(Path("/tmp/test_outputs").resolve()))


class TestCLIHelpAndExecution(unittest.TestCase):
    """Test --help formatting and subprocess execution from both root and ui/."""

    def test_help_text_content(self):
        """Parser help text documents all flags with defaults."""
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("--host", help_text)
        self.assertIn("--port", help_text)
        self.assertIn("--demo", help_text)
        self.assertIn("--inputs-dir", help_text)
        self.assertIn("--models-dir", help_text)
        self.assertIn("--outputs-dir", help_text)
        self.assertIn("--reload", help_text)
        self.assertIn("7878", help_text)
        self.assertIn("0.0.0.0", help_text)

    def test_subprocess_help_from_project_root(self):
        """Running `python ui/app.py --help` from project root exits with code 0."""
        proc = subprocess.run(
            [sys.executable, "ui/app.py", "--help"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage: app.py", proc.stdout)
        self.assertIn("--port PORT", proc.stdout)
        self.assertIn("--demo", proc.stdout)

    def test_subprocess_help_from_ui_dir(self):
        """Running `python app.py --help` from ui/ directory exits with code 0."""
        proc = subprocess.run(
            [sys.executable, "app.py", "--help"],
            cwd=str(UI_DIR),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage: app.py", proc.stdout)
        self.assertIn("--port PORT", proc.stdout)
        self.assertIn("--demo", proc.stdout)


class TestMainExecution(unittest.TestCase):
    """Test main() startup flow, uvicorn invocation, and fallback logging."""

    from unittest.mock import patch
    import io

    def test_main_with_busy_port_fallback(self):
        """When requested port is busy, main() logs fallback and launches on open port."""
        from unittest.mock import patch
        import io
        from ui.app import main

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            busy_port = s.getsockname()[1]
            s.listen(1)

            stdout_buf = io.StringIO()
            with patch("sys.stdout", stdout_buf):
                with patch("uvicorn.run") as mock_uvicorn:
                    main(["--host", "127.0.0.1", "--port", str(busy_port), "--demo"])

                    mock_uvicorn.assert_called_once()
                    called_args, called_kwargs = mock_uvicorn.call_args
                    # Port passed to uvicorn must be an open port > busy_port
                    self.assertGreater(called_kwargs["port"], busy_port)
                    self.assertEqual(called_kwargs["host"], "127.0.0.1")
                    self.assertFalse(called_kwargs["reload"])

            out = stdout_buf.getvalue()
            self.assertIn(f"[INFO] Port {busy_port} is already in use. Automatically falling back to open port:", out)
            self.assertIn("Starting Qwen Image 2.1 Web UI", out)

    def test_main_with_reload_flag(self):
        """When --reload is provided, main() passes app import string and reload=True."""
        from unittest.mock import patch
        import io
        from ui.app import main

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            with patch("uvicorn.run") as mock_uvicorn:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", 0))
                    free_port = s.getsockname()[1]

                main(["--host", "127.0.0.1", "--port", str(free_port), "--reload"])

                mock_uvicorn.assert_called_once()
                called_args, called_kwargs = mock_uvicorn.call_args
                self.assertEqual(called_args[0], "ui.server:app")
                self.assertTrue(called_kwargs["reload"])
                self.assertEqual(called_kwargs["port"], free_port)


if __name__ == "__main__":
    unittest.main()

