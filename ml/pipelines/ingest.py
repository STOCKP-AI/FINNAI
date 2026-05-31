import yfinance as yf
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import os
import requests
from datetime import datetime, timedelta

print("Loading environment variables...")

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("Connecting to database...")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

def fetch_fii_data(start_date, end_date):
    """
    Fetch FII flow data from NSE public data.
    Data is available at: https://www.nseindia.com/products/content/derivatives/equities/bhav_copy_fo.htm
    This fetches monthly FII data which is publicly available.
    """
    print("Fetching FII data...")
    fii_data = {}
    
    # Try fetching from NSE FII statistics
    try:
        url = "https://www.nseindia.com/api/historical/fiiData"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print("Successfully fetched FII data from NSE API")
            # Parse response and store in fii_data dict
            # Structure: {date: fii_flow_value}
        else:
            print("NSE API unavailable, using placeholder data")
    except Exception as e:
        print(f"Could not fetch from NSE API: {e}")
        print("Using placeholder data - update this with real API once available")
    
    return fii_data

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

# Fetch and merge FII data
fii_data = fetch_fii_data(df["date"].min(), df["date"].max())

# Add FII flow column (0 as placeholder if not fetched)
if fii_data:
    df["fii_flow"] = df["date"].map(fii_data).fillna(0)
else:
    df["fii_flow"] = 0
    print("Warning: FII data not available, using placeholder zeros")

# Drop nulls
df.dropna(inplace=True)

print(df.head())

print(f"Rows fetched: {len(df)}")

# Prepare rows
rows = []

# Save downloaded CSVs for inspection/backup
#os.makedirs("data", exist_ok=True)
#nifty.to_csv(os.path.join("data", "nifty.csv"), index=False)
#vix.to_csv(os.path.join("data", "vix.csv"), index=False)
#df.to_csv(os.path.join("data", "market_data.csv"), index=False)
#print("Saved CSVs to data/ (nifty.csv, vix.csv, market_data.csv)")

for _, row in df.iterrows():
    rows.append((
        row["date"],
        float(row["open"]),
        float(row["high"]),
        float(row["low"]),
        float(row["close"]),
        int(row["volume"]),
        float(row["vix_close"]),
        float(row["fii_flow"])
    ))

print("Inserting into PostgreSQL...")

query = """
INSERT INTO market_data
(date, open, high, low, close, volume, vix_close, fii_flow)
VALUES %s
ON CONFLICT (date)
DO UPDATE SET
open = EXCLUDED.open,
high = EXCLUDED.high,
low = EXCLUDED.low,
close = EXCLUDED.close,
volume = EXCLUDED.volume,
vix_close = EXCLUDED.vix_close,
fii_flow = EXCLUDED.fii_flow;
"""

execute_values(cur, query, rows)

conn.commit()

print("Data inserted successfully!")

cur.close()
conn.close()

print("DONE!")