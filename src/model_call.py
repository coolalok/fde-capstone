"""model_call.py — put a wall-clock deadline on one provider call (D-13).

Satisfies: NFR-03 (a misbehaving provider must not end a run), A9 (the
           evaluation set is processed unattended in one command),
           A11 (degrade rather than hang).

Why this exists: MODEL_TIMEOUT_SECONDS reaches httpx, whose read timeout is the
maximum gap BETWEEN bytes, not a limit on the request. OpenRouter sends periodic
keep-alive comments on a waiting request, and each one resets that clock, so a
call can wait forever while the timeout never fires. It did: on 20 Sep a
12-ticket run (llama-3.1-8b-instruct + nemotron-3-super-120b:free) stopped after
ticket 8 with a connection open and silent for over seven minutes, while the
same endpoint answered a probe in 0.8 s. The run had to be killed, which is A9
failing.

The deadline is enforced by the CALLER, not the call: the work runs in a daemon
thread and the caller waits at most ``MODEL_CALL_DEADLINE_SECONDS`` for it. A
hung call is abandoned rather than cancelled — Python cannot interrupt a thread
blocked in a socket read — so the socket may stay open until the provider drops
it. That is a leaked socket, not a stalled run: the thread is a daemon, so it
never holds up interpreter exit, and every caller already has an A11 path for a
raised exception (classifier fallback, unknown_fallback, guardrail fail-safe).

Signals were the obvious alternative and do not work here: signal.alarm only
fires on the main thread, and since D-12 the guardrails call the provider from a
thread pool.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, TypeVar

from src.config import MODEL_CALL_DEADLINE_SECONDS

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ModelCallTimeout(TimeoutError):
    """A provider call outlived MODEL_CALL_DEADLINE_SECONDS and was abandoned."""


def bounded(call: Callable[[], T], *, seconds: float = MODEL_CALL_DEADLINE_SECONDS,
            stage: str = "") -> T:
    """Run ``call`` with a hard deadline. Re-raises whatever it raises.

    Raises ModelCallTimeout when the deadline passes with the call still
    running. The call itself keeps running in its daemon thread until the
    provider answers or the process exits; its result is discarded.
    """
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = call()
        except BaseException as exc:  # noqa: BLE001 — re-raised on the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True,
                              name=f"model-call{'-' + stage if stage else ''}")
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        logger.warning(
            "model_call.deadline_exceeded",
            extra={"stage": stage, "deadline_seconds": seconds},
        )
        raise ModelCallTimeout(
            f"provider did not answer within {seconds:g}s and the call was "
            f"abandoned (stage={stage or 'unknown'})"
        )
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]
