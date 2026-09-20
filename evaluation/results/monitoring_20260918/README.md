# Monitoring evidence — 18 Sep 2026

`metrics_endpoint.txt` is a live scrape of `http://localhost:8001/metrics`, taken
about 45 seconds into a 4-ticket harness run started with `--metrics-port 8001`.
Two of the four tickets had finished at that moment, which is why the counters
read 2.

Configuration: `meta-llama/llama-3.1-8b-instruct` drafting and classifying,
`nvidia/nemotron-3-super-120b-a12b:free` judging, both on OpenRouter — the
committed defaults, not the graded configuration (D-01a).

The run itself finished with 0 auto-sent, 2 escalated, 2 blocked, 0 degraded,
17 model calls, and the decision log reconciling 4/4. Both blocks were fail-safe
blocks: the free judge returned no choices on two calls, which is the same
intermittent fault the 18 Sep probe found. `model_call_failures_total` in the
scrape shows them, labelled by stage and error type.

The endpoint serves only while the harness runs, so a scrape after it exits
returns nothing. See docs/monitoring.md.
