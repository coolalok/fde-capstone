# Monitoring

What the system exposes while it runs, and what a dashboard should show. The
metrics live in `src/metrics.py`; the scrape config is `ops/prometheus.yml`.

## Running it

```
python -m evaluation.harness --input data/validation_tickets.json \
    --output evaluation/results/run --metrics-port 8001
curl -s localhost:8001/metrics
```

`--metrics-port 0` (the default) does not start the server. The default is off
on purpose: a graded run on an unfamiliar machine must not fail because a port
is taken, and the assessed artefact is `metrics_report.json` (A10), not a live
endpoint. `METRICS_PORT` in `.env` sets it without the flag.

Captured output from a real run is in
`evaluation/results/monitoring_20260918/metrics_endpoint.txt`.

## The five panels, and the metric behind each

Setup Guide §06 names the panels. Each maps to one metric:

| Panel | Metric | Query |
|---|---|---|
| Tickets per hour, by channel and outcome | `tickets_processed_total{channel, outcome}` | `sum by (channel, outcome) (rate(tickets_processed_total[5m])) * 3600` |
| Auto-answered against escalated | same counter, outcome label | `sum by (outcome) (tickets_processed_total)` |
| Latency, median and 95th percentile | `response_seconds` histogram | `histogram_quantile(0.95, sum by (le) (rate(response_seconds_bucket[5m])))` |
| Guardrail activations over time, by guardrail | `guardrail_blocks_total{guardrail}` | `sum by (guardrail) (rate(guardrail_blocks_total[5m]))` |
| Confidence distribution | `classification_confidence` histogram | `sum by (le) (rate(classification_confidence_bucket[5m]))` |

Two more exist because the build needed them, and both belong on the same
board:

| Panel | Metric | Why |
|---|---|---|
| Model call failures, by stage and error type | `model_call_failures_total{stage, error_type}` | The 13 Sep gate run lost 46 of 80 classifications. A rate-limit and a malformed envelope need different responses, so the error class is a label. |
| Decision-log write failures | `decision_log_write_failures_total{stage}` | A decision that was taken but not logged breaks FR-20 and A8. It should alert, not sit on a chart. |

## What the numbers mean here, and what they do not

- **`guardrail_blocks_total` counts every check that did not pass, including
  fail-safe blocks** — a block caused by the judge erroring rather than by a bad
  draft. On a dashboard a spike is a reason to look; `metrics_report.json`
  separates the two (`guardrail_fail_safe_blocks`). On the 18 Sep free-tier
  probe, 7 of 10 blocks were fail-safe, so reading that chart as "the model is
  fabricating" would have been wrong.
- **`classification_confidence` excludes fallbacks.** A failed classification
  reports 0.0 because the model never answered; recording it would put a spike
  at zero that reads as an overcautious classifier rather than an outage.
  `model_call_failures_total` is where an outage shows.
- **Latency here is the whole pipeline per ticket**, including up to six
  sequential model calls. p95 was 30.3s on the 15 Sep run against NFR-02's 4.0s
  target — see the Stage 5 revision log.

## What is not built

- **No Grafana dashboard file.** The panels above are specified but not built as
  JSON. A reader can recreate them from the queries in about ten minutes.
- **No alerting.** The incident procedure in the Governance Framework depends on
  someone reading a run; nothing pages. `decision_log_write_failures_total` is
  the first thing that should get a rule.
- **No continuous scrape target.** The harness serves metrics only while it
  runs, because `src/api.py` is a stub (B-29, first to cut). Prometheus shows
  the target as down between runs.
