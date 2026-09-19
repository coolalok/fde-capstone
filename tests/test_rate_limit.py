"""Adaptive pacing: idle until the provider refuses, then spacing that relaxes.

The design decision under test is that a healthy run pays nothing. A fixed delay
between calls would slow every run to guard against a limit we may not be near —
the 13 and 17 Sep free-tier failures were upstream capacity, which self-pacing
would not have avoided.

No sleeping and no network: the clock and time.sleep are fakes.
"""
from __future__ import annotations

import pytest

import src.rate_limit as rate_limit


class FakeClock:
    """Monotonic time that only moves when a sleep asks it to."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(rate_limit.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(rate_limit.time, "sleep", fake.sleep)
    rate_limit.reset()
    yield fake
    rate_limit.reset()


class RateLimitError(Exception):
    """Stands in for openai.RateLimitError, which is matched by class name."""

    def __init__(self, retry_after=None):
        super().__init__("429 rate limited")
        if retry_after is not None:
            self.response = type("R", (), {"headers": {"retry-after": retry_after},
                                           "status_code": 429})()


def test_a_healthy_run_never_waits(clock):
    """The whole point: no cost until the provider says no."""
    for _ in range(5):
        assert rate_limit.guarded(lambda: "ok") == "ok"
    assert clock.slept == []
    assert rate_limit.state()["interval_seconds"] == 0.0


def test_pacing_starts_only_after_a_rate_limit(clock):
    with pytest.raises(RateLimitError):
        rate_limit.guarded(lambda: (_ for _ in ()).throw(RateLimitError()))
    assert rate_limit.state()["interval_seconds"] == 2.0

    rate_limit.guarded(lambda: "ok")
    assert clock.slept == [2.0], "the next call waits the engaged interval"


def test_other_errors_do_not_engage_pacing(clock):
    """A malformed envelope or a timeout is not a rate limit."""
    with pytest.raises(ValueError):
        rate_limit.guarded(lambda: (_ for _ in ()).throw(ValueError("no choices")))
    assert rate_limit.state()["interval_seconds"] == 0.0
    rate_limit.guarded(lambda: "ok")
    assert clock.slept == []


def test_repeated_rate_limits_space_calls_further_apart(clock):
    for _ in range(3):
        with pytest.raises(RateLimitError):
            rate_limit.guarded(lambda: (_ for _ in ()).throw(RateLimitError()))
    assert rate_limit.state()["interval_seconds"] == 8.0  # 2 -> 4 -> 8


def test_the_interval_is_capped_so_a_run_still_terminates(clock):
    """A9: an unattended run must not pace itself into never finishing."""
    from src.config import MODEL_RATE_LIMIT_MAX_SECONDS

    for _ in range(12):
        with pytest.raises(RateLimitError):
            rate_limit.guarded(lambda: (_ for _ in ()).throw(RateLimitError()))
    assert rate_limit.state()["interval_seconds"] == MODEL_RATE_LIMIT_MAX_SECONDS


def test_the_providers_own_retry_after_wins(clock):
    """It knows its limit better than our doubling does."""
    with pytest.raises(RateLimitError):
        rate_limit.guarded(lambda: (_ for _ in ()).throw(RateLimitError(retry_after="7")))
    assert rate_limit.state()["interval_seconds"] == 7.0


def test_spacing_relaxes_after_calls_succeed_again(clock):
    with pytest.raises(RateLimitError):
        rate_limit.guarded(lambda: (_ for _ in ()).throw(RateLimitError(retry_after="8")))
    assert rate_limit.state()["interval_seconds"] == 8.0

    for _ in range(3):
        rate_limit.guarded(lambda: "ok")
    assert rate_limit.state()["interval_seconds"] == 4.0, "halves after three successes"

    for _ in range(6):
        rate_limit.guarded(lambda: "ok")
    assert rate_limit.state()["interval_seconds"] == 1.0

    for _ in range(3):
        rate_limit.guarded(lambda: "ok")
    assert rate_limit.state()["interval_seconds"] == 0.0, "back to no pacing"


def test_time_already_spent_counts_towards_the_interval(clock):
    """A slow call has already done the waiting; do not wait it twice."""
    with pytest.raises(RateLimitError):
        rate_limit.guarded(lambda: (_ for _ in ()).throw(RateLimitError(retry_after="10")))
    clock.advance(6.0)  # the failed call's own retries took six seconds
    rate_limit.guarded(lambda: "ok")
    assert clock.slept == [4.0]
