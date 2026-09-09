"""Structured logging setup. Call once from an entry point.

Every module in this project logs with ``logger.warning("event.name",
extra={...})`` — the structured style capstone-component-impl asks for. But
nothing ever configured a handler, so those records fell through to Python's
last-resort handler: bare stderr, WARNING and above only, and **every
`extra` field silently discarded**. A generation failure logged as

    logger.warning("generate.grounded_branch.failure",
                   extra={"ticket_id": ..., "attempt": ..., "error": ...})

reached the terminal as the four words ``generate.grounded_branch.failure``.
Found 2026-09-04 while reading the stderr of a validation sweep.

`python-json-logger` was already pinned in requirements.txt and imported by
nothing. It merges `extra` keys into the emitted JSON object automatically,
so wiring it up is all that was missing — no call site changes.

Configuration is deliberately NOT done at import of the library modules. A
library that reconfigures root logging surprises whoever imports it; entry
points own that decision. Call `configure_logging()` from harnesses, scripts
and the API, not from `src/classify.py`.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from pythonjsonlogger import jsonlogger

from src.config import LOG_FILE, LOG_LEVEL

# Marks our handler so repeated calls replace rather than stack. An unattended
# run that configured twice would emit every line twice, which corrupts any
# log-derived count.
_HANDLER_NAME = "capstone-json"

# LogRecord attributes worth keeping on every line. Anything passed via
# `extra=` is merged in on top of these by the formatter.
_FORMAT = " ".join(
    f"%({field})s"
    for field in ("asctime", "levelname", "name", "message")
)


def configure_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    stream=None,
) -> logging.Logger:
    """Install a JSON handler on the root logger. Idempotent.

    Args:
        level: log level name; defaults to LOG_LEVEL from config (env-driven).
        log_file: optional path to also write JSON lines to. Defaults to
            LOG_FILE from config. Useful for an unattended run (A9) where
            stderr is not being watched.
        stream: stream for the console handler; defaults to stderr.

    Returns:
        The configured root logger.
    """
    root = logging.getLogger()
    resolved = (level or LOG_LEVEL).upper()
    root.setLevel(resolved)

    # Drop any handler we installed previously so a second call reconfigures
    # instead of duplicating output.
    for existing in [h for h in root.handlers if getattr(h, "name", None) == _HANDLER_NAME]:
        root.removeHandler(existing)

    formatter = jsonlogger.JsonFormatter(_FORMAT)

    console = logging.StreamHandler(stream or sys.stderr)
    console.name = _HANDLER_NAME
    console.setFormatter(formatter)
    root.addHandler(console)

    # Third-party loggers, pinned deliberately rather than inherited.
    #
    # openai._base_client emits "Retrying request ... in 0.8 seconds" at INFO.
    # That line is how you tell a rate-limited run from a slow one, so it must
    # survive a quieter LOG_LEVEL — a gate run set to WARNING would otherwise
    # keep the failures and lose every sign of why they happened.
    logging.getLogger("openai._base_client").setLevel(logging.INFO)
    # Chroma's telemetry emits an ERROR per call about its own broken
    # analytics ("capture() takes 1 positional argument"). Not our failure,
    # and it drowns real errors in an unattended run.
    logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

    target = log_file if log_file is not None else LOG_FILE
    if target:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(target, encoding="utf-8")
        file_handler.name = _HANDLER_NAME
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return root
