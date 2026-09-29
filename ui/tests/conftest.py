"""Keep test writes out of application storage and detect regressions."""

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_runtime_storage(tmp_path_factory):
    root = Path(__file__).resolve().parents[2]

    def snapshot():
        files = {}
        for directory in ("outputs", "inputs", "models", ".cache"):
            for path in (root / directory).rglob("*"):
                if path.is_file() or path.is_symlink():
                    stat = path.lstat()
                    files[str(path.relative_to(root))] = (stat.st_mode, stat.st_size, stat.st_mtime_ns)
        return files

    before = snapshot()
    with patch("ui.server.THUMBNAILS_DIR", tmp_path_factory.mktemp("ui-thumbnails")):
        yield
    after = snapshot()
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    assert not changed, f"UI tests changed repository runtime assets: {changed}"
