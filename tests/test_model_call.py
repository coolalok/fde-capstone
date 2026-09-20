"""T-model_call: the wall-clock bound on one provider call (D-13).

The failure this closes: MODEL_TIMEOUT_SECONDS is an httpx read timeout, so a
provider that keeps sending keep-alive bytes resets it forever and the call
never ends. A9 requires the run to finish unattended, so the CALLER stops
waiting rather than trusting the provider's stream.
"""
from __future__ import annotations

import threading
import time

import pytest

from src.model_call import ModelCallTimeout, bounded


def test_a_normal_call_returns_its_value():
    assert bounded(lambda: "verdict", seconds=5) == "verdict"


def test_the_calls_exception_reaches_the_caller():
    def explode():
        raise RuntimeError("provider said no")

    with pytest.raises(RuntimeError, match="provider said no"):
        bounded(explode, seconds=5)


def test_a_call_that_never_answers_is_abandoned_at_the_deadline():
    """The point of D-13: the caller returns even though the call does not."""
    release = threading.Event()
    try:
        started = time.monotonic()
        with pytest.raises(ModelCallTimeout, match="abandoned"):
            bounded(lambda: release.wait(30), seconds=0.2, stage="guardrail")
        # Promptly, not after the call finishes.
        assert time.monotonic() - started < 5
    finally:
        release.set()


def test_the_abandoned_call_cannot_hold_up_the_process():
    """A9: a hung call must not keep the interpreter alive at exit."""
    release = threading.Event()
    before = {t.name for t in threading.enumerate()}
    try:
        with pytest.raises(ModelCallTimeout):
            bounded(lambda: release.wait(30), seconds=0.2)
        left = [t for t in threading.enumerate() if t.name not in before]
        assert left and all(t.daemon for t in left)
    finally:
        release.set()


def test_the_deadline_does_not_fire_early_on_a_slow_but_answering_call():
    assert bounded(lambda: (time.sleep(0.3), "late")[1], seconds=5) == "late"
