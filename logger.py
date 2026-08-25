"""Logging setup.

Author: Sagar Saitwal
"""

import logging
from pathlib import Path


def configure_logging(log_dir: str) -> logging.Logger:
    """Configure a file logger once and return the application logger."""
    logger = logging.getLogger("domain_inventory")
    if logger.handlers:
        return logger
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(Path(log_dir) / "inventory.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger
