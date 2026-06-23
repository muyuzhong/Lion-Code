import logging


def get_logger(name: str) -> logging.Logger:
    """Thin wrapper: named logger; no handler imposed (harness configures)."""
    if not isinstance(name, str):
        raise TypeError("name must be str")
    return logging.getLogger("nanoagent" if name == "" else f"nanoagent.{name}")
