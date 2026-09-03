"""Prometheus metrics — exposed at :8001/metrics.

Metrics dashboard covers: tickets processed by outcome, end-to-end latency,
guardrail activations, confidence distribution (for calibration monitoring).
Setup Guide §06 shape; extended for our needs.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram, start_http_server

TICKETS = Counter(
    "tickets_processed_total",
    "Tickets processed",
    ["channel", "outcome"],  # outcome: auto_respond | escalate | block
)

LATENCY = Histogram(
    "response_seconds",
    "End-to-end response time",
    buckets=(0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
)

GUARDRAIL_BLOCKS = Counter(
    "guardrail_blocks_total",
    "Responses blocked by guardrail",
    ["guardrail"],  # pii | grounding | instruction_integrity | tone | confidence_floor
)

CONFIDENCE = Histogram(
    "classification_confidence",
    "Distribution of classification confidence scores (for calibration monitoring)",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

DECISION_LOG_FAILURES = Counter(
    "decision_log_write_failures_total",
    "Decision-log writes that failed — FR-20 not satisfied for those decisions",
    ["stage"],  # classification | routing | generation | validation
)


def start_metrics_server(port: int = 8001) -> None:
    """Start the /metrics HTTP endpoint on the given port."""
    start_http_server(port)
