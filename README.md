# FDE Capstone — CloudServe Support Automation

An intelligent customer support system for CloudServe Solutions (fictional client).
Built for the Forward Deployed AI Engineering capstone project.

**Author:** Alok Kulkarni
**Deadline:** 13 September 2026
**Status:** Week 1 — Discovery and Requirements

---

## What this system does

It processes incoming support tickets from four channels (email, live chat, docs comments, community forum), classifies intent and urgency, retrieves relevant documentation, and either drafts an auto-response with citations or escalates to a human agent with context. Every decision is logged; guardrails block responses that would leak PII, make unsupported claims, or fall outside support scope.

## Quick start

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
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

# 6. Run the API
python -m src.api

# 7. Run the full evaluation harness (the gate command)
python -m evaluation.harness \
    --input data/validation_tickets.json \
    --output evaluation/results/

# 8. Run tests
python -m pytest tests/ -v
```

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

The hidden evaluation set (120 tickets) is **not** in this repo. The harness must accept `--input` and `--output` paths so it can be pointed at that unseen file.

## Architecture at a glance

Ingest → Classify → Retrieve → Route → Generate → Validate

Cross-cutting: decision log, metrics, guardrails.

Full details in `docs/architecture.md`.

## Attribution

Any code generated with AI assistance is declared in the project report. Third-party libraries are listed in `requirements.txt` with pinned versions.
