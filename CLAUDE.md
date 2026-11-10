# CLAUDE.md — MapleRoute

Read [AGENTS.md](AGENTS.md) first; it is canonical. This file adds what is specific to this product.

## The buyer's workflow

A CTO at a small Canadian software vendor is asked by a municipal or health customer where AI prompts are processed. The vendor's engineer connects the vendor's own AWS or Azure account, binds a model alias to a route that the provider reports as Canada-only, and points the application at MapleRoute. The privacy lead downloads a monthly report and attaches it to the questionnaire. The decisive question for the whole repository is in [Decision.md](Decision.md#44-which-requirement-is-unmet): which requirement do the customer's own cloud controls and Trango leave unmet?

## Highest-consequence error

**Silent out-of-Canada serve reported as Canadian.** A request is processed outside Canada while the log and report say it stayed in Canada. Eight ways it can happen and the control for each are in [TRD.md](TRD.md#highest-consequence-failure-sequence). Treat any change that touches forwarding, the allow-list, verification, or report wording as a change to this risk.

## Sensitive data

| Data | Rule |
|---|---|
| Customers' prompts and responses | Pass through memory only. Never stored, logged, hashed, traced or sampled. No debug switch |
| Customers' provider credentials | AWS: role assumption, nothing stored. Azure: envelope-encrypted, decrypted only in the gateway and worker. Never displayed after entry |
| Project API keys | Stored as a hash; shown once |
| Request metadata | Tenant-scoped; reveals usage patterns; kept in `ca-central-1` |
| Questionnaires collected in sales | Customer confidential; never committed here |

## Prohibited shortcuts

- Do not add a fallback, a retry on another route, or a "best effort" mode. Reject.
- Do not accept a customer's description of a deployment in place of the provider's API answer.
- Do not infer Canadian processing from a profile prefix, a deployment name or a host name.
- Do not enable LiteLLM routing, fallbacks, caching, callbacks or message logging.
- Do not log request bodies, headers carrying credentials, or provider error text, even temporarily.
- Do not write "proof", "guaranteed" or "verified in Canada" in the interface, a report or a sales message. Use the grades EG-1 to EG-5.
- Do not put the founder's VPS, or any host whose location is not evidenced, in the data path. If its location is unknown or outside Canada the residency statement is false.
- Do not mark a binding verified unless the customer-side deny policy (L2) was read in place at that check.
- Do not describe an Azure route as continuously confirmed. State the true bound: 15 minutes while checks succeed, up to 60 minutes when they fail.
- Do not say the operator cannot access credentials. Say no application path exposes them and administrator access is logged.
- Do not edit an allow-list version. Publish a new one.
- Do not send outreach before the legal gate (T-0.1.1), and never to an address found only by a tool.
- Do not imply Canada-only means Quebec-only.
- Do not begin build tasks before T-0.6.1.

## First verification checks when implementation begins

1. IT-03: fifty ineligible inputs, zero outbound calls on the stub.
2. IT-04: database down, request rejected with `audit_unavailable`, zero outbound calls.
3. IT-06: canary strings in a prompt, a response and an Azure secret; zero hits in the database, logs, bucket and a restored backup.
4. T-6.1.1 on real test accounts: with the generated IAM policy applied, AWS itself refuses a `us.` profile; with the Azure policy applied, a Global deployment cannot be created.
5. IT-05 and IT-21: a stale check rejects; a customer-side mismatch un-verifies that binding only; a provider-definition mismatch suspends the route for every tenant; an Azure deployment swapped between checks is caught and its requests flagged.
6. IT-08: one tenant cannot read another's rows or files.
7. IT-16: a register row without a location withholds the report.

Before relying on anything in [Decision.md](Decision.md#41-what-keeps-inference-in-canada-today-read-2026-11-10), re-read the provider pages: the tables are dated 2026-11-10 and providers change them.
