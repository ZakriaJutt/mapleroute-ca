-- 0006 (B1 fix round 4: B1-012 under clock skew).
-- No worker wall clock takes part in a safety decision. A binding carries a check generation; every
-- mismatch increments it in the transaction that un-verifies or suspends; a match verifies only by
-- a compare-and-set on the generation its check recorded when it took the lease, while it still
-- holds the lease (identified by its token). Lease times and validity stamps come from the database
-- clock, `app_now()`.

-- ---------------------------------------------------------------- the database clock
-- `app_now()` is clock_timestamp() of the database server. `clock_override` is a test seam: the test
-- harness, connecting as the database owner, pins the database clock to the fake clock. No
-- application role can write it; it must be empty outside tests (a readiness check for that is not built).
CREATE TABLE clock_override (
  id boolean PRIMARY KEY DEFAULT true,
  at timestamptz NOT NULL,
  CONSTRAINT ck_clock_override_single CHECK (id)
);
GRANT SELECT ON clock_override TO mapleroute_gateway, mapleroute_console, mapleroute_worker, mapleroute_operator;
CREATE FUNCTION public.app_now() RETURNS timestamptz
LANGUAGE sql VOLATILE SET search_path = pg_catalog, public, pg_temp AS
$$ SELECT COALESCE((SELECT o.at FROM public.clock_override o WHERE o.id), clock_timestamp()) $$;
REVOKE EXECUTE ON FUNCTION public.app_now() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.app_now()
  TO mapleroute_gateway, mapleroute_console, mapleroute_worker, mapleroute_operator;

-- ---------------------------------------------------------------- check generation
ALTER TABLE binding ADD COLUMN check_generation bigint NOT NULL DEFAULT 0;
GRANT UPDATE (check_generation) ON binding TO mapleroute_worker;
-- The generation of the binding when this lease was claimed.
ALTER TABLE binding_check_lease ADD COLUMN generation bigint NOT NULL DEFAULT 0;
GRANT UPDATE (generation) ON binding_check_lease TO mapleroute_worker;

-- The generation never decreases, and a statement that increments it cannot also turn a binding verified.
CREATE FUNCTION public.binding_generation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
  IF NEW.check_generation < OLD.check_generation THEN
    RAISE EXCEPTION 'binding % check_generation cannot decrease', OLD.id USING ERRCODE = 'P0001';
  END IF;
  IF NEW.check_generation > OLD.check_generation AND NEW.status = 'verified' AND OLD.status <> 'verified' THEN
    RAISE EXCEPTION 'binding % cannot be verified by a mismatch', OLD.id USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
REVOKE EXECUTE ON FUNCTION public.binding_generation_guard() FROM PUBLIC;
CREATE TRIGGER binding_generation_monotonic BEFORE UPDATE ON binding
  FOR EACH ROW EXECUTE FUNCTION public.binding_generation_guard();
