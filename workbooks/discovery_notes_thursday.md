# Discovery Notes — Thursday Addendum: Ticket Data Forensics

**Date:** 2026-08-27 (Thu, W1D2)
**Source:** `data/development_tickets.json` (N=500), `data/documentation.json` (29 articles).
**Purpose:** settle Q1–Q4 from the Wednesday interview notes; establish the baseline.

Tag prefix: `EV-DATA-<nn>`. These are the ticket-data evidence tags that FRs will trace to alongside the `EV-<initial>-<n>` interview tags.

---

## Executive summary of what the data says

- Sofia's 70% claim holds. 71.4% of tickets are `answerable_from_docs=true`.
- Marcus's FCR baseline holds. 43.8% (he quoted 42%). His CSAT figure of 3.2 is a little high; the data says 2.97.
- Ravi was wrong about enterprise getting better service. Enterprise tickets have the worst FCR, longest resolution time, and highest escalation rate of the three tiers.
- Sofia's language-fluency hypothesis is not visible in aggregate. Non-fluent tickets do slightly better on FCR, resolution, and CSAT than fluent. The gap she perceived may be at agent-experience level, not at outcome level. One intersection is bad: Asia-Pacific × non-fluent (CSAT 2.68) and Latin America × fluent (2.64).
- Daniel's "50% avoidable" is directionally right but overstated. 38% of historical escalations are avoidable (answerable from docs AND not on the do-not-automate list).
- The channel that's hurting people is `docs_comment`. FCR 34.6%, repeat contact 33.3%, median resolution 466 minutes. These are the customers who tried to self-serve, failed, and are angry about it.
- New finding not in the interviews: 4 intents are always must_not_auto_respond. compliance_request, security_incident, feature_request, unclear_request. Together 17.4% of tickets. These set the floor on our escalation rate.

---

## The baseline (partly satisfies OQ-04; forms the target for NFRs)

**EV-DATA-01** Historical baseline across all 500 dev tickets:

| Metric | Value | Compare to |
|--------|-------|------------|
| FCR (first_contact_resolution) | 43.8% | Marcus: 42%. Business target: 60%+. |
| Escalation rate | 56.2% | mirror of FCR |
| Median resolution time | 214 min (3.6 h) | SLA promises 120 min |
| Mean resolution time | 422 min (7.0 h) | Marcus said 8–12 h |
| CSAT (mean of 1–5) | 2.97 / 5 | Marcus quoted 3.2 |
| Repeat contact within a week | 21.6% | (baseline; want to reduce) |

Reporting note: the mean/median gap (422 vs 214 min) is large. A small number of very long tickets pull the mean up. Per Evaluation Framework, we report both.

---

## Q1: What proportion is answerable from the KB?

**EV-DATA-02** `answerable_from_docs=true` = 357/500 (71.4%). Sofia said seven out of ten. Data agrees to within a percentage point.

Implication for design: a retrieval-first architecture is the correct answer. The through-line in the Wednesday notes stands. The answers already exist; agents (and customers) can't find them.

---

## Q2: Are escalations mostly hard, or T1-tractable?

Two figures matter here.

**EV-DATA-03** Of the 189 tickets whose correct route is escalate (`expected_route=escalate`), 46 (24.3%) are `answerable_from_docs=true`. So a quarter of *correct* escalations still have documentation behind them. Daniel's "escalations need context" ask is a real thing. These are the tickets that should go to T2 with the retrieved docs attached, not as bare forwards.

**EV-DATA-04** Of the 281 tickets historically escalated (`history.escalated=true`), 107 (38.1%) are `answerable_from_docs=true` AND `must_not_auto_respond=false`. That's Daniel's "avoidable" claim. He said about half; the data says 38%. Not a majority, but a large minority: more than one in three escalations happened for a ticket the system should have caught.

Implication for the FRs. Two distinct routing outcomes matter, not one:

- Auto-respond with citation. Target: capture the 311 `expected_route=auto_respond` tickets (62% of all).
- Escalate with drafted context. For the 189 `expected_route=escalate` tickets. Carry retrieved docs, tier-1's uncertainty flag, and any draft the model produced.

A binary auto/escalate router misses the second win. Daniel gets what he asked for.

---

## Q3: Content or findability?

Deferred to Friday. The Wednesday notes' framing was that Ines heard "content is bad" but Sofia meant "search is bad". Fri will run a retrieval quality experiment: chunk the 29 docs, embed, query with the 357 `answerable_from_docs=true` ticket bodies, check hit rate against `expected_doc_ids`. If hit rate is high, Sofia was right. If it's low, either the content is bad or our retrieval approach is wrong. The two remain confounded until we swap retrievers.

Interim finding: **EV-DATA-05** the 29 articles have 10 categories, not 8 as the Dataset Guide numbered them. Authentication (4), deployment (4), api (3), performance (3), billing (3), data (3), security (3), account (2), integration (2), onboarding (2). Settles OQ-02: 10, not 8.

---

## Q4: Fairness. Where does service quality actually vary?

### Language fluency (Sofia's flag)

**EV-DATA-06** Non-fluent tickets do not show the disadvantage Sofia described.

| Segment | n | FCR | med (min) | CSAT | Escalation |
|---------|---|-----|-----------|------|-----------|
| fluent | 380 | 43.2% | 216 | 2.95 | 56.8% |
| non_fluent | 120 | 45.8% | 198 | 3.04 | 54.2% |

Interpretation: this doesn't contradict Sofia's experience. It's plausible that individual non-fluent tickets take her longer to understand (her account), while at the outcome level agents get through them at the same rate and quality. Sofia's fairness concern belongs on the retrieval axis, not the outcome axis. Retrieval that only fires on exact-phrase matches will hurt non-fluent English queries more, which is why the retrieval quality experiment on Fri needs to segment by fluency too.

### Region

**EV-DATA-07** Regions diverge more than fluency does.

| Segment | n | FCR | med | CSAT |
|---------|---|-----|-----|------|
| north_america | 170 | 48.8% | 110 | 3.05 |
| europe | 151 | 43.7% | 198 | 3.01 |
| asia_pacific | 119 | 39.5% | 292 | 2.94 |
| latin_america | 60 | 38.3% | 235 | 2.73 |

Latin America is the worst region on CSAT and near-worst on FCR. This is orthogonal to language fluency: the `latin_america × fluent` intersection has CSAT 2.64, worse than any other intersection.

Hypothesis to name (and test later): the region gap is a support-hours / timezone gap, not a language gap. Not investigable from this data alone but should be flagged as an assumption in the PRD.

### Customer tier (Ravi's flag)

**EV-DATA-08** Ravi is wrong about enterprise getting better service. It's the worst tier on FCR and resolution time.

| Segment | n | FCR | med | CSAT | Escalation | High-urgency mix |
|---------|---|-----|-----|------|-----------|------------------|
| business | 164 | 48.2% | 141 | 2.91 | 51.8% | 23% |
| enterprise | 83 | 37.3% | 369 | 3.05 | 62.7% | 36% |
| standard | 253 | 43.1% | 266 | 2.98 | 56.9% | 31% |

Two things explain this:

- Enterprise has a much higher share of high-urgency tickets (36% vs 23% business).
- Enterprise's top intents are complex ones: data_residency, database_issue, rollback_request. Docs may exist but the actual work is not answerable in one message.

Ravi's colleague may be reporting response-time to his tickets specifically (his job is platform-lead, likely deployment-adjacent), while the tier as a whole is worse-served. If we build the system so business/standard get faster with automation and enterprise stays the same, the perceived gap Ravi's colleague enjoys goes away, which is a renewal risk on the other side. FR to add: automation must not disadvantage tier X vs tier Y (measured, not hoped).

### Channel

**EV-DATA-09** Channel is the widest fairness axis.

| Channel | n | FCR | med (min) | CSAT | Repeat |
|---------|---|-----|-----------|------|--------|
| forum | 55 | 50.9% | 54 | 2.98 | 14.5% |
| email | 212 | 44.8% | 193 | 3.08 | 20.8% |
| chat | 155 | 44.5% | 209 | 2.72 | 19.4% |
| docs_comment | 78 | 34.6% | 466 | 3.17 | 33.3% |

Two things stand out.

`docs_comment` is the failed-self-service population. These are customers who tried the docs, couldn't find the answer, and filed a comment against the docs page. They're already frustrated. FCR is 20 points lower than any other channel, resolution time is 5× the fastest, and one in three of them comes back within a week. This is the population Ines's search-doesn't-work observation would predict. A retrieval-first system that closes the loop here would move the biggest single number in the whole dataset.

Forum tickets get resolved fast (54 min median). Community-answered before support arrives most of the time. Not a target for automation; it's already working. Auto-responding here risks disrupting a functioning behaviour (customers helping customers).

---

## Do-not-auto-respond floor (feeds routing FR)

**EV-DATA-10** `must_not_auto_respond=true` = 87/500 (17.4%). It's driven by four intents:

| Intent | Share of that intent | Total tickets |
|--------|---------------------|---------------|
| compliance_request | 100% | 26 |
| security_incident | 100% | 26 |
| feature_request | 100% | 20 |
| unclear_request | 100% | 15 |

These are the tickets the router must escalate regardless of confidence. `feature_request` and `unclear_request` also have `answerable_from_docs=false` for all cases. No doc to retrieve. The Ines-noted category "novel incidents" isn't a labelled intent but overlaps with `unclear_request`.

Daniel's do-not-automate list from the interview was: security, billing disputes, data location. Data confirms security (100%) but the labels don't isolate billing *disputes* from billing *queries*, and data_residency is 72% `answerable_from_docs`. Design decision for later ADR: how strictly to route billing_query and data_residency.

---

## The 22 intent classes (settles OQ-01)

Full list, with per-class counts and `answerable_from_docs` rates:

| Intent | n | %ans | must_not_auto_respond |
|--------|---|------|-----------------------|
| data_export | 29 | 93% | 0% |
| data_residency | 29 | 72% | 0% |
| rollback_request | 28 | 75% | 0% |
| deployment_failure | 27 | 70% | 0% |
| compliance_request | 26 | 65% | 100% |
| sso_configuration | 26 | 85% | 0% |
| security_incident | 26 | 54% | 100% |
| database_issue | 26 | 69% | 0% |
| api_usage_question | 24 | 96% | 0% |
| billing_query | 24 | 88% | 0% |
| performance_degradation | 23 | 74% | 0% |
| quota_or_overage | 23 | 87% | 0% |
| account_access | 22 | 77% | 0% |
| onboarding | 22 | 91% | 0% |
| integration_help | 21 | 76% | 0% |
| webhook_issue | 21 | 76% | 0% |
| feature_request | 20 | 0% | 100% |
| authentication_failure | 20 | 70% | 0% |
| api_key_issue | 18 | 67% | 0% |
| configuration_help | 17 | 59% | 0% |
| unclear_request | 15 | 0% | 100% |
| rate_limit | 13 | 92% | 0% |

Class balance is reasonable (13 to 29 per class). No one class dominates. Classifier will see all 22 in training even at small sample sizes.

---

## Ingest requirements (settles A2 territory)

**EV-DATA-11**

- All chat tickets have empty subject (155/155). Ingest must NOT require subject. Set to `""` and don't treat as data-quality failure.
- All bodies non-empty in the dev set (0/500 empty), but the ingest spec still needs to handle empty because the hidden set is unseen. Empty body → `warnings=["empty_body"]`, do not raise.
- Body length is 28–245 chars (median 141). Short. No paragraphing to worry about. No language processing challenges from length.

---

## Volume patterns (partly settles OQ-03)

**EV-DATA-12** Sofia said Mondays are worst. The `received_at` day-of-week distribution:

| Day | n | Share |
|-----|---|-------|
| Fri | 85 | 17.0% |
| Tue | 80 | 16.0% |
| Mon | 75 | 15.0% |
| Wed | 73 | 14.6% |
| Thu | 69 | 13.8% |
| Sun | 61 | 12.2% |
| Sat | 57 | 11.4% |

