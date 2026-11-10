"""One-line logging setup. Level via REMO_LOG_LEVEL (default INFO)."""
from __future__ import annotations

import logging
import os


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(os.environ.get("REMO_LOG_LEVEL", "INFO").upper())
    return logger
