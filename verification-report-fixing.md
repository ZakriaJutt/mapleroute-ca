# Verification, report and fixing — MapleRoute

**Question this file answers:** what passed, what failed, and what remains untested?

Until 2026-11-10 this repository contained planning documents only. Build milestone B1 (2026-11-11) added a backend with migrations and tests; what ran is recorded in [section 2a](#2a-build-milestone-b1-2026-11-11). Every other application check below is planned and marked **Not run**. A planned control is not evidence of compliance. A provider's documentation is not proof of where a request was processed.

IDs: must-haves `MH-01`–`MH-15` ([PRD.md](PRD.md#must-haves)); screens `S-01`–`S-15` ([App-flow.md](App-flow.md#screen-and-route-inventory)); architecture decisions `AD-01`–`AD-14` ([TRD.md](TRD.md#9-architecture-decisions)); tasks `T-…` and tests `UT-`, `IT-`, `E2E-` ([execution-plan.md](execution-plan.md#planned-tests)); risks `R-01`–`R-22` (this file); author self-checks `SC-…` (this file); review findings `F-001…` (this file, reserved for the independent reviewer).

**Highest-consequence failure (same name as in [PRD.md](PRD.md#highest-consequence-failure) and [CLAUDE.md](CLAUDE.md)):** silent out-of-Canada serve reported as Canadian.

## 1. Checks performed on the documents and repository

Performed by the author on 2026-11-10 before hand-off and re-run after fix round 1 (SC-11). This is a self-check, not an independent review. Details are in the [self-check log](#author-self-check-log-not-independent-review).

| Check | Result |
|---|---|
| Exactly ten required files, nothing else | Done (SC-01) |
| Internal links and anchors resolve | Done (SC-02) |
| Every ID referenced is defined | Done (SC-03) |
| Every must-have is in the traceability matrix | Done (SC-04) |
| 22 risk rows, each with an existing task | Done (SC-05) |
| Screens, routes, tables, endpoints and tasks agree across files | Done (SC-06) |
| Arithmetic re-run by script | Done (SC-07) |
| Brief figures quoted exactly; departures recorded | Done (SC-08) |
| Primary sources opened today | 22 opened, 1 blocked (SC-09) |
| No credentials, no real customer data, diagrams in Mermaid | Done (SC-10) |

Not checked by the author: rendering on GitHub; whether a fresh reader can use the documents; the legal reading of any statute.

## 2. Application checks planned for future implementation

All **Not run**.

| Area | Tests | Status |
|---|---|---|
| Eligibility and allow-list | UT-01, UT-02, UT-03 | Ran in B1, passed (section 2a) |
| Fail-closed forwarding | IT-03, IT-04, IT-20 | IT-03, IT-04 ran in B1 against the provider stub, passed; IT-20 Not run |
| Normal forwarding and streaming | IT-01, IT-02 | IT-01 passed on the stub; IT-02 passed with a simulated disconnect (section 2a) |
| Verification, mismatch kinds and suspension | UT-06, UT-10, IT-05, IT-10 | UT-06, UT-10, IT-05 passed on fakes; IT-10 partly (alert rows, no delivery) |
| Customer-side policy, Azure change window, customer logging state | IT-21, IT-22 | Passed on fakes (three IT-21 variants); not on real accounts (T-6.1.1) |
| Sign-in, identity and operator access | UT-13 | Partly, B2 (section 2b): the local provider's parts ran and passed (invitation with a different verified email refused; operator without a second factor or a recent authentication refused). The OIDC parts (nonce, issuer, same email from the other provider) Not run: OIDC deferred |
| No content or credential persistence | UT-07, IT-06, IT-07 | UT-07 passed; IT-06 partly (database, application and server logs; bucket and restored backup Not run); IT-07 partly since fix round 1 (ciphertext refused to the console role; KMS decrypt Not run) |
| Tenant isolation and roles | UT-12, IT-08 | IT-08 passed (rows, API, job; files since B2 against MinIO, section 2b); UT-12 passed in B2 |
| Request state and timeouts | UT-05, IT-09 | Passed |
| Report and register | UT-08, IT-16 | Not run |
| Reconciliation | IT-11 | Not run |
| Watcher | IT-17 | Not run |
| Retention, deletion, restore | IT-13, IT-15 | Not run |
| Migrations | IT-14 | Partly: ORM parity part passed; head check and backfill resume Not run |
| Performance | IT-12 | Not run |
| Startup and logging | IT-18 | Partly: worker starts without web packages, constants hash equal across processes, `make smoke` green; clean machine and read-only containers Not run |
| Billing | UT-09, IT-19 | Not run |
| Files and links | UT-11 | Not run |
| Console journeys | E2E-01 to E2E-05, E2E-07 | Not run |
| Accessibility (manual) | E2E-06 | Not run |
| Security requirements listed in [TRD.md](TRD.md#8-crosscutting-concepts) | Review against ASVS 5.0.0 text | Not run; six rows listed as not met or partly met |

## 2a. Build milestone B1 (2026-11-11)

**Authorisation.** On 2026-11-11 the owner authorised implementation in this repository before the Phase 0 sales gate (T-0.6.1) had passed. Decision.md still records the author's recommendation and is unchanged; this row is the record of the override. Phase 0 tasks remain open.

**Environment.** macOS developer machine (not `ca-central-1`); Python 3.12.16; PostgreSQL 16 at localhost; databases `mapleroute_dev`, `mapleroute_test`; application role `mapleroute_app` (NOSUPERUSER, NOBYPASSRLS), all tenant tables FORCE ROW LEVEL SECURITY. AWS, Azure, KMS, alert delivery and sign-in are interfaces with in-memory fakes only; no real cloud call was made. Redis is not used.

**Tasks implemented** (code in `backend/`): T-2.1.1 (layout and import-boundary check), T-2.1.2 (one start command with readiness checks, adapted: processes run directly, no Compose), T-2.2.1 (migrations, RLS, grants, immutability and transition triggers), T-2.2.2 (ORM parity check), T-3.1.1 (allow-list loader, evaluator, `Decision` type), T-3.1.2 (key hashing, tenant from key, per-key rate limit in memory), T-3.1.3 (audit-before-forward, compare-and-set, trigger), T-3.1.6 (error contract, timeouts mapped, no retry, provider text dropped), T-3.1.7 (outcome sweeper, late reconciliation), T-3.1.8 (`core.logging` field allow-list, correlation ID), T-4.1.5 (verification job on fakes: ordering rule, two mismatch kinds, resume needs newer match), T-4.1.9 (L2 reads, Azure timestamp and activity look-back, window flagging, logging-state reads, on fakes). Partly: T-3.1.4 and T-3.1.5 (interfaces and stub only; envelope decryption in memory), T-4.1.3 (key create show-once and revoke API, no screens), T-4.1.4 (envelope encryption with a fake key service; no policy templates), T-4.1.8 (operator publish, two-step approve with typed confirmation, suspend, resume API; no screens, no `allowlist_change_notice` alert), T-5.1.2 (only the Azure route-line figures and wording, `core/window.py`).

**Commands and results** (run from `mapleroute-ca/`):

| Command | Result |
|---|---|
| `make test` (drops and re-migrates `mapleroute_test`, then `pytest`) | 72 passed, 0 failed at hand-off; **96 passed, 0 failed** after fix round 1 |
| `make orm-parity` | `orm parity: OK` |
| `make lint` (ruff 0.8.6) | All checks passed |
| `make typecheck` (mypy 1.13, strict, incl. tests) | No issues (47 files; 49 after fix round 1) |
| `make check-imports` | `import boundaries: OK` |
| `make smoke` (migrate dev, start gateway :8110, console :3110, worker, health summary, stop) | Three services ok, same constants hash; exit 0 |

**Tests that ran** (file `backend/tests/…`; all synthetic):

| Test | Function(s) | Result | Scope note |
|---|---|---|---|
| UT-01 | `test_allowlist.py::test_ut01_*` | Passed | Only the `ca.` profile is eligible; prefix never substitutes for destinations |
| UT-02 | `test_ut02_draft_with_one_us_destination_is_refused_naming_the_route` | Passed | — |
| UT-03 | `test_ut03_altered_byte_gives_policy_unavailable`, `test_ut03_db_altered_document_rejects_requests` | Passed | Also through the gateway after altering the stored row behind the trigger |
| UT-04 | `test_gateway.py::test_ut04_valid_revoked_malformed_keys` | Passed | — |
| UT-05 | `test_unit_core.py::test_ut05_only_listed_transitions`; trigger in IT-09 test | Passed | — |
| UT-06 | `test_verification.py::test_ut06_late_match_after_mismatch_leaves_route_suspended` | Passed | — |
| UT-07 | `test_ut07_body_and_authorization_never_logged`, `test_ut07_correlation_id_on_every_line` | Passed | Correlation ID into jobs is set by the worker; not separately asserted |
| UT-10 | `test_ut10_three_model_arns_give_three_regions` | Passed | — |
| IT-01 | `test_it01_eligible_request_forwarded_once_and_logged`, `test_it01_models_lists_only_bound_forwardable_aliases` | Passed | Provider stub, Bedrock and Azure shapes |
| IT-02 | `test_it02_streaming_passes_chunks_and_records_client_abort` | Passed | Disconnect simulated by closing the response iterator, not a real socket |
| IT-03 | `test_it03_fifty_ineligible_inputs_zero_outbound_calls` | Passed | 50 inputs plus a malformed body; stub recorded zero calls; 51 `rejected` rows |
| IT-04 | `test_it04_database_down_rejects_audit_unavailable`, `test_it04_log_insert_failure_rejects_audit_unavailable` | Passed | Unreachable database, and insert privilege revoked |
| IT-05 | `test_it05a_*`, `test_it05b_*`, `test_it05c_*`, `test_it05d_*` | Passed | Fakes |
| IT-06 | `test_canary_and_boundaries.py::test_it06_canaries_never_reach_database_or_logs`; fix round 1: `test_b1_006_adapter_exception_text_reaches_no_log` | Passed, partly | Every table, the application log stream and (round 1) server stdout/stderr scanned; bucket and restored backup Not run (none exist) |
| IT-08 | `test_it08_no_tenant_context_reads_zero_rows`, `test_it08_job_for_a_reads_zero_rows_of_b`, `test_it08_b_session_and_key_on_a_ids_get_404` | Passed | No files exist yet, so the file part is Not run |
| IT-09 | `test_it09_sweeper_then_late_completion_reconciles` | Passed | — |
| IT-10 | `test_it10_suspension_alerts_every_bound_tenant_once` | Passed, partly | Alert rows de-duplicated; delivery and the 5-minute bound Not run |
| IT-14 | `test_it14_partial_parity_passes_and_a_removed_index_fails` | Passed, partly | Two-heads check and backfill resume Not run |
| IT-18 | `test_it18_worker_starts_without_web_modules_and_hashes_agree`; `make smoke` | Passed, partly | Clean machine and read-only containers Not run |
| IT-21 | `test_it21_variant1_*`, `test_it21_variant2_*` (with and without visible activity log), `test_it21_variant3_*` | Passed on fakes | Variant 3: requests served until exactly 60 minutes after the last matching check, rejected 1 s later; alert after the second failed check, once; line prints 3 failed checks and 60 minutes. Whether real Azure readers see these fields stays O-13 |
| IT-22 | `test_it22_missing_l2_us_logging_and_broad_role_never_verified` | Passed on fakes | — |

All other tests in [execution-plan.md](execution-plan.md#planned-tests) remain **Not run**.

**Blocked, with reason.** T-6.1.1 and every real-account half of IT-03/IT-21 (no AWS or Azure test accounts in B1); T-3.1.4 and T-3.1.5 real adapters and the LiteLLM pin (no accounts; O-11 unverified); T-2.1.3, T-2.1.4, IT-20 (no AWS account, no deployment in scope); T-4.1.1, T-4.1.2, UT-12, UT-13 (OIDC needs registered identity-provider applications); IT-07 decrypt half (needs a real KMS key policy; the role half runs since fix round 1); T-5.1.x, T-5.2.1 (reports, watcher, reconciliation, billing need real data sources or Stripe); T-1.1.3 Azure header check (needs a test deployment).

**Deviations from the documents, recorded.**
- ~~One application role `mapleroute_app` for all three processes~~: replaced in fix round 1 (B1-005) by the per-process roles; see [schema.md](schema.md#roles-and-permissions) "As built". Local names carry the `mapleroute_` prefix because roles are cluster-wide.
- `verification.route_id` added (the route compared at that check), so the resume trigger can find a newer match for a route without joining through a binding that may be re-bound. Index `ix_verification_route_match` added. Recorded in schema.md. Fix round 1: a composite foreign key ties it to the binding's route (B1-005).
- `request_log` primary key is (`id`, `received_at`) because PostgreSQL requires the partition key in it; one DEFAULT partition only; monthly partition creation is not built.
- Three `SECURITY DEFINER` functions: `resolve_api_key`, `tenants_bound_to_route` and the trigger function `route_resume_guard` (the round-0 text said two; B1-011). Since fix round 1 all three are owned by the non-superuser NOLOGIN role `mapleroute_definer`, use `search_path = pg_catalog, public, pg_temp` with qualified names, and are not executable by PUBLIC (B1-004). Recorded in schema.md.
- Error contract: a request whose credential cannot be obtained (AWS role assumption or Azure secret decryption fails) is rejected as `route_unverified`, not forwarded; a body that is not a JSON object is rejected as `unsupported_parameter`. Recorded in TRD.md.
- The first allow-list fixture `backend/fixtures/allowlist-2026.11.10-1.json` (32 routes, from Decision.md §4.1) uses Bedrock model identifiers and Azure model versions that are assumptions `[A]`; three Azure versions are unknown and marked `assumed-1`. It is a synthetic draft, not an approved version.

### B1 fix round 1 (2026-11-11)

Independent code review `mapleroute-ca-b1-round1.md`: 0 blocker, 6 major, 5 minor. Fixes are the author's; retest verdicts are the reviewer's and are not set here. Regression tests: `backend/tests/test_round1_regressions.py` (each reproduces the reviewer's adversarial case) and two tests in `test_unit_core.py`.

| Finding | Fix | Regression test(s) | Status |
|---|---|---|---|
| B1-001 | `checked_at` is the end of the provider reads; `last_verified_at` is the start of the matching check's reads; a mismatch flags every served request since then with no upper bound; the worker applies under an exclusive per-binding advisory lock that the gateway takes shared while it decides and commits | `test_b1_001_request_served_during_the_check_reads_is_flagged`, `test_b1_003_gateway_waits_for_a_mismatch_being_applied` | Fixed, awaiting retest |
| B1-002 | Activity look-back starts at the start of the reads of the last check whose reads completed (`match`, `config_mismatch`, `definition_mismatch`); failed checks never move it | `test_b1_002_failed_check_never_moves_the_activity_lookback` (1 and 2 failed checks) | Fixed, awaiting retest |
| B1-003 | Reads first, then the binding lock, then the decision; a mismatch is always applied (binding un-verified, route suspended) however late; only a late match is discarded | `test_b1_003_later_observed_mismatch_with_earlier_stamp_is_applied`, UT-06 | Fixed, awaiting retest |
| B1-004 | Migration `0003`: the three SECURITY DEFINER functions are owned by `mapleroute_definer`, use `search_path = pg_catalog, public, pg_temp` and `public.`-qualified names, and have no PUBLIC execute; the resume guard also requires the operator role | `test_b1_004_temp_table_cannot_shadow_verification_in_resume_guard` (as each of the four roles), `test_b1_004_only_the_operator_resumes` | Fixed, awaiting retest |
| B1-005 | Roles `mapleroute_gateway`, `_console`, `_worker`, `_operator` with column-level least privilege; `mapleroute_app` retired; `verification` tied to the binding's route by a composite foreign key | `test_b1_005_gateway_role_cannot_list_tenants_users_or_forge_verification`, `test_b1_005_console_cannot_mark_verified_or_read_ciphertext_it07`, `test_b1_005_worker_reads_tenant_ids_but_not_names`, `test_b1_005_verification_route_must_be_the_bindings_route`; IT-08 now runs per role | Fixed, awaiting retest |
| B1-006 | Any adapter exception after the commit becomes `upstream_error` (502), logged by class only; mid-stream failures end the stream; an ASGI layer turns any escaped exception into a generic 500 without re-raising; uvicorn loggers carry a filter that withholds message arguments and tracebacks, and run with `log_config=None` | `test_b1_006_adapter_exception_text_reaches_no_log` (real uvicorn; scans the response, the `core.logging` stream, the root logger, stdout and stderr), `test_b1_006_unhandled_exception_becomes_generic_500` | Fixed, awaiting retest |
| B1-007 | The evaluator's capability is exchanged for an HMAC over every field; `dataclasses.replace` or any field change gives an unsealed object that `forward()` refuses | `test_b1_007_replace_on_a_sealed_decision_unseals_it` | Fixed, awaiting retest |
| B1-008 | `model` longer than 128 characters is rejected `route_not_eligible` | `test_b1_008_overlong_model_is_rejected_not_served` | Fixed, awaiting retest |
| B1-009 | `forward()` passes adapters only allow-listed fields per endpoint and sets `model` to the Decision's identifier | `test_b1_009_adapter_receives_only_validated_fields` | Fixed; recheck when T-3.1.4/5 adapters land |
| B1-010 | Idempotency token stored as method, path and key; malformed `connection_id` gives 422 | `test_b1_010_idempotency_key_is_scoped_to_the_endpoint`, `test_b1_010_malformed_ids_are_4xx` | Fixed, awaiting retest |
| B1-011 | Documents list all three functions with owner and search_path | — | Fixed, awaiting retest |

**IT-07** now runs in part: the console role is refused `SELECT ciphertext` and `SELECT wrapped_data_key` on `connection_secret` (passed). The "decrypt denied" half needs the real KMS key policy: **Not run**.

**Commands after the fixes** (from `mapleroute-ca/`): `make check` (ruff: all checks passed; mypy strict: no issues in 49 files; `import boundaries: OK`; `make test` on a re-migrated `mapleroute_test`: **96 passed, 0 failed**; `orm parity: OK`); `make smoke`: three services ok, exit 0.

**Reviewer's adversarial script**, run unchanged (`PYTHONPATH=. .venv/bin/pytest -p tests.conftest -c pyproject.toml --rootdir . -q ../../_coordination/review/mapleroute-ca-b1-adversarial.py` from `backend/`): before the fixes 3 passed, 8 failed; after, **8 passed** (A1, A2, A2b, A3, A4, A5, A6, A7) and **3 failed**, each failing on a statement the new roles now refuse:
- A8 stops at `permission denied for table tenant`: the gateway role can no longer read `tenant`. The case's own assertion expects the read to succeed with at most one row.
- A10 stops at `permission denied for function tenants_bound_to_route`: the gateway role is no longer allowed to call it. Its assertions on `resolve_api_key` still hold.
- A9 wires the gateway to `world.app`, which in the test harness is now the worker role. The worker cannot call `resolve_api_key`, so the request is refused before it reaches the adapter. It also asserts HTTP 500, but the error contract answers `upstream_error` 502. A copy of the script kept outside the repository, with only those two lines changed (the gateway's session factory, and 502), passes A9: no canary in the response, the uvicorn error log or the row (`upstream_error`). The in-repo test `test_b1_006_*` covers the same case.

### B1 fix round 2 (2026-11-11)

**Reviewer's round-2 verdicts** (copied unchanged from `mapleroute-ca-b1-verdicts.json`, retest of commit `77e32cb`; adversarial 19 passed, 2 failed: N3, N4):

| ID | Verdict | Open part (reviewer) |
|---|---|---|
| B1-001 | Closed | — |
| B1-002 | Closed | — |
| B1-003 | Closed, part open | ordering by end of reads lets an older observation's match undo a newer mismatch; raised as B1-012 |
| B1-004 | Closed | — |
| B1-005 | Closed, part open | job table has no RLS; console may insert any job kind for any tenant (N4: false route_suspended alert to another tenant) |
| B1-006 | Closed | — |
| B1-007 | Closed, part open | a Decision hand-built with the private eligibility._SEAL is sealed for any host |
| B1-008 | Closed | — |
| B1-009 | Closed | recheck when real adapters land |
| B1-010 | Closed | — |
| B1-011 | Closed | — |
| B1-012 (new, major) | Open | Concurrent checks: a match whose reads started before a newer applied mismatch re-verifies the binding; Global deployment served until next check |

**This round's edits (author; fixed after retest, not re-reviewed):**

| Finding | Fix | Regression test(s) | Status |
|---|---|---|---|
| B1-012 (and B1-003 open part) | Migration `0004` adds `binding.state_observed_at`. Each check's observation is the start of its reads; under the binding lock a `match` is applied only if it observed later than the result behind the current status; a mismatch observed at or after the verifying observation always un-verifies; a `definition_mismatch` records its observation and always suspends; an older mismatch still flags its window | `test_b1_012_older_observation_match_cannot_undo_a_newer_mismatch` (N3), `test_b1_012_three_concurrent_checks_any_finish_order`, `test_b1_012_older_mismatch_still_flags_its_window` | Fixed after retest |
| B1-005 open part | `job` is FORCE ROW LEVEL SECURITY: console inserts and sees only its own tenant's `verify_binding` jobs, operator only tenant-less `notify_route_suspended` jobs, worker all | `test_b1_005_console_cannot_queue_jobs_for_other_tenants_or_kinds` (N4) | Fixed after retest |
| B1-007 open part | `evaluate` issues each Decision into a module-private identity registry plus a field MAC; `is_sealed` requires that exact object. A hand-built Decision, with any `_seal` value (including the old `_SEAL`, which now grants nothing), a copy or a field change is unsealed. Residual risk, recorded: code in the same process that deliberately writes to the module's private registry can still forge one; Python offers no stronger in-process boundary | `test_b1_007_hand_built_decision_with_private_seal_is_not_sealed`, `test_b1_007_replace_on_a_sealed_decision_unseals_it` | Fixed after retest, residual risk recorded |

**Commands after round 2** (from `mapleroute-ca/`): `make check` (ruff: all checks passed; mypy strict: no issues in 49 files; `import boundaries: OK`; `make test` on a re-migrated `mapleroute_test`: **101 passed, 0 failed**; `orm parity: OK`); `make smoke`: three services ok, exit 0. Reviewer's round-2 adversarial script, unchanged: **19 passed, 0 failed** (A1–A10 including A7 for each of four roles, N1–N5).

### B1 fix round 3 (2026-11-11)

**Reviewer's round-3 verdicts** (copied unchanged from `mapleroute-ca-b1-verdicts.json`, retest of commit `60ea225`; reproduced: `make test` 101 passed, orm parity OK, ruff clean, mypy strict clean (49 files), check-imports OK, smoke 3 services ok; adversarial 23 cases, 21 passed, 2 failed: R1, R3):

| ID | Verdict |
|---|---|
| B1-001 | Closed |
| B1-002 | Closed |
| B1-003 | Still open: regression in the round-2 fix; a config_mismatch whose reads started before the verifying match's reads started is discarded even when it read the provider later, so the binding stays verified and a Global deployment is served unflagged until the next check (case R1; core/verification.py config_mismatch branch, `wins = observed >= verifying`) |
| B1-004 | Closed |
| B1-005 | Closed, part open: job unique key (kind, dedupe_key) is global, so the console role can take another tenant's scheduled-check key and suppress that check (case R3); needs direct database access and the other tenant's binding ID; bounded by the validity period; minor |
| B1-006 | Closed |
| B1-007 | Closed |
| B1-008 | Closed |
| B1-009 | Closed |
| B1-010 | Closed |
| B1-011 | Closed |
| B1-012 | Closed, part open: older match finishing last no longer re-verifies (N3, R2 pass); the same start-of-reads ordering now discards a later-read mismatch, tracked as B1-003 |

Reviewer's notes (unchanged): B1-007 residual risk (same-process code writing the private issue registry) judged acceptable. B1-009 to be rechecked when real adapters land. Round-2 adversarial count was 19 cases (17 passed, 2 failed), not 21.

**This round's edits (author). Status of each: fixed after round-3 retest, awaiting recheck.** The design changed; results are no longer ordered by comparing timestamps of concurrent checks:

| Finding | Fix | Regression test(s) | Status |
|---|---|---|---|
| B1-003 (and B1-012 open part) | Rule 1, serialised checks: migration `0005` adds `binding_check_lease`. `verify_binding` claims the binding's lease in its own committed transaction before the first provider read and releases it in the result transaction (`core.locks.claim_check` / `holds_check` / `release_check`). A second check while the lease is held is skipped (`skipped`, nothing recorded; the job raises `CheckInProgress` and is retried). A lease past `CHECK_LEASE` (2 minutes, `core.config`) is taken over; the old holder is fenced. Rule 2, asymmetric: any `config_mismatch` un-verifies and any `definition_mismatch` suspends, whatever its timing or lease, and sets `binding.last_mismatch_at` to when it was recorded; a `match` applies only if its check still holds the lease and started after `last_mismatch_at`. `binding.state_observed_at` is dropped; `verification.started_at` added; the route resume guard requires a match that started after the suspension and every later `definition_mismatch` | `tests/test_check_serialisation.py`: `test_r1_mismatch_read_after_the_verifying_match_unverifies` (R1), `test_r1_overlap_after_lease_expiry_mismatch_still_unverifies`, `test_n3_match_of_a_check_that_lost_its_lease_never_re_verifies`, `test_three_concurrent_checks_never_overlap` (three threads), `test_worker_dies_mid_check_lease_expires_then_checks_resume`, `test_mismatch_older_than_the_verifying_match_still_unverifies_and_flags`, `test_match_must_start_after_the_latest_recorded_mismatch`; `test_ut06_late_match_after_mismatch_leaves_route_suspended` updated. The three round-2 B1-012 tests in `test_round1_regressions.py` were replaced by these (their overlapping-check premise can no longer occur) | Fixed after round-3 retest, awaiting recheck |
| B1-005 minor part | `job` unique key is now `(kind, tenant_id, dedupe_key)` NULLS NOT DISTINCT; check `ck_job_verify_key` requires a `verify_binding` job to have a tenant and a key starting with its payload's `binding_id`; the console insert policy allows only `<binding>:initial` and `<binding>:manual:<token>` for a binding visible in its own tenant, never a scheduled slot key | `test_console_cannot_create_or_squat_another_tenants_scheduled_key` (R3 squat); `test_b1_005_console_cannot_queue_jobs_for_other_tenants_or_kinds` updated to a valid manual key | Fixed after round-3 retest, awaiting recheck |

**Commands after round 3** (from `mapleroute-ca/`): `make test` (re-migrates `mapleroute_test`): **106 passed, 0 failed**; `make orm-parity`: `orm parity: OK`; `make check-imports`: `import boundaries: OK`; `make lint` (ruff): all checks passed; `make typecheck` (mypy strict): no issues in 50 files; `make smoke`: gateway, console and worker ok, same constants hash (it changed because `CHECK_LEASE` joined the hashed constants). Reviewer's adversarial script, unchanged: **21 passed, 2 failed (N3, R2)**; R1 and R3 now pass. N3 and R2 fail by design: each starts a second and third check of the binding inside the first check's provider reads, in the same thread; under rule 1 those nested checks are skipped (`skipped`), so the assertions that expect them to run (`config_mismatch` / `match` results) cannot hold. The equivalent overlaps, now only possible after a lease expiry, are covered by `test_n3_match_of_a_check_that_lost_its_lease_never_re_verifies` and `test_r1_overlap_after_lease_expiry_mismatch_still_unverifies`. Not run: any check against real AWS or Azure.

### B1 fix round 4 (2026-11-11)

**Reviewer's round-4 verdicts** (copied unchanged from `mapleroute-ca-b1-verdicts.json`, retest of commit `bc5a456`; reproduced: `make test` 106 passed, orm parity OK, ruff clean, mypy strict clean (50 files), check-imports OK, smoke 3 services ok, old adversarial 21 passed, 2 failed (N3, R2: setup only, nested checks now skipped); round-4 script `mapleroute-ca-b1-round4_adversarial.py`: 15 cases, 13 passed, 2 failed: L4a, L4b):

| ID | Verdict |
|---|---|
| B1-001 | Closed |
| B1-002 | Closed |
| B1-003 | Closed |
| B1-004 | Closed |
| B1-005 | Closed |
| B1-006 | Closed |
| B1-007 | Closed |
| B1-008 | Closed |
| B1-009 | Closed |
| B1-010 | Closed |
| B1-011 | Closed |
| B1-012 | Still open: lease times and last_mismatch_at come from each worker's clock (core/locks.py claim_check, core/verification.py apply_outcome), so with clock skew between workers a pre-change match passes the fence after a recorded mismatch and re-verifies the binding; served ok on a GlobalStandard deployment with 90 s skew (L4a) and with 5 s skew plus a check past CHECK_LEASE (L4b); skew also lets a worker take a live lease (L4d); major |

Reviewer's notes (unchanged): N3/R2 rewritten for the lease design (N3v2, N3v3, R2v2) pass. B1-009 to be rechecked when real adapters land. Worker crash: binding stays verified and traffic is served until the lease expires and the job retry (backoff 1, 4 min) runs, about 5 min; requests in between are flagged. Repeated skipped checks fail closed at the end of validity but raise no alert (minor, not raised).

**This round's edits (author). Status: fixed after round-4 retest, awaiting recheck.** Wall clocks are removed from the safety decision (coordinator's ruling):

| Finding | Fix | Regression test(s) | Status |
|---|---|---|---|
| B1-012 (clock skew) | Migration `0006`: `binding.check_generation` (bigint) and `binding_check_lease.generation`. The claim (one SQL statement) records a random token, the binding's generation and `app_now()`-based `started_at`/`expires_at`; takeover only when `expires_at <= app_now()`. Every mismatch increments the generation and un-verifies (or suspends) in the same transaction. A match verifies only by `UPDATE binding ... WHERE check_generation = <claimed> AND` the lease row carries its token. `last_mismatch_at` stays, informational. `started_at`, `checked_at`, `last_verified_at` and the gateway's decision time (`received_at`, validity) are taken from `app_now()`. Trigger `binding_generation_monotonic` refuses a decreasing generation. `clock_override` (owner-only) lets tests pin the database clock to the fake clock | `tests/test_check_serialisation.py`: `test_l4a_lagging_worker_clock_cannot_expose_its_live_lease`, `test_l4b_small_skew_genuine_lease_expiry_pre_flip_match_never_re_verifies`, `test_l4_leading_worker_clock_cannot_take_a_live_lease`, `test_lease_token_reused_after_expiry_never_verifies`, `test_match_verifies_only_if_no_mismatch_since_its_lease_was_claimed`; round-3 tests kept | Fixed after round-4 retest, awaiting recheck |

**Commands after round 4** (from `mapleroute-ca/`): `make test` (re-migrates `mapleroute_test`): **110 passed, 0 failed**; `make lint` (ruff): all checks passed; `make typecheck` (mypy strict): no issues in 50 files; `make check-imports`: OK; `make orm-parity`: OK; `make smoke`: three services ok. Reviewer's round-4 script, unchanged: **13 passed, 2 failed (L4a, L4d)**. L4b, N3v2, N3v3, R2v2, L1, L1b, L2, L3, L3b, L4c, L6, L6b and L7 pass. L4a and L4d now fail on their premise: both expect a worker with a skewed clock to take over a live lease, and with database-clock leases that worker is skipped (L4d's assertion is literally "expected the skewed worker to overlap"). The developer's `test_l4a_…` asserts the new behaviour for the same setup: B skipped, A's mismatch un-verifies, requests rejected. Old script: 21 passed, 2 failed (N3, R2, setup only, as in round 3). Outstanding: no readiness check yet refuses a non-empty `clock_override` outside tests. Not run: real AWS or Azure.

## 2b. Build milestone B2: local sign-in, mail, file storage (2026-11-11)

Branch `feat/b2-local-auth`, created from `feat/b1-foundation` at `40a8e2b` (pushed and independently reviewed; no open review item was named, so no Step 0). Owner request 2026-11-11: build what needs no external account. Synthetic data only; Mailpit and MinIO on this machine; no real provider, identity provider or deployment.

**Deviation from AD-13, recorded.** The TRD specifies Microsoft and Google OIDC only, with no password and no email link. Registered identity-provider applications are external accounts, so OIDC stays **deferred** (T-4.1.1 (a), UT-13 OIDC parts). In its place, behind the same interface, a **local identity provider: password plus TOTP authenticator code**. It produces the same `Identity` an OIDC callback would (`idp = 'local'`, random subject, verified email, `amr = [pwd, otp]`, `auth_time`), and sign-in, sessions, tenant resolution, invitations and the operator checks are shared code. Email is used only to prove an address before a credential exists (one-time enrolment link) and for invitations; it never signs anyone in and there is no email recovery (ASVS 6.3.6). `MAPLEROUTE_IDENTITY_PROVIDERS` accepts only `local` today. Whether the local provider stays once OIDC exists is a founder decision (O-18).

**Tasks implemented.** T-4.1.1 (b) session store and cookie attributes, (d) operator claim check and re-authentication, with the local provider in place of (a); T-4.1.2 (a) onboarding, (b) invitations, (c) role checks (`core.permissions`); report-file storage and the authorised download of T-5.1.x's output (generation itself still blocked); mail through SMTP (Mailpit locally); UT-11 key parts (`core.storage.object_key`). Migration `0007_local_auth_storage`: `session`, `local_credential`, `email_challenge`, `report` (FORCE RLS), invitation columns on `membership`, two definer functions `memberships_for_user` and `accept_invitation`, column grants ([schema.md](schema.md#roles-and-permissions)). The B1 "admit nobody" authenticator is removed; the default is the session authenticator; unit tests may still inject a fake principal.

**Tests that ran** (`backend/tests/test_b2_auth.py`, `backend/tests/test_b2_integration.py`; all passed):

| Test | What it shows |
|---|---|
| `test_totp_rfc6238_vector_and_single_use` | RFC 6238 vector; a code is accepted once; outside the drift window refused |
| `test_password_policy` | 12 to 128 characters, blocked context words, no composition rules |
| `test_ut12_role_action_matrix_matches_prd` | UT-12: role x action matrix equals PRD.md roles |
| `test_sliding_window` | Rate-limit window |
| `test_enrol_sign_in_session_cookie_and_logout` | Enrolment does not sign in; `__Host-` cookie with Secure, HttpOnly, SameSite=Lax, Path=/, no Domain; HSTS, nosniff, CSP; only the token hash stored; logout invalidates the old cookie |
| `test_enrolment_link_reused_and_expired_refused` | Reused and expired (16 min) enrolment links refused; an enrolled address gets a notice without a link |
| `test_wrong_factor_replayed_code_and_lockout` | Wrong password refused; replayed TOTP refused; unknown email gets the same answer; lock after 10 failures, released after 15 min |
| `test_sign_in_rate_limit` | 429 per email for sign-in and for enrolment requests |
| `test_session_idle_and_absolute_expiry_and_new_token_per_sign_in` | New token per sign-in and the old one ends; 30-minute idle and 12-hour absolute limits |
| `test_anti_forgery_and_origin_on_mutations` | Mutations without or with a wrong anti-forgery token, or from a foreign Origin, refused; sign-in from a foreign Origin refused |
| `test_cross_tenant_session_refused` | A's session on B's project: 404; switching or signing in into B without membership refused |
| `test_invitation_flow_email_bound_one_use_and_expiry` | UT-13 part: invitation refused to another address at the same domain; accepted by the invited address; one use; expired refused; reviewer cannot write or see members; last owner cannot be demoted; removing a member ends their sessions |
| `test_console_role_cannot_create_operator` | The console role can neither insert nor set `is_operator` |
| `test_operator_session_needs_recent_reauth` | Operator approve refused 6 minutes after authentication; `/auth/reauth` with password and code allows it |
| `test_secrets_never_logged` | Password, TOTP seed, enrolment token, session cookie and anti-forgery token absent from logs; only an Argon2id hash and ciphertext stored |
| `test_b2_sign_in_end_to_end_through_mailpit` | SMTP to Mailpit; link read through the Mailpit API; enrolment, sign-in, replay refused, reused and expired links refused, logout, rate limit; test messages deleted |
| `test_b2_invitation_through_mailpit` | Invitation mail through Mailpit and acceptance |
| `test_b2_report_files_in_minio_tenant_scoped` | IT-08 file part and UT-11 parts: report stored in MinIO under `<tenant>/worker/report/`; A downloads it (hash matches); B's session gets an empty list and 404; the store refuses A's key under B for get, put and presign; unsigned GET refused (403); presigned link works, more than 300 s refused; an altered object refused by hash; objects deleted and deletion checked |

**Commands** (from `mapleroute-ca/`, clean test database): `make test` (drops and re-migrates `mapleroute_test`): **128 passed, 0 failed** (110 from B1, 18 new); `make lint` (ruff): all checks passed; `make typecheck` (mypy strict): no issues in 62 files; `make check-imports`: OK; `make orm-parity`: OK; `make smoke`: gateway, console (database, mail and storage ready) and worker ok. Test configuration: botocore's `utcnow` deprecation warning is ignored in `pyproject.toml`; with it recorded, the run stalled about 14 minutes after the last test on this machine (cause not found).

**OWASP ASVS 5.0.0 requirements implemented** (local provider; IDs read from the 5.0.0 text on 2026-11-11; implemented is not a compliance claim): 3.3.1, 3.3.2, 3.3.3, 3.3.4 (cookie); 3.4.1, 3.4.4, 3.4.5, 3.4.6 (headers; CSP `default-src 'none'` on the JSON API); 3.5.1, 3.5.3 (anti-forgery token and Origin check on unsafe methods); 6.1.1 (anti-automation documented in TRD.md); 6.2.1, 6.2.5, 6.2.8, 6.2.9, 6.2.10 (password policy); 6.3.1 (rate limits and lockout); 6.3.2 (no default accounts); 6.3.3 (password plus TOTP on every sign-in); 6.3.6 (email not a factor); 6.3.8 (same answer for unknown addresses, enrolled addresses and wrong factors; dummy hash for unknown addresses); 6.4.1 (enrolment link random, 15 minutes, one use); 6.4.2 (no hints or questions); 6.5.1, 6.5.3, 6.5.5, 6.5.8 (TOTP single use, CSPRNG seed, 30-second step, server time); 6.8.1 (identity is provider plus subject); 6.8.4 (operator `amr` and recency checked); 7.2.1, 7.2.2, 7.2.3, 7.2.4 (server-side 256-bit reference tokens, new token at sign-in and re-authentication); 7.3.1, 7.3.2 (30 minutes idle, 12 hours absolute); 7.4.1 (logout deletes the session); 7.5.3 (operator re-authentication before approve, suspend, resume); 8.2.1, 8.4.1 (role checks in `core`; row-level security on `report`; tenant-prefixed keys).

**Not implemented or not met:** 6.1.2 and 6.2.11 only partly (a short built-in word list); 6.2.2, 6.2.3 (no password change); 6.2.4 (no 3,000-password list); 6.2.12 (no breached-password check); 6.2.6, 6.2.7 (no UI yet); 6.3.5, 6.3.7 (no notice of suspicious sign-ins or factor changes); 6.4.3, 6.4.4 (no reset or factor recovery: a lost authenticator needs the operator, process not built); 6.5.6 (no factor revocation screen); 6.8.2, 6.8.3 and the V10 OIDC items (deferred with OIDC); 7.1.1-7.1.3 only in TRD.md, 7.1.2 concurrent-session limit not set; 7.4.2 (no account disable); 7.4.3, 7.5.1, 7.5.2 (no session list or factor change); 7.4.4 (no UI); 7.4.5 (no administrator session termination beyond member removal); 7.6.1, 7.6.2 (no IdP session); 3.4.2 (no CORS configured, so none allowed); 3.4.3 only as a deny-all policy; 8.4.2 not met (unchanged).

**Blocked or not run.** OIDC (needs registered applications); real SMTP provider and S3 in `ca-central-1` (accounts); report generation (T-5.1.x); IT-06 bucket and restored-backup parts (no generated report content and no backup); UI screens S-01, S-02, S-13, S-15.

### B2 security review round 1: security fixes after B2 review, awaiting recheck (2026-11-11)

Reviewer's round-1 report `_coordination/review/mapleroute-ca-b2-sec-round1.md` (retest of `9a5ea82`): blocker 1, minor 4. Attack script `mapleroute-ca-b2-sec_attack.py`, unchanged, run from `backend/` before the fixes: **17 passed, 4 failed** (A06b, A15, A17, A19; the reviewer counts A11b as an observation, hence "16 of 20"). After the fixes: **21 passed, 0 failed**. Findings `B2-S0n` are the reviewer's; verdicts are the reviewer's to set.

| Finding | Fix | Regression test(s) (`backend/tests/test_b2_security.py`) | Status |
|---|---|---|---|
| B2-S01 (blocker) logout and logout-all failed with 500 for tenant sessions; the session stayed alive | `console/auth.py`: the session delete commits in its own transaction; the audit event is written afterwards by `audit_after`, which sets tenant context, retries once and only logs `audit_failed` if both attempts fail, so it can never undo a sign-out | `test_b2_s01_logout_ends_a_tenant_session`, `test_b2_s01_logout_all_ends_every_tenant_session`, `test_b2_s01_logout_of_operator_session`, `test_b2_s01_audit_failure_never_keeps_a_session` (audit insert revoked: logout still 204, row gone) | Fixed, awaiting recheck |
| B2-S02 forwarding headers trusted by uvicorn's default | `MAPLEROUTE_TRUSTED_PROXIES` (default empty). `console/main.py` `server_config`: `proxy_headers` off unless proxies are configured, then `forwarded_allow_ips` pinned to them. `console.auth.client_key`: with no trusted proxy, any request carrying `Forwarded`, `X-Forwarded-For` or `X-Real-IP` shares one rate-limit window, so rotating the header buys nothing even under a server that rewrites the client; the wrong comment is replaced | `test_b2_s02_server_config_does_not_trust_proxy_headers_by_default`, `test_b2_s02_rotating_forwarded_for_does_not_bypass_the_address_limit` (live uvicorn with `server_config`), `test_b2_s02_header_rewriting_server_still_shares_one_window` | Fixed, awaiting recheck |
| B2-S03 locked account answered faster | `core/local_idp.py`: the locked branch runs the same Argon2 verification before refusing | `test_b2_s03_locked_unknown_and_wrong_password_take_the_same_work` (medians within a factor of two; one answer) | Fixed, awaiting recheck |
| B2-S04 concurrent mutual demotion left no owner | Role change and member removal first lock every owner row of the tenant (`SELECT ... FOR UPDATE`, ordered by ID), then read the target and count the remaining owners | `test_b2_s04_concurrent_mutual_demotion_leaves_an_owner` (4 concurrent rounds) | Fixed, awaiting recheck |
| B2-S05 claimed controls without a failing test | Tests added for each named ID | `test_b2_s05_684_…` (6.8.4: fresh `auth_time` with `amr={pwd}` refused), `test_b2_s05_724_…` (7.2.4 at re-authentication: old cookie refused), the S01 tests (7.4.1 for tenant sessions), `test_b2_s05_345_346_…` (Referrer-Policy, CSP `frame-ancestors`, `object-src`, `base-uri`), `test_b2_s05_628_…` (case, trimming, truncation refused), `test_b2_s05_629_…` (64, 100, 128 characters accepted; 129 refused), `test_b2_s05_632_…` (no account rows in migrations; common default credentials refused) | Fixed, awaiting recheck |

Observation (b) also fixed: two concurrent enrolment completions for one address now return 400, not 500. Observations (a), (c), (d), (e) unchanged (product decision, local key, accepted lockout risk, unbounded windows). Against the code before the fixes, 6 of the new tests fail (the four S01 tests, S03, S04); the S02 live test depends on `server_config` and the S05 tests guard controls that already worked.

**Commands after the fixes** (from `mapleroute-ca/`, clean test database): `make test`: **143 passed, 0 failed** (128 plus 15 new); `make lint`: all checks passed; `make typecheck` (mypy strict): no issues in 63 files; `make check-imports`: OK; `make orm-parity`: OK; `make smoke`: three services ok. Reviewer's attack script: 21 passed, 0 failed.

## 3. Traceability of must-haves

| MH | Screen or API | Decision | Schema or permission | Tasks | Planned tests |
|---|---|---|---|---|---|
| MH-01 | S-07; `POST /v1/chat/completions`, `/v1/embeddings` | AD-03 | `api_key`, `binding`; role `mr_gateway` | T-3.1.2, T-3.1.4, T-3.1.5, T-4.1.3 | UT-04, IT-01, IT-02, E2E-01 |
| MH-02 | S-14, S-12 | AD-01, AD-12 | `allowlist_version`, `allowlist_route`, `route` | T-1.1.1, T-3.1.1, T-4.1.8 | UT-01, UT-02, UT-03 |
| MH-03 | Error contract; S-08 | AD-02, AD-04 | `request_log.state`, `code` | T-1.1.2, T-3.1.6, T-6.1.1 | IT-03, IT-04, IT-20 |
| MH-04 | S-06 | AD-02, AD-14 | `binding`, `verification`, `route.global_status`, `request_log.flags` | T-4.1.5, T-4.1.6, T-4.1.9 | UT-06, UT-10, IT-05, IT-21, IT-22, E2E-02 |
| MH-05 | S-05, S-07 | AD-06 | `provider_connection`, `connection_secret`; split encrypt and decrypt roles | T-3.1.5, T-4.1.4 | IT-06, IT-07 |
| MH-06 | S-08 | AD-05 | `request_log` has no content column | T-3.1.3, T-3.1.8, T-4.1.7, T-6.1.2 | UT-07, IT-06 |
| MH-07 | S-10 | AD-11 | `report`, `log_digest` | T-1.1.3, T-5.1.2 | UT-08, IT-16, E2E-03 |
| MH-08 | S-14, S-12 | AD-12 | `watcher_snapshot`, `watcher_diff` | T-0.2.3, T-4.1.8, T-5.1.3 | IT-17, E2E-04 |
| MH-09 | S-01, S-02, S-13, S-15 | AD-07, AD-13 | Row-level security; `membership`, `session` | T-2.2.1, T-4.1.1, T-4.1.2, T-6.1.3 | UT-12, UT-13, IT-08 |
| MH-10 | S-09, S-04 | AD-02 | `alert` | T-5.1.4 | IT-10 |
| MH-11 | S-11, S-10 | AD-08, AD-09, AD-11 | `infra_asset`, `subprocessor` | T-0.4.3, T-0.6.2, T-2.1.3, T-5.1.1 | IT-16, IT-20 |
| MH-12 | S-13 | AD-05 | `deletion_request`; retention table | T-5.1.6 | IT-13, IT-15 |
| MH-13 | S-08, S-09 | AD-11 | `region_observation` | T-5.1.5 | IT-11 |
| MH-14 | S-13 | AD-07 | `usage_month` | T-5.2.1 | UT-09, IT-19 |
| MH-15 | S-06, S-10 | AD-11 | `logging_observation` | T-0.5.2, T-4.1.9 | IT-22 |

Walk-through of the pilot promise "zero requests forwarded on a route outside the allow-list": MH-03 → error contract → `request_log` → T-3.1.6 → IT-03; second layer T-6.1.1 against real accounts; detection MH-13 → IT-11; Azure change window MH-04 → IT-21; reported by MH-07 → IT-16. Limit: a customer-side change that Azure does not expose to a reader stays undetected (O-13).

## 4. Findings register

Findings F-001 to F-015 are from the independent reviewer's round 1 (2026-11-10; 0 blocker, 10 major, 5 minor; note file `mapleroute-ca-round1.md`). Evidence and impact are the reviewer's, shortened. Owner of every fix: Author B. Fixes were made on 2026-11-10. The retest column is set by the reviewer, not by the author. Retest on 2026-11-10 (`mapleroute-ca-round2.md`): 8 closed, 6 closed with a part open, 1 open by design (F-008), 0 still open, no new blocker or major finding; the lead transcribed the reviewer's verdicts into the retest column unchanged.

| Issue ID | Severity | File | Evidence (reviewer) | Impact | Fix made (round 1) | Files changed | Retest condition | Retest result |
|---|---|---|---|---|---|---|---|---|
| F-001 | Major | TRD, execution-plan | An Azure deployment can be re-created as Global Standard under the same name between checks; L2 was an unverified template | The highest-consequence failure with no bug and no provider change | L2 is now required and read at every check (AD-02); Azure checked every 15 minutes with 1-hour validity; timestamps and activity-log look-back; requests in a changed window flagged and counted; failure row 8; new TRD section "Residual window on Azure"; report and buyer wording state the gap; tests IT-21, IT-22; task T-4.1.9. **Left open and stated:** an unobserved window of 15 minutes while checks succeed, and up to 60 minutes (the validity of the last matching check) when checks fail or run late, and the reader-visible signals are unverified (O-13). Window wording edited after retest; checked by the lead, not re-reviewed | TRD, PRD, Decision, schema, App-flow, design, execution-plan, CLAUDE | Path, control and swap test present | Closed, part open: prose says 'up to 15 minutes' but 1-hour validity allows up to 60 minutes unobserved when checks fail; Azure reader-visible signals unverified (O-13) (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-002 | Major | PRD, TRD, schema | One `mismatch` with two contradictory outcomes; global `route.api_host` cannot hold a customer's Azure host | Implementer cannot tell the blast radius | Two results: `config_mismatch` (that binding only) and `definition_mismatch` (route suspended for all tenants, Bedrock shared profiles only); rule per provider and blast radius in TRD; routes carry no host; `endpoint_host` on the connection, `deployment_name` on the binding; IT-05 rewritten; AD-14 | TRD, PRD, schema, App-flow, execution-plan, AGENTS, CLAUDE | Two named outcomes, rule, schema, test | Closed (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-003 | Major | Decision §9.3 | Build gate ignored the document's own negative economics | "Build" could be recorded on evidence that leaves break-even untouched | Economics row added (average tier ≥ CAD 399, or a referral-sourced pilot, or counted pool ≥ 2,778); Build needs three rows together; text says Build authorises only a second-stage test and adds a further gate at 5 accounts or month 9 | Decision, execution-plan | Numeric §7.4 condition in the gate | Closed, part open: break-even with founder pay still unreachable at assumed rates (O-16) (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-004 | Major | Decision §9.3, §12.8 | No false-stop rate for the revised rule; no questionnaire yield | Revised rule presented without its own error rate | Yield assumption stated (pilots supply theirs; 1 in 2 of other meetings); false-stop 28.0% / 35.7% / 52.6% at yields 1, 1/2, 1/4, computed exactly and matching the reviewer's simulation; expected-questionnaires row in §12.8; yield recorded in T-0.4.2. **Open:** the yield is unknown (O-14) | Decision, execution-plan | Yield, probability, row | Closed, part open: questionnaire yield unknown; false-stop 35.7% at the assumed yield (O-14) (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-005 | Major | TRD, Decision, schema | Egress list incomplete; no register rows | L3 undefined for most destinations; subprocessor evidence had no content | TRD "Egress destinations" lists every destination per process with path and data; alerts delivered from AWS services in `ca-central-1`; draft register of eight parties in Decision §4.3, each "not evidenced" until read; IT-20 widened. **Open:** every location in the register (O-15) | TRD, Decision, schema, execution-plan, AGENTS | Complete list and first register | Closed, part open: every subprocessor location not evidenced (O-15) (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-006 | Major | execution-plan, Decision | Pilot tools' location and the grade rules came after the pilot | First paid deliverable produced on unevidenced tools | New T-0.4.3 (tool locations) and T-0.4.4 (grade catalogue v0, pack template) are entry conditions of milestone 0.5 | execution-plan, Decision | Entry conditions present | Closed (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-007 | Major | Decision §4.3, PRD, TRD, schema | Customer's own invocation logging promised but not built | Largest content store absent from the report | MH-15 added with verifier reads, `logging_observation`, S-06 and report lines, IT-22, T-4.1.9; logging to a destination outside Canada is a `config_mismatch`; hand-run pilot records it too | PRD, TRD, schema, App-flow, execution-plan, Decision | Must-have, permission, field, test | Closed (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-008 | Major | PRD, TRD | "Operator cannot read credentials" unsupported | Buyer told something untrue about key custody | Statement withdrawn. Now: no application path exposes a credential; the founder as administrator can, and that is logged; where the customer can and cannot see it; 13.3.2 marked partly met. **Open by design** (O-09) | PRD, TRD, Decision, schema, CLAUDE | True statement or real control | Open by design: administrator access to stored secrets is logged, not prevented (O-09) (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-009 | Major | TRD, App-flow, schema | Multi-factor wording inaccurate; three tenant-resolution rules; OIDC and cookie requirements missing | Operator takeover; cross-tenant join by email domain | One rule: identity is (provider, subject); join only by creating a tenant or by an invitation matched on verified email; no domain matching. Operator: separate host, Entra only, `amr` and recent authentication. ASVS rows for 6.8.1, 6.8.2, 6.8.4, 7.3.1, 7.5.3, 8.4.2, V3 and V10 added after reading their text; 8.4.2 marked not met; UT-13. **Open:** claim support per provider (O-09) | TRD, App-flow, schema, execution-plan, Decision | One rule in three files; operator requirement; V3 and V10 rows | Closed, part open: ASVS 8.4.2 not met; tenant multi-factor off by default; claim support per provider unverified (O-09) (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-010 | Major | design | Secret forms blocked below 640 px, failing reflow at 400% zoom | Stated target failed by construction | Forms reflow to one column at 320 px; blocking message removed; 1.4.10 row added to the accessibility map | design | Forms reflow | Closed (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-011 | Minor | PRD, TRD, App-flow | Determinism claim overstated; resume without a fresh check | A manual resume could reopen a route | `listed` is the pure part; mutable inputs are copied to each log row; resume requires a match newer than the suspension (schema trigger, S-14, IT-05) | PRD, TRD, schema, App-flow, execution-plan | Scoped claim; guarded resume | Closed (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-012 | Minor | PRD, TRD | Revocation "on the next request" against 15-minute sessions | Criterion unmeetable for AWS-side revocation | MH-05 and TRD distinguish deletion in MapleRoute (next request) from revocation in AWS (up to 15 minutes); S-05 says so | PRD, TRD, App-flow | Distinction stated | Closed (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-013 | Minor | TRD | Semicolons in sequence-diagram messages | Diagrams may not render | Semicolons removed from both diagrams. Rendering on GitHub not checked by the author | TRD | Renders | Closed, part open: rendering on GitHub not checked (O-17) (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-014 | Minor | Decision | Vertex count 9, reviewer counts 10; Trango's custom models and white-label programme omitted | Count error; competitor reach understated | Page re-opened: 10, listed by name. Trango row and objection answer now state both items and no longer say flatly that Trango does not offer other models | Decision | Count and row corrected | Closed (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |
| F-015 | Minor | Decision | Startup cost shown as 100 hours; two timelines; `[C]` on a re-timed budget | Reader takes CAD 10,000 as the startup cost | Startup row shows the brief's CAD 10,000 and the author's CAD 27,100–40,800; §7.3 uses §12.8's cash schedule and one stated timeline; both budgets named in §1, §7.1 and §12.8; tag changed to `[P]` | Decision | Both figures; one timeline; tag | Closed (independent reviewer retest, 2026-11-10, `mapleroute-ca-round2.md`; verdict transcribed by the lead) |

### Outstanding items

Open before any review. None is hidden by a compliance or residency claim.

| Item | What remains open | Evidence needed | Where it will be recorded |
|---|---|---|---|
| O-01 | The decisive question itself: which requirement is unmet | Three coded questionnaires (T-0.4.2) | [Decision.md](Decision.md#44-which-requirement-is-unmet) |
| O-02 | Founder VPS provider and location unknown | T-0.6.2 record | Evidence register; AD-09 |
| O-03 | Quebec statute not read (source blocked) | Text of the provision; counsel (T-0.1.1) | [Decision.md](Decision.md#13-sources-and-assumptions) SRC-17 |
| O-04 | No per-request region or deployment-type field identified for Azure | Header check on a test deployment (T-1.1.3) | Grade catalogue |
| O-05 | Whether Bedrock In-Region calls record `inferenceRegion` | CloudTrail sample from MapleRoute's own account (T-0.2.1) | Grade catalogue |
| O-06 | Consent basis for LinkedIn and referral messages; regulations under the anti-spam Act not read | Counsel (T-0.1.1) | Outreach rules page |
| O-07 | Distinct reachable prospects not counted | T-0.1.3 | [Decision.md](Decision.md#8-funnel-recomputed-from-distinct-reachable-prospects) |
| O-08 | Meaning of the CAD 249 launch price; two budgets; fixed-cost breakdown | Founder decision (T-0.5.4, T-0.6.1) | [Decision.md](Decision.md#11-missing-inputs) |
| O-09 | The founder, as infrastructure administrator, can reach stored secrets and alter log rows (F-008, open by design: no preventing control exists with one founder); multi-factor checking depends on claims the identity provider sends (F-009); ASVS 8.4.2 not met and tenant multi-factor checking off by default (F-009, closed with this part open); secret rotation partly met | A second administrator or an external key holder; claim support confirmed per provider (T-4.1.1) | [TRD.md](TRD.md#8-crosscutting-concepts) |
| O-10 | Single operator, single region, single-AZ database | Buyer feedback on uptime needs | [TRD.md](TRD.md#7-deployment-view) |
| O-11 | LiteLLM settings that disable routing, fallback and logging are named from memory, not verified | Read its documentation at the pinned version (T-3.1.4) | AD-03 |
| O-12 | Operating cost estimate not read from a price list | Provider calculators (T-2.1.3) | [TRD.md](TRD.md#4-solution-strategy) |

| O-13 | Azure residual window (F-001, closed with this part open): 15 minutes while checks succeed, and up to 60 minutes (the validity of the last matching check) when checks fail or run late; whether a reader can see deployment timestamps, activity-log write and delete events, and policy exemptions; the AWS policy-simulation and logging-configuration API names | Test on MapleRoute's own Azure and AWS accounts (T-1.1.3, T-6.1.1) | [TRD.md](TRD.md#residual-window-on-azure); grade catalogue |
| O-14 | F-004, closed with this part open. The revised stop rule still stops wrongly about 36% of the time at an assumed questionnaire yield; the yield is unknown (F-004) | Questionnaires per meeting from T-0.4.2 | [Decision.md](Decision.md#93-proposed-revision-p--a-change-to-the-rules-above-not-a-restatement) |
| O-15 | F-005, closed with this part open. Every location in the draft subprocessor register is "not evidenced"; the uptime-probe vendor is not chosen | T-0.4.3 for pilot tools; T-0.6.2 and T-5.1.1 for production | [Decision.md](Decision.md#43-evidence-grades) |
| O-16 | F-003, closed with this part open. Break-even with founder pay is unreachable at the assumed rates; the pool-count option in the Build gate makes 12 accounts reachable, not 45 | Tier chosen by converted pilots, referral share, counted pool, observed churn | [Decision.md](Decision.md#73-cash-required-during-the-ramp) |
| O-18 | B2 deviation from AD-13: console sign-in is a local provider (password plus TOTP) until OIDC is built; whether it remains afterwards, and the lost-authenticator process, are undecided | Founder decision; OIDC applications registered (T-4.1.1 (a)) | [TRD.md](TRD.md#8-crosscutting-concepts); section 2b |
| O-17 | F-013, closed with this part open. Diagram rendering on GitHub not checked by author or reviewer | View after push | This file |

### Author self-check log (not independent review)

A script kept outside the repository (in the author's scratch directory) was run on 2026-11-10.

| ID | Check | Method | Result |
|---|---|---|---|
| SC-01 | File inventory | Directory listing | Ten files, names exact |
| SC-02 | Links and anchors | Script resolves every relative link and heading anchor | 88 links, zero unresolved |
| SC-03 | ID definitions | Script collects every `MH-`, `S-`, `AD-`, `T-`, `UT-`, `IT-`, `E2E-`, `R-`, `SRC-`, `EG-`, `RQ-`, `M-` reference and checks a defining row exists | Zero undefined at hand-off |
| SC-04 | Must-have coverage | Script compares PRD must-haves with the matrix above | 14 of 14 |
| SC-05 | Risk rows | Script counts rows and checks each task ID exists in the plan | 22 of 22 |
| SC-06 | Cross-file agreement | Script compares screen IDs and routes (App-flow, design, matrix), tables (schema, matrix), error codes (TRD, App-flow, schema) | Zero mismatches at hand-off |
| SC-07 | Arithmetic | Script recomputes gross profit, break-even, payback, lifetime value, funnel, binomial stop-rule probabilities, tier mixes, ramp table, hours and estimate sums | All figures in Decision.md and execution-plan.md reproduce to the printed precision |
| SC-08 | Source fidelity | Manual comparison with the brief | Five departures, all listed in [Decision.md](Decision.md#41-what-keeps-inference-in-canada-today-read-2026-11-10); CAC, tier and budget inconsistencies listed in section 11 there |
| SC-09 | Sources | Fetch log | SRC-01 to SRC-16 and SRC-18 to SRC-23 opened; SRC-17 blocked; two member-list pages returned 404 |
| SC-11 | Re-run after fix round 1 | Same script; economics script extended with the false-stop computation and the new estimate sums | Ten files; zero unresolved links; zero undefined IDs; 15 of 15 must-haves traced; 22 risks; build 271–408 hours; phase 0 155–204 hours. Counts in SC-02 and SC-04 above are the hand-off values |
| SC-10 | Hygiene | Search for key-like strings, real names, non-Mermaid diagrams | None found; message examples are synthetic |

## Production risk register

Single home of the 22 production risks. Other files cite the ID only. Tests are planned and **Not run**.

| ID | Risk | Impact on this product's buyer and data | Proposed prevention | Detection signal | Test and expected outcome | Task |
|---|---|---|---|---|---|---|
| R-01 | Out-of-order or duplicate events overwrite a newer job state | A late "match" result from the verifier reactivates a route already suspended for a US destination; requests resume and the report says Canada | Suspension and verification updates apply only if `checked_at` is newer; request states change by compare-and-set | Count of ignored stale results; any route moving `suspended` → `active` without an operator audit event | UT-06: late match after mismatch → stays suspended. UT-05: illegal transitions refused B1 2026-11-11: UT-06 and UT-05 passed (section 2a). | T-4.1.5 |
| R-02 | A caller timeout prevents reconciliation with a valid later completion | The vendor's app times out, the provider still answers; the row stays `forwarding` and the report cannot say whether the request was served | Sweeper marks `unknown_outcome`; late completion may update it and stamps `reconciled_at`; report counts unknowns separately | Share of `unknown_outcome` rows (M-7) | IT-09: unknown, then completed with `reconciled_at` B1 2026-11-11: IT-09 passed. | T-3.1.7 |
| R-03 | New utilities duplicate behaviour already owned by shared code | A second, slightly different Region parser or eligibility check in the worker disagrees with the gateway; a route is "verified" by one and "eligible" by the other on different grounds | One implementation in `core`; review rule; import-boundary check | Two functions with the same purpose found in review | UT-01 and UT-10 are the only tests of those functions; a duplicate has no test and fails coverage gate B1 2026-11-11: `listed` and Region parsing exist once in `core`; `make check-imports` passes. | T-2.1.1 |
| R-04 | Applications import private code across architectural boundaries | `console` imports the gateway's forward function to "test a connection" and sends a real prompt outside the audited path | `gateway`, `console`, `worker` import only `core`; connection tests use configuration reads, never inference | Boundary check failure in the pipeline | Deliberate cross-import fails the check B1 2026-11-11: `test_t211_deliberate_cross_import_fails_the_check` passed. | T-2.1.1 |
| R-05 | Tenant enforcement is scattered or bypassed through APIs, workers, caches, or files | One vendor sees another vendor's request volumes, model choices or report: commercially sensitive and a breach to disclose | Row-level security in the database; tenant set once in `core.tenancy`; tenant-prefixed object keys; no shared cache | Queries returning zero rows where the application expected some; 404 counts on foreign IDs | IT-08: B on A's IDs → 404; job for A reads B → zero rows B1 2026-11-11: IT-08 passed for rows, API and job (files Not run). | T-2.2.1 |
| R-06 | Workers copy configuration and utility modules, causing behavioural drift | The worker keeps an older copy of the Canadian Region set after `ca-west-1` handling changes; it verifies against the wrong set | Configuration and constants only in `core.config`; no copies | Hash of the constants printed at start by each process differs | IT-18 compares the printed hash across the three processes B1 2026-11-11: IT-18 hash comparison passed. | T-2.1.1 |
| R-07 | Worker logging imports web-only modules and crashes during startup | The worker does not start; verification ages past its validity (1 hour for Azure, 24 for Bedrock) and every customer request is rejected; until then Azure requests are served for up to 60 minutes on configuration nobody is re-reading | `core.logging` has no web imports; worker image built without web packages | Worker health check failing; verification age rising | IT-18: worker starts in an image without web packages. IT-21 variant 3: failed checks reject at 60 minutes B1 2026-11-11: worker import without web packages and IT-21 variant 3 passed (image build Not run). | T-3.1.8 |
| R-08 | ORM declarations omit indexes or constraints present in migrations | The "one active allow-list" partial unique index is missing in a rebuilt environment; two versions are active and the decision depends on query order | Parity check between models and a migrated database | Parity check failure | IT-14: model missing an index → check fails B1 2026-11-11: IT-14 parity part passed. | T-2.2.2 |
| R-09 | Interrupted migrations or backfills cannot resume safely | A backfill of `allowlist_version` on old log rows stops halfway; reports for that month cite no version for some rows | Backfills separate, batched, with a progress row | Progress row not at end; null counts | IT-14: killed backfill resumes and finishes | T-2.2.3 |
| R-10 | Merged branches introduce conflicting migration order | Two branches both add a `request_log` column; production and staging differ and a deploy fails mid-traffic, causing `audit_unavailable` rejections | Linear history check; rebase rule | Two heads detected | IT-14: two heads → pipeline fails | T-2.2.3 |
| R-11 | Index creation locks busy production tables during deployment | An index build locks `request_log`; audit inserts block; every request is rejected for the duration | Concurrent builds, lock timeout, retry; lint rule | Lock wait metric; `audit_unavailable` spike during deploy | IT-14: non-concurrent index on a large table → lint fails | T-2.2.3 |
| R-12 | Correlation IDs disappear across jobs and retries, or sensitive data leaks into logs | A prompt containing a patient's details or an Azure key is written to application logs, contradicting the product's central statement; or an incident cannot be traced from alert to request | Field allow-list in `core.logging`; request ID as correlation ID carried into jobs; provider error text dropped | Canary scan hits; log lines without correlation ID | UT-07; IT-06: zero canary hits in database, logs, bucket and restored backup B1 2026-11-11: UT-07 passed; IT-06 passed for database and logs only. | T-3.1.8 |
| R-13 | Upload keys collide or fail to isolate tenant, source, and purpose | No user uploads exist. The risk applies to generated reports and exports: one vendor's report overwrites or is served as another's | Keys built by one function: tenant, kind, period, identifier | Object count per tenant against report rows | UT-11: key starts with tenant ID; two tenants, same period → different keys | T-5.1.7 |
| R-14 | Temporary uploads survive retention expiry or failed cleanup | No uploads. Export files of request logs outlive their 7 days or survive a tenant's deletion | Expiry rule on the bucket prefix and a purge job; deletion drops the prefix | Objects older than 7 days under the export prefix | IT-15: export files gone after purge and after deletion | T-5.1.6 |
| R-15 | Missing persistent volumes cause data loss after service recreation | Not applicable to the proposed design: containers hold no state. It would apply if the gateway moved to the founder's VPS with a local database, where recreating the service could lose the request log that reports depend on | State only in managed database, bucket and key service | Any container writing to local disk | IT-13 restore drill; IT-18 runs containers with read-only file systems | T-2.1.3 |
| R-16 | Generated file links use internal hosts or `localhost` behind a public proxy | A reviewer's report link or an alert email points to an internal address and cannot be opened; the report is not delivered before a questionnaire deadline | Links built from one configured public base URL; signed, 5-minute | Link check; 4xx on report downloads | UT-11: link uses the public host when an internal host is configured | T-5.1.7 |
| R-17 | Local dependencies and workers lack a reliable single startup command and health checks | A developer tests the gateway without the worker; verification never runs locally and the fail-closed paths go untested | One command starts everything with readiness checks | Health summary | IT-18 on a clean machine B1 2026-11-11: `make smoke` green; IT-18 partly. | T-2.1.2 |
| R-18 | Browser Back, refresh, or deep links lose the user's result or task state | An engineer refreshes after creating a key and expects to see it again; or a reviewer's saved link to a filtered log opens unfiltered and is attached to a questionnaire | Filters in the URL; show-once is explicit; forms idempotent | Support questions; duplicate records | E2E-05 | T-6.1.7 |
| R-19 | Bulk processing skips files, hides partial failures, or duplicates successful work on retry | Reconciliation skips one hour of CloudTrail events and the report says every request matched; or a retried report double-counts | Idempotent jobs keyed by connection and hour; unmatched rows stay "not yet matched"; report totals must equal log totals or the run fails | Unmatched count; hours without a completed job | IT-11: failed page reported and retried, no double counts. IT-16: second run identical | T-5.1.5 |
| R-20 | Unclear labels, icons, stale routes, or broken links misdirect users | A status chip reading "OK" is taken as confirmation of location; a privacy lead cites it | Fixed vocabulary and grade badges; label list reviewed against the design brief | Link check; wording review | E2E-07: no dead links; labels match the inventory | T-6.1.7 |
| R-21 | Unrequested features consume effort without a requirement or pilot need | Caching, guardrails or a "debug log" get built; each one stores or inspects content and breaks the no-content statement | Non-goals list; scope review before release | Features without an MH reference | Review record lists every merged feature against an MH | T-7.1.5 |
| R-22 | Misnamed, duplicate, or stale branches obscure the active work or endanger unmerged changes | An old branch with a permissive allow-list draft is deployed to staging and copied to production | Protected `main`; releases from tags only; branch naming and monthly clean-up | Stale-branch report | Deploy from a non-tag is refused by the pipeline | T-2.1.5 |