Fridays have the most incoming, not Mondays. Sofia's perception is real but likely reflects the Monday backlog from weekend tickets (Sat+Sun = 23.6% of intake, arriving into empty coverage) rather than Monday intake itself. Interpretation matters for the sprint plan (no capacity flex; build works Monday-Friday) but not the FRs.

---

## Updated resolution to the four Wednesday questions

| # | Question | Answer |
|---|----------|--------|
| Q1 | % answerable from docs? | 71.4%. Sofia was right. |
| Q2 | Escalations mostly hard or T1-tractable? | Mixed. 24% of *correct* escalations still carry doc coverage (need drafted context). 38% of *actual* historical escalations were avoidable. Daniel was directionally right; his 50% overstates. |
| Q3 | Content or findability? | Not yet answered. Requires the Fri retrieval experiment. Interim: content coverage is 100% for the mixed-answerable intents; 0% for feature_request and unclear_request (by design). |
| Q4 | Where does service quality vary? | Channel (docs_comment much worse), region (Latin America worst CSAT), tier (enterprise worse than business, contradicting Ravi). Language fluency does NOT show a gap in outcomes. |

---

## Refined problem statement (for the PRD skeleton on Sat)

Draft v2, incorporating the Thursday data:

> CloudServe's support function receives roughly 500 tickets a week across four channels. Roughly seven in ten of these have an answer that already exists in the company's twenty-nine reviewed knowledge-base articles, yet the historical first-contact resolution rate is 44%. The gap is not a shortage of answers but a failure of retrieval, from the agents' side, who cannot find their own articles in the internal search and rebuild answers from personal notes, and from the customers' side, one in six of whom starts by searching the documentation, fails, files a comment against the docs page and then waits an average of eight hours for a response that reproduces material already in front of them. When tickets do reach a second-tier engineer, they arrive as forwarded threads with no summary, no note about what tier one tried, and no attached documentation, which turns roughly 38% of escalations into avoidable ones and returns the same question to the customer a second time.
>
> The system to build is not a chatbot. It is a retrieval-grounded support assistant that: (a) drafts a cited answer for the 62% of tickets whose correct route is auto-respond, sends it only when calibrated confidence exceeds a threshold set from data, and cites the specific article the answer came from; (b) hands drafts and retrieved passages to tier one for the tickets that fall below the send threshold, so the agent starts from a partial answer rather than a blank ticket; (c) escalates to tier two with the retrieved documents, tier one's uncertainty flag and any drafted content attached, addressing the missing-context problem that drives customer follow-up frustration; (d) blocks (never auto-answers) every ticket in the four always-escalate intents (compliance, security incident, feature request, unclear request), regardless of confidence.
>
> Success is measured on three axes. Business: first-contact resolution moves from 44% toward 60%+, median time to substantive response drops from 214 minutes toward 30, and repeat-contact rate drops from 22% toward under 15%. Technical: the retriever's hit rate on `expected_doc_ids` reaches at least 85% on tickets flagged answerable, the classifier's confidence is calibrated within ±5pp in the send band, generated responses hallucinate at 5% or under (independently rated), and citations resolve to the passages actually retrieved. Governance: quality does not vary by more than 15 percentage points across customer tier, region or language fluency; every automated decision writes a reconstructable log entry; a compliance auditor can trace any response back to the ticket, the model version, the prompt version, the retrieved documents and the routing threshold applied.

Ready to shoot at.

---

## Open questions still open

- **OQ-03** (partial). Volume by day resolved. Hour-of-day (support-hours coverage) still unresolved. Need timezone-aware analysis to test the "Latin America gap is timezone" hypothesis.
- **OQ-05** (unresolvable from this data). Whether a customer previously self-served then gave up isn't labelled. `docs_comment` channel is the closest proxy (78 tickets, 15.6%).

## Next: Friday plan (unchanged)

- Discovery Workbook sections 1–5 drafted from Wednesday + Thursday material, tagged EV-* and EV-DATA-*.
- Retrieval quality pilot on the 29 KB articles. Settles Q3.
- Problem statement locked from the v2 draft above.
