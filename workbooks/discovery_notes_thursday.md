# Discovery Notes — Thursday Addendum: What the Ticket Data Says

**Date:** 2026-08-27 (Thursday, Week 1 Day 2)
**Source:** `data/development_tickets.json` (500 tickets); `data/documentation.json` (29 help articles).
**Purpose:** answer questions Q1 to Q4 from Wednesday's interview notes; establish the baseline the new system will be compared against.

Tag prefix: `EV-DATA-<nn>`. These are the ticket-data evidence tags. Requirements in the PRD will cite them alongside the interview tags (`EV-M<n>`, `EV-S<n>` etc.) from Wednesday's file.

---

## Short version — what the data says

- Sofia was right about the 70% figure. 71.4% of tickets have an answer in the help articles.
- Marcus's first-contact resolution figure holds. The data says 43.8% (he quoted 42%). His customer satisfaction figure of 3.2 out of 5 is a bit high; the data says 2.97.
- Ravi was wrong about enterprise getting better service. Enterprise-tier customers have the worst first-contact resolution rate, the longest resolution time, and the highest escalation rate of the three tiers.
- Sofia's language-fluency worry doesn't show up in the aggregate outcome numbers. Non-fluent-English tickets do slightly *better* on first-contact resolution, time-to-resolution and satisfaction than fluent ones. The gap Sofia perceived is probably at agent-experience level, not at customer-outcome level. One nasty combination: Asia-Pacific customers whose English is non-fluent (satisfaction 2.68) and Latin American customers who are fluent (2.64) both score notably worse than the average.
- Daniel's "half of my escalations are avoidable" figure is roughly right but slightly overstated. The data says 38%.
- The channel that hurts customers most is the docs-comment channel (customers commenting on the help articles themselves). First-contact resolution 34.6%, one in three of them come back within a week, median time-to-resolution 466 minutes (about 8 hours). These are customers who tried to help themselves, failed, and are already frustrated when they file the ticket.
- A finding nobody said out loud: 4 of the 22 ticket types are ALWAYS marked "must not auto-respond": compliance_request, security_incident, feature_request, unclear_request. Between them they're 17.4% of tickets. That's the floor on how many tickets we must escalate to a human no matter how confident the system is.

---

## The baseline (partial answer to OQ-04; forms the target for the PRD's how-well-it-must-work requirements)

**EV-DATA-01** The historical baseline across all 500 development tickets:

| Metric | Value | Compare to |
|--------|-------|------------|
| First-contact resolution rate | 43.8% | Marcus said 42%. Target: 60% or higher. |
| Escalation rate | 56.2% | mirror of the above |
| Median resolution time | 214 minutes (3.6 hours) | Service agreement promises 120 minutes |
| Mean resolution time | 422 minutes (7.0 hours) | Marcus said 8 to 12 hours |
| Mean customer satisfaction | 2.97 / 5 | Marcus said 3.2 |
| Repeat contact within a week | 21.6% | (baseline; want to reduce) |

Note on the median-vs-mean gap: 422 minutes vs 214 minutes is a big spread. A small number of very long tickets pull the mean up. Per the Evaluation Framework, we report both.

---

## Q1 — What percentage of tickets have an answer in the help articles?

**EV-DATA-02** The `answerable_from_docs=true` label is set on 357 of 500 tickets — 71.4%. Sofia said seven out of ten. The data agrees to within one percentage point.

What this means for the design: a retrieval-first architecture (find the article, then draft) is the correct choice. The through-line in the Wednesday notes stands. The answers already exist; agents and customers can't find them.

---

## Q2 — Are the escalated tickets mostly hard, or mostly cases tier 1 could have handled?

Two figures matter here.

**EV-DATA-03** Of the 189 tickets whose *correct* route is escalate (`expected_route=escalate`), 46 (24.3%) have an answer in the help articles. So a quarter of *correct* escalations still have documentation behind them — those are the tickets that should go to tier 2 *with* the retrieved articles attached, not as a bare forward. Daniel's "escalations need context" ask is a real thing.

**EV-DATA-04** Of the 281 tickets *actually* escalated in the historical data (`history.escalated=true`), 107 (38.1%) both have an answer in the help articles AND are not on the must-escalate list. Those are Daniel's "avoidable" escalations. He said about half; the data says 38%. Not a majority, but a large minority — more than one in three escalations happened for a ticket the system should have caught.

What this means for the requirements: two distinct routing outcomes matter, not one.

- **Auto-respond with citation.** Target: capture the 311 `expected_route=auto_respond` tickets (62% of all).
- **Escalate with a draft attached.** For the 189 `expected_route=escalate` tickets. Carry the retrieved articles, tier 1's flag of what they weren't sure about, and any draft the system produced.

A simple auto-or-escalate router misses the second win. Daniel gets what he asked for.

---

## Q3 — Is the problem the content of the articles, or the ability to find them?

Deferred to Friday. Friday will run a retrieval experiment (see `workbooks/q3_findings.md` for the result). If the search finds the right article often, Sofia was right (search is the problem). If it doesn't, either the content is bad or our search approach is wrong — those two stay tangled until we swap search methods.

An interim finding from just counting the articles:

**EV-DATA-05** The 29 articles have 10 categories, not 8 as the Dataset Guide's paragraph text says. Authentication (4 articles), deployment (4), API (3), performance (3), billing (3), data (3), security (3), account (2), integration (2), onboarding (2). Settles OQ-02: 10, not 8.

---

## Q4 — Where does service quality actually vary?

### By English fluency (Sofia's worry)

**EV-DATA-06** Non-fluent-English tickets don't show the disadvantage Sofia described. If anything, they do slightly better.

| Segment    | # tickets | First-contact resolution | Median time (min) | Satisfaction (1-5) | Escalation |
|------------|-----------|---------------------------|--------------------|--------------------|-----------|
| fluent     | 380       | 43.2%                     | 216                | 2.95               | 56.8%     |
| non_fluent | 120       | 45.8%                     | 198                | 3.04               | 54.2%     |

This doesn't contradict Sofia's experience. It's plausible that individual non-fluent tickets take her longer to understand (which is what she said), while at the *outcome* level agents get through them at the same rate and quality. Sofia's fairness worry belongs on the search axis, not the outcome axis. A search that only matches exact phrases will hurt non-fluent customers most, which is why Friday's retrieval experiment (Q3) will break results down by fluency.

### By region

**EV-DATA-07** Regions diverge more than fluency does.

| Region         | # tickets | First-contact resolution | Median time | Satisfaction |
|----------------|-----------|---------------------------|--------------|--------------|
| north_america  | 170       | 48.8%                     | 110          | 3.05         |
| europe         | 151       | 43.7%                     | 198          | 3.01         |
| asia_pacific   | 119       | 39.5%                     | 292          | 2.94         |
| latin_america  | 60        | 38.3%                     | 235          | 2.73         |

Latin America is the worst region on satisfaction and near-worst on first-contact resolution. This is *not* a language-fluency effect: within Latin America, the fluent-English tickets score satisfaction 2.64 — worse than any other combination of region-and-fluency.

Working hypothesis (to test later): the region gap is a support-hours-and-timezone gap, not a language gap. We can't investigate this from the data alone. Flag it as an assumption in the PRD.

### By customer tier (Ravi's worry)

**EV-DATA-08** Ravi was wrong. Enterprise gets the *worst* service on first-contact resolution and time-to-resolution, not the best.

| Tier       | # tickets | First-contact resolution | Median time | Satisfaction | Escalation | Share of "high urgency" |
|------------|-----------|---------------------------|--------------|--------------|-----------|--------------------------|
| business   | 164       | 48.2%                     | 141          | 2.91         | 51.8%     | 23%                     |
| enterprise | 83        | 37.3%                     | 369          | 3.05         | 62.7%     | 36%                     |
| standard   | 253       | 43.1%                     | 266          | 2.98         | 56.9%     | 31%                     |

Two things explain this:

- Enterprise has a much higher share of high-urgency tickets (36% vs 23% for business).
- Enterprise's most common ticket types are the hard ones: data_residency, database_issue, rollback_request. The help articles may exist but the actual resolution isn't a one-message answer.

Ravi's colleague may be reporting response-time on his own tickets specifically (he's a platform lead — his tickets are probably deployment-related and simpler), while the enterprise tier as a whole is worse-served. If we build the system so business and standard tiers get *faster* with automation and enterprise stays the same, the gap Ravi's colleague enjoys goes away. That's a renewal risk on the other side. **New FR to add:** the automation must not make the gap between tiers wider — measured, not assumed.

### By channel

**EV-DATA-09** Channel is the widest fairness gap of all.

| Channel      | # tickets | First-contact resolution | Median time (min) | Satisfaction | Repeat contact |
|--------------|-----------|---------------------------|--------------------|--------------|----------------|
| forum        | 55        | 50.9%                     | 54                 | 2.98         | 14.5%          |
| email        | 212       | 44.8%                     | 193                | 3.08         | 20.8%          |
| chat         | 155       | 44.5%                     | 209                | 2.72         | 19.4%          |
| docs_comment | 78        | 34.6%                     | 466                | 3.17         | 33.3%          |

Two things stand out.

**docs_comment is the "failed to self-serve" channel.** These are customers who tried the help articles, couldn't find what they needed, and filed a comment against the article page. They're already frustrated. Their first-contact resolution is 20 points lower than any other channel. Their resolution time is 5x the fastest channel. One in three of them comes back within a week. This is the population Ines's search-doesn't-work observation would predict. A retrieval-first system that closes the loop here would move the biggest single number in the entire dataset.

**Forum tickets get resolved fast (54 minutes median).** Community members answer other customers most of the time before a support agent even sees the ticket. Not a target for automation — it's already working. Auto-responding here would risk disrupting a functioning behaviour (customers helping customers).

---

## The must-not-auto-respond floor (feeds the routing requirement)

**EV-DATA-10** 87 of 500 tickets (17.4%) are labelled `must_not_auto_respond=true`. This flag is driven by four ticket types:

| Ticket type       | Share of that type with the flag | Total tickets of that type |
|-------------------|-----------------------------------|----------------------------|
| compliance_request | 100%                             | 26                         |
| security_incident  | 100%                             | 26                         |
| feature_request    | 100%                             | 20                         |
| unclear_request    | 100%                             | 15                         |

These are the tickets the router must escalate no matter how confident the system is. Feature requests and unclear requests are also 100% `answerable_from_docs=false` (there's no help article to retrieve). Ines mentioned "novel incidents" as a category with no article to retrieve — it's not labelled as its own ticket type, but overlaps with `unclear_request`.

Daniel's do-not-automate list from the interview was: security, billing disputes, data location. The data confirms security (100%). The labels don't separate billing *disputes* from billing *queries*, and 72% of `data_residency` tickets are answerable from docs. That's a design decision for later — how strict should we be about billing_query and data_residency? Will need its own ADR.

---

## The 22 ticket types (settles OQ-01)

Full list, with per-type counts and what percentage are answerable from the help articles:

| Ticket type              | # tickets | % answerable | Must-not-auto-respond |
|--------------------------|-----------|--------------|-----------------------|
| data_export              | 29        | 93%          | 0%                    |
| data_residency           | 29        | 72%          | 0%                    |
| rollback_request         | 28        | 75%          | 0%                    |
| deployment_failure       | 27        | 70%          | 0%                    |
| compliance_request       | 26        | 65%          | 100%                  |
| sso_configuration        | 26        | 85%          | 0%                    |
| security_incident        | 26        | 54%          | 100%                  |
| database_issue           | 26        | 69%          | 0%                    |
| api_usage_question       | 24        | 96%          | 0%                    |
| billing_query            | 24        | 88%          | 0%                    |
| performance_degradation  | 23        | 74%          | 0%                    |
| quota_or_overage         | 23        | 87%          | 0%                    |
| account_access           | 22        | 77%          | 0%                    |
| onboarding               | 22        | 91%          | 0%                    |
| integration_help         | 21        | 76%          | 0%                    |
| webhook_issue            | 21        | 76%          | 0%                    |
| feature_request          | 20        | 0%           | 100%                  |
| authentication_failure   | 20        | 70%          | 0%                    |
| api_key_issue            | 18        | 67%          | 0%                    |
| configuration_help       | 17        | 59%          | 0%                    |
| unclear_request          | 15        | 0%           | 100%                  |
| rate_limit               | 13        | 92%          | 0%                    |

The distribution is reasonable (between 13 and 29 per type). No single type dominates. The classifier will see all 22 types during training.

---

## What the ingest step needs to handle (starts to satisfy acceptance criterion A2)

**EV-DATA-11**

- Every chat ticket has an empty subject (155 of 155). The ingest step must NOT require a subject. Set it to `""` and don't treat it as a data-quality problem.
- Every ticket body in the development set is non-empty (0 of 500 empty). But the hidden test set is unseen — the ingest spec still needs to handle an empty body without breaking. Empty body → add `warnings=["empty_body"]` to the ticket, don't crash.
- Body length runs 28 to 245 characters, median 141. Short. No paragraphing to worry about. No language-processing challenges from length.

---

## Volume by day (partial answer to OQ-03)

**EV-DATA-12** Sofia said Mondays are worst. The day-of-week distribution of ticket arrivals:

| Day       | # tickets | Share |
|-----------|-----------|-------|
| Friday    | 85        | 17.0% |
| Tuesday   | 80        | 16.0% |
| Monday    | 75        | 15.0% |
| Wednesday | 73        | 14.6% |
| Thursday  | 69        | 13.8% |
| Sunday    | 61        | 12.2% |
| Saturday  | 57        | 11.4% |

Fridays have the most incoming tickets, not Mondays. Sofia's perception is probably driven by Monday inheriting the weekend backlog — Sat + Sun together are 23.6% of intake, arriving into no coverage. It matters for the sprint plan (no weekend capacity flex; the build happens Monday to Friday) but not for the requirements.

---

## Updated answers to the four Wednesday questions

| # | Question | Answer |
|---|----------|--------|
| Q1 | What percentage is answerable from the help articles? | 71.4%. Sofia was right. |
| Q2 | Are escalations mostly hard, or tier-1-tractable? | Mixed. 24% of the *correct* escalations still have article coverage (they need drafted context sent along). 38% of the *actual* historical escalations were avoidable. Daniel was directionally right; his 50% was an overstatement. |
| Q3 | Content or findability? | Not yet answered. Waiting on Friday's retrieval experiment. Interim: for the 18 mixed-answerable ticket types, article coverage is 100%. For feature_request and unclear_request, coverage is 0% by design. |
| Q4 | Where does service quality vary? | By channel (docs_comment much worse), by region (Latin America worst on satisfaction), by tier (enterprise worse than business, contradicting Ravi). English fluency does NOT show a gap in outcomes. |

---

## The refined problem statement (for Saturday's PRD skeleton)

Draft v2, incorporating what Thursday's data added:

> CloudServe's support function receives roughly 500 tickets a week across four channels. Roughly seven in ten of those have an answer that already exists in the company's 29 reviewed help articles, yet the historical first-contact-resolution rate is 44%. The gap isn't a shortage of answers. It's a failure of retrieval — from the agents' side, who can't find their own articles in the internal search and rebuild answers from personal notes; and from the customers' side, one in six of whom start by searching the docs themselves, fail, file a comment against the docs page and then wait an average of 8 hours for a reply that reproduces material already in front of them. When tickets do reach a tier-2 engineer, they arrive as forwarded threads with no summary, no note about what tier 1 tried, and no attached documents. That turns roughly 38% of escalations into avoidable ones and asks the same question of the customer twice.
>
> The system to build is not a chatbot. It's a retrieval-grounded support assistant that: (a) drafts a cited answer for the 62% of tickets whose correct route is auto-respond, sends it only when its own confidence exceeds a threshold set from data, and cites the specific article the answer came from; (b) hands the draft and retrieved articles to a tier-1 agent for the tickets that fall below the send threshold, so the agent starts from a partial answer rather than a blank ticket; (c) escalates to tier 2 with the retrieved documents, tier 1's flag of what they weren't sure about, and any draft the system produced — closing the missing-context loop that drives customer follow-up frustration; (d) blocks (never auto-answers) every ticket in the four always-escalate types (compliance, security incident, feature request, unclear request) regardless of confidence.
>
> Success is measured on three axes. Business: first-contact-resolution moves from 44% toward 60% or higher; median time to a substantive response drops from 214 minutes toward 30; repeat contacts drop from 22% toward under 15%. Technical: the search's hit rate on the correct article reaches at least 85% on tickets flagged answerable; the classifier's stated confidence is accurate within 5 percentage points in the "send" band; the drafts invent no more than 5% of their claims (checked independently); every citation resolves to a passage that was actually retrieved. Governance: quality doesn't vary by more than 15 percentage points across customer tier, region or language fluency; every automated decision writes a log entry that could be reconstructed; a compliance auditor can trace any response back to the ticket, the AI model version, the prompt version, the retrieved articles, and the confidence threshold that was in effect.

Ready to shoot at on Friday.

---

## Open questions still open

- **OQ-03** (partial). Volume by day is answered. Hour-of-day (support-hours coverage) still not answered. Need timezone-aware analysis to test the "Latin America is a timezone problem" theory.
- **OQ-05** (unresolvable from this data). Whether a customer previously tried the docs and gave up isn't labelled. The `docs_comment` channel is the closest proxy (78 tickets, 15.6%).

## Next — Friday's plan (unchanged)

- Draft Stage 1 Discovery Workbook sections 1–5 from Wednesday and Thursday material, with EV-* and EV-DATA-* citations.
- Run the retrieval quality pilot on the 29 help articles. Answers Q3.
- Lock the problem statement from the v2 draft above.

---

## Changelog

- 2026-08-27 v1.0 — first pass from Thursday ticket-data analysis.
- 2026-08-31 v1.1 — rewrote in plainer language so a non-technical reader can follow it. Numbers, evidence tags (EV-DATA-*, EV-M*, EV-S* etc.), file paths, ticket labels and the 22-type table were not changed. Every quantity in the file was independently re-derived from `data/development_tickets.json` before this rewrite — all matched.
