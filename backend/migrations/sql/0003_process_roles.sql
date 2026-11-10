-- 0003_process_roles (B1 fix round 1: B1-004, B1-005).
-- Per-process least-privilege roles (schema.md "Roles and permissions"); the B1 single role
-- mapleroute_app loses every privilege. SECURITY DEFINER functions move to a dedicated
-- non-superuser NOLOGIN owner with a pinned search_path (pg_temp last) and qualified names.
-- Roles are created by tools/db_bootstrap before migrations run.

-- ---------------------------------------------------------------- retire the single role
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM mapleroute_app;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM mapleroute_app;
REVOKE ALL ON SCHEMA public FROM mapleroute_app;
-- Functions are executable by PUBLIC by default; nothing here is.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public
  TO mapleroute_gateway, mapleroute_console, mapleroute_worker, mapleroute_operator, mapleroute_definer;
GRANT EXECUTE ON FUNCTION public.app_tenant_id()
  TO mapleroute_gateway, mapleroute_console, mapleroute_worker, mapleroute_operator;

-- ---------------------------------------------------------------- a verification belongs to its binding's route
ALTER TABLE binding ADD CONSTRAINT uq_binding_tenant_id_route UNIQUE (tenant_id, id, route_id);
ALTER TABLE verification DROP CONSTRAINT fk_verification_binding;
ALTER TABLE verification ADD CONSTRAINT fk_verification_binding_route
  FOREIGN KEY (tenant_id, binding_id, route_id) REFERENCES binding (tenant_id, id, route_id);

-- ---------------------------------------------------------------- definer: the three SECURITY DEFINER functions
CREATE POLICY definer_read ON api_key FOR SELECT TO mapleroute_definer USING (true);
CREATE POLICY definer_read ON binding FOR SELECT TO mapleroute_definer USING (true);
CREATE POLICY definer_read ON verification FOR SELECT TO mapleroute_definer USING (true);
GRANT SELECT (id, tenant_id, project_id, state, key_hash) ON api_key TO mapleroute_definer;
GRANT SELECT (tenant_id, route_id) ON binding TO mapleroute_definer;
GRANT SELECT (route_id, result, checked_at) ON verification TO mapleroute_definer;

