-- 006_chat_feedback.sql
-- Phase 5: thumbs up / down on AI answers (CHAT-09), kept to improve the evals.
--
-- One rating per answer; a second click replaces the first. Only the API writes it (as the
-- connecting user, after checking that the answer belongs to the caller's session); the
-- read-only agent_reader role and the Data API roles get nothing. RLS on, no policies.
-- Nothing is deleted or dropped. No BEGIN/COMMIT: the runner applies the file in one transaction.

CREATE TABLE IF NOT EXISTS public.chat_feedback (
    message_id  bigint PRIMARY KEY REFERENCES public.chat_messages (id) ON DELETE CASCADE,
    rating      smallint NOT NULL CHECK (rating IN (-1, 1)),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.chat_feedback IS
    'Thumbs up (1) / down (-1) on assistant answers (CHAT-09). Written only by the API.';

ALTER TABLE public.chat_feedback ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON TABLE public.chat_feedback FROM anon, authenticated;
    END IF;
END $$;
