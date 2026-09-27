# FDE Capstone — CloudServe Support Automation

An intelligent customer support system for CloudServe Solutions (fictional client).
Built for the Forward Deployed AI Engineering capstone project.

**Author:** Alok Kulkarni
**Deadline:** 20 September 2026
**Status:** Week 3 — submission-ready

---

## What this system does

It processes incoming support tickets from four channels (email, live chat, docs comments, community forum), classifies intent and urgency, retrieves relevant documentation, and either drafts an auto-response with citations or escalates to a human agent with context. Every decision is logged; guardrails block responses that would leak PII, make unsupported claims, or fall outside support scope.

## Quick start

Requires **Python 3.11** (the version CI runs). The pinned `numpy` and `pandas`
have no wheels for 3.12 or later, so `pip install` fails there.

```bash
# 1. Create and activate a virtual environment (Python 3.11)
python3.11 -m venv .venv
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Then edit .env and set OPENROUTER_API_KEY

# 4. Verify setup
python -m scripts.verify_setup

# 5. Index the documentation corpus (one-time)
python -m src.index_docs

# 6. Run the full evaluation harness (the gate command — A9/A10)
python -m evaluation.harness \
    --input data/validation_tickets.json \
    --output evaluation/results/run_$(date +%Y%m%d)

# 7. Run tests
python -m pytest tests/ -v

# 8. (optional) Run the HTTP API for a live demo
python -m src.api                             # starts on http://127.0.0.1:8000
curl -s http://127.0.0.1:8000/healthz | jq
curl -s -X POST http://127.0.0.1:8000/ticket \
     -H "Content-Type: application/json" \
     -d '{"ticket_id":"DEMO-1","channel":"email",
          "body":"How do I revert to the previous release?"}' | jq
curl -s http://127.0.0.1:8000/metrics | head -20
```

The graded artefact is `evaluation/results/<run>/metrics_report.json` produced
by step 6. The API in step 8 wraps the same pipeline for demonstration and
Prometheus monitoring; it is not the assessed interface (Build Spec §04
labels its launch command *illustrative rather than prescriptive*).

### On Windows

The Python commands (steps 2, 4, 5, 7 and `python -m src.api`) are the same.
The rest of the block above is bash. In PowerShell, use these instead:

```powershell
# 1. Python 3.11 through the py launcher
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
# If activation is blocked: Set-ExecutionPolicy -Scope Process Bypass

# 3.
Copy-Item .env.example .env

# 6. One line; PowerShell does not continue lines with \
python -m evaluation.harness --input data/validation_tickets.json --output "evaluation/results/run_$(Get-Date -Format yyyyMMdd)"

# 8. In Windows PowerShell, curl is Invoke-WebRequest and does not take these flags
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod -Method Post http://127.0.0.1:8000/ticket -ContentType "application/json" `
    -Body '{"ticket_id":"DEMO-1","channel":"email","body":"How do I revert to the previous release?"}'
curl.exe -s http://127.0.0.1:8000/metrics | Select-Object -First 20
```

In Git Bash the block above works as written, with two changes: `py -3.11`
in place of `python3.11`, and `source .venv/Scripts/activate`. `jq` is not
included with Git Bash; drop `| jq` or install it.

### Processing order (D-17)

The harness works high-urgency tickets first. It classifies every ticket, orders
the queue by that rating, then runs the rest of the pipeline — so an interrupted
run, an exhausted free-tier quota or a `--limit` slice has spent its calls on the
tickets that matter most. Phase 2 reuses phase 1's result, so this costs no extra
model calls, and a run that completes reports the same figures it would have in
any order.

`--limit N` still takes the first N tickets in file order and prioritises within
them; it does not find the N most urgent tickets in the file.

Every run committed under `evaluation/results/` predates this and was produced in
file order. To reproduce one, add `--no-prioritize`:

```
python -m evaluation.harness --no-prioritize \
    --input data/validation_tickets.json \
    --output evaluation/results/run_$(date +%Y%m%d)
