# AGENTS.md — MapleRoute

Canonical instructions for any agent or developer working in this repository. [CLAUDE.md](CLAUDE.md) adds product-specific guidance and defers to this file.

**State of the repository:** ten planning documents plus build milestone B1 (branch `feat/b1-foundation`, 2026-11-11): `backend/` holds the deterministic core (allow-list, `forwardable`, verification, request log, tenancy), a gateway, a minimal console API and a worker, all against in-memory fakes for AWS, Azure, KMS, alerting and sign-in. No real provider integration, sign-in, report, deployment or infrastructure exists. The owner's authorisation to build before T-0.6.1, and what was tested, are in [verification-report-fixing.md](verification-report-fixing.md#2a-build-milestone-b1-2026-11-11). Every command not marked "exists" below is **proposed**; do not report a command as run unless you ran it and it exists.

## Reading order

1. [Decision.md](Decision.md) — whether to build at all; labels, sources, evidence grades, economics, go-to-market.
2. [PRD.md](PRD.md) — must-haves `MH-01`–`MH-15`, roles, metrics.
3. [TRD.md](TRD.md) — eligibility rule, error contract, architecture decisions `AD-01`–`AD-14`.
4. [App-flow.md](App-flow.md) and [design.md](design.md) — screens `S-01`–`S-15`.
5. [schema.md](schema.md) — tables, roles, retention.
6. [execution-plan.md](execution-plan.md) — tasks `T-…`, tests.
7. [verification-report-fixing.md](verification-report-fixing.md) — traceability, risks `R-01`–`R-22`, findings.

## Sources of truth

| Subject | File |
|---|---|
| Labels, sources, evidence grades, prices, funnel, stop rule | Decision.md |
| Requirements and acceptance criteria | PRD.md |
| Eligibility rule, error contract, jobs, security table | TRD.md |
| Screens and routes | App-flow.md |
| Wording, components, accessibility map | design.md |
| Data model, permissions, retention | schema.md |
| Tasks, estimates, tests | execution-plan.md |
| Risk register, traceability, findings, outstanding items | verification-report-fixing.md |

State each fact once and cite it by ID elsewhere. Do not restate a risk; cite `R-nn`.

## Product boundaries

- A deterministic policy proxy, a console and a report. No AI function. No model hosting.
- Phase 0 (sales by hand) comes before any build task. Do not start phases 1–7 until task T-0.6.1 records "Build".
- Non-goals are listed in [PRD.md](PRD.md#non-goals). A feature without an `MH` reference is not built (R-21).

## Architecture conventions (proposed)

- Three processes (`gateway`, `console`, `worker`) import only from `core` (R-03, R-04, R-06).
- `listed` and `forwardable` each have one implementation in `core`. Never add a second check elsewhere.
- A customer-side mismatch changes one binding; a provider-definition mismatch changes the route for all tenants. Never mix the two.
- Every outbound destination must be a row in the egress table of TRD.md before code calls it.
- Every failure path rejects. There is no fallback route and no automatic upstream retry.
- The request log row is committed before forwarding (AD-04).
- Request and response bodies, provider credentials and provider error text never reach a log, a database column, a file, a trace or a report (AD-05).
- All MapleRoute resources live in `ca-central-1`. Adding any service, tool or copy elsewhere requires a register row first (MH-11).
- Configuration is read in `core.config` only.

## Reuse

Before writing a helper, search `core`. Region parsing, key hashing, object keys, public links, logging and tenancy each have exactly one implementation.

### Utilities index (`backend/core`, B1)

| Need | Module | Notes |
|---|---|---|
| Configuration, Canadian Region set, classes, validity, intervals, constants hash | `core.config` | The only place environment variables are read |
| Route key, eligibility rule `listed`, canonical serialisation, hash, publish check | `core.allowlist` | Pure |
| `forwardable` and the sealed `Decision` | `core.eligibility` | Only `evaluate` builds a `Decision` |
| Publish, approve, activate, load the active version | `core.policy_store` | Versions never edited |
| Error codes, HTTP status, `forwarded` flag, messages | `core.errors` | Matches [TRD.md](TRD.md#error-contract) |
| Request log insert, transitions, sweep | `core.requestlog` | Compare-and-set; trigger enforces the same |
| Verification checks and applying one outcome per mismatch kind | `core.verification` | |
| Azure route-line figures and wording | `core.window` | |
| Tenant context | `core.tenancy` | Transaction-local setting |
| Structured logging, field allow-list, correlation ID | `core.logging` | No web imports |
| Key generation and hashing | `core.keys` | |
| Envelope encryption, key service interface | `core.crypto` | Fake key service only |
| Secret wrapper that never prints | `core.secretvalue` | |
| Bedrock ARN Region parsing | `core.regions` | |
| Provider interfaces | `core.providers` | |
| Fakes for every provider interface | `core.fakes` | Tests and local start only |
| Alerts with de-duplication; pager interface | `core.alerts` | |
| Job table enqueue, claim, retry | `core.jobs` | |
| Audit events | `core.audit` | |
| Clock | `core.clock` | Tests set it |
| Per-binding advisory lock (worker exclusive, gateway shared); per-binding check lease (one check at a time, `CHECK_LEASE` timeout) | `core.locks` | Orders decisions against a mismatch being applied; checks of one binding never overlap (B1-003) |

### Commands

| Command | Status |
|---|---|
| `make dev` (migrate dev database, start gateway :8110, console :3110, worker; health summary) | Exists (B1); runs processes directly, no Compose |
| `make smoke`, `make test`, `make lint`, `make typecheck`, `make check-imports`, `make orm-parity`, `make check` | Exist (B1) |
| `tools/orm_parity` (`python -m tools.orm_parity`) | Exists (B1) |
| `tools/check_imports`, `tools/db_bootstrap`, `tools/dev` | Exist (B1) |
| `tools/check_migrations`, `tools/canary_scan`, `tools/publish_allowlist`, `tools/restore_drill`, `tools/link_check` | Proposed |

## Tenant safety

- Every tenant table carries `tenant_id` and a row-level security policy.
- The tenant is set once per request or job by `core.tenancy`, from the authenticated key or session. Never from a request parameter.
- Foreign identifiers return 404. Object keys start with the tenant ID.
- Operator views show names and counts only.

## Migrations

One linear history. Schema changes and backfills are separate. Indexes on large tables are built concurrently. Models and migrations must match (R-08 to R-11). Details: [schema.md](schema.md#migrations).

## Tests

- Any change to forwarding, adapters or the LiteLLM version must pass IT-03 (zero outbound calls for ineligible inputs) and IT-06 (zero canary hits).
- Any change to tenancy must pass IT-08.
- A report line type without a grade must fail the build (UT-08).
- Use synthetic fixtures only. Never use a real customer prompt, key or account ID.

## Git hygiene

- `main` is protected; work on short-lived branches named `type/short-topic`; releases are tags (R-22).
- Never commit credentials, tokens, account IDs of real customers or real questionnaires.
- The root holds the ten planning documents plus `.gitignore`, `Makefile` and `backend/` (B1). Scratch files, checkers and briefs stay outside it.
- Do not rewrite history on shared branches.

## What to update when something changes

| Change | Update |
|---|---|
| A requirement | PRD.md (must-have, metric); traceability matrix; execution-plan.md task and test; App-flow.md if a screen changes |
| A screen or route | App-flow.md inventory; design.md; traceability matrix; E2E tests |
| A permission or role | PRD.md roles; schema.md roles; TRD.md security table; UT-12 |
| A table, column, index or retention period | schema.md; TRD.md if a job changes; migration tests |
| The eligibility rule, a Canadian Region or a deployment class | TRD.md eligible routes; Decision.md section 4.1; UT-01; a new allow-list version, never an edit |
| An error code | TRD.md error contract; App-flow.md API client flow; design.md microcopy; IT-03 |
| A subprocessor, hosting location or tool | Decision.md section 4.3; schema register tables; S-11; outstanding items |
| A price, rate, volume or budget | Decision.md sections 6–9 and 12 together; re-run the arithmetic; PRD.md metrics |
| A provider page that changed | Decision.md section 4.1 with the new date; the map; an allow-list version if eligibility changes |
| A risk | The register in verification-report-fixing.md only |

## Accurate completion reporting

- Say what was done, what was not, and what was not verified. "Planned" is not "implemented"; "implemented" is not "tested".
- Never describe provider documentation or a configuration read as proof of processing location. Use the grades.
- Never write "compliant", "certified" or "guaranteed" about security, accessibility or residency.
- If a test was not run, write **Not run**.
- Findings `F-nnn` are assigned by the independent reviewer; authors record fixes and do not set retest results.
