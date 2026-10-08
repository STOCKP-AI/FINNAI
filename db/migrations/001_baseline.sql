-- 001_baseline.sql
-- Baseline of the live Supabase schema (project FINNAI) as of 7 Oct 2026.
-- Generated from information_schema / pg_catalog during the Phase 2.5 audit.
--
-- Replaces db/schema/schema.sql, which had drifted from the database
-- (it lacked market_data.fii_flow). From now on every schema change is a new
-- numbered file in this folder; never edit a migration that has been applied.
--
-- Written with IF NOT EXISTS so it is a no-op on the live database and builds
-- an identical schema on an empty Postgres 15+ database (CI, local, new project).
-- gen_random_uuid() is built into Postgres 13+, so pgcrypto is not required.
--
-- Not included: Supabase-managed objects (the ensure_rls event trigger and its
-- function public.rls_auto_enable(), extensions, auth/storage schemas).

CREATE TABLE IF NOT EXISTS public.market_data (
    date       date PRIMARY KEY,
    open       double precision,
    high       double precision,
    low        double precision,
    close      double precision,
    volume     bigint,
    vix_close  double precision,
    fii_flow   double precision DEFAULT 0  -- no permitted source yet; excluded from modelling
);

CREATE TABLE IF NOT EXISTS public.features (
    date            date PRIMARY KEY,
    volatility_20d  double precision,
    sharpe_60d      double precision,
    autocorr_lag1   double precision,
    vix_level       double precision,
    vix_change_30d  double precision,
    drawdown_60d    double precision,
    skewness_30d    double precision,
    bb_width        double precision,
    fii_flow        double precision
);

CREATE TABLE IF NOT EXISTS public.regime_output (
    date           date PRIMARY KEY,
    label          varchar(10),
    confidence     double precision,
    signal_1       text,
    signal_2       text,
    signal_3       text,
    model_version  text,
    created_at     timestamptz DEFAULT now()
);

-- Unused in the prototype (Supabase Auth replaces it in Phase 7). Kept so the
-- baseline matches the live database; a later migration may drop it.
CREATE TABLE IF NOT EXISTS public.users (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email        text NOT NULL UNIQUE,
    plan         varchar(20) DEFAULT 'trial',
    trial_start  date DEFAULT CURRENT_DATE,
    created_at   timestamptz DEFAULT now()
);

-- Row Level Security is enabled on every table with no policies: the Data API
-- (anon / authenticated keys) sees nothing; the backend and pipelines connect
-- as the database owner and are not affected.
ALTER TABLE public.market_data   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.features      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.regime_output ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users         ENABLE ROW LEVEL SECURITY;
