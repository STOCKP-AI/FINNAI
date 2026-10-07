-- 002_revoke_public_api_privileges.sql
-- Audit finding A5. NOT YET APPLIED to the live database: apply only after the
-- team approves (Supabase SQL editor, or the migration tool we choose).
--
-- Why: Supabase grants the API roles anon and authenticated ALL privileges on
-- tables in public. Today only RLS (with no policies) stops them, and TRUNCATE
-- is not governed by RLS. The prototype never reads these tables through the
-- Data API (the FastAPI backend connects directly), so the API roles need no
-- privileges at all. Defence in depth: if RLS is ever disabled by mistake,
-- nothing leaks.
--
-- Effect on the app: none. Pipelines and the backend connect as postgres
-- (the owner), which keeps all privileges.
--
-- Supabase-specific: it needs the anon and authenticated roles, which plain
-- Postgres does not have (create them first in a local or CI database).

BEGIN;

REVOKE ALL ON TABLE public.market_data, public.features, public.regime_output, public.users
    FROM anon, authenticated;

-- Stop new tables created by postgres in public from being granted to the API roles.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;

-- rls_auto_enable() is Supabase's event-trigger function that switches RLS on for
-- new tables. As an event-trigger function it cannot actually be called through
-- the API, but the Security Advisor flags it (lint 0028/0029). Removing EXECUTE
-- from the API roles silences the warning; the event trigger keeps working
-- because event triggers do not check EXECUTE when they fire.
DO $$
BEGIN
    IF to_regprocedure('public.rls_auto_enable()') IS NOT NULL THEN
        REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon, authenticated, PUBLIC;
    END IF;
END $$;

COMMIT;

-- Verify after applying (expect 0 rows):
--   SELECT grantee, table_name, privilege_type
--   FROM information_schema.role_table_grants
--   WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated');
