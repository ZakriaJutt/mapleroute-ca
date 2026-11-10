-- 0001_core: tables the B1 deterministic core needs (schema.md), with row-level security,
-- constraints, indexes and immutability triggers. Written by hand; tools/orm_parity compares
-- it with core/models.py (R-08). There is no table or column for prompt or response content.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Tenant context: unset or empty means NULL, so a policy matches no row.
CREATE FUNCTION app_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;

-- ---------------------------------------------------------------- identity and tenancy
CREATE TABLE tenant (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  legal_name text NOT NULL,
  state text NOT NULL DEFAULT 'active',
  plan text NOT NULL DEFAULT 'pilot',
  log_retention_months integer NOT NULL DEFAULT 13,
  require_mfa_claim boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_tenant_state CHECK (state IN ('active', 'deletion_pending', 'deleted')),
  CONSTRAINT ck_tenant_plan CHECK (plan IN ('pilot', 'starter', 'pro', 'business')),
  CONSTRAINT ck_tenant_retention CHECK (log_retention_months BETWEEN 1 AND 24)
);

CREATE TABLE user_account (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  idp text NOT NULL,
  idp_subject text NOT NULL,
  email text NOT NULL,
  display_name text NOT NULL,
  is_operator boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_user_account_idp_subject UNIQUE (idp, idp_subject)
);

CREATE TABLE membership (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  user_id uuid REFERENCES user_account(id),
  role text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_membership_role CHECK (role IN ('owner', 'engineer', 'reviewer')),
  CONSTRAINT uq_membership_tenant_user UNIQUE (tenant_id, user_id)
);

CREATE TABLE form_token (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  token text NOT NULL,
  result_ref text,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_form_token_tenant_token UNIQUE (tenant_id, token)
);

-- ---------------------------------------------------------------- projects, connections, keys
CREATE TABLE project (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_project_tenant_name UNIQUE (tenant_id, name),
  CONSTRAINT uq_project_tenant_id UNIQUE (tenant_id, id)
);

CREATE TABLE provider_connection (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  project_id uuid NOT NULL,
  provider text NOT NULL,
  account_ref text NOT NULL,
  source_region text NOT NULL,
  role_arn text,
  external_id text,
  endpoint_host text,
  resource_group text,
  cloudtrail_read boolean NOT NULL DEFAULT false,
  state text NOT NULL DEFAULT 'pending',
  last_read_ok_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_connection_project FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, id),
  CONSTRAINT ck_connection_provider CHECK (provider IN ('aws', 'azure')),
  CONSTRAINT ck_connection_region CHECK (source_region IN ('ca-central-1', 'ca-west-1', 'canadacentral', 'canadaeast')),
  CONSTRAINT ck_connection_provider_region CHECK (
    (provider = 'aws' AND source_region IN ('ca-central-1', 'ca-west-1'))
    OR (provider = 'azure' AND source_region IN ('canadacentral', 'canadaeast'))),
  CONSTRAINT ck_connection_aws_fields CHECK (provider <> 'aws' OR (role_arn IS NOT NULL AND external_id IS NOT NULL)),
  CONSTRAINT ck_connection_azure_fields CHECK (provider <> 'azure' OR (endpoint_host IS NOT NULL AND resource_group IS NOT NULL)),
  CONSTRAINT ck_connection_state CHECK (state IN ('pending', 'connected', 'access_failed', 'deleted')),
  CONSTRAINT uq_connection_account UNIQUE (project_id, provider, account_ref),
  CONSTRAINT uq_connection_tenant_id UNIQUE (tenant_id, id)
);

CREATE TABLE connection_secret (
  connection_id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  ciphertext bytea NOT NULL,
  wrapped_data_key bytea NOT NULL,
  kms_key_arn text NOT NULL,
  rotated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_secret_connection FOREIGN KEY (tenant_id, connection_id) REFERENCES provider_connection(tenant_id, id)
);

CREATE TABLE api_key (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  project_id uuid NOT NULL,
  key_hash bytea NOT NULL,
  prefix text NOT NULL,
  last_four text NOT NULL,
  state text NOT NULL DEFAULT 'active',
  created_by uuid,
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_api_key_project FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, id),
  CONSTRAINT ck_api_key_state CHECK (state IN ('active', 'revoked')),
  CONSTRAINT uq_api_key_hash UNIQUE (key_hash)
);

