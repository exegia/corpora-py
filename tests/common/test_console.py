"""Logger configuration: no duplicate handlers, propagation disabled."""

import logging

from common.utils.console import configure_logger, logger


def _isolated(name: str) -> logging.Logger:
    """A logger whose ancestor chain reports no handlers.

    Under pytest the root logger carries capture handlers, which makes
    ``hasHandlers()`` true for every logger and suppresses handler
    installation -- detach from the hierarchy to exercise the real branch.
    """
    inst = logging.getLogger(name)
    inst.handlers.clear()
    inst.parent = None
    return inst


def test_configure_logger_adds_handler_and_disables_propagation():
    inst = _isolated("test-console-unique-1")
    inst.setLevel(logging.DEBUG)
    configure_logger(inst)
    assert len(inst.handlers) == 1
    assert inst.propagate is False
    assert inst.handlers[0].level == logging.DEBUG


def test_configure_logger_idempotent():
    inst = _isolated("test-console-unique-2")
    configure_logger(inst)
    configure_logger(inst)
    assert len(inst.handlers) == 1


def test_logger_sets_level_and_returns_same_instance():
    a = logger("test-console-unique-3", level=logging.WARNING)
    b = logger("test-console-unique-3")
    assert a is b
    assert a.level == logging.INFO  # second call's default level wins
    assert a.propagate is False