```

## Demo: four tickets, four behaviours

Four single-ticket files in `data/`, plus one file containing all four. Each is
a JSON array, which is what `--input` expects.

```
# All four in one run (about 4 minutes on local models, ~40s on a hosted one)
python -m evaluation.harness \
    --input data/demo_tickets.json \
    --output evaluation/results/demo_$(date +%Y%m%d)

# Or one behaviour at a time
python -m evaluation.harness --input data/01_success_rollback.json          --output /tmp/demo1
python -m evaluation.harness --input data/02_escalate_security.json         --output /tmp/demo2
python -m evaluation.harness --input data/03_injection_attempt.json         --output /tmp/demo3
python -m evaluation.harness --input data/04_escalate_no_documentation.json --output /tmp/demo4
```

What each one shows, and how reliable it is:

| File | Shows | Always behaves this way? |
|------|-------|--------------------------|
| `01_success_rollback.json` | A grounded reply sent automatically (`auto_respond`) | **No — model-dependent.** Verified sent on `gpt-4o-mini`; the local `llama3.1:8b` draft was blocked by the grounding check on 20 Sep. |
| `02_escalate_security.json` | Policy escalation: `security_incident` never auto-answers (D-07) | **Yes.** The rule is on the intent, not the draft. |
| `03_injection_attempt.json` | An injection attempt recorded (`injection_flags`) and never answered | **The flag, yes** (deterministic pattern match, D-16). The decision is `escalate` unless a guardrail also faults the draft, which outranks it and gives `block`. |
| `04_escalate_no_documentation.json` | No help article covers the question → `empty_retrieval` escalation | **Yes.** Retrieval does not depend on the model. |

Reading the result of a demo run:

```
# the decision, why, and what a human would receive
python -c "import json;[print(r['ticket_id'], r['decision'], r['trigger'], r.get('injection_flags')) \
  for r in map(json.loads, open('evaluation/results/demo_$(date +%Y%m%d)/results.jsonl'))]"

# the run's report and the Evaluation Framework results table
cat evaluation/results/demo_$(date +%Y%m%d)/metrics_report.json
cat evaluation/results/demo_$(date +%Y%m%d)/results_table.md
```

Every escalated or blocked row carries `escalation_bundle`: the retrieved
passages, the classifier's runners-up, the draft (flagged when a check found a
fault in it) and the rule that stopped the send (FR-11).

### Running on the free tier

`.env` ships pointing at OpenRouter. Two things to know before a free run:

- **Check the model id exists.** The `:free` suffix is part of an id, not a
  switch you can append — `meta-llama/llama-3.3-70b-instruct:free` and
  `google/gemini-2.5-flash:free` do not exist. List what is actually free:

  ```
  curl -s https://openrouter.ai/api/v1/models \
    | python3 -c "import sys,json;[print(m['id']) for m in json.load(sys.stdin)['data'] if m['id'].endswith(':free')]"
  ```

- **Cap the retries.** The free allowance is 50 requests a day on an account
  with under \$10 of credit, and one ticket makes six calls. With the default
  retry budget a single ticket can consume 30 of the 50:

  ```
  MODEL_MAX_RETRIES=1 python -m evaluation.harness \
      --input data/demo_tickets.json --output /tmp/free_demo
  ```

  Check what is left with:

  ```
  curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['free_model_daily_requests'])"
  ```

Verified working on 20 Sep 2026: `nvidia/nemotron-3-super-120b-a12b:free`
drafting with `nex-agi/nex-n2.5-pro:free` judging — a completed 5-ticket run at
\$0.00, though 3 of 16 calls returned an empty response and p95 latency was
195s. Both Google free models were rate-limited *upstream* the same day, which
is shared capacity rather than your quota. The local Ollama path
(`MODEL_BASE_URL=http://localhost:11434/v1`) has no quota at all and is the
more dependable free option.

## Monitoring: testing the Prometheus endpoint

The metrics server is **off by default** (`--metrics-port 0`), so a graded run
cannot fail because a port is taken. Two ways to see it working:

