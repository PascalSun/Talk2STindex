"""Logging utilities for Talk2STIndex using loguru."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from loguru import logger


class _InterceptHandler(logging.Handler):
    """Redirect stdlib logging records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_string: Optional[str] = None,
) -> None:
    """Setup logging configuration using loguru."""
    logger.remove()

    if format_string is None:
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )

    logger.add(
        sys.stderr,
        format=format_string,
        level=level.upper(),
        colorize=True,
    )

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            format=format_string,
            level=level.upper(),
            colorize=False,
            rotation="10 MB",
        )

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)


def get_logger(name: str) -> logger.__class__:
    """Get a loguru logger bound to a module name."""
    return logger.bind(name=name)
