# Discovery Notes — Stakeholder Interviews

**Read date:** 2026-08-26 (Wednesday, Week 1 Day 1)
**Source:** `docs/Stakeholder_Interviews.docx`, five transcripts.
**Purpose:** raw evidence for the Stage 1 workbook. To be checked against the 500 development tickets on Thursday.

**About the quotes below.** All quotes are from the transcripts. A three-dot ellipsis (…) means text was left out inside an answer. Square brackets like [the docs] mean a word was added or replaced to make the quote read as a stand-alone sentence. Where a quote joins two separate answers from the same person, it's labelled *[composite]* and both source questions are named. Numbers cited under evidence tags (EV-M1, EV-S1 and so on) were re-checked against the transcript on Monday of Week 2 and every one matched.

## What each of the five people said, in one line

| # | Person | Role | The line that matters most |
|---|--------|------|----------------------------|
| 1 | Marcus Adeyemi | Head of Support | *"I would rather it said nothing than said something wrong."* |
| 2 | Sofia Restrepo | Tier 1 agent | *[composite]* *"Seven out of ten I could answer without looking anything up… searching [the docs] is painful, so most of us do not."* — the first half is her answer to "What proportion are ones you have seen before?"; the second half is her answer to "If the answer is already known, where does the time go?" |
| 3 | Daniel Okonkwo | Tier 2 engineer | *"[In practice,] about half of what reaches me is something tier one could have resolved if they had been confident, or if they had found the right page."* |
| 4 | Ines Varga | Tech writer | *"Internally, I do not think the support team uses [the docs] at all, and it took me a year to work out that this was happening."* |
| 5 | Ravi Menon | Customer | *"If I know a person wrote it I will act without checking. If I know a machine drafted it I will verify first. Hiding that would be the thing that annoys me."* |

Each of them can see one part of the problem, and each of them is describing that part accurately. The interesting question is what those five parts add up to.

---

## The claims we want to keep

These are tagged EV-M<n>, EV-S<n> and so on. Each tag becomes a citation later — every requirement in the PRD points at one of these tags as its source of evidence.

### How much work, how fast, what shape

- **EV-M1** More than 500 tickets a week. Six agents. The service agreement says a first reply within 2 hours; actual replies take 8 to 12 hours. First-contact resolution (the ticket is fixed on the first reply, no back-and-forth) sits at 42%. The industry benchmark Marcus is measured against is 65%. Every escalated ticket costs about four times what a resolved one costs. Source: Marcus.
- **EV-S1** Each morning brings 40 to 70 tickets per agent. Mondays are worst. Agents sort by age because the oldest tickets are about to breach the 2-hour service agreement. Source: Sofia.
- **EV-S2** A ticket Sofia has seen before takes 4 to 5 minutes. An unusual one can take 40 minutes and still get escalated. Source: Sofia.
- **EV-D1** Escalations arrive as a forwarded ticket — no summary, no note about what tier 1 already tried. Daniel then has to ask the customer questions they already answered. Source: Daniel.

### What the tickets are actually about

- **EV-S3** About 70% of tickets are patterns Sofia has seen the same month. Examples she gave: password lockouts, rate limits, "why is my invoice higher", deployment rollbacks. Source: Sofia.
- **EV-I1** There are 29 help articles. They cover authentication, deployment, API, billing, data, security and account. Customers use them a lot. The support team, according to Ines, doesn't use them at all. Source: Ines.
- **EV-I2** The internal search matches on titles and exact words. Customers describe their problem in different words than the article titles. Example Ines gave: a customer writes *"my deployment keeps dying"* against an article titled *"resolving container health check failures"* — no words in common. Source: Ines.
- **EV-D2** Every agent has a private file of answers they've written before. Daniel's is "better than mine" (Sofia). Some entries in these files are two-plus years old and no longer correct. Source: Daniel + Sofia.

### Fairness — where the service quality already looks uneven

- **EV-S4** Tickets from customers whose first language isn't English take longer. Agents can misread the question, answer the wrong one, then have to go back and forth. "Those tickets have our worst satisfaction scores and I do not think anyone has noticed." Source: Sofia.
- **EV-R1** Enterprise customers get a reply in about 1 hour. Business-plan customers (like Ravi) wait longer. Ravi: "If this change makes that gap bigger, we will notice at renewal." Source: Ravi.

### What "success" looks like from each seat

- **EV-M2** Marcus cares about first-contact resolution going up more than about reply time going down. Reply time is what's in the contract, so it's what gets reported to executives. Source: Marcus.
- **EV-S5** Sofia's ideal: the system hands her a **draft plus the relevant help article**, not a full auto-answer. "Would save me half of every ticket." Source: Sofia.
- **EV-D3** Daniel's ideal on escalations: the original ticket, plus what tier 1 thought it was about, plus the relevant help articles, plus the specific point where tier 1 wasn't sure. Source: Daniel.
- **EV-R2** Ravi will accept an automated reply if it (a) is honest about being automated, (b) says how sure it is, (c) says where its answer came from, (d) is followed up by a human. Source: Ravi.

### What must not happen

- **EV-M3** Confidently wrong answers. CloudServe's customers are engineers — a screenshot goes public within the hour. Source: Marcus.
- **EV-M4** Enterprise service must not visibly get worse than it is today. Source: Marcus.
- **EV-M5** A compliance review is coming in the autumn. Every action the system takes has to be explainable. Source: Marcus.
- **EV-D4** Never send an automated reply for tickets about: security, billing disputes (those become contractual), data location (those become compliance). Source: Daniel.
- **EV-I3** Feature requests, roadmap questions and never-seen-before incidents have no help article to answer them. A system that invents an answer anyway is doing the wrong thing. Source: Ines.

---

## What the interviewees disagreed about — to be settled with ticket data on Thursday

| # | The disagreement | Who says what | Where to look |
|---|-------------------|---------------|---------------------------|
| Q1 | What percentage of tickets can be answered from the 29 help articles? | Marcus doesn't know. Sofia says about 70%. Ines says a lot from the customer side, none from the support team's side. | The label `answerable_from_docs` on the 500 development tickets. |
| Q2 | Are the escalated tickets mostly hard cases, or mostly tickets tier 1 could have handled if they were more confident or if they'd found the right article? | Marcus assumes hard (that's what tier 2 exists for). Daniel says about half are avoidable. | Cross-check `expected_route=escalate` against `answerable_from_docs=true` and read a sample. |
| Q3 | Is the underlying problem the quality of the help articles, or the ability to find them? | Ines heard "content is bad" (from a conversation with Sofia). Sofia actually meant "search is bad, content is fine". | A retrieval experiment on Friday — index the 29 articles, query with the 500 ticket bodies, see how often the right article comes back. |
| Q4 | Is there a service-quality gap by English fluency, tier, or region? | Sofia sees a fluency gap. Ravi sees a tier gap. | Cross-check `first_contact_resolution` and `csat_rating` against `language_fluency`, `customer_tier`, `customer_region`. |

---

## What none of them said outright — the through-line

Marcus asked for a chatbot because that's the mechanism he can picture. But the five interviews together describe a different problem.

**The answers to most tickets already exist inside the 29 reviewed help articles. The people who need those answers can't find them.**

Agents rebuild answers from memory or from personal note files (which drift, sometimes by years). Tier 1 under-answers when they're not sure. Escalations arrive at tier 2 without any context, so tier 2 has to read the whole thread and often ask the customer the same questions again. The customer waits 8 to 12 hours to receive an answer they could have retrieved themselves in 10 minutes.

A "chatbot" that just generates answers using a language model — without solving the finding-the-right-article problem — makes this worse, because it puts more confidently-worded wrong answers into the queue.

What the system should be is **retrieval, drafting, and escalation-context**. Same AI techniques as a chatbot, but shaped around what's actually broken.

That's what the problem statement should say. Test: does each stakeholder agree with the part of it that touches their world?

- Marcus: yes. First-contact resolution goes up because the right answer is found first time.
- Sofia: yes. Her hand-off is *draft plus article*, not "the machine replies for me".
- Daniel: yes. Escalations arrive with context. He works twice as fast.
- Ines: yes. Her articles finally get used internally.
- Ravi: yes. Automation is honest, cites its source, states its confidence, and is confirmed by a human.

None of them could have written that sentence on their own. That's the discovery.

---

## Open questions to resolve later

- **OQ-01** What are the 22 intent classes actually used in the ticket labels? (Extract from `development_tickets.json` on Thursday.)
- **OQ-02** How many categories does the help-article corpus really have? The Dataset Guide says 8, but lists 10 names.
- **OQ-03** Is Sofia right that Mondays are worst? Look at day-of-week distribution. Is her Monday US-time or customer-local?
- **OQ-04** What fraction of tickets are labelled `must_not_auto_respond=true`? This sets the floor on how many tickets must be escalated to a human no matter what.
- **OQ-05** Is there a signal in the data for "customer tried the docs, failed, then filed a ticket"? Ravi implied this is common.

---

## The problem statement — first draft, to test on Thursday

Rough shape, in the client's words:

> CloudServe's support team receives more than 500 tickets a week. About three-quarters of those have an answer that already exists in the company's own help articles. Agents cannot find those answers reliably, so they either reconstruct them from memory or personal notes, or pass the ticket on. The result is a service that is slower than promised, resolves fewer than half of incoming tickets on the first reply, and — because escalations arrive without context — passes the customer's question back to the customer a second time. Customers accept waiting for hard problems. They don't accept waiting hours for information they could have retrieved themselves.
>
> The system to build is not a chatbot. It is a retrieval-first assistant that: (a) drafts a cited answer for tickets whose answer exists in the help articles and where the confidence is high enough to send it; (b) hands the drafted answer to a tier 1 agent as a starting point when confidence is borderline; (c) enriches escalations with everything a tier 2 engineer needs, so they don't have to re-read the ticket from scratch. Every response cites the article it came from and says how confident it is. Every decision is logged so the autumn compliance review can trace what happened and why.

To be tested on Thursday against the ticket data, and revised before it's written into Stage 1.

---

## Changelog

- 2026-08-26 v1.0 — first pass from Wednesday interview reading.
- 2026-08-31 v1.1 — added the "About the quotes" note at the top; labelled Sofia's headline quote as *[composite]* (it joins her answers to two separate questions) with both source questions named inline; added the `[In practice,]` bracket to Daniel's headline quote so the elided prefix is marked rather than silent. All eight numeric evidence claims (EV-M1, S1, S2, S3, I1, I2, D2, R1) were re-checked against the transcript verbatim — no numbers changed. Motivation: the Data Fidelity rule was added to `capstone-conventions` after a paraphrase was caught in `PR-CLASSIFY-01`'s test-case body. See that file's changelog.
- 2026-08-31 v1.2 — rewrote the document in plainer language so a non-technical reader can follow it, without changing the meaning or any of the evidence tags. Terms of art like "retrieval", "chunking", "expected_route" now come with a short in-line gloss. All EV tags, numbers, and file paths preserved.
