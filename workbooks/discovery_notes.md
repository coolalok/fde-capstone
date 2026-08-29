# Discovery Notes — Stakeholder Interviews

**Read date:** 2026-08-26 (Wed, W1D1)
**Source:** `docs/Stakeholder_Interviews.docx`, five transcripts.
**Purpose:** raw evidence for Stage 1 workbook. To be triangulated against the 500 dev tickets on Thu.

---

## The five voices, in one line each

| # | Person | Role | The line that matters most |
|---|--------|------|----------------------------|
| 1 | Marcus Adeyemi | Head of Support | *"I would rather it said nothing than said something wrong."* |
| 2 | Sofia Restrepo | Tier 1 agent | *"Seven out of ten I could answer without looking anything up… searching [the docs] is painful, so most of us do not."* |
| 3 | Daniel Okonkwo | Tier 2 engineer | *"About half of what reaches me is something tier one could have resolved if they had been confident, or if they had found the right page."* |
| 4 | Ines Varga | Tech writer | *"Internally, I do not think the support team uses [the docs] at all, and it took me a year to work out that this was happening."* |
| 5 | Ravi Menon | Customer | *"If I know a person wrote it I will act without checking. If I know a machine drafted it I will verify first. Hiding that would be the thing that annoys me."* |

---

## Claims to keep (to be tagged with EV-01, EV-02, … in the workbook)

### Volume, pace, structure
- **EV-M1** 500+ tickets/week, 6 agents. SLA 2h, actual 8–12h. FCR 42% (industry benchmark quoted 65%). Escalation costs about 4× a resolved ticket. Source: Marcus.
- **EV-S1** Queue is 40–70/day per agent, Mondays worst. Agents sort by age (SLA breach fear). Source: Sofia.
- **EV-S2** Known-pattern tickets take 4–5 min; unusual can take 40 min and still escalate. Source: Sofia.
- **EV-D1** Escalations arrive as a forwarded ticket with no summary, no note about what was tried. Duplicate customer questions follow. Source: Daniel.

### What the tickets actually are
- **EV-S3** About 70% are patterns Sofia has seen the same month. Examples cited: password lockouts, rate limits, invoice questions, deployment rollbacks. Source: Sofia.
- **EV-I1** 29 KB articles cover: auth, deployment, API, billing, data, security, account. Externally used a lot; internally, not at all. Source: Ines.
- **EV-I2** Search matches titles and exact terms. Customers describe problems in different words than the article titles. Example: *"my deployment keeps dying"* against *"resolving container health check failures"*. Source: Ines.
- **EV-D2** Every agent has a private snippet file. Daniel's is "better than mine" (Sofia). Some entries are 2+ years old and no longer correct. Source: Daniel + Sofia.

### Fairness signals
- **EV-S4** Non-fluent English tickets take longer; agents misread the question, answer the wrong one, round-trip; "worst satisfaction scores and I do not think anyone has noticed". Source: Sofia.
- **EV-R1** Enterprise customers get about 1h reply; business plan customers wait longer. "If this change makes that gap bigger, we will notice at renewal." Source: Ravi (customer, business plan).

### What "success" looks like from each seat
- **EV-M2** Marcus: FCR up is more important to him than reply-time down, though the latter is what's contractually tracked. Source: Marcus.
- **EV-S5** Sofia's ideal: system hands her a **draft + the relevant doc**, not full auto-answer. "Would save me half of every ticket." Source: Sofia.
- **EV-D3** Daniel's ideal on escalations: ticket + what T1 thought + retrieved docs + specific point of uncertainty. Source: Daniel.
- **EV-R2** Ravi's tolerance: automation is fine if it (a) is honest about being automated, (b) states uncertainty, (c) cites its source, (d) a human confirms. Source: Ravi.

### What must not happen
- **EV-M3** Confidently wrong answers. Customers are engineers, screenshots go public within the hour. Source: Marcus.
- **EV-M4** Enterprise service must not visibly regress against current baseline. Source: Marcus.
- **EV-M5** Compliance review in autumn requires explainability (why each action was taken). Source: Marcus.
- **EV-D4** Never automate on: security, billing disputes (contractual), data location (compliance). Source: Daniel.
- **EV-I3** Feature requests, roadmap and timing questions, and novel incidents have no article to retrieve. A system that answers anyway is doing the wrong thing. Source: Ines.

