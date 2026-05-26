import yfinance as yf
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import os

print("Loading environment variables...")

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("Connecting to database...")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print("Downloading NIFTY data...")

nifty = yf.download("^NSEI", period="10y", interval="1d")

print("Downloading India VIX data...")

vix = yf.download("^INDIAVIX", period="10y", interval="1d")

print("Processing data...")

# Reset index
nifty = nifty.reset_index()
vix = vix.reset_index()

# Flatten multi-index columns if present
if isinstance(nifty.columns, pd.MultiIndex):
    nifty.columns = ['_'.join(col).strip() if isinstance(col, tuple) else col for col in nifty.columns.values]

if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = ['_'.join(col).strip() if isinstance(col, tuple) else col for col in vix.columns.values]

print("NIFTY columns:")
print(nifty.columns)

print("VIX columns:")
print(vix.columns)

# Rename columns properly
nifty = nifty.rename(columns={
    nifty.columns[0]: "date",
    [c for c in nifty.columns if "Open" in c][0]: "open",
    [c for c in nifty.columns if "High" in c][0]: "high",
    [c for c in nifty.columns if "Low" in c][0]: "low",
    [c for c in nifty.columns if "Close" in c][0]: "close",
    [c for c in nifty.columns if "Volume" in c][0]: "volume"
})

vix = vix.rename(columns={
    vix.columns[0]: "date",
    [c for c in vix.columns if "Close" in c][0]: "vix_close"
})

# Keep only required columns
nifty = nifty[["date", "open", "high", "low", "close", "volume"]]
vix = vix[["date", "vix_close"]]

# Merge
df = pd.merge(nifty, vix, on="date", how="inner")

# Drop nulls
df.dropna(inplace=True)

print(df.head())

print(f"Rows fetched: {len(df)}")

# Prepare rows
rows = []

for _, row in df.iterrows():
    rows.append((
        row["date"],
        float(row["open"]),
        float(row["high"]),
        float(row["low"]),
        float(row["close"]),
        int(row["volume"]),
        float(row["vix_close"])
    ))

print("Inserting into PostgreSQL...")

query = """
INSERT INTO market_data
(date, open, high, low, close, volume, vix_close)
VALUES %s
ON CONFLICT (date)
DO UPDATE SET
open = EXCLUDED.open,
high = EXCLUDED.high,
low = EXCLUDED.low,
close = EXCLUDED.close,
volume = EXCLUDED.volume,
vix_close = EXCLUDED.vix_close;
"""

execute_values(cur, query, rows)

conn.commit()

print("Data inserted successfully!")

cur.close()
conn.close()

print("DONE!")