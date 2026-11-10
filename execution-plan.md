# Execution plan — MapleRoute

**Question this file answers:** what is the sequence from validation to pilot?

Structure: phase → milestone → task → subtask. Nothing is built; every script, command and environment is **proposed**. Estimates are author proposals in hours. Owners: **Founder-S** (sales and delivery), **Founder-E** (engineering), **Counsel** (privacy lawyer, one hour `[C]`), **Customer** (the vendor's CTO). With one founder both founder roles are the same person. Requirements: [PRD.md](PRD.md#must-haves). Risks: [verification-report-fixing.md](verification-report-fixing.md#production-risk-register).

## Phase map

| Phase | Purpose | Weeks | Gate to enter |
|---|---|---|---|
| 0 | Validation and go-to-market, by hand | 1–13 | None |
| 1 | Specification and design | 14 | **T-0.6.1 records "Build"** |
| 2 | Environment and schema | 15–16 | Milestone 1.1 |
| 3 | Gateway core | 16–18 | Milestone 2.2 |
| 4 | Control plane | 18–20 | Milestone 3.1 |
| 5 | Evidence | 20–22 | Milestone 4.1 |
| 6 | Verification and hardening | 22–23 | Milestone 5.1 |
| 7 | Pilot on the gateway, release and operations | 24 onward | Milestone 6.1 |

No task in phases 1–7 starts before T-0.6.1 records "Build" under the three-row rule in [Decision.md](Decision.md#93-proposed-revision-p--a-change-to-the-rules-above-not-a-restatement). The only specification work done earlier is the hand-pilot grade catalogue (T-0.4.4), which the pilot itself needs. Weeks assume about 30 engineering hours a week beside sales.

**Critical path:** T-0.1.1 → T-0.1.2 → T-0.3.1 → T-0.4.1 → T-0.4.3 → T-0.4.4 → T-0.5.1 → T-0.6.1 → T-2.1.3 → T-2.2.1 → T-3.1.1 → T-3.1.3 → T-3.1.4 → T-4.1.4 → T-4.1.5 → T-6.1.1 → T-7.1.3.

**Parallel work:** T-0.2.1 beside T-0.1.2; T-0.4.3 and T-0.4.4 beside outreach; T-3.1.5 beside T-3.1.4; phases 4 and 5 if a second developer joins.

**External dependencies:** T-0.3.1 on the legal gate (T-0.1.1). T-0.5.2 on a paid invoice and read-only access. T-0.5.3 on the customer's questionnaire. T-5.1.5 on a customer's CloudTrail grant. T-5.2.1 on a Stripe account. T-7.1.3 on a customer's role or reader assignment and its decision to put the gateway in its request path.

## Phase 0 — Validation and go-to-market

First milestone achievable with a spreadsheet, an email account and a static page. Volumes, rates and hours are those of [Decision.md](Decision.md#12-go-to-market-plan): 300 contacts, 50 a week.

### Milestone 0.1 — Legal gate and list
Entry: none. Dependencies: Counsel. Owner: Founder-S. Outcome: 300 verified contacts and a prospect count. Exit: counsel's answers filed; list complete; count recorded.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-0.1.1 | Outreach law; Quebec wording | Founder-S, Counsel | 3–4 | One-page outreach rules | Counsel has answered: consent basis per channel; LinkedIn messages; referral messages; the Quebec sentence; pilot data-handling page | (a) send questions with [Decision.md](Decision.md#124-channel-and-sequence); (b) record answers; (c) fix the message footer |
| T-0.1.2 | Prospect list | Founder-S | 30–36 | Spreadsheet of 300 | Every row has company, evidence of an LLM feature, evidence of a public-sector or health customer, contact, URL where the address is published, date seen | (a) pull companies from the sources; (b) qualify; (c) find the published address; (d) drop rows with a no-solicitation notice |
| T-0.1.3 | Distinct reachable prospects | Founder-S | 3–5 | A count with method | Count of qualified vendors per source after de-duplication; stated as lower bound | (a) de-duplicate across sources; (b) record rejected rows and reason |

### Milestone 0.2 — Free availability map
Entry: none. Owner: Founder-S. Outcome: a dated one-page map. Exit: published; re-read weekly.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-0.2.1 | Offer step 1 `[C]` | Founder-S | 10–14 | Map v1 | Every row cites a provider page and date; non-eligible rows show destinations; caveat line present | (a) re-read SRC-01, 02, 06, 07, 09, 10; (b) call `ListInferenceProfiles` and `GetInferenceProfile` from MapleRoute's own AWS account in both Canadian Regions; (c) record differences from pages |
| T-0.2.2 | Publication | Founder-S | 2–4 | Static page and inquiry address | Page hosted where no visitor data is stored outside Canada, or uses a mail link only | (a) publish; (b) test the inquiry path |
| T-0.2.3 | Upkeep | Founder-S | 24–26 | Weekly dated revision | 12 revisions in 12 weeks; each change logged | (a) Monday re-read; (b) note changes; (c) tell pilots |

### Milestone 0.3 — Outreach cohort
Entry: milestone 0.1 exit. Owner: Founder-S. Outcome: 300 first touches in 6 weeks. Exit: all sent and followed up; reply log complete.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-0.3.1 | First touches | Founder-S | 20–24 | 50 messages a week, weeks 1–6 | Each carries identification, address, contact and unsubscribe; send log kept | (a) personalise; (b) send; (c) log |
| T-0.3.2 | Follow-ups and replies | Founder-S | 14.5–18 | One follow-up each; replies answered in one business day | Unsubscribes honoured the same day and logged | (a) follow up after 5 business days; (b) answer; (c) book calls |
| T-0.3.3 | Backup channel | Founder-S | 4–6 | Two conversations with privacy consultants | Notes on whether they see RQ-C or RQ-D clauses | (a) ask for introductions; (b) explain referral terms `[C]` |

### Milestone 0.4 — Discovery and questionnaire coding
Entry: first reply. Owner: Founder-S. Outcome: calls held and clauses coded. Exit: every call has notes against the five discovery questions `[C]`; at least 3 questionnaires requested.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-0.4.1 | Discovery calls | Founder-S | 10.8–14 | Call notes | Each records: models and clouds used; who asked about residency; whether own cloud settings suffice (yes or no, in their words) | (a) ask the questions; (b) show the map; (c) offer the pilot |
| T-0.4.2 | Metric M-1 | Founder-S | 3–6 | Coding sheet | Each AI-location clause coded RQ-A to RQ-F with the clause text; no customer names leave the sheet; questionnaires per meeting recorded | (a) collect; (b) code; (c) second coding on the review call |
| T-0.4.3 | Location of pilot working tools (MH-11 by hand) | Founder-S | 2–3 | Register rows for every tool that will hold a questionnaire or a configuration record: laptop, mail, spreadsheet, storage, VPS | Each row has provider, legal entity, data location and evidence; a tool without evidence is not used for pilot material; the customer sees the list in the data-handling page | (a) list tools; (b) get provider evidence; (c) replace or exclude unknowns |
| T-0.4.4 | Grade catalogue v0 and pack template (MH-07 by hand) | Founder-S | 3–4 | One page fixing EG-1 to EG-5 per answer type, and the pack template with its "Not evidenced" section | Every answer type the first questionnaire needs has one grade; counsel has seen the template | (a) take the table in [Decision.md](Decision.md#43-evidence-grades); (b) add answer types; (c) template |

### Milestone 0.5 — Hand-run paid pilot
Entry: a vendor says yes **and T-0.4.3 and T-0.4.4 are done**. Dependencies: payment, access, questionnaire. Owner: Founder-S. Outcome: S1 and S2 delivered on time. Exit: review call held; conversion decision recorded.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-0.5.1 | Pilot agreement and invoice | Founder-S, Customer | 2–4 | Signed agreement, data-handling page, paid CAD 500 invoice | Terms equal [Decision.md](Decision.md#5-offer-channel-pilot); payment received before day 1 | (a) send; (b) sign; (c) invoice; (d) confirm tax status |
| T-0.5.2 | S1 configuration record | Founder-S, Customer | 4–6 | Record of every in-scope profile and deployment | Each row: identifier, destinations or `sku.name` as returned by the provider, eligible or not; delivered by day 10 | (a) read through a read-only role or screen share; (b) hand over the L2 policy templates; (c) re-read after the customer applies them; (d) record the state and destination of the customer's own invocation or diagnostic logging |
| T-0.5.3 | S2 evidence pack | Founder-S | 10–14 | Answers to the questionnaire's AI-residency items | Every answer carries a grade; a "Not evidenced" list is included; delivered by day 20 | (a) draft; (b) privacy lead reviews; (c) revise |
| T-0.5.4 | Review and conversion | Founder-S, Customer | 1–2 | Day-25 call notes | Records M-1, M-3 so far, M-6, tier chosen or reason for stopping, and what "CAD 249" should mean if raised | (a) hold call; (b) record; (c) invoice the tier or close |

### Milestone 0.6 — Decision
Entry: day 90 or cohort exhausted. Owner: Founder-S. Outcome: Stop, Continue or Build. Exit: signed decision record.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-0.6.1 | Stop rule | Founder-S | 3–4 | Decision record | Applies the table in [Decision.md](Decision.md#93-proposed-revision-p--a-change-to-the-rules-above-not-a-restatement) to the logged counts; states the fixed-cost breakdown and which budget applies | (a) tally; (b) decide; (c) file |
| T-0.6.2 | Hosting location record for the build decision | Founder-S | 1–2 | T-0.4.3's register extended to the VPS, domain host and every planned production service | Provider, legal entity, data-centre city and evidence for each; anything unknown is marked "Location not evidenced" and kept out of the data path | (a) export provider details; (b) fill rows |

## Phase 1 — Specification and design

### Milestone 1.1 — Frozen contracts
Entry: T-0.6.1 "Build". Owner: Founder-E. Outcome: four documents. Exit: each reviewed against two real questionnaires.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-1.1.1 | MH-02 | Founder-E | 4–6 | Allow-list document format and eligibility rule | UT-01 fixtures written from it | (a) schema; (b) canonical serialisation; (c) first version from the map |
| T-1.1.2 | MH-03 | Founder-E | 3–4 | Error contract | Every code has a trigger and a `forwarded` value | (a) table; (b) example bodies |
| T-1.1.3 | MH-07, MH-11 | Founder-E | 6–8 | Grade catalogue for software line types, extending T-0.4.4 | Each line type has one fixed grade and source; records whether Azure returns a per-request region, and which deployment timestamps and activity-log events a reader can see | (a) list line types; (b) assign grades; (c) check Azure response headers, timestamps and activity log on a test deployment |
| T-1.1.4 | Screens S-01 to S-15; R-20 | Founder-E | 8–12 | Wireframes | Labels match [design.md](design.md); every route in the inventory has a frame | (a) draw; (b) walk the PRD mistake scenario |

## Phase 2 — Environment and schema

### Milestone 2.1 — Repository and environments
Entry: T-0.6.1 "Build". Owner: Founder-E. Outcome: a deployable empty system in `ca-central-1`. Exit: health checks green in local and staging.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-2.1.1 | R-03, R-04, R-06 | Founder-E | 4–6 | Package layout with `core` and an import-boundary check | A deliberate cross-import fails the check | (a) layout; (b) rule; (c) shared config and utilities only in `core` |
| T-2.1.2 | R-17 | Founder-E | 4–6 | One local start command with health checks | IT-18 | (a) compose file; (b) provider stubs; (c) readiness endpoints |
| T-2.1.3 | AD-02, AD-08; R-15 | Founder-E | 12–18 | Network, endpoints, egress proxy, key, database, bucket | IT-20 against every row of [TRD.md](TRD.md#egress-destinations); register rows produced from API reads | (a) private subnets; (b) VPC endpoints; (c) proxy allow-list per process; (d) deny cross-region copy |
| T-2.1.4 | Quality | Founder-E | 4–6 | Pipeline: lint, tests, image build, deploy to staging | A failing test blocks deploy | (a) workflow; (b) secrets in the platform store |
| T-2.1.5 | R-22 | Founder-E | 1–2 | Branch and release rules in `AGENTS.md` | Protected `main`; stale-branch report | (a) protection; (b) naming rule |

### Milestone 2.2 — Schema
Entry: milestone 2.1. Owner: Founder-E. Outcome: schema of [schema.md](schema.md) applied. Exit: IT-14 and IT-08 pass on an empty system.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-2.2.1 | MH-09; R-05 | Founder-E | 10–14 | Migrations, roles, row-level security | A session without tenant setting reads zero rows | (a) tables; (b) policies; (c) role grants; (d) immutability triggers |
| T-2.2.2 | R-08 | Founder-E | 3–5 | ORM parity check | A removed index fails the check | (a) build from migrations; (b) compare |
| T-2.2.3 | R-09, R-10, R-11 | Founder-E | 4–6 | Migration safety checks | Two heads fail; a non-concurrent index on a large table fails; an interrupted backfill resumes | (a) head check; (b) lint rule; (c) backfill helper |

## Phase 3 — Gateway core

### Milestone 3.1 — Fail-closed forwarding
Entry: milestone 2.2. Owner: Founder-E. Outcome: stub requests forwarded only on eligible routes. Exit: IT-01 to IT-04 and IT-09 pass.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-3.1.1 | MH-02, MH-03 | Founder-E | 6–9 | Allow-list loader and evaluator | UT-01 to UT-03 | (a) load and hash check; (b) evaluator; (c) `Decision` type |
| T-3.1.2 | MH-01, MH-09 | Founder-E | 5–8 | Key authentication and tenant context | UT-04 | (a) hash lookup; (b) set tenant; (c) rate limit |
| T-3.1.3 | MH-06; AD-04; R-01 | Founder-E | 6–9 | Audit-before-forward and state machine | UT-05, IT-04 | (a) insert; (b) compare-and-set updates; (c) trigger |
| T-3.1.4 | MH-01 | Founder-E | 10–14 | Bedrock adapter | IT-01, IT-02 | (a) role assumption; (b) translation; (c) streaming |
| T-3.1.5 | MH-01, MH-05 | Founder-E | 8–12 | Azure adapter | IT-01 on Azure stub | (a) decrypt in memory; (b) translation; (c) reject stateful parameters |
| T-3.1.6 | MH-03 | Founder-E | 8–12 | Error mapping, timeouts, no-retry rule | IT-03 | (a) codes; (b) timeouts; (c) drop provider message text |
| T-3.1.7 | R-02 | Founder-E | 3–5 | Outcome sweeper and late reconciliation | IT-09 | (a) job; (b) late update path |
| T-3.1.8 | R-07, R-12 | Founder-E | 4–6 | `core.logging` with field allow-list and correlation ID | UT-07, IT-18 | (a) logger; (b) propagate ID into jobs |

## Phase 4 — Control plane

### Milestone 4.1 — Console to first verified route
Entry: milestone 3.1. Owner: Founder-E. Outcome: a user can go from sign-in to a verified binding. Exit: E2E-01, E2E-02 pass.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-4.1.1 | MH-09 | Founder-E | 6–9 | Sign-in and sessions (S-01, S-15) | New token per sign-in; sign-out invalidates; UT-13 | (a) OIDC with PKCE, state, nonce; (b) session store and cookie attributes; (c) timeout warning; (d) operator claim check and re-authentication |
| T-4.1.2 | MH-09 | Founder-E | 5–8 | Tenants, members, roles (S-02, S-13 members) | UT-12 | (a) onboarding; (b) invitations; (c) role checks |
| T-4.1.3 | MH-01 | Founder-E | 5–8 | Projects and keys (S-03, S-04, S-07) | Key shown once | (a) screens; (b) show-once panel |
| T-4.1.4 | MH-05 | Founder-E | 10–14 | Connections and custody (S-05) | IT-07 | (a) policy templates; (b) envelope encryption; (c) connection test |
| T-4.1.5 | MH-04; R-01 | Founder-E | 10–14 | Verification job | UT-06, UT-10, IT-05 | (a) Bedrock read; (b) Azure read; (c) ordering rule; (d) two mismatch kinds; (e) resume needs newer match |
| T-4.1.6 | MH-04 | Founder-E | 6–9 | Routes screen and record (S-06) | E2E-02 | (a) two tables; (b) reason lines |
| T-4.1.7 | MH-06 | Founder-E | 6–9 | Request log screens and export (S-08) | E2E-05 | (a) filters in URL; (b) export job |
| T-4.1.9 | MH-04, MH-15; AD-02 | Founder-E | 6–9 | L2 confirmation, Azure change look-back, logging-state reads | IT-21, IT-22 | (a) AWS role policy read and simulation; (b) Azure policy assignment and exemption read; (c) timestamps and activity log; (d) window flagging; (e) logging configuration |
| T-4.1.8 | MH-02, MH-08 | Founder-E | 8–12 | Operator console (S-14) | UT-02, E2E-04 | (a) draft and diff; (b) two-step approval; (c) suspend and resume |

## Phase 5 — Evidence

### Milestone 5.1 — Report and watch
Entry: milestone 4.1. Owner: Founder-E. Outcome: a report whose lines all carry grades. Exit: IT-10, IT-11, IT-15 to IT-17 pass.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-5.1.1 | MH-11 | Founder-E | 5–8 | Register and daily refresh (S-11) | A missing location withholds the report | (a) API reads; (b) drift alert |
| T-5.1.2 | MH-07; R-19 | Founder-E | 12–18 | Report generator (S-10) | UT-08, IT-16 | (a) totals; (b) grades; (c) PDF, JSON, CSV; (d) withheld state |
| T-5.1.3 | MH-08 | Founder-E | 8–12 | Availability watcher (S-12, S-14) | IT-17 | (a) fetch and hash; (b) extract; (c) diff |
| T-5.1.4 | MH-10 | Founder-E | 4–6 | Alerts (S-09) | IT-10 | (a) suspension; (b) hourly summary; (c) de-duplicate |
| T-5.1.5 | MH-13; R-19 | Founder-E | 8–12 | Bedrock reconciliation | IT-11 | (a) CloudTrail read; (b) match; (c) incident path |
| T-5.1.6 | MH-12; R-14 | Founder-E | 6–9 | Retention purge, export, tenant deletion | IT-15 | (a) partition drop; (b) export clean-up; (c) resumable deletion; (d) restore replay |
| T-5.1.7 | R-13, R-16 | Founder-E | 2–4 | Object keys and public links | UT-11 | (a) key builder; (b) link builder from public base URL |

### Milestone 5.2 — Billing
Entry: first conversion. Owner: Founder-E. Outcome: plans charged. Exit: IT-19, UT-09 pass.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-5.2.1 | MH-14 | Founder-E | 8–12 | Metering and Stripe | Rejected requests not counted | (a) monthly counts; (b) subscription; (c) webhook |

## Phase 6 — Verification and hardening

### Milestone 6.1 — Evidence that it fails closed
Entry: milestone 5.1. Owner: Founder-E. Outcome: all planned tests run and recorded. Exit: zero off-list forwards and zero canary hits; results entered in the verification file.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-6.1.1 | MH-03; highest-consequence failure | Founder-E | 6–9 | Fail-closed suite against real test accounts | IT-03 and IT-21 on staging: providers refuse through L2 as well | (a) apply L2 templates; (b) attempt `us.` and Global; (c) remove the policy, swap the deployment, restore; (d) record what the reader could and could not see |
| T-6.1.2 | MH-06; R-12 | Founder-E | 4–6 | Canary scan | IT-06 | (a) send canaries; (b) scan database, logs, bucket, restored backup |
| T-6.1.3 | MH-09; R-05 | Founder-E | 4–6 | Tenant-isolation suite | IT-08 | (a) API; (b) worker; (c) files |
| T-6.1.4 | Accessibility | Founder-E | 4–6 | Manual pass of the map in [design.md](design.md#accessibility-map) | E2E-06 recorded per criterion | (a) keyboard; (b) screen reader; (c) contrast |
| T-6.1.5 | Quality targets | Founder-E | 4–6 | Load and latency run | IT-12 | (a) stub upstream; (b) measure |
| T-6.1.6 | Restore | Founder-E | 3–5 | Restore drill | IT-13 | (a) restore; (b) replay deletions; (c) time it |
| T-6.1.7 | R-18, R-20 | Founder-E | 3–5 | Navigation and link checks | E2E-05, E2E-07 | (a) Back, refresh, deep links; (b) crawl routes |

## Phase 7 — Pilot on the gateway, release and operations

### Milestone 7.1 — First customer traffic
Entry: milestone 6.1; a customer agrees to route one non-critical feature `[C]`. Owner: Founder-E. Outcome: 30 days of traffic with S3 met. Exit: first monthly report issued.

| ID | Need | Owner | Hours | Deliverable | Acceptance check | Subtasks |
|---|---|---|---|---|---|---|
| T-7.1.1 | Release, rollback | Founder-E | 4–6 | Runbook; tagged release | Rollback rehearsed on staging | (a) tag; (b) migrate; (c) roll; (d) roll back |
| T-7.1.2 | Monitoring | Founder-E | 4–6 | Alerts of [TRD.md](TRD.md#7-deployment-view) wired to the founder's phone | Each alert fired once in staging | (a) metrics; (b) external probe; (c) paging |
| T-7.1.3 | MH-01 to MH-13 in use | Founder-E, Customer | 3–5 | Customer connected; one feature routed | First eligible request logged; one deliberate ineligible request rejected and seen by the customer | (a) role or reader; (b) bind; (c) key; (d) switch base URL |
| T-7.1.4 | Incident response | Founder-E | 3–5 | Runbook incl. region incident | Table-top run of the highest-consequence failure | (a) suspend; (b) notify; (c) report note |
| T-7.1.5 | R-21 | Founder-S | 1–2 | Scope review | Every merged feature maps to an MH or a pilot need; others removed or listed | (a) list; (b) decide |

## Estimate summary

| Phase | Hours, low–high |
|---|---|
| 0 (with 1.296 expected pilots) | 155–204 |
| 1 | 21–30 |
| 2 | 42–63 |
| 3 | 50–75 |
| 4 | 62–92 |
| 5 | 53–81 |
| 6 | 28–43 |
| 7 | 15–24 |
| **Build, phases 1–7** | **271–408** |

The brief's estimate is 100 hours or 13 days `[C]`. That covers a proxy with a block list and a log; it does not cover verification, custody, the register, reconciliation or tests. At the brief's rate of 7.7 hours a day `[D]` the range is 35–53 working days. At CAD 100 an hour `[C]` it is CAD 27,100–40,800 of founder time.

## Proposed scripts

| Script | Purpose | Inputs | Outputs | Failure behaviour |
|---|---|---|---|---|
| `make dev` | Start database, three processes and stubs | none | Health check summary | Non-zero exit naming the unhealthy service |
| `tools/check_migrations` | Linear history, lock-safe statements | Migration directory | Pass or list of violations | Blocks merge |
| `tools/orm_parity` | Compare models with a migrated database | Database URL | Differences | Blocks merge |
| `tools/canary_scan` | Search stores for canary strings | Canary list, store locations | Hit list | Any hit fails the release |
| `tools/publish_allowlist` | Validate and hash a draft | Draft file | Version, hash | Refuses a route that fails the rule; never activates |
| `tools/restore_drill` | Restore and replay deletions | Snapshot ID | Timing, row counts | Stops before switch-over on mismatch |
| `tools/link_check` | Crawl console routes per role | Base URL, role sessions | Broken links, 5xx | Blocks release |

## Planned tests

All **Not run**. Fixtures are synthetic.

### Unit

| ID | Fixture | Action | Expected |
|---|---|---|---|
| UT-01 | Routes: `ca.` profile with two Canadian destinations; `us.` profile; `global.`; empty destinations; Azure `GlobalStandard`; unknown provider | Evaluate | Only the first is eligible |
| UT-02 | Draft with one US destination | Publish | Refused, naming the route |
| UT-03 | Active version with altered byte | Load | `policy_unavailable` |
| UT-04 | Valid, revoked, malformed keys | Authenticate | 200 path, 401, 401 |
| UT-05 | Every state pair | Transition | Only the listed transitions succeed |
| UT-06 | Mismatch at 10:00 then match stamped 09:55 arriving late | Apply | Route stays suspended |
| UT-07 | Log call given body and authorization header | Emit | Neither field in output |
| UT-08 | Report line type without a grade | Build | Fails |
| UT-09 | 500,000 forwarded and 20,000 rejected on Starter | Bill | 3 overage units = CAD 30; rejected ignored |
| UT-10 | `GetInferenceProfile` answer with three model ARNs | Parse | Three Regions |
| UT-11 | Tenant, kind, period; internal host configured | Build key and link | Key starts with tenant ID; link uses the public host |
| UT-13 | ID tokens: wrong nonce; wrong issuer; same email from the other provider; operator token without multi-factor claim; invitation with a different verified email | Sign in or accept | All refused; the same-email identity gets no access to the first identity's tenant |
| UT-12 | Role × action matrix | Authorise | Matches [PRD.md](PRD.md#users-and-roles) |

### Integration

| ID | Fixture | Action | Expected |
|---|---|---|---|
| IT-01 | Verified binding to a stub | Chat request | 200; row `completed` with route and version |
| IT-02 | Streaming stub; client disconnects midway | Stream | Chunks pass unbuffered; row `client_aborted` |
| IT-03 | 50 ineligible inputs: unbound alias, `us.` identifier, Global deployment, suspended route, `store: true` | Send each | Contract code; stub records **zero** outbound calls |
| IT-04 | Database stopped | Send request | 503 `audit_unavailable`; zero outbound calls |
| IT-05 | (a) Bedrock binding last matched 25 hours ago; (b) tenant A's Azure deployment reports GlobalStandard; (c) a `ca.` profile reports a US destination; (d) operator tries to resume | Send; run verifier | (a) `route_unverified`; (b) `config_mismatch`: A's binding un-verified, tenant B on the same route unaffected; (c) `definition_mismatch`: route suspended for A and B; (d) refused until a newer match exists |
| IT-06 | Prompt, response and Azure secret containing canaries | Send; dump database, logs, bucket, restored backup | Zero hits |
| IT-07 | Console database role | Select ciphertext; decrypt | Denied; denied |
| IT-08 | Tenants A and B | B's session and key on A's IDs; job for A reads B | 404; zero rows |
| IT-09 | Stub answers after the client timed out; sweeper runs first | Observe | `unknown_outcome`, then `completed` with `reconciled_at` |
| IT-10 | Mismatch at time T | Observe alerts | Alert sent by T + 5 minutes; one alert, not many |
| IT-11 | CloudTrail fixture, 1,000 events, one out-of-set Region, 10 duplicates, one failing page | Reconcile twice | One incident; no double counts; failed page reported and retried |
| IT-12 | Stub upstream, 20 requests a second for 10 minutes | Load | p95 added latency ≤ 50 ms; zero off-list |
| IT-13 | Snapshot plus a later deletion | Restore drill | Service back within 2 hours; deleted tenant absent |
| IT-14 | Backfill killed midway; two migration heads; model missing an index | Run checks | Resumes; fails; fails |
| IT-15 | Tenant with exports and 14-month-old rows | Purge; delete | Old partitions gone; export files gone; deletion resumable after a kill |
| IT-16 | 10,000 rows incl. 12 unknown outcome; register row without location | Generate twice | Totals equal the log; unknown listed separately; second run identical; `withheld` |
| IT-17 | Provider page fixture changed | Watch | Difference recorded; allow-list unchanged |
| IT-18 | Clean machine; containers with read-only file systems | `make dev` | All health checks green; worker starts without web packages; the three processes print the same hash of shared constants |
| IT-19 | Same Stripe event twice | Webhook | One change |
| IT-20 | Each staging process | Connect to one listed host and one unlisted host | Listed succeeds; unlisted refused |
| IT-21 | Verified Azure binding; between two checks the fixture removes the deny policy, re-creates the deployment as Global Standard under the same name, then (variant) restores both | Send requests throughout; run checks | Variant 1: next check gives `config_mismatch`, binding un-verified, requests since the last match flagged. Variant 2: change detected from timestamps or activity log, same flags. Variant 3, the swap happens and every later check fails (`access_failed`): requests keep flowing until 60 minutes after the last matching check, then get `route_unverified`; an alert fires after the second failed check; the report prints the failed checks and a longest served time of 60 minutes. Report prints flagged count and longest served time in all variants |
| IT-22 | Connection without the L2 policy; connection whose invocation logging writes to a US bucket; AWS role with `bedrock:*` on all resources | Bind and verify | Never `verified`; reasons `l2_missing`, `logging_outside_canada`, `role_too_broad` |

### End to end

| ID | Fixture | Action | Expected |
|---|---|---|---|
| E2E-01 | New owner, test AWS account | Sign in → connect → bind → key → request | First eligible request visible in S-08 |
| E2E-02 | Azure deployment named `gpt-4o-canada`, type Global Standard | Register; then redeploy as Standard | "Not eligible" with the reported type; then `verified` |
| E2E-03 | Reviewer | Open S-07; download a report | 403; file with hash matching S-10 |
| E2E-04 | Operator removes a route used by one tenant | Approve in two steps | Tenant gets `allowlist_change_notice` at approval; version cannot activate for 7 days; after activation requests are rejected with `route_not_eligible` |
| E2E-05 | S-05 to S-10 | Back, Forward, refresh, deep link, double submit | State preserved; one record per submit |
| E2E-06 | Keyboard and screen reader | Walk the accessibility map | Each criterion recorded pass or fail |
| E2E-07 | Each role | Crawl navigation | No dead links; labels match the inventory |