---

## Disagreements to settle with ticket data on Thu

| # | The disagreement | Who says what | Where to look in the data |
|---|-------------------|---------------|---------------------------|
| Q1 | What % of incoming tickets are answerable from the 29 KB articles? | Marcus: doesn't know. Sofia: about 70%. Ines: a lot externally, none internally. | `labels.answerable_from_docs` across the 500 dev tickets. |
| Q2 | Are escalations mostly hard cases, or mostly T1-tractable ones that lacked confidence or findability? | Marcus (implicit): they must be hard, that's what T2 is for. Daniel: about half are avoidable. | Cross tabulate `labels.expected_route=escalate` × `labels.answerable_from_docs=true` × `history.escalated=true` and read the bodies for a sample. |
| Q3 | Is the problem the documentation content or the ability to find it? | Ines heard the former; Sofia meant the latter. | Retrieval quality experiment on Fri. Chunk the 29 docs, run against 500 tickets, check hit-rate on `expected_doc_ids`. |
| Q4 | Is there a service-quality gap by language fluency, tier, or region? | Sofia (fluency), Ravi (tier: business vs enterprise). | Segment `history.first_contact_resolution` and `history.csat_rating` by `language_fluency`, `customer_tier`, `customer_region`. |

---

## What nobody said outright (the through-line)

Marcus asked for a chatbot because that's the mechanism he can picture. What the five interviews together describe is a different failure mode:

**The answers to most tickets already exist inside 29 reviewed articles, but the people who need those answers can't find them.** So agents rebuild answers from memory or private snippet files (which drift, some by years), tier one under-answers when uncertain, escalations arrive to tier two without context, tier two spends time re-reading what tier one already read, and the customer waits eight to twelve hours to receive an answer they could have retrieved themselves in ten minutes.

A "chatbot" that generates answers from a language model without solving retrieval scales the underlying problem. What the system should be is **retrieval, drafting, and escalation-context**. Same LLM techniques, but shaped by what's broken.

This is what the problem statement should say. Testing it: does each stakeholder agree with the part of it that touches their world?

- Marcus: yes. FCR up because agents (or the system) find the right answer first time.
- Sofia: yes. Her hand-off is *draft + doc*, not "the machine replies for me".
- Daniel: yes. Escalations arrive with context, he moves 2× faster.
- Ines: yes. Her articles finally get used internally.
- Ravi: yes. Automation is honest, cited, calibrated, human-confirmed.

None of them could have written that sentence on their own. That's the discovery.

---

## Open questions to resolve later

- **OQ-01** What are the 22 intent classes? (Extract from `development_tickets.json` on Thu.)
- **OQ-02** True documentation-category count. Dataset Guide says 8, lists 10 names.
- **OQ-03** Time-of-day and day-of-week distribution. Sofia says Mondays worst; is that Monday US or Monday customer-local?
- **OQ-04** What fraction of tickets carry `must_not_auto_respond=true`? Sets the floor on escalation rate.
- **OQ-05** Is there any signal in the data for "customer previously self-served the docs then gave up and raised a ticket"? Ravi implied that's common.

---

## For the problem statement draft (Sat)

Rough shape, in the client's words:

> CloudServe's support team receives more than five hundred tickets a week, and about three-quarters of those have an answer that already exists inside the company's own knowledge base. Agents cannot find those answers reliably, so they either reconstruct them from memory or personal notes, or pass the ticket on. The result is a service that is slower than promised, resolves fewer than half of incoming tickets on first contact, and (because escalations arrive without context) passes the customer's question back to the customer a second time. Customers accept waiting for hard problems; they don't accept waiting hours for information they could have retrieved themselves.
>
> The system to build is not a chatbot. It is a retrieval-first assistant that: (a) drafts a cited answer for tickets whose answer exists in the KB and where confidence is high enough to send it, (b) hands the drafted answer to a tier one agent as a starting point when confidence is borderline, and (c) enriches escalations with everything a tier two engineer needs to skip re-reading the thread. Every response cites the article it came from and states its uncertainty. Every decision is logged so that the autumn compliance review can trace what happened and why.

To be tested on Thursday against the ticket data, and revised before it's written into Stage 1.
