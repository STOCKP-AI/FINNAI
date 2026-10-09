-- 005_agent_tables.sql
-- Phase 4: backend API and AI analyst. Written together with backend/app/.
--
-- 1. agent_reader: a NOLOGIN role for every public read and every AI tool. The API switches
--    to it with SET LOCAL ROLE inside a READ ONLY transaction, so tools can only SELECT the
--    market tables below - never chat data, never writes. RLS stays on: the policies here
--    let only agent_reader read (anon/authenticated still have no privileges, migration 002).
-- 2. glossary (seeded from db/seed/glossary.sql), daily_briefs (one AI-written brief a day).
-- 3. chat_sessions / chat_messages: server-side history, so a client cannot forge turns.
--    No names or emails: the prototype has no accounts; client_hash = HMAC of the IP.
-- 4. usage_daily: the prototype's 10-chats-per-IP-per-day limit (atomic counters), plus a
--    looser cap on cached chip answers so they cannot be used to fill the database.
-- 5. answer_cache: answers to the fixed suggestion chips, once per day and regime.
-- Nothing is deleted or dropped. No BEGIN/COMMIT: the runner applies the file in one transaction.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_reader') THEN
        CREATE ROLE agent_reader NOLOGIN;
    END IF;
END $$;

-- The connecting user (postgres on Supabase and in CI) may switch to agent_reader.
GRANT agent_reader TO postgres;

CREATE TABLE IF NOT EXISTS public.glossary (
    term        text PRIMARY KEY,
    aliases     text[] NOT NULL DEFAULT '{}',
    definition  text NOT NULL CHECK (length(definition) BETWEEN 20 AND 600),
    category    text NOT NULL DEFAULT 'general'
);

CREATE TABLE IF NOT EXISTS public.daily_briefs (
    date          date PRIMARY KEY,
    brief         text NOT NULL,
    what_changed  text,
    source        text NOT NULL CHECK (source IN ('llm', 'template')),
    model         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_hash     text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_active_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_sessions_client_idx ON public.chat_sessions (client_hash);

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  uuid NOT NULL REFERENCES public.chat_sessions (id) ON DELETE CASCADE,
    role        text NOT NULL CHECK (role IN ('user', 'assistant')),
    content     text NOT NULL,
    tools       jsonb NOT NULL DEFAULT '[]'::jsonb,
    warnings    jsonb NOT NULL DEFAULT '[]'::jsonb,
    model       text,
    tokens_in   integer,
    tokens_out  integer,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_messages_session_idx ON public.chat_messages (session_id, id DESC);

CREATE TABLE IF NOT EXISTS public.usage_daily (
    client_hash  text NOT NULL,
    day          date NOT NULL,
    chats        integer NOT NULL DEFAULT 0 CHECK (chats >= 0),   -- AI answers (limit 10)
    cached       integer NOT NULL DEFAULT 0 CHECK (cached >= 0),  -- cached chip answers (limit 50)
    PRIMARY KEY (client_hash, day)
);

CREATE TABLE IF NOT EXISTS public.answer_cache (
    day         date NOT NULL,
    chip_id     text NOT NULL,
    regime      text NOT NULL,
    as_of       date NOT NULL,
    answer      text NOT NULL,
    tools       jsonb NOT NULL DEFAULT '[]'::jsonb,
    model       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (day, chip_id, regime)
);

COMMENT ON TABLE public.glossary IS 'Curated definitions for the AI lookup_glossary tool (seed: db/seed/glossary.sql).';
COMMENT ON TABLE public.daily_briefs IS 'Dashboard brief, one per trading day (mm-brief); template text when the AI check fails.';
COMMENT ON TABLE public.chat_sessions IS 'Anonymous chat sessions; client_hash is an HMAC of the IP, never the IP itself.';
COMMENT ON TABLE public.usage_daily IS 'Chats per client per IST day (prototype limit: 10).';
COMMENT ON TABLE public.answer_cache IS 'Answers to the fixed suggestion chips, reused for everyone on the same day and regime.';

-- RLS on every new table (Supabase also does this automatically for new tables).
ALTER TABLE public.glossary ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_briefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.answer_cache ENABLE ROW LEVEL SECURITY;

-- agent_reader: SELECT on the market tables only, through explicit RLS policies.
GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON public.market_data, public.features, public.regime_output, public.model_registry,
    public.daily_briefs, public.glossary TO agent_reader;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['market_data', 'features', 'regime_output', 'model_registry',
                             'daily_briefs', 'glossary'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_policies
                       WHERE schemaname = 'public' AND tablename = t AND policyname = 'agent_reader_select') THEN
            EXECUTE format('CREATE POLICY agent_reader_select ON public.%I FOR SELECT TO agent_reader USING (true)', t);
        END IF;
    END LOOP;
END $$;

-- The API roles get nothing on the new tables (also covered by migration 002's defaults).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON TABLE public.glossary, public.daily_briefs, public.chat_sessions,
            public.chat_messages, public.usage_daily, public.answer_cache FROM anon, authenticated;
        REVOKE ALL ON SEQUENCE public.chat_messages_id_seq FROM anon, authenticated;
    END IF;
END $$;