CREATE OR REPLACE FUNCTION public.resolve_api_key(p_hash bytea)
RETURNS TABLE (api_key_id uuid, tenant_id uuid, project_id uuid, state text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS
$$ SELECT k.id, k.tenant_id, k.project_id, k.state FROM public.api_key k WHERE k.key_hash = p_hash $$;
ALTER FUNCTION public.resolve_api_key(bytea) OWNER TO mapleroute_definer;
REVOKE EXECUTE ON FUNCTION public.resolve_api_key(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.resolve_api_key(bytea) TO mapleroute_gateway;

CREATE OR REPLACE FUNCTION public.tenants_bound_to_route(p_route text)
RETURNS TABLE (tenant_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS
$$ SELECT DISTINCT b.tenant_id FROM public.binding b WHERE b.route_id = p_route $$;
ALTER FUNCTION public.tenants_bound_to_route(text) OWNER TO mapleroute_definer;
REVOKE EXECUTE ON FUNCTION public.tenants_bound_to_route(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.tenants_bound_to_route(text) TO mapleroute_worker, mapleroute_operator;

-- Only the operator resumes a suspended route, and only with a real match newer than the suspension.
CREATE OR REPLACE FUNCTION public.route_resume_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
  IF OLD.global_status = 'suspended' AND NEW.global_status = 'active' THEN
    IF session_user <> 'mapleroute_operator' THEN
      RAISE EXCEPTION 'route % cannot resume: only the operator resumes a route', OLD.id USING ERRCODE = 'P0001';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.verification v WHERE v.route_id = OLD.id AND v.result = 'match'
                   AND v.checked_at > OLD.status_changed_at) THEN
      RAISE EXCEPTION 'route % cannot resume: no match newer than the suspension', OLD.id USING ERRCODE = 'P0001';
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

-- ---------------------------------------------------------------- gateway: decide, record, forward
-- No access to tenant, user_account, job, verification or tenants_bound_to_route; cannot change a binding.
GRANT SELECT ON binding, route, provider_connection, connection_secret, allowlist_version, allowlist_route
  TO mapleroute_gateway;
GRANT SELECT (id, tenant_id, project_id, state) ON api_key TO mapleroute_gateway;
GRANT UPDATE (last_used_at) ON api_key TO mapleroute_gateway;
GRANT SELECT, INSERT ON request_log TO mapleroute_gateway;
GRANT UPDATE (state, code, http_status, latency_ms, upstream_ms, input_tokens, output_tokens, response_bytes,
              provider_request_id, completed_at, reconciled_at) ON request_log TO mapleroute_gateway;

-- ---------------------------------------------------------------- console: tenant screens and API
-- Cannot read connection_secret ciphertext; cannot set a binding's verification fields.
GRANT SELECT ON project, membership, provider_connection, api_key, binding, request_log, alert,
  allowlist_version, allowlist_route, route TO mapleroute_console;
GRANT SELECT, INSERT, DELETE ON form_token TO mapleroute_console;
GRANT INSERT ON provider_connection, api_key TO mapleroute_console;
GRANT UPDATE (state) ON provider_connection TO mapleroute_console;
GRANT UPDATE (state, revoked_at) ON api_key TO mapleroute_console;
GRANT INSERT (connection_id, tenant_id, ciphertext, wrapped_data_key, kms_key_arn, rotated_at) ON connection_secret
  TO mapleroute_console;
GRANT SELECT (connection_id, tenant_id, kms_key_arn, rotated_at, created_at) ON connection_secret
  TO mapleroute_console;
GRANT INSERT (id, tenant_id, project_id, connection_id, route_id, alias, deployment_name) ON binding
  TO mapleroute_console;
GRANT INSERT ON job TO mapleroute_console;
GRANT SELECT (id, kind, dedupe_key) ON job TO mapleroute_console;
GRANT INSERT ON audit_event TO mapleroute_console;

-- ---------------------------------------------------------------- worker: verification and jobs
GRANT SELECT (id, state) ON tenant TO mapleroute_worker;
GRANT SELECT ON binding, route, provider_connection, connection_secret, allowlist_version, allowlist_route,
  verification, logging_observation, alert, request_log, job TO mapleroute_worker;
GRANT UPDATE (status, last_verified_at, last_checked_at, l2_confirmed_at, provider_modified_at) ON binding
  TO mapleroute_worker;
-- To `suspended` only: route_resume_guard refuses suspended -> active for anyone but the operator.
GRANT UPDATE (global_status, status_reason, status_changed_at, status_checked_at) ON route TO mapleroute_worker;
GRANT UPDATE (state, last_read_ok_at) ON provider_connection TO mapleroute_worker;
GRANT UPDATE (state, activated_at) ON allowlist_version TO mapleroute_worker;
GRANT INSERT ON verification, logging_observation, alert, job, audit_event TO mapleroute_worker;
GRANT UPDATE (flags, state) ON request_log TO mapleroute_worker;
GRANT UPDATE (state, run_after, attempts, locked_at, last_error_code) ON job TO mapleroute_worker;

-- ---------------------------------------------------------------- operator: allow-list and routes
GRANT SELECT ON user_account, allowlist_version, allowlist_route, route TO mapleroute_operator;
GRANT INSERT ON allowlist_version, allowlist_route, route, job, audit_event TO mapleroute_operator;
GRANT SELECT (id, kind, dedupe_key) ON job TO mapleroute_operator;
GRANT UPDATE (state, approved_by, approved_at, activate_after, activated_at) ON allowlist_version
  TO mapleroute_operator;
GRANT UPDATE (global_status, status_reason, status_changed_at) ON route TO mapleroute_operator;
