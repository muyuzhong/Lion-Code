import logging


def get_logger(name: str) -> logging.Logger:
    """Thin wrapper: named logger; no handler imposed (harness configures)."""
    return logging.getLogger(f"nanoagent.{name}")
