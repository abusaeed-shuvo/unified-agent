import logging

from ua.config.logging import configure_logging, get_logger


def test_no_duplicate_handlers():
    configure_logging()
    configure_logging()
    assert len(logging.getLogger().handlers) == 1


def test_get_logger_returns_named_logger():
    logger = get_logger("some.module.name")
    assert logger.name == "some.module.name"


def test_level_override(monkeypatch):
    configure_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG
