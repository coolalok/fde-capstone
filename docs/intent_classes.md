# The 22 ticket types

The list of 22 ticket types the classifier will choose from, plus a 23rd fallback called `unknown`. This file has three kinds of content mixed together and it matters which is which — the table just below spells it out.

## Where each piece of this file comes from

| What's in this file | Where it came from | How we know |
|---|---|---|
| The 22 type names | **From the source data** — the `labels.intent` field in `data/development_tickets.json` | A one-line Python count on the 500 tickets returns exactly these 22 names |
| The ticket count per type (`n = ...`) | **From the source data — measured** | Same one-line count, 500 tickets |
| Dataset facts — 500 tickets, 22 unevenly-distributed types | **From the pack** — `docs/Dataset_Guide.docx` Table 9 | Read from the pack |
| The **operational definitions** of each type (the "What it means" column below) | **Written by us** — the pack does not define the type codes anywhere. Each definition was inferred from the code name plus a small sample of real tickets carrying that label | Sanity-checked against real ticket bodies at time of writing (Week 2 Day 1) for the five types we were least sure of: `unclear_request`, `feature_request`, `rollback_request`, `compliance_request`, `quota_or_overage`. None of the checks contradicted the definition. Unverified for the other 17 (probably fine, but worth flagging that they weren't checked). |
| The rule about when to return `unknown` vs `unclear_request` | **Our design decision** — informed by requirement FR-05 | Rationale below; adopted for this project only |
| The "types most likely to be confused" list at the bottom | **Our guess** — analysis based on reading the definitions | **Not yet checked against real classifier behaviour.** Backlog item B-16 (the D-05 threshold sweep next week) will produce the actual confusion matrix. Some of our guesses will be validated, some will turn out to be nothing, and pairs we haven't listed will probably show up. Treat this section as candidates to watch, not settled fact. |

**Rule:** every ticket resolves to exactly one of the 23 values. Adding a new type is a schema change — bump `PR-CLASSIFY-01` version and update this file in the same commit.

## The 22 known types (names and counts from the source; definitions written by us)

| Code                     | # tickets | What it means — our working definition |
|--------------------------|-----------|----------------------------------------|
| `account_access`         | 22        | Locked out of the account, can't reset password, invitation link expired, unable to switch accounts. Similar to but different from `authentication_failure`. |
| `api_key_issue`          | 18        | API key rotation, revocation, accidental exposure in a repo, scope changes, permission errors from a valid-looking key. |
| `api_usage_question`     | 24        | "How do I call endpoint X?", "what does field Y mean in the response?", "is this rate limit per key or per account?" These are education requests, not something-is-broken. |
| `authentication_failure` | 20        | Login rejected despite correct credentials, MFA code rejected, SSO redirect loop, session token invalidated too soon. |
| `billing_query`          | 24        | Invoice questions, charge disputes, credit card update, missing receipts, pro-ration on plan change. |
| `compliance_request`     | 26        | Audit log export for SOC 2, ISO or GDPR; data processing agreement questions; subprocessor list; retention policy questions. Example tickets we checked: DEV-0003, DEV-0013, DEV-0021 — all "auditor asked for access records" or retention questions. |
| `configuration_help`     | 17        | Environment variables not applying, override precedence, feature flag not visible, config drift between environments. |
| `data_export`            | 29        | GDPR/CCPA data subject request, bulk export of customer records, format conversion (JSON to CSV) for a scheduled export. |
| `data_residency`         | 29        | "Where is our data stored?", "can it be pinned to the EU region?", changes to residency configuration, cross-region replication questions. |
| `database_issue`         | 26        | Query timeouts, replication lag, unexpected migration behaviour, connection pool exhaustion. |
| `deployment_failure`     | 27        | Build or deploy pipeline fails, dependency resolution errors, environment-specific breakage, blue-green switchover problems. |
| `feature_request`        | 20        | "Please add X." Support can't do anything with these — they route to product. Always escalates. Example tickets: DEV-0005 ("Please add per-project spend caps"), DEV-0007. |
| `integration_help`       | 21        | Webhook signature verification, third-party OAuth flow, SDK setup for a specific language, custom-app callback URL setup. |
| `onboarding`             | 22        | First-time setup, workspace creation, inviting the first teammate, working through the initial getting-started guide. |
| `performance_degradation`| 23        | Response times degraded, latency spikes, throughput below expected, retries increasing but not obviously an outage. |
| `quota_or_overage`       | 23        | **Spend caps stopping production workloads** (the dominant pattern we saw in DEV-0044, DEV-0048, DEV-0064), unexpected overage charges, requests to raise a cap, "we'd rather pay overage than be throttled" framing. Similar to but different from `rate_limit`. |
| `rate_limit`             | 13        | The API returned a 429 rate-limit error; unclear which limit was hit (per-second / per-minute / per-account); request to raise a limit temporarily. |
| `rollback_request`       | 28        | User wants to revert to an earlier configuration, deployment, or product version. Sometimes framed as "how do I undo my last change?" Example tickets: DEV-0004, DEV-0009 ("How do I revert to the previous revision"), DEV-0030 ("Bad release in production"). |
| `security_incident`      | 26        | Suspected unauthorised access, phishing attempt against the account, leaked credentials, request for a security audit report. |
| `sso_configuration`      | 26        | New SAML or OIDC identity provider setup, SSO metadata update, group-to-role mapping, just-in-time provisioning problems. |
| `unclear_request`        | 15        | The ticket doesn't describe a specific problem or ask. Example tickets: DEV-0091 ("Urgent help needed / Nothing is loading properly today"), DEV-0120 ("It is not working"), DEV-0134 ("it not working. Please help."). Can't be classified further. |
| `webhook_issue`          | 21        | Webhooks not firing, delivery failures, retry backoff not working, HMAC signature check failing, ordering guarantees. |

## The fallback

- `unknown` — the classifier is not confident enough that the ticket fits any of the 22 codes above. Not the same as `unclear_request`. `unclear_request` is a *deliberate* label for tickets that a human would also read as incoherent (see the DEV example tickets above). `unknown` is the classifier's own admission that it couldn't decide (per FR-05). The router treats both the same way — escalate — but the decision log records them separately, so we can tell later how often the classifier was stuck versus how often the ticket was genuinely unclear.

## When to use `unknown` vs `unclear_request` (our design decision)

Per FR-05, `unknown` is reserved for two cases:

1. The AI model provider failed or returned malformed output. The classification code (`src/classify.py`) issues `unknown` programmatically. The AI model never has to know.
2. The AI model read the ticket and returned `unknown` as its own answer with confidence at or below 0.2, meaning "I don't have enough signal to pick one of the 22."

If the ticket is coherent and the AI model would clearly pick `unclear_request` (as opposed to being paralysed between two options), the answer is `unclear_request`, not `unknown`.

## Types most likely to be confused — this is a guess, not a measurement

Below are the pairs we predict will trip up the classifier — the "top guess and second guess will be close" cases. **This has not been measured yet.** The B-16 confusion matrix from the D-05 threshold sweep next week will produce the real pairs. Some of these will be validated, some will turn out to be non-issues, and pairs we haven't listed will probably show up. The three test cases in `PR-CLASSIFY-01` should cover at least one of these pairs. After B-16 this section is updated with measured pairs and the "guess" caveat comes out.

- `account_access` vs `authentication_failure` — "I'm locked out of my account" versus "I can't log in with the right credentials"
- `api_key_issue` vs `authentication_failure` — a rejected key versus a rejected session
- `api_usage_question` vs `integration_help` — "how does X work?" versus "my X isn't working"
- `configuration_help` vs `deployment_failure` — bad environment variable versus the build that fails because of it
- `quota_or_overage` vs `rate_limit` — hit a spend cap versus hit a per-minute rate cap
- `onboarding` vs `configuration_help` — first-time setup versus later configuration changes
- `security_incident` vs `authentication_failure` — a suspicious login versus a legitimate rejection
- `data_export` vs `compliance_request` — a bulk export versus a GDPR or audit-driven export

For tickets in these bands, the classifier's `alternatives` list is expected to be non-empty — but even that expectation is a guess, not a measurement.

## Changelog

- 2026-08-31 v1.0 — first pass. Names and counts verified from source; definitions and the confusion-pair list written by us. Sanity-checked 5 types against real tickets.
- 2026-08-31 v1.1 — added the "Where each piece came from" table at the top so a reader can tell which content is from the source and which was written by us. Renamed the definition column to say "What it means — our working definition". Renamed the confusion-pair section to say "our guess, not a measurement". Added example ticket IDs for the 5 types we sanity-checked. Refined the `quota_or_overage` definition to lead with the actual dominant pattern (spend caps stopping production) rather than the generic "monthly quota" wording, based on tickets DEV-0044, 48, 64. Added example ticket IDs to `unclear_request` and `feature_request`.
- 2026-08-31 v1.2 — rewrote in plainer language. All 22 type names, counts, DEV ticket IDs, requirement IDs and file paths preserved.
