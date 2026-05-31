import yfinance as yf
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv, find_dotenv
import os
import io
import requests
from datetime import datetime, timedelta

print("Loading environment variables...")

dotenv_path = find_dotenv()
if dotenv_path:
    print(f"Found .env file at: {dotenv_path}")
    load_dotenv(dotenv_path)
else:
    print(".env file not found automatically; using current environment variables")

DATABASE_URL = os.getenv("DATABASE_URL")

print("Connecting to database...")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

def parse_fii_payload(payload):
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, str):
        try:
            payload = pd.read_csv(io.StringIO(payload))
        except Exception:
            payload = []

    records = []
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, pd.DataFrame):
        records = payload.to_dict(orient="records")
    else:
        return {}

    mapping = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        date_key = next((k for k in row if "date" in k.lower()), None)
        if not date_key:
            continue
        value_key = next((k for k in row if any(x in k.lower() for x in ["fii", "flow", "net", "buy", "sell"])), None)
        if not value_key:
            numeric_keys = [k for k, v in row.items() if isinstance(v, (int, float))]
            value_key = numeric_keys[0] if numeric_keys else None
        if not value_key:
            continue
        try:
            date_val = pd.to_datetime(row[date_key], dayfirst=True, errors="coerce")
            if pd.isna(date_val):
                continue
            value = row[value_key]
            if isinstance(value, str):
                value = value.replace(",", "").strip()
            value = float(value)
            mapping[date_val.strftime("%Y-%m-%d")] = value
        except Exception:
            continue
    return mapping


def fetch_fii_data(start_date, end_date):
    print("Fetching FII data...")

    csv_path = os.getenv("FII_FLOW_CSV_PATH")
    if csv_path and os.path.exists(csv_path):
        print(f"Loading FII flow data from CSV: {csv_path}")
        try:
            csv_df = pd.read_csv(csv_path)
            return parse_fii_payload(csv_df)
        except Exception as exc:
            print(f"Failed to read FII CSV: {exc}")

    api_url = os.getenv("FII_FLOW_API_URL")
    api_key = os.getenv("FII_FLOW_API_KEY")
    if api_url:
        if "example" in api_url:
            print("FII_FLOW_API_URL is still a placeholder. Set it to a real endpoint or use FII_FLOW_CSV_PATH.")
        params = {
            "fromDate": start_date.strftime("%d-%m-%Y"),
            "toDate": end_date.strftime("%d-%m-%Y"),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = requests.get(api_url, headers=headers, params=params, timeout=20)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "json" in content_type.lower():
                payload = response.json()
            else:
                payload = response.text
            return parse_fii_payload(payload)
        except Exception as exc:
            print(f"Failed to fetch FII from API: {exc}")

    print("Attempting NSE endpoint fallback...")
    try:
        session = requests.Session()
        fallback_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": "https://www.nseindia.com/",
        }
        session.get("https://www.nseindia.com", headers=fallback_headers, timeout=20)
        params = {
            "fromDate": start_date.strftime("%d-%m-%Y"),
            "toDate": end_date.strftime("%d-%m-%Y"),
        }
        nse_url = "https://www.nseindia.com/api/historical/fiiData"
        response = session.get(nse_url, headers=fallback_headers, params=params, timeout=20)
        if response.status_code == 200:
            return parse_fii_payload(response.json())
        print(f"NSE fallback returned {response.status_code}")
    except Exception as exc:
        print(f"NSE fallback failed: {exc}")

    print("No FII data source available. Using placeholder zeros.")
    return {}

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
    df["fii_flow"] = df["date"].dt.strftime("%Y-%m-%d").map(fii_data).fillna(0)
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