import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import os
import numpy as np

print("Loading environment variables...")

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("Connecting to database...")

conn = psycopg2.connect(DATABASE_URL)

query = "SELECT * FROM market_data ORDER BY date ASC;"

df = pd.read_sql(query, conn)

print("Computing features...")

# Daily returns
df["returns"] = df["close"].pct_change()

# Volatility (20-day rolling std)
df["volatility_20d"] = df["returns"].rolling(20).std()

# Sharpe ratio approximation
df["sharpe_60d"] = (
    df["returns"].rolling(60).mean() /
    df["returns"].rolling(60).std()
)

# Autocorrelation lag-1
df["autocorr_lag1"] = (
    df["returns"]
    .rolling(30)
    .apply(lambda x: x.autocorr(lag=1), raw=False)
)

# VIX level
df["vix_level"] = df["vix_close"]

# VIX 30-day change
df["vix_change_30d"] = df["vix_close"].pct_change(30)

# Drawdown
rolling_max = df["close"].rolling(60).max()
df["drawdown_60d"] = (df["close"] - rolling_max) / rolling_max

# Skewness
df["skewness_30d"] = (
    df["returns"]
    .rolling(30)
    .skew()
)

# Bollinger Band width
rolling_mean = df["close"].rolling(20).mean()
rolling_std = df["close"].rolling(20).std()

upper_band = rolling_mean + (2 * rolling_std)
lower_band = rolling_mean - (2 * rolling_std)

df["bb_width"] = (
    (upper_band - lower_band) / rolling_mean
)

# FII flow from market_data table
df["fii_flow"] = df["fii_flow"]  # Already in the dataframe from query

# Drop NaNs
df.dropna(inplace=True)

print(df.head())

print(f"Feature rows: {len(df)}")

cur = conn.cursor()

# Upsert features incrementally by date
insert_query = """
INSERT INTO features (
    date,
    volatility_20d,
    sharpe_60d,
    autocorr_lag1,
    vix_level,
    vix_change_30d,
    drawdown_60d,
    skewness_30d,
    bb_width,
    fii_flow
)
VALUES %s
ON CONFLICT (date) DO UPDATE SET
    volatility_20d = EXCLUDED.volatility_20d,
    sharpe_60d = EXCLUDED.sharpe_60d,
    autocorr_lag1 = EXCLUDED.autocorr_lag1,
    vix_level = EXCLUDED.vix_level,
    vix_change_30d = EXCLUDED.vix_change_30d,
    drawdown_60d = EXCLUDED.drawdown_60d,
    skewness_30d = EXCLUDED.skewness_30d,
    bb_width = EXCLUDED.bb_width,
    fii_flow = EXCLUDED.fii_flow;
"""

rows = []
for _, row in df.iterrows():
    rows.append((
        row["date"],
        float(row["volatility_20d"]),
        float(row["sharpe_60d"]),
        float(row["autocorr_lag1"]),
        float(row["vix_level"]),
        float(row["vix_change_30d"]),
        float(row["drawdown_60d"]),
        float(row["skewness_30d"]),
        float(row["bb_width"]),
        float(row["fii_flow"])
    ))

if rows:
    execute_values(cur, insert_query, rows)
    conn.commit()
    print("Features upserted successfully!")
else:
    print("No feature rows to upsert.")

cur.close()
conn.close()

print("DONE!")