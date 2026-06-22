from nanoagent.utils import get_logger


def test_get_logger_returns_package_root_for_empty_name():
    logger = get_logger("")

    assert logger.name == "nanoagent"


def test_get_logger_prefixes_child_names():
    logger = get_logger("agent.loop")

    assert logger.name == "nanoagent.agent.loop"
