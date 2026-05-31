CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE market_data (
    date DATE PRIMARY KEY,
    open FLOAT,
    high FLOAT,
    low FLOAT,
    close FLOAT,
    volume BIGINT,
    vix_close FLOAT
);

CREATE TABLE features (
    date DATE PRIMARY KEY,
    volatility_20d FLOAT,
    sharpe_60d FLOAT,
    autocorr_lag1 FLOAT,
    vix_level FLOAT,
    vix_change_30d FLOAT,
    drawdown_60d FLOAT,
    skewness_30d FLOAT,
    bb_width FLOAT,
    fii_flow FLOAT
);

CREATE TABLE regime_output (
    date DATE PRIMARY KEY,
    label VARCHAR(10),
    confidence FLOAT,
    signal_1 TEXT,
    signal_2 TEXT,
    signal_3 TEXT,
    model_version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    plan VARCHAR(20) DEFAULT 'trial',
    trial_start DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);