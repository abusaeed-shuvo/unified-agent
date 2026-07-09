import logging
from typing import Optional

from ua.config.settings import get_settings


def configure_logging(level: Optional[str] = None) -> None:
    """Configure the root logger once. Idempotent — safe to call multiple times."""
    # Determine the log level
    if level is None:
        level = get_settings().log_level

    # Get the root logger
    root_logger = logging.getLogger()

    # Set the log level
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Idempotency: clear existing handlers to ensure exactly 1 handler
    root_logger.handlers.clear()

    # Create a single StreamHandler with the specified format
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)

    # Add the handler to the root logger
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Does not configure logging itself — call configure_logging() first."""
    return logging.getLogger(name)
