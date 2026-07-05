"""Structured logging setup (docs/07).

One JSON log stream for the whole process — our own events *and* Scrapy/Twisted's
stdlib logs are routed through the same structlog ``ProcessorFormatter``, so every
line is JSON and carries any bound context (notably ``run_id``). Bind per-run
context with :func:`bind_run` and read loggers via :func:`get_logger`.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterator

# Processors shared by structlog-native and foreign (stdlib) log records.
_SHARED_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]


def configure_logging(level: int = logging.INFO) -> None:
    """Install a JSON log handler on the root logger and configure structlog.

    Idempotent: replaces existing root handlers so repeated calls (e.g. per crawl)
    do not stack duplicate output.
    """
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger


@contextmanager
def bind_run(**context: Any) -> Iterator[None]:
    """Bind key/values (e.g. ``run_id=...``) to all logs emitted inside the block."""
    structlog.contextvars.bind_contextvars(**context)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars(*context)
