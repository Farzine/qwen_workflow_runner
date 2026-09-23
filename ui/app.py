#!/usr/bin/env python3
"""ui/app.py

Single-command entrypoint and CLI runner for the Qwen Image 2.1 Workflow Web UI.
Supports automatic open port probe fallback, environment overrides, and Uvicorn launch.

Usage:
    python app.py
    python ui/app.py
    python ui/app.py --port 7878 --demo
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import sys
from typing import List, Optional

# Ensure both project root and ui/ directory are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

UI_DIR = Path(__file__).resolve().parent
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

# Import FastAPI app from server
from ui.server import app


def find_open_port(host: str = "0.0.0.0", start_port: int = 7878, max_tries: int = 100) -> int:
    """Find an available TCP port starting from start_port up to start_port + max_tries.

    If start_port is available, returns start_port.
    If occupied, probes subsequent ports sequentially until an open one is found.
    Raises RuntimeError if no open port is found within max_tries attempts.
    """
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"Could not find an available port on {host} between {start_port} and {start_port + max_tries - 1}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for the Web UI server."""
    parser = argparse.ArgumentParser(
        description="Qwen Image 2.1 Workflow Runner — Modern Web UI Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host IP address to bind to.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7878,
        help="Port number to listen on.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help="Run in demo mode with synthetic backend for fast mock execution.",
    )
    parser.add_argument(
        "--inputs-dir",
        type=str,
        default=None,
        help="Custom inputs directory path containing reference images.",
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default=None,
        help="Custom models directory path for cached model weights and uploads.",
    )
    parser.add_argument(
        "--outputs-dir",
        type=str,
        default=None,
        help="Custom outputs directory path for generated images and run records.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload for local development.",
    )
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = build_parser()
    return parser.parse_args(argv)


def configure_app(args: argparse.Namespace) -> None:
    """Apply CLI argument overrides to environment variables and app state."""
    demo_enabled = args.demo or os.environ.get("DEMO_MODE", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    app.state.demo_mode = demo_enabled
    if args.demo:
        os.environ["DEMO_MODE"] = "1"
    if args.inputs_dir:
        resolved_inputs = str(Path(args.inputs_dir).resolve())
        os.environ["INPUTS_DIR"] = resolved_inputs
        app.state.inputs_dir = resolved_inputs
    if args.models_dir:
        resolved_models = str(Path(args.models_dir).resolve())
        os.environ["MODELS_DIR"] = resolved_models
        app.state.models_dir = resolved_models
    if args.outputs_dir:
        resolved_outputs = str(Path(args.outputs_dir).resolve())
        os.environ["OUTPUTS_DIR"] = resolved_outputs
        app.state.outputs_dir = resolved_outputs


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entrypoint: parse args, probe open port, configure app, and launch uvicorn."""
    import uvicorn

    args = parse_args(argv)
    configure_app(args)

    target_port = args.port
    open_port = find_open_port(host=args.host, start_port=target_port)
    if open_port != target_port:
        print(
            f"[INFO] Port {target_port} is already in use. Automatically falling back to open port: {open_port}",
            flush=True,
        )

    print(
        f"[INFO] Starting Qwen Image 2.1 Web UI on http://{args.host}:{open_port} (demo={args.demo})",
        flush=True,
    )

    # When reload is enabled, pass import string; otherwise pass app directly
    app_target = "ui.server:app" if args.reload else app
    uvicorn.run(
        app_target,
        host=args.host,
        port=open_port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
