import pandas as pd
import psycopg2
from dotenv import load_dotenv
import os
from sklearn.preprocessing import StandardScaler
from hmmlearn.hmm import GaussianHMM
import matplotlib.pyplot as plt

print("Loading environment variables...")

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("Connecting to database...")

conn = psycopg2.connect(DATABASE_URL)

query = """
SELECT *
FROM features
ORDER BY date ASC;
"""

df = pd.read_sql(query, conn)

conn.close()

print("Preparing features...")

feature_cols = [
    "volatility_20d",
    "sharpe_60d",
    "autocorr_lag1",
    "vix_level",
    "vix_change_30d",
    "drawdown_60d",
    "skewness_30d",
    "bb_width"
]

X = df[feature_cols]

# Scale features
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

print("Training HMM model...")

model = GaussianHMM(
    n_components=3,
    covariance_type="full",
    n_iter=1000,
    random_state=42
)

model.fit(X_scaled)

print("Predicting market regimes...")

hidden_states = model.predict(X_scaled)

df["regime"] = hidden_states

# Label regimes using VIX averages
regime_means = df.groupby("regime")["vix_level"].mean()

sorted_regimes = regime_means.sort_values()

label_map = {
    sorted_regimes.index[0]: "Bull",
    sorted_regimes.index[1]: "Neutral",
    sorted_regimes.index[2]: "Bear"
}

df["label"] = df["regime"].map(label_map)

print(df[["date", "label"]].head())

print("Connecting again to store predictions...")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Clear previous predictions
cur.execute("DELETE FROM regime_output;")

insert_query = """
INSERT INTO regime_output (
    date,
    label,
    confidence,
    signal_1,
    signal_2,
    signal_3,
    model_version
)
VALUES (%s,%s,%s,%s,%s,%s,%s);
"""

print("Storing predictions into database...")

for _, row in df.iterrows():

    confidence = 0.85

    if row["label"] == "Bull":
        signal_1 = "Low volatility"
        signal_2 = "Positive momentum"
        signal_3 = "Risk appetite strong"

    elif row["label"] == "Bear":
        signal_1 = "High volatility"
        signal_2 = "Negative sentiment"
        signal_3 = "Defensive positioning"

    else:
        signal_1 = "Mixed signals"
        signal_2 = "Range-bound market"
        signal_3 = "Wait and watch"

    cur.execute(insert_query, (
        row["date"],
        row["label"],
        confidence,
        signal_1,
        signal_2,
        signal_3,
        "HMM_v1"
    ))

conn.commit()

print("Regime predictions stored successfully!")

cur.close()
conn.close()

# Plot regimes
plt.figure(figsize=(15,6))

for label in df["label"].unique():

    mask = df["label"] == label

    plt.scatter(
        df["date"][mask],
        df["vix_level"][mask],
        s=10,
        label=label
    )

plt.legend()

plt.title("Market Regimes using HMM")
plt.xlabel("Date")
plt.ylabel("VIX Level")

plt.show()

print("DONE!")