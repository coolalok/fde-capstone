"""Serve /metrics from a fake run, so the dashboard can be shown without a provider.

    python -m scripts.demo_metrics

Runs the real pipeline path (process_ticket, guardrails, routing, decision log)
with the smoke test's fake model client, one ticket every two seconds, and serves
Prometheus metrics on :8001 throughout. No network, no API credit, no rate limit
— which is what makes it usable in a demonstration or on a machine with no keys.

For real numbers, run the harness itself with --metrics-port 8001. See
docs/monitoring.md.
"""
from __future__ import annotations

import time

import evaluation.harness as harness
from src.logging_config import configure_logging
from src.metrics import start_metrics_server
from src.schema import Passage
from tests.test_harness_smoke import SMOKE_TICKETS, FakeModelClient

PORT = 8001
TICKETS = 30
GAP_SECONDS = 2.0


def main() -> int:
    configure_logging()
    # Keep the demo off Chroma as well as off the network.
    harness.retrieve = lambda query, **kw: [
        Passage(doc_id="DOC-AUTH-001", score=0.7, title="Auth",
                category="authentication", text="Security page shows the lock.")
    ]
    start_metrics_server(PORT)
    print(f"[demo] metrics on http://localhost:{PORT}/metrics — ctrl-c to stop", flush=True)
    for i in range(1, TICKETS + 1):
        row = harness.process_ticket(SMOKE_TICKETS[i % len(SMOKE_TICKETS)],
                                     call_model=FakeModelClient())
        print(f"[demo]   {i}/{TICKETS} {row['ticket_id']} -> {row['decision']}", flush=True)
        time.sleep(GAP_SECONDS)
    print("[demo] done; the endpoint stops with this process", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
