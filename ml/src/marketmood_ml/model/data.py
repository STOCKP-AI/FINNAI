"""Load the model's input table: date, the 8 features and the NIFTY close, one row per day."""

import pandas as pd

from marketmood_ml.common import FEATURE_COLUMNS, MM_DATA_002, PipelineError

COLUMNS = ["date", *FEATURE_COLUMNS, "close"]

FRAME_SQL = f"""
SELECT f.date, {", ".join("f." + c for c in FEATURE_COLUMNS)}, m.close
FROM features f
JOIN market_data m USING (date)
ORDER BY f.date;
"""


def load_frame(conn):
    with conn.cursor() as cur:
        cur.execute(FRAME_SQL)
        rows = cur.fetchall()
    return _clean(pd.DataFrame(rows, columns=COLUMNS))


def load_frame_csv(path):
    """Offline input (same columns), e.g. a CSV exported from Supabase."""
    return _clean(pd.read_csv(path)[COLUMNS])


def _clean(frame):
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for col in COLUMNS[1:]:
        frame[col] = pd.to_numeric(frame[col]).astype(float)
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise PipelineError(MM_DATA_002, "duplicate dates in the model input")
    if frame[COLUMNS[1:]].isna().any().any():
        raise PipelineError(MM_DATA_002, "missing values in the model input (run mm-features first)")
    return frame
