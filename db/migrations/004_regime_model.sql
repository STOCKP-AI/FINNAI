-- 004_regime_model.sql
-- Phase 3: tables for the real regime model. Written together with the code that uses them
-- (ml/src/marketmood_ml/model/registry.py, pipelines/infer.py).
--
-- 1. model_registry: one row per released model, with the SHA-256 of each file; exactly
--    one active row (partial unique index). Inference refuses files whose checksum differs.
-- 2. pipeline_runs: one row per job run (status, row counts, error text) for ops visibility.
-- 3. regime_output: the 2,408 Phase 2 placeholder rows are deleted (migration 003 tagged them;
--    they were never model output). New columns hold the label probabilities, the confirmed
--    label (2-day rule), the top signals as JSON and whether the explanation model agrees
--    with the HMM that day; signal_1..3 (fixed text) are dropped.
--    model_version must exist in model_registry. mm-infer then fills every day.
--
-- Privileges: migration 002's default privileges mean anon/authenticated get nothing on
-- the new tables; the explicit REVOKE and ENABLE ROW LEVEL SECURITY below make that hold
-- on any Postgres (CI) as well. No BEGIN/COMMIT: the runner applies the file in one transaction.

CREATE TABLE IF NOT EXISTS public.model_registry (
    version        text PRIMARY KEY,
    created_at     timestamptz NOT NULL DEFAULT now(),
    status         text NOT NULL CHECK (status IN ('validated', 'experimental', 'retired')),
    train_start    date NOT NULL,
    train_end      date NOT NULL,
    data_end       date NOT NULL,
    config         jsonb NOT NULL,
    metrics        jsonb NOT NULL,
    label_map      jsonb NOT NULL,
    artifact_path  text NOT NULL,
    checksums      jsonb NOT NULL,
    is_active      boolean NOT NULL DEFAULT false,
    CHECK (train_start <= train_end AND train_end <= data_end)
);

-- At most one active model.
CREATE UNIQUE INDEX IF NOT EXISTS model_registry_one_active
    ON public.model_registry (is_active) WHERE is_active;

CREATE TABLE IF NOT EXISTS public.pipeline_runs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job          text NOT NULL,
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz,
    status       text NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    rows         jsonb NOT NULL DEFAULT '{}'::jsonb,
    error        text
);

CREATE INDEX IF NOT EXISTS pipeline_runs_job_started_idx
    ON public.pipeline_runs (job, started_at DESC);

-- regime_output: remove the placeholder rows, then reshape the table.
DELETE FROM public.regime_output WHERE model_version = 'HMM_v1-placeholder';

ALTER TABLE public.regime_output
    DROP COLUMN IF EXISTS signal_1,
    DROP COLUMN IF EXISTS signal_2,
    DROP COLUMN IF EXISTS signal_3,
    ADD COLUMN IF NOT EXISTS p_bull double precision,
    ADD COLUMN IF NOT EXISTS p_sideways double precision,
    ADD COLUMN IF NOT EXISTS p_crisis double precision,
    ADD COLUMN IF NOT EXISTS confirmed_label varchar(10),
    ADD COLUMN IF NOT EXISTS signals jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS surrogate_agrees boolean NOT NULL DEFAULT true;

-- Constraints (Postgres has no ADD CONSTRAINT IF NOT EXISTS, hence the checks).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'regime_output_label_check'
                   AND conrelid = 'public.regime_output'::regclass) THEN
        ALTER TABLE public.regime_output ADD CONSTRAINT regime_output_label_check
            CHECK (label IN ('Bull', 'Sideways', 'Crisis')
                   AND confirmed_label IN ('Bull', 'Sideways', 'Crisis'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'regime_output_probability_check'
                   AND conrelid = 'public.regime_output'::regclass) THEN
        ALTER TABLE public.regime_output ADD CONSTRAINT regime_output_probability_check
            CHECK (p_bull BETWEEN 0 AND 1 AND p_sideways BETWEEN 0 AND 1 AND p_crisis BETWEEN 0 AND 1
                   AND confidence BETWEEN 0 AND 1);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'regime_output_model_version_fkey'
                   AND conrelid = 'public.regime_output'::regclass) THEN
        ALTER TABLE public.regime_output ADD CONSTRAINT regime_output_model_version_fkey
            FOREIGN KEY (model_version) REFERENCES public.model_registry (version);
    END IF;
END $$;

ALTER TABLE public.regime_output
    ALTER COLUMN label SET NOT NULL,
    ALTER COLUMN confidence SET NOT NULL,
    ALTER COLUMN p_bull SET NOT NULL,
    ALTER COLUMN p_sideways SET NOT NULL,
    ALTER COLUMN p_crisis SET NOT NULL,
    ALTER COLUMN confirmed_label SET NOT NULL,
    ALTER COLUMN model_version SET NOT NULL;

CREATE INDEX IF NOT EXISTS regime_output_model_version_idx
    ON public.regime_output (model_version);

COMMENT ON TABLE public.regime_output IS
    'One row per trading day from the active model in model_registry (causal filtered probabilities). Rewritten by mm-infer.';
COMMENT ON COLUMN public.regime_output.label IS 'Most likely regime that day (filtered, no look-ahead).';
COMMENT ON COLUMN public.regime_output.confirmed_label IS 'Label shown to users: changes only after 2 consecutive days.';
COMMENT ON COLUMN public.regime_output.signals IS
    'Top 3 features for the confirmed label: [{feature, value, contribution, direction}] (LightGBM TreeSHAP).';
COMMENT ON COLUMN public.regime_output.confidence IS
    'Filtered probability of confirmed_label (the label shown). The model is overconfident: not a calibrated probability.';
COMMENT ON COLUMN public.regime_output.surrogate_agrees IS
    'False when the explanation model disagrees with the HMM that day: treat the signals as approximate.';
COMMENT ON TABLE public.model_registry IS
    'Released regime models. Exactly one is_active row; checksums are verified before a model is loaded.';
COMMENT ON TABLE public.pipeline_runs IS 'One row per pipeline job run (infer, nightly).';

-- Row Level Security on, no policies: the Data API sees nothing (same as the other tables).
ALTER TABLE public.model_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pipeline_runs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON TABLE public.model_registry, public.pipeline_runs FROM anon, authenticated;
        REVOKE ALL ON SEQUENCE public.pipeline_runs_id_seq FROM anon, authenticated;
    END IF;
END $$;
