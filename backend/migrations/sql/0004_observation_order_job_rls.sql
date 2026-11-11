-- 0004 (B1 fix round 2: B1-012, B1-005 part).

-- B1-012: the provider observation (start of the reads) behind the binding's current state.
-- A result changes the binding only if its observation is newer than this one.
ALTER TABLE binding ADD COLUMN state_observed_at timestamptz;
UPDATE binding SET state_observed_at = last_verified_at WHERE status = 'verified';
GRANT UPDATE (state_observed_at) ON binding TO mapleroute_worker;

-- B1-005 part: job rows are tenant-scoped for the console and kind-scoped for the operator, so a
-- tenant session cannot make the worker act or alert for another tenant (N4).
ALTER TABLE job ENABLE ROW LEVEL SECURITY;
ALTER TABLE job FORCE ROW LEVEL SECURITY;
CREATE POLICY worker_all ON job FOR ALL TO mapleroute_worker USING (true) WITH CHECK (true);
CREATE POLICY console_insert ON job FOR INSERT TO mapleroute_console
  WITH CHECK (tenant_id = app_tenant_id() AND kind = 'verify_binding');
CREATE POLICY console_select ON job FOR SELECT TO mapleroute_console
  USING (tenant_id = app_tenant_id() AND kind = 'verify_binding');
CREATE POLICY operator_insert ON job FOR INSERT TO mapleroute_operator
  WITH CHECK (tenant_id IS NULL AND kind = 'notify_route_suspended');
CREATE POLICY operator_select ON job FOR SELECT TO mapleroute_operator
  USING (tenant_id IS NULL AND kind = 'notify_route_suspended');
