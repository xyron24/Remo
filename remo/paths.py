"""Filesystem locations. User memories live outside the repo (local-first)."""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """The Remo/ project directory (parent of the `remo` package)."""
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """User data dir for notes/voices; created on first use. Never in the repo."""
    path = Path(os.environ.get("REMO_DATA_DIR", Path.home() / ".remo"))
    path.mkdir(parents=True, exist_ok=True)
    return path