-- ---------------------------------------------------------------- allow-list and routes (global)
CREATE TABLE allowlist_version (
  version text PRIMARY KEY,
  document jsonb NOT NULL,
  sha256 bytea NOT NULL,
  state text NOT NULL DEFAULT 'draft',
  approved_by uuid REFERENCES user_account(id),
  approved_at timestamptz,
  activate_after timestamptz,
  activated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_allowlist_state CHECK (state IN ('draft', 'active', 'superseded')),
  CONSTRAINT ck_allowlist_approval CHECK (state = 'draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
CREATE UNIQUE INDEX ux_allowlist_one_active ON allowlist_version (state) WHERE state = 'active';

CREATE TABLE route (
  id text PRIMARY KEY,
  provider text NOT NULL,
  source_region text NOT NULL,
  identifier text NOT NULL,
  deployment_class text NOT NULL,
  model_version text,
  global_status text NOT NULL DEFAULT 'active',
  status_reason text,
  status_changed_at timestamptz,
  status_checked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_route_class CHECK (
    (provider = 'aws' AND deployment_class IN ('in_region', 'geo_ca') AND model_version IS NULL)
    OR (provider = 'azure' AND deployment_class IN ('Standard', 'ProvisionedManaged') AND model_version IS NOT NULL)),
  CONSTRAINT ck_route_status CHECK (global_status IN ('active', 'suspended'))
);

CREATE TABLE allowlist_route (
  version text NOT NULL REFERENCES allowlist_version(version),
  route_id text NOT NULL REFERENCES route(id),
  destinations text[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (version, route_id),
  CONSTRAINT ck_allowlist_route_destinations CHECK (
    cardinality(destinations) > 0
    AND destinations <@ ARRAY['ca-central-1', 'ca-west-1', 'canadacentral', 'canadaeast']::text[])
);

-- ---------------------------------------------------------------- bindings and verification
CREATE TABLE binding (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  project_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  route_id text NOT NULL REFERENCES route(id),
  alias text NOT NULL,
  status text NOT NULL DEFAULT 'unverified',
  deployment_name text,
  last_verified_at timestamptz,
  last_checked_at timestamptz,
  l2_confirmed_at timestamptz,
  provider_modified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_binding_project FOREIGN KEY (tenant_id, project_id) REFERENCES project(tenant_id, id),
  CONSTRAINT fk_binding_connection FOREIGN KEY (tenant_id, connection_id) REFERENCES provider_connection(tenant_id, id),
  CONSTRAINT ck_binding_status CHECK (status IN ('unverified', 'verified')),
  CONSTRAINT ck_binding_verified_needs_l2 CHECK (status <> 'verified' OR (l2_confirmed_at IS NOT NULL AND last_verified_at IS NOT NULL)),
  CONSTRAINT ck_binding_azure_deployment CHECK (route_id NOT LIKE 'azure:%' OR deployment_name IS NOT NULL),
  CONSTRAINT uq_binding_project_alias UNIQUE (project_id, alias),
  CONSTRAINT uq_binding_tenant_id UNIQUE (tenant_id, id)
);
CREATE INDEX ix_binding_route ON binding (route_id);

CREATE TABLE verification (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  binding_id uuid NOT NULL,
  route_id text NOT NULL REFERENCES route(id),
  checked_at timestamptz NOT NULL,
  result text NOT NULL,
  reason text,
  provider_answer jsonb NOT NULL,
  allowlist_version text NOT NULL,
  grade text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_verification_binding FOREIGN KEY (tenant_id, binding_id) REFERENCES binding(tenant_id, id),
  CONSTRAINT ck_verification_result CHECK (result IN ('match', 'config_mismatch', 'definition_mismatch', 'access_failed', 'error')),
  CONSTRAINT ck_verification_grade CHECK (grade IN ('EG-3', 'EG-4'))
);
CREATE INDEX ix_verification_binding_checked ON verification (tenant_id, binding_id, checked_at DESC);
CREATE INDEX ix_verification_route_match ON verification (route_id, checked_at) WHERE result = 'match';

CREATE TABLE logging_observation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  connection_id uuid NOT NULL,
  observed_at timestamptz NOT NULL,
  state text NOT NULL,
  destination text,
  destination_region text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_logging_obs_connection FOREIGN KEY (tenant_id, connection_id) REFERENCES provider_connection(tenant_id, id),
  CONSTRAINT ck_logging_obs_state CHECK (state IN ('off', 'on', 'not_readable'))
);

-- ---------------------------------------------------------------- request_log (partitioned by month)
CREATE TABLE request_log (
  id uuid NOT NULL,
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  project_id uuid NOT NULL,
  api_key_id uuid NOT NULL,
  received_at timestamptz NOT NULL,
  endpoint text NOT NULL,
  alias text NOT NULL,
  route_id text,
  allowlist_version text,
  route_status text,
  binding_verified_at timestamptz,
  flags text[] NOT NULL DEFAULT '{}',
  state text NOT NULL,
  code text,
  http_status integer,
  latency_ms integer,
  upstream_ms integer,
  input_tokens integer,
  output_tokens integer,
  request_bytes integer,
  response_bytes integer,
  provider_request_id text,
  completed_at timestamptz,
  reconciled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, received_at),
  CONSTRAINT ck_request_log_endpoint CHECK (endpoint IN ('chat', 'embeddings')),
  CONSTRAINT ck_request_log_alias_len CHECK (char_length(alias) <= 128),
  CONSTRAINT ck_request_log_state CHECK (state IN ('rejected', 'forwarding', 'completed', 'upstream_error', 'client_aborted', 'unknown_outcome')),
  CONSTRAINT ck_request_log_decided CHECK (state = 'rejected' OR (route_id IS NOT NULL AND allowlist_version IS NOT NULL))
) PARTITION BY RANGE (received_at);
-- Monthly partitions are created ahead by a job (not in B1); the default partition catches the rest.
CREATE TABLE request_log_default PARTITION OF request_log DEFAULT;
CREATE INDEX ix_request_log_list ON request_log (tenant_id, project_id, received_at DESC);
CREATE INDEX ix_request_log_forwarding ON request_log (tenant_id, state, received_at) WHERE state = 'forwarding';
CREATE INDEX ix_request_log_provider_request ON request_log (tenant_id, provider_request_id);

-- ---------------------------------------------------------------- alerts, audit, jobs
CREATE TABLE alert (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  kind text NOT NULL,
  dedupe_key text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}',
  sent_at timestamptz,
  acknowledged_by uuid,
  acknowledged_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_alert_kind CHECK (kind IN ('route_suspended', 'config_mismatch', 'allowlist_change_notice',
    'rejections_summary', 'access_failed', 'region_incident', 'register_gap')),
  CONSTRAINT uq_alert_dedupe UNIQUE (tenant_id, dedupe_key)
);
CREATE INDEX ix_alert_open ON alert (tenant_id, created_at DESC) WHERE acknowledged_at IS NULL;

