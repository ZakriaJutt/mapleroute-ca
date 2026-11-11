-- 0007_local_auth_storage (B2): console sign-in through the local identity provider, server-side
-- sessions, invitations on membership, and the report table for stored files.
-- OIDC (TRD.md AD-13) is deferred; a local identity is (idp 'local', random subject), exactly as an
-- OIDC identity is (issuer, sub), so both share user_account, membership and session.

-- ---------------------------------------------------------------- invitations (schema.md membership)
ALTER TABLE membership
  ADD COLUMN invited_email text,
  ADD COLUMN invite_token_hash bytea,
  ADD COLUMN invite_expires_at timestamptz,
  ADD COLUMN accepted_at timestamptz;
ALTER TABLE membership ADD CONSTRAINT uq_membership_invite_token UNIQUE (invite_token_hash);
-- A row is either a member (user bound) or a pending invitation with its email, token and expiry.
ALTER TABLE membership ADD CONSTRAINT ck_membership_member_or_invite CHECK (
  user_id IS NOT NULL OR (invited_email IS NOT NULL AND invite_token_hash IS NOT NULL
                          AND invite_expires_at IS NOT NULL));

-- ---------------------------------------------------------------- sessions (global, console only)
CREATE TABLE session (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
  tenant_id uuid REFERENCES tenant(id) ON DELETE CASCADE,
  token_hash bytea NOT NULL,
  idp text NOT NULL,
  amr text[] NOT NULL DEFAULT '{}',
  auth_time timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_session_token_hash UNIQUE (token_hash),
  CONSTRAINT ck_session_expiry CHECK (expires_at > auth_time)
);
CREATE INDEX ix_session_user ON session (user_id);

-- ---------------------------------------------------------------- local identity provider
CREATE TABLE local_credential (
  user_id uuid PRIMARY KEY REFERENCES user_account(id) ON DELETE CASCADE,
  email_normalised text NOT NULL,
  password_hash text NOT NULL,
  totp_ciphertext bytea NOT NULL,
  totp_wrapped_key bytea NOT NULL,
  totp_kms_key_arn text NOT NULL,
  totp_confirmed_at timestamptz,
  totp_last_step bigint,
  failed_count integer NOT NULL DEFAULT 0,
  locked_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_local_credential_email UNIQUE (email_normalised),
  CONSTRAINT ck_local_credential_failed CHECK (failed_count >= 0)
);

CREATE TABLE email_challenge (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  purpose text NOT NULL,
  email_normalised text NOT NULL,
  token_hash bytea NOT NULL,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_email_challenge_token UNIQUE (token_hash),
  CONSTRAINT ck_email_challenge_purpose CHECK (purpose IN ('enrol'))
);

-- ---------------------------------------------------------------- reports (schema.md report)
CREATE TABLE report (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  period_start date NOT NULL,
  period_end date NOT NULL,
  kind text NOT NULL,
  state text NOT NULL DEFAULT 'generating',
  allowlist_versions text[],
  object_key text,
  sha256 bytea,
  totals jsonb,
  content_type text,
  byte_size bigint,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_report_tenant_period_kind UNIQUE (tenant_id, period_start, period_end, kind),
  CONSTRAINT ck_report_kind CHECK (kind IN ('monthly', 'custom')),
  CONSTRAINT ck_report_state CHECK (state IN ('generating', 'ready', 'failed', 'withheld')),
  CONSTRAINT ck_report_period CHECK (period_end >= period_start),
  CONSTRAINT ck_report_ready CHECK (state <> 'ready' OR (allowlist_versions IS NOT NULL AND object_key IS NOT NULL
    AND sha256 IS NOT NULL AND totals IS NOT NULL AND content_type IS NOT NULL AND byte_size IS NOT NULL)),
  -- R-13: a report's file lives under its own tenant's prefix.
  CONSTRAINT ck_report_object_key_tenant CHECK (object_key IS NULL OR starts_with(object_key, tenant_id::text || '/'))
);
ALTER TABLE report ENABLE ROW LEVEL SECURITY;
ALTER TABLE report FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON report USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id());

-- ---------------------------------------------------------------- definer: sign-in lookups across tenants
-- A signing-in user has no tenant context yet, and membership is tenant-scoped. These two functions
-- are the only cross-tenant reads the console has; both key on the user, never on an email domain.
CREATE POLICY definer_read ON membership FOR SELECT TO mapleroute_definer USING (true);
CREATE POLICY definer_accept ON membership FOR UPDATE TO mapleroute_definer USING (user_id IS NULL)
  WITH CHECK (user_id IS NOT NULL);
