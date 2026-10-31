"""Logging setup that runs with or without the internal HCP library.

Inside the company network the HCP logger owns logging and reads its own
logger.yml. Outside it, logger.yml at the repo root is applied with the
standard library so the same code runs everywhere (same as pr-batch).
"""

import logging
import logging.config
import re
from pathlib import Path

import yaml

from core.config import ROOT
from core.request_context import install_log_field

LOGGER_CONFIG = ROOT / "logger.yml"
# our keys and theirs (pas_ ours, exe_ executor, bat_ pr-batch), and an
# X-Api-Key header written out
SECRET = re.compile(
    r"\b(?:pas|exe|bat)_(?:live|dev|test)_[A-Za-z0-9_\-]+"
    r"|(?i:x-api-key)[\"']?\s*[:=]\s*[\"']?[^\s,\"'}]+"
)


class SecretFilter(logging.Filter):
    """Masks API keys in every record before a handler writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = SECRET.sub("***", message)
        if masked != message:
            record.msg, record.args = masked, None
        return True


def configure_logging(path: Path = LOGGER_CONFIG) -> None:
    try:
        from hcp.framework.logger import (  # ty: ignore[unresolved-import]
            init_logger,
        )
    except ImportError:
        apply_logger_config(path)
    else:
        init_logger()
    install_log_field()
    mask_secrets()


def mask_secrets() -> None:
    """Puts ``SecretFilter`` on every handler configured so far."""
    secret_filter = SecretFilter()
    loggers = [logging.getLogger()] + [
        logger
        for logger in logging.root.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    ]
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(f, SecretFilter) for f in handler.filters):
                handler.addFilter(secret_filter)


def apply_logger_config(path: Path) -> None:
    if not path.is_file():
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
        )
        return
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    # Loggers created at import time (core.*, uvicorn.*) must stay enabled.
    config.setdefault("disable_existing_loggers", False)
    logging.config.dictConfig(config)
