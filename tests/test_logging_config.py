"""Structured logging must actually preserve the fields call sites pass.

Regression for 2026-09-04: nothing configured logging, so every
`logger.warning("event", extra={...})` in the codebase reached stderr as the
event name alone — ticket_id, error_type and the rest silently dropped by
Python's last-resort handler. LOG_LEVEL was read from env and never applied,
and `python-json-logger` was pinned but imported by nothing.
"""
from __future__ import annotations

import io
import json
import logging

import pytest

from src.logging_config import configure_logging


@pytest.fixture(autouse=True)
def _restore_root_logging():
    """Configuring root logging is global; put it back after each test."""
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def _emit(level="INFO", **extra):
    buf = io.StringIO()
    configure_logging(level=level, log_file="", stream=buf)
    logging.getLogger("src.generate").warning("generate.failure", extra=extra)
    return buf.getvalue()


def test_extra_fields_survive_into_the_log_line():
    out = _emit(ticket_id="VAL-0042", attempt=1, error_type="ReadTimeout")
    rec = json.loads(out.strip())
    assert rec["message"] == "generate.failure"
    assert rec["ticket_id"] == "VAL-0042"
    assert rec["attempt"] == 1
    assert rec["error_type"] == "ReadTimeout"


def test_output_is_one_json_object_per_line():
    buf = io.StringIO()
    configure_logging(level="INFO", log_file="", stream=buf)
    log = logging.getLogger("src.route")
    log.warning("first", extra={"ticket_id": "A"})
    log.warning("second", extra={"ticket_id": "B"})
    lines = buf.getvalue().strip().splitlines()
    assert [json.loads(x)["ticket_id"] for x in lines] == ["A", "B"]


def test_log_level_from_argument_is_applied():
    """LOG_LEVEL was read from config and never used before this module."""
    buf = io.StringIO()
    configure_logging(level="ERROR", log_file="", stream=buf)
    log = logging.getLogger("src.classify")
    log.warning("suppressed")
    log.error("emitted")
    messages = [json.loads(x)["message"] for x in buf.getvalue().strip().splitlines()]
    assert messages == ["emitted"]


def test_configure_is_idempotent():
    """A second call must replace our handler, not stack another one — an
    unattended run that configured twice would double every line."""
    buf = io.StringIO()
    for _ in range(3):
        configure_logging(level="INFO", log_file="", stream=buf)
    logging.getLogger("src.retrieve").warning("once", extra={"ticket_id": "T"})
    assert len(buf.getvalue().strip().splitlines()) == 1


def test_optional_log_file_receives_the_same_json(tmp_path):
    """A9: an unattended run has nobody watching stderr."""
    target = tmp_path / "logs" / "run.jsonl"
    buf = io.StringIO()
    configure_logging(level="INFO", log_file=str(target), stream=buf)
    logging.getLogger("src.guardrails").warning("blocked", extra={"ticket_id": "T-9"})
    logging.shutdown()
    rec = json.loads(target.read_text().strip())
    assert rec["ticket_id"] == "T-9"
    assert rec["message"] == "blocked"


def test_library_modules_do_not_configure_logging():
    """Entry points own logging configuration. A library that reconfigures
    root logging on import surprises whoever imports it."""
    import ast
    import pathlib

    def _calls_it(path: pathlib.Path) -> bool:
        # Parse rather than substring-match: config.py mentions
        # configure_logging() in a comment, and a grep-style check reports
        # that as a call. (It did, on the first version of this test.)
        tree = ast.parse(path.read_text())
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "configure_logging"
            for node in ast.walk(tree)
        )

    offenders = [
        p.name
        for p in pathlib.Path("src").glob("*.py")
        if p.name not in {"logging_config.py", "index_docs.py"} and _calls_it(p)
    ]
    assert not offenders, f"library modules calling configure_logging(): {offenders}"