GRANT SELECT (id, tenant_id, user_id, role, invited_email, invite_token_hash, invite_expires_at, created_at) ON membership
  TO mapleroute_definer;
GRANT UPDATE (user_id, accepted_at, invite_token_hash) ON membership TO mapleroute_definer;
GRANT SELECT (id, state, require_mfa_claim) ON tenant TO mapleroute_definer;
-- The tenant policy on membership also applies to the definer's UPDATE and calls app_tenant_id().
GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO mapleroute_definer;
GRANT SELECT (id, email) ON user_account TO mapleroute_definer;

CREATE FUNCTION public.memberships_for_user(p_user uuid)
RETURNS TABLE (tenant_id uuid, role text, require_mfa_claim boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS
$$ SELECT m.tenant_id, m.role, t.require_mfa_claim FROM public.membership m JOIN public.tenant t ON t.id = m.tenant_id
   WHERE m.user_id = p_user AND t.state = 'active' ORDER BY m.created_at, m.tenant_id $$;
ALTER FUNCTION public.memberships_for_user(uuid) OWNER TO mapleroute_definer;
REVOKE EXECUTE ON FUNCTION public.memberships_for_user(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.memberships_for_user(uuid) TO mapleroute_console;

-- Accept one invitation: unexpired, unused, and the signed-in user's stored (verified) email equals the
-- invited email. The email is read from user_account, not passed by the caller. One use: the token
-- hash is cleared. Zero rows means refused, without saying why.
CREATE FUNCTION public.accept_invitation(p_token_hash bytea, p_user uuid, p_now timestamptz)
RETURNS TABLE (tenant_id uuid, role text)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS
$$ UPDATE public.membership m SET user_id = p_user, accepted_at = p_now, invite_token_hash = NULL
   FROM public.user_account u, public.tenant t
   WHERE m.invite_token_hash = p_token_hash AND m.user_id IS NULL AND m.invite_expires_at > p_now
     AND u.id = p_user AND lower(u.email) = lower(m.invited_email)
     AND t.id = m.tenant_id AND t.state = 'active'
     AND NOT EXISTS (SELECT 1 FROM public.membership x WHERE x.tenant_id = m.tenant_id AND x.user_id = p_user)
   RETURNING m.tenant_id, m.role $$;
ALTER FUNCTION public.accept_invitation(bytea, uuid, timestamptz) OWNER TO mapleroute_definer;
REVOKE EXECUTE ON FUNCTION public.accept_invitation(bytea, uuid, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.accept_invitation(bytea, uuid, timestamptz) TO mapleroute_console;

-- ---------------------------------------------------------------- console grants
-- The console creates identities but can never set is_operator (operators are seeded by the owner).
GRANT SELECT (id, idp, idp_subject, email, display_name, is_operator) ON user_account TO mapleroute_console;
GRANT INSERT (id, idp, idp_subject, email, display_name) ON user_account TO mapleroute_console;
GRANT SELECT, INSERT, DELETE ON session TO mapleroute_console;
GRANT UPDATE (tenant_id, token_hash, auth_time, amr, last_seen_at) ON session TO mapleroute_console;
GRANT SELECT, INSERT ON local_credential TO mapleroute_console;
GRANT UPDATE (totp_confirmed_at, totp_last_step, failed_count, locked_until) ON local_credential
  TO mapleroute_console;
GRANT SELECT, INSERT ON email_challenge TO mapleroute_console;
GRANT UPDATE (used_at) ON email_challenge TO mapleroute_console;
-- New tenant in S-02: insert only, no read of other tenants' names.
GRANT INSERT (id, legal_name) ON tenant TO mapleroute_console;
GRANT INSERT (id, tenant_id, user_id, role, invited_email, invite_token_hash, invite_expires_at) ON membership
  TO mapleroute_console;
GRANT UPDATE (role) ON membership TO mapleroute_console;
GRANT DELETE ON membership TO mapleroute_console;
GRANT SELECT ON report TO mapleroute_console;

-- ---------------------------------------------------------------- worker grants (report files)
GRANT SELECT, INSERT ON report TO mapleroute_worker;
GRANT UPDATE (state, allowlist_versions, object_key, sha256, totals, content_type, byte_size) ON report
  TO mapleroute_worker;