CREATE TABLE audit_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid REFERENCES tenant(id),
  actor_user_id uuid,
  actor_kind text NOT NULL,
  action text NOT NULL,
  target text NOT NULL,
  correlation_id text,
  detail jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_audit_actor_kind CHECK (actor_kind IN ('user', 'operator', 'system'))
);

CREATE TABLE job (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind text NOT NULL,
  dedupe_key text NOT NULL,
  tenant_id uuid,
  payload jsonb NOT NULL DEFAULT '{}',
  run_after timestamptz NOT NULL DEFAULT now(),
  state text NOT NULL DEFAULT 'queued',
  attempts integer NOT NULL DEFAULT 0,
  locked_at timestamptz,
  last_error_code text,
  correlation_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_job_state CHECK (state IN ('queued', 'running', 'done', 'failed')),
  CONSTRAINT uq_job_kind_dedupe UNIQUE (kind, dedupe_key)
);
CREATE INDEX ix_job_queued ON job (run_after) WHERE state = 'queued';

-- ---------------------------------------------------------------- row-level security
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['membership', 'form_token', 'project', 'provider_connection', 'connection_secret',
    'api_key', 'binding', 'verification', 'logging_observation', 'request_log', 'alert']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id = app_tenant_id()) '
                   'WITH CHECK (tenant_id = app_tenant_id())', t);
  END LOOP;
END $$;
-- audit_event: tenant rows visible to their tenant; operator-global rows (NULL tenant) are written
-- by the operator path and are not readable through the tenant policy.
ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_event FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_read ON audit_event FOR SELECT USING (tenant_id = app_tenant_id());
CREATE POLICY audit_insert ON audit_event FOR INSERT WITH CHECK (tenant_id IS NULL OR tenant_id = app_tenant_id());

-- ---------------------------------------------------------------- immutability and state triggers
CREATE FUNCTION reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% on % is not allowed (append-only)', TG_OP, TG_TABLE_NAME USING ERRCODE = 'P0001';
END $$;

