-- 002_revoke_public_api_privileges.sql
-- Audit finding A5. Applied to Supabase on 7 Oct 2026.
--
-- Why: Supabase granted the API roles anon and authenticated ALL privileges on
-- tables in public. Only RLS (with no policies) stopped them, and TRUNCATE is
-- not governed by RLS. The prototype never reads these tables through the
-- Data API (the FastAPI backend connects directly), so the API roles need no
-- privileges at all. Defence in depth: if RLS is ever disabled by mistake,
-- nothing leaks. This also matches Supabase's new platform default (new tables
-- are no longer exposed to the Data API automatically; enforced on all projects
-- from 30 Oct 2026): https://supabase.com/docs/guides/api/securing-your-api
--
-- Effect on the app: none. Pipelines and the backend connect as postgres
-- (the owner), which keeps all privileges. If the Data API is ever needed for
-- a table, grant it explicitly in a new migration together with RLS policies.
--
-- Supabase-specific: it needs the anon and authenticated roles, which plain
-- Postgres does not have (CI creates them first). No BEGIN/COMMIT: the runner
-- applies each migration in a single transaction (psql -1, Supabase CLI/MCP).

REVOKE ALL ON TABLE public.market_data, public.features, public.regime_output, public.users
    FROM anon, authenticated;

-- Objects that postgres creates in public later are not granted to the API roles.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM anon, authenticated;
-- EXECUTE for PUBLIC is a global (not per-schema) default in Postgres, so it can
-- only be removed without "IN SCHEMA". New functions created by postgres then
-- need an explicit GRANT EXECUTE to be callable by anyone else.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- rls_auto_enable() is Supabase's event-trigger function that switches RLS on for
-- new tables. As an event-trigger function it cannot actually be called through
-- the API, but the Security Advisor flags it (lint 0028/0029). Removing EXECUTE
-- silences the warning; the event trigger keeps working because event triggers
-- do not check EXECUTE when they fire (verified on Postgres 16).
DO $$
BEGIN
    IF to_regprocedure('public.rls_auto_enable()') IS NOT NULL THEN
        REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon, authenticated, PUBLIC;
    END IF;
END $$;

-- Verify (expect 0 rows):
--   SELECT grantee, table_name, privilege_type
--   FROM information_schema.role_table_grants
--   WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated');
