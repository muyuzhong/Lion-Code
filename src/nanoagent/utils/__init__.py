"""nanoagent.utils — foundation: ids, logging. Depends on nothing."""

from nanoagent.utils.ids import new_id
from nanoagent.utils.logging import get_logger

__all__ = ["new_id", "get_logger"]
