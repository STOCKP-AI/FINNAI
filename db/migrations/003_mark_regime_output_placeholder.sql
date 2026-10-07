-- 003_mark_regime_output_placeholder.sql
-- Data migration, audit finding A2. Applied to Supabase on 7 Oct 2026.
--
-- The 2,408 rows in regime_output were written once (29 Jun 2026) by the Phase 2
-- prototype script: labels from Viterbi decoding (which uses future data), states
-- named by VIX level only, confidence hard-coded to 0.85 and fixed signal text
-- (98.5% of days labelled Bull). Tag them so nobody presents them as model output.
-- Phase 3 replaces them with the real model's output under a new model_version.

UPDATE public.regime_output
SET model_version = 'HMM_v1-placeholder'
WHERE model_version = 'HMM_v1';

COMMENT ON TABLE public.regime_output IS
    'Rows with model_version HMM_v1-placeholder are a Phase 2 placeholder (fixed 0.85 confidence, hard-coded signals). Not model output.';
