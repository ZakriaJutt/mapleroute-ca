-- 0005 (B1 fix round 3: B1-003, B1-012, B1-005 part).

-- ---------------------------------------------------------------- B1-003: one check of a binding at a time
-- A check claims its binding's lease in its own committed transaction before the first provider read
-- and releases it in the transaction that records its result. A second check while the lease is held
-- is skipped (the job is retried later). A lease past expires_at is taken over, so a dead worker
-- blocks for at most the lease timeout (core.config.CHECK_LEASE).
CREATE TABLE binding_check_lease (
  binding_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  holder uuid NOT NULL,
  started_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  CONSTRAINT fk_check_lease_binding FOREIGN KEY (tenant_id, binding_id) REFERENCES binding (tenant_id, id)
    ON DELETE CASCADE,
  CONSTRAINT ck_check_lease_expiry CHECK (expires_at > started_at)
);
ALTER TABLE binding_check_lease ENABLE ROW LEVEL SECURITY;
ALTER TABLE binding_check_lease FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON binding_check_lease
  USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id());
GRANT SELECT, INSERT, DELETE ON binding_check_lease TO mapleroute_worker;
GRANT UPDATE (holder, started_at, expires_at) ON binding_check_lease TO mapleroute_worker;

-- ---------------------------------------------------------------- B1-003, B1-012: asymmetric ordering
-- Any mismatch un-verifies, whatever its timing; a match re-verifies only if its check started after
-- the latest recorded mismatch. The observation-order column of round 2 is retired.
ALTER TABLE binding DROP COLUMN state_observed_at;
ALTER TABLE binding ADD COLUMN last_mismatch_at timestamptz;
UPDATE binding b SET last_mismatch_at = (
  SELECT max(v.checked_at) FROM verification v
  WHERE v.binding_id = b.id AND v.result IN ('config_mismatch', 'definition_mismatch'));
GRANT UPDATE (last_mismatch_at) ON binding TO mapleroute_worker;

-- Start of a check's provider reads. NULL only for rows not written by the worker; such a row can
-- never re-verify a binding or justify resuming a route.
ALTER TABLE verification ADD COLUMN started_at timestamptz;
UPDATE verification
  SET started_at = COALESCE((provider_answer -> 'coverage' ->> 'reads_started_at')::timestamptz, checked_at);
ALTER TABLE verification ADD CONSTRAINT ck_verification_started CHECK (started_at IS NULL OR started_at <= checked_at);
GRANT SELECT (started_at) ON verification TO mapleroute_definer;

-- Resuming a suspended route needs a match whose reads STARTED after the suspension and after every
-- later definition mismatch on that route (same rule as a binding).
CREATE OR REPLACE FUNCTION public.route_resume_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE fence timestamptz;
BEGIN
  IF OLD.global_status = 'suspended' AND NEW.global_status = 'active' THEN
    IF session_user <> 'mapleroute_operator' THEN
      RAISE EXCEPTION 'route % cannot resume: only the operator resumes a route', OLD.id USING ERRCODE = 'P0001';
    END IF;
    SELECT GREATEST(OLD.status_changed_at, max(v.checked_at)) INTO fence FROM public.verification v
      WHERE v.route_id = OLD.id AND v.result = 'definition_mismatch';
    IF NOT EXISTS (SELECT 1 FROM public.verification v WHERE v.route_id = OLD.id AND v.result = 'match'
                   AND v.started_at IS NOT NULL AND v.started_at > COALESCE(fence, OLD.status_changed_at)) THEN
      RAISE EXCEPTION 'route % cannot resume: no match started after the suspension', OLD.id USING ERRCODE = 'P0001';
    END IF;
  END IF;
  IF NEW.provider <> OLD.provider OR NEW.source_region <> OLD.source_region OR NEW.identifier <> OLD.identifier
     OR NEW.deployment_class <> OLD.deployment_class OR NEW.model_version IS DISTINCT FROM OLD.model_version THEN
    RAISE EXCEPTION 'route definition fields are immutable' USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
ALTER FUNCTION public.route_resume_guard() OWNER TO mapleroute_definer;
REVOKE EXECUTE ON FUNCTION public.route_resume_guard() FROM PUBLIC;

-- ---------------------------------------------------------------- B1-005 part: tenant-scoped job keys
-- The unique key includes the tenant, so one tenant's row can never collide with (squat) another
-- tenant's key. A verify_binding key must name the job's own binding; the console may only write
-- the `initial` and `manual:` keys, never a scheduled slot, and only for a binding of its tenant.
ALTER TABLE job DROP CONSTRAINT uq_job_kind_dedupe;
ALTER TABLE job ADD CONSTRAINT uq_job_kind_tenant_dedupe UNIQUE NULLS NOT DISTINCT (kind, tenant_id, dedupe_key);
-- ON CONFLICT on the new key needs SELECT on its columns; row visibility stays limited by the policies.
GRANT SELECT (tenant_id) ON job TO mapleroute_console, mapleroute_operator;
ALTER TABLE job ADD CONSTRAINT ck_job_verify_key CHECK (
  kind <> 'verify_binding'
  OR (tenant_id IS NOT NULL AND payload ? 'binding_id'
      AND starts_with(dedupe_key, (payload ->> 'binding_id') || ':')));
DROP POLICY console_insert ON job;
CREATE POLICY console_insert ON job FOR INSERT TO mapleroute_console
  WITH CHECK (
    tenant_id = app_tenant_id() AND kind = 'verify_binding'
    AND (dedupe_key = (payload ->> 'binding_id') || ':initial'
         OR starts_with(dedupe_key, (payload ->> 'binding_id') || ':manual:'))
    AND EXISTS (SELECT 1 FROM binding b
                WHERE b.tenant_id = app_tenant_id() AND b.id::text = payload ->> 'binding_id'));
