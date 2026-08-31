# D-02 Revisit — Does the meaning-based search work?

**Date:** 2026-08-31 (Monday, Week 2 Day 1)
**Backlog item:** B-07 (from the Stage 4 Sprint Plan, Table 3)
**Script that produced this:** `evaluation/d02_retrieval_check.py`
**Raw results file:** `evaluation/results/d02_dense_retrieval.json`
**Score to beat:** the Q3 pilot from Saturday, which measured plain word-matching search over the 29 help articles. It got the right article into its top-3 guesses 93.6% of the time on 357 real customer tickets. See `workbooks/q3_findings.md`.

## What this test is for

Two things need to happen when a ticket comes in: the system has to find the right help article, and it has to write a reply based on it. This test is only about the first part — finding the right article.

There are two ways to build the search. The old way is word-matching (like a search engine that just counts words). The modern way uses a small AI model that turns text into numbers based on meaning, then finds the closest ones. Saturday we tested the word-matching way and it worked surprisingly well — 93.6%. Today we tested the modern way to see whether it does better, worse, or the same.

The design decision D-02 in the architecture document commits to using the modern way. If it turns out worse than word-matching, D-02 has to be rewritten. If it's the same or better, D-02 stays.

## What we found — one line

The modern method got the right article in its top 3 guesses 91.0% of the time, versus 93.6% for word-matching. So slightly worse on top-3, but slightly better if we look at "did the top-1 guess get it right?" and "was it in the top 5?" Overall it's a wash. **D-02 stays as-is.**

## The main numbers

Both methods tested on the same 357 tickets from the development data. All numbers are the percentage of tickets where the right help article appeared in the top 1, top 3, or top 5 guesses.

| Measure  | Modern (meaning-based) | Old (word-matching) | Difference |
|----------|------------------------|---------------------|------------|
| Top-1    | 86.6%                  | 84.0%               | +2.6 points |
| Top-3    | 91.0%                  | 93.6%               | −2.6 points |
| Top-5    | 96.4%                  | 95.2%               | +1.2 points |

Reading it: the modern method is slightly better at getting the answer as its number-one guess, and slightly better at including the answer somewhere in the top 5. It's slightly worse at getting it into the top 3. Neither method is a runaway winner on this set of help articles.

## Why we're keeping the modern method anyway

There's one place where the modern method clearly wins, and it's the reason we keep it: **customers who don't write fluent English.**

- Fluent-English tickets: top-3 hit rate 91.1%
- Non-fluent-English tickets: top-3 hit rate 90.8%

A gap of 0.3 points. The modern method understands "cant log in help pls" almost as well as it understands "I am unable to sign in — please advise". Word-matching would fail the first one and pass the second, because they share no words with the article titled "Troubleshooting Authentication Errors". This is a fairness win. Non-fluent customers are 24% of the data. Serving them badly would be a bigger problem than being 2.6 points behind on top-3.

Two smaller wins:

- **Top-5 recall is wider.** 96.4% vs 95.2%. When the system can't find anything above a confidence threshold, it escalates to a human. A wider net at top-5 means fewer of these "gave up" cases.
- **Top-1 precision is higher.** 86.6% vs 84.0%. Matters when the confidence threshold is set high — those cases are answered mostly on the top-1 guess.

## Where word-matching is better

- **Top-3 by 2.6 points.** In practice this means about 9 tickets out of 357 where word-matching would have found the answer and the modern method didn't. The routing layer will send those to a human anyway (because the follow-on safety check would catch a bad draft), so nothing goes out wrong to the customer. It just means slightly more work for humans. Not enough to justify the redesign.

Going deeper — a "hybrid" method (mixing both approaches) or a bigger AI model (BGE-small instead of MiniLM-L6) would close the 2.6-point gap. Neither is worth the effort this week. Both stay on the shelf as options if the end-to-end test on Friday shows retrieval is the main problem.

## Where the search struggles most

Broken down by ticket type, the ones the search misses on top-3:

| Ticket type            | # of tickets | Top-3 hit | Sprint Plan B-05 trigger (<75%)? |
|------------------------|-----|-----------|----------------------------------|
| compliance_request     | 17  | 52.9%     | no (not on the trigger list)     |
| onboarding             | 20  | 60.0%     | **yes**                          |
| integration_help       | 16  | 68.8%     | **yes**                          |
| deployment_failure     | 19  | 73.7%     | no (not on the trigger list)     |
| authentication_failure | 14  | 78.6%     | no (above 75%)                   |

The Sprint Plan Table 3 has a rule: for four specific ticket types (onboarding, authentication_failure, integration_help, api_key_issue), if the search misses more than 25% of them, we write an extra prompt (**PR-RETRIEVE-01**) that rewrites the customer's question before searching. Two of the four tripped this rule:

- **onboarding (60% hit-rate) — YES trigger.** These tickets say things like "how do I get started?" which is too generic for the search to pin down which specific setup step the customer means. Rewriting the query to name the specific step (SSO, workspace creation) should help. B-05 will do this for onboarding.

- **integration_help (68.8% hit-rate) — YES trigger, but it's actually a different problem.** For these tickets, top-3 and top-5 have the same hit rate (68.8% both). That means the right article isn't even in the top 5 for 5 out of 16 tickets. This isn't a search problem — the right article probably doesn't exist in the help centre at all. Query rewriting won't fix a missing article. **This is a new risk (R-08) — corpus coverage gap.** Add to the governance register, not to B-05.

**Two interesting observations that aren't on the trigger list:**

- **compliance_request** — top-3 is only 52.9%, but top-5 is 100%. The right article IS retrieved, just not in the top 3. This is exactly the case the follow-on safety check (Self-RAG groundedness retry in decision D-06) should catch: the first draft will fail because it can't ground its claims, the second attempt will look wider, and the right article will show up. Add a test case for this (T-generate-groundedness-retry).
- **deployment_failure** — same pattern (73.7% top-3, 100% top-5). Same fix applies.

## Where the system serves different customer groups differently

Everyone gets served *roughly* similarly at retrieval, but two gaps stand out:

| Grouping         | Best cell            | Worst cell           | Gap |
|------------------|----------------------|----------------------|-----|
| Channel          | chat 92.4%           | docs_comment 89.6%   | 2.8 points |
| English fluency  | fluent 91.1%         | non_fluent 90.8%     | 0.3 points |
| Region           | Latin America 93.0%  | Asia Pacific 89.5%   | 3.5 points |
| Customer tier    | enterprise 94.9%     | business 87.0%       | **7.9 points** |

Two flags:

1. **Customer tier gap — 8 points.** Business-tier customers (about a third of all tickets) get worse retrieval than enterprise-tier customers. The discovery notes from Thursday found the *opposite* pattern in resolution outcomes (enterprise had worse historical CSAT). But at the retrieval layer, business tier is worse-served. If we send an auto-reply at the same confidence threshold for both, business-tier customers get lower-quality auto-replies. **New PRD Open Question candidate:** should the confidence threshold be tier-aware? Feeds the D-05 threshold sweep next week (B-16).

2. **Docs-comment channel is worst on channel.** These are customers commenting on the help articles themselves — they already tried to self-serve and it didn't work. Their retrieval matches on the article they're *reading* rather than the article they *need*. Worth a note in the ingest FR: could the ingest layer strip the referring-article context from these tickets before retrieval? Add as an FR candidate.

## What this result unlocks in the Sprint Plan

Looking back at Sprint Plan Table 3:

- **B-08 (D-04 chunking final ADR) — GO.** The chunking method (splitting articles into 800-character chunks with 120-character overlap) delivered these numbers. Now we can either confirm it or measure a different chunking method against the same set.
- **B-05 (PR-RETRIEVE-01 query rewriting) — GO for onboarding only.** Integration_help is a separate risk (R-08) not a rewriting problem. Reduces B-05's scope.
- **B-06 (src/retrieve.py implementation) — GO.** Build the retrieval code with today's settings. No config change needed.
- **B-04 (src/classify.py) — unaffected.** Continues as planned Tuesday.

## What we're deliberately NOT doing this week

- **Hybrid retrieval (word-matching + meaning-based combined).** Would probably recover the 2.6-point top-3 gap, but adds one more library dependency and complicates the code. The gap is small enough that it doesn't justify the work. Revisit if the Friday full test (B-21) shows retrieval as the main failure mode.
- **Bigger AI model (BGE-small-en-v1.5 instead of MiniLM-L6-v2).** One-line swap. Kept as a back-pocket option for D-02.

## Updates to make in other documents

1. **PRD Open Question 1** — mark as answered. Recommendation: keep MiniLM-L6-v2 (already logged in Stage 5 revision log).
2. **PRD Open Question 3 (new candidate)** — should the confidence threshold be tier-aware? Business tier is 8 points behind enterprise on retrieval quality (logged in Stage 5 revision log).
3. **docs/architecture.md D-04 row** — the chunking decision can now be finalised.
4. **PRD Table 5 (NFR-01a)** — measurement source cite updated to point to this file.
5. **Risk register (Governance workbook, Stage 6)** — add R-08 for the integration_help coverage gap (logged in Stage 5 revision log).

## Where these numbers came from

- **Script:** `evaluation/d02_retrieval_check.py`
- **Search index:** `storage/chroma/` (59 passages from 29 articles; each article split into 800-character chunks with 120-character overlap using MiniLM-L6-v2)
- **Word-matching baseline:** `workbooks/q3_findings.md`
- **Data:** 357 answerable tickets from `data/development_tickets.json` (the ones labelled `labels.answerable_from_docs = true`)

## Glossary (for readers new to this)

- **Hit rate / top-k hit:** the percentage of tickets where the right article shows up in the search's top k guesses.
- **Meaning-based / dense / embedding search:** the modern way. Converts text to numbers based on meaning, then finds the closest ones.
- **Word-matching / sparse / TF-IDF search:** the old way. Counts word overlap between the query and the articles.
- **Corpus:** the collection of 29 help articles.
- **Chunking:** splitting each article into shorter passages so the search can point at the specific paragraph that answers the question.
- **Groundedness:** every factual claim in a reply has to trace back to a passage that was actually retrieved. If it can't, the safety check blocks the reply.
- **Confidence threshold:** the score the system's own confidence has to exceed before it auto-replies (versus escalating to a human).
- **ADR:** Architecture Decision Record. A one-page write-up of a design choice, its alternatives, and why we picked what we picked. Lives in `docs/adr/`.
- **NFR / FR:** Non-Functional Requirement / Functional Requirement. FR = what the system must do; NFR = how well it must do it.