```
# A. Real numbers — run the harness with the endpoint on, then scrape it
python -m evaluation.harness --input data/demo_tickets.json \
    --output /tmp/demo_metrics --metrics-port 8001
# ...and from a second terminal, while it runs:
curl -s http://localhost:8001/metrics | grep -v '^#' | grep -E '^[a-z]'

# B. No provider, no credit, no keys — a fake run that serves the same endpoint
python -m scripts.demo_metrics          # one ticket every 2s on :8001, 30 tickets
curl -s http://localhost:8001/metrics | grep tickets_processed_total
```

What you should see (verified 20 Sep 2026):

```
tickets_processed_total{channel="chat",outcome="auto_respond"} 5.0
response_seconds_count 14.0
classification_confidence_bucket{le="0.9"} 14.0
kill_switch_active 0.0
```

| Metric | What it tells you |
|--------|-------------------|
| `tickets_processed_total{channel,outcome}` | Volume by channel and by decision |
| `response_seconds` | Latency histogram, end to end per ticket |
| `classification_confidence` | Confidence distribution — the calibration check |
| `guardrail_blocks_total{guardrail}` | Which check is firing |
| `injection_flags_total{pattern}` | Injection attempts by shape (D-16) |
| `model_cache_hits_total{stage}` | Replayed calls (D-08) |
| `model_call_failures_total{stage,error_type}` | Provider trouble, by stage |
| `kill_switch_active` | 1 while automatic answering is halted (D-15) |

A label appears only after its first event, so a counter you have not triggered
yet is absent rather than zero.

To scrape it with a real Prometheus, `ops/prometheus.yml` already targets
`localhost:8001`:

```
prometheus --config.file=ops/prometheus.yml    # then browse http://localhost:9090
```

The API serves the same registry at `http://127.0.0.1:8000/metrics`, which is
the more realistic target: it stays up between harness runs. See
`docs/monitoring.md` for the five dashboard panels and what each one is for.

## Repository layout

```
fde-capstone/
├── README.md                setup and run instructions
├── requirements.txt         pinned dependencies
├── .env.example             every variable, placeholder values only
├── .gitignore
│
├── src/                     application code
│   ├── ingest.py            normalise tickets from all four channels
│   ├── classify.py          intent + urgency + confidence
│   ├── retrieve.py          vector search over docs
│   ├── route.py             escalation decision + threshold
│   ├── generate.py          answer drafting with citations
│   ├── guardrails.py        blocking checks
│   ├── logging_store.py     decision log
│   └── api.py               FastAPI application
│
├── prompts/                 versioned prompts (design artefacts)
│   ├── build/               prompts that run inside the system
│   └── evaluation/          prompts used to judge output
│
├── tests/                   pytest suite
│
├── evaluation/
│   ├── harness.py           runs full ticket set end-to-end
│   └── results/             dated output from each run
│
├── docs/
│   └── architecture.md
│
├── data/                    ticket sets and documentation corpus
│
├── workbooks/               filled-in stage workbooks
│
├── storage/                 generated at runtime (gitignored)
│
└── .github/workflows/       CI
```

## Data files (in `data/`)

| File | Purpose |
|------|---------|
| `development_tickets.json` | 500 labelled tickets — used for building |
| `validation_tickets.json`  | 80 labelled tickets — used for self-check |
| `ground_truth_responses.json` | 200 senior-agent reference answers |
| `documentation.json` | 29 KB articles — the retrieval corpus |
| `demo_tickets.json` | The four demo tickets below, in one file |
| `01_success_rollback.json` … `04_escalate_no_documentation.json` | One demo ticket each — see [Demo](#demo-four-tickets-four-behaviours) |

The hidden evaluation set (120 tickets) is **not** in this repo. The harness must accept `--input` and `--output` paths so it can be pointed at that unseen file.

## Architecture at a glance

Ingest → Classify → Retrieve → Generate → Validate → Route

Cross-cutting: decision log, metrics, guardrails.

Full details in `docs/architecture.md`.

## Attribution

Any code generated with AI assistance is declared in the project report. Third-party libraries are listed in `requirements.txt` with pinned versions.
