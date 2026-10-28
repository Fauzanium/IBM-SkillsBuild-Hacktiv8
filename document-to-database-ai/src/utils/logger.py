"""
utils/logger.py
────────────────
Structured JSON logging setup using structlog.

All modules call `get_logger(__name__)` — never configure logging directly.
Log level is read from settings so it can be changed via environment variable.
"""

import logging
import structlog
from src.config import settings


def setup_logging() -> None:
    """
    Configure structlog + stdlib logging.
    Call once at application startup (main.py does this).
    """
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),   # switch to JSONRenderer() in production
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a standard library logger — structlog wraps it transparently."""
    return logging.getLogger(name)