CREATE TRIGGER verification_append_only BEFORE UPDATE OR DELETE ON verification
  FOR EACH ROW EXECUTE FUNCTION reject_change();
CREATE TRIGGER audit_event_append_only BEFORE UPDATE OR DELETE ON audit_event
  FOR EACH ROW EXECUTE FUNCTION reject_change();
CREATE TRIGGER allowlist_route_append_only BEFORE UPDATE OR DELETE ON allowlist_route
  FOR EACH ROW EXECUTE FUNCTION reject_change();

-- An allow-list version is never edited (AD-12): only its state and approval fields move forward.
CREATE FUNCTION allowlist_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'allow-list versions are never deleted' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.version <> OLD.version OR NEW.document <> OLD.document OR NEW.sha256 <> OLD.sha256 THEN
    RAISE EXCEPTION 'allow-list version % is immutable; publish a new version', OLD.version USING ERRCODE = 'P0001';
  END IF;
  IF NOT ((OLD.state = 'draft' AND NEW.state IN ('draft', 'active'))
       OR (OLD.state = 'active' AND NEW.state IN ('active', 'superseded'))
       OR (OLD.state = 'superseded' AND NEW.state = 'superseded')) THEN
    RAISE EXCEPTION 'allow-list state % -> % is not allowed', OLD.state, NEW.state USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER allowlist_version_immutable BEFORE UPDATE OR DELETE ON allowlist_version
  FOR EACH ROW EXECUTE FUNCTION allowlist_version_guard();

-- request_log transitions (schema.md): forwarding -> completed | upstream_error | client_aborted |
-- unknown_outcome; unknown_outcome -> completed | upstream_error. Decision inputs never change.
CREATE FUNCTION request_log_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'request_log rows are removed only by partition drop' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.id <> OLD.id OR NEW.tenant_id <> OLD.tenant_id OR NEW.project_id <> OLD.project_id
     OR NEW.api_key_id <> OLD.api_key_id OR NEW.received_at <> OLD.received_at OR NEW.alias <> OLD.alias
     OR NEW.endpoint <> OLD.endpoint
     OR NEW.route_id IS DISTINCT FROM OLD.route_id
     OR NEW.allowlist_version IS DISTINCT FROM OLD.allowlist_version
     OR NEW.route_status IS DISTINCT FROM OLD.route_status
     OR NEW.binding_verified_at IS DISTINCT FROM OLD.binding_verified_at THEN
    RAISE EXCEPTION 'request_log decision fields are immutable' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.state <> OLD.state AND NOT (
       (OLD.state = 'forwarding' AND NEW.state IN ('completed', 'upstream_error', 'client_aborted', 'unknown_outcome'))
    OR (OLD.state = 'unknown_outcome' AND NEW.state IN ('completed', 'upstream_error'))) THEN
    RAISE EXCEPTION 'request_log state % -> % is not allowed', OLD.state, NEW.state USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER request_log_transition BEFORE UPDATE OR DELETE ON request_log
  FOR EACH ROW EXECUTE FUNCTION request_log_guard();

-- suspended -> active needs a match for this route newer than the suspension (F-011). The check reads
-- verification across tenants, so it runs as the function owner.
CREATE FUNCTION route_resume_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
BEGIN
  IF OLD.global_status = 'suspended' AND NEW.global_status = 'active' THEN
    IF NOT EXISTS (SELECT 1 FROM verification v WHERE v.route_id = OLD.id AND v.result = 'match'
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
CREATE TRIGGER route_resume_needs_newer_match BEFORE UPDATE ON route
  FOR EACH ROW EXECUTE FUNCTION route_resume_guard();

-- ---------------------------------------------------------------- narrow cross-tenant lookups
-- The gateway learns the tenant from the key, so the key lookup itself runs before tenant context.
CREATE FUNCTION resolve_api_key(p_hash bytea)
RETURNS TABLE (api_key_id uuid, tenant_id uuid, project_id uuid, state text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT k.id, k.tenant_id, k.project_id, k.state FROM api_key k WHERE k.key_hash = p_hash $$;

-- Tenants affected by a route suspension (schema.md index binding(route_id)); IDs only.
CREATE FUNCTION tenants_bound_to_route(p_route text)
RETURNS TABLE (tenant_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT DISTINCT b.tenant_id FROM binding b WHERE b.route_id = p_route $$;
