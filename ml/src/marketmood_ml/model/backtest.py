"""Causal backtest of a simple regime-aware allocation against buy-and-hold.

A research result for the report, not a recommendation (Full Project Document 12.7):
    NIFTY weight 100% in Bull, 60% in Sideways, 30% in Crisis; the rest earns a fixed
    liquid-fund rate. The label known after the close of day t sets the weight from day
    t + delay (delay=1: trade at that close, earn the next day's return). Costs are 0.1%
    of the value traded. NIFTY here is the price index (no dividends), which understates
    buy-and-hold by roughly 1-1.5% a year.
"""

import numpy as np
import pandas as pd

ALLOCATION = {"Bull": 1.0, "Sideways": 0.6, "Crisis": 0.3}
CASH_RATE = 0.06  # assumed liquid-fund return per year
COST = 0.001  # 0.1% of the value traded
TRADING_DAYS = 252


def backtest(close, labels, delay=1, cost=COST, cash_rate=CASH_RATE, allocation=ALLOCATION):
    """Return (metrics dict, daily DataFrame) for the strategy and buy-and-hold."""
    if delay < 1:
        raise ValueError("delay must be >= 1 (a label is known only after the close)")
    close = pd.Series(np.asarray(close, dtype=float))
    ret = close.pct_change().fillna(0.0)
    target = pd.Series([allocation[lab] for lab in labels], dtype=float)
    weight = target.shift(delay).bfill()  # before the first signal: start at the first weight
    turnover = weight.diff().abs().fillna(0.0)
    cash_daily = (1 + cash_rate) ** (1 / TRADING_DAYS) - 1
    strategy = weight * ret + (1 - weight) * cash_daily - turnover * cost
    daily = pd.DataFrame({"weight": weight, "strategy": strategy, "buy_hold": ret})
    metrics = {
        "strategy": _summary(strategy, cash_daily),
        "buy_hold": _summary(ret, cash_daily),
        "weight_changes": int((turnover > 0).sum()),
        "delay_days": delay,
        "cost": cost,
        "cash_rate": cash_rate,
    }
    return metrics, daily


def _summary(daily_returns, cash_daily):
    r = pd.Series(daily_returns, dtype=float)
    value = (1 + r).cumprod()
    years = len(r) / TRADING_DAYS
    vol = float(r.std(ddof=0) * np.sqrt(TRADING_DAYS))
    excess = r - cash_daily
    sharpe = float(excess.mean() / excess.std(ddof=0) * np.sqrt(TRADING_DAYS)) if excess.std() > 0 else 0.0
    return {
        "cagr": round(float(value.iloc[-1] ** (1 / years) - 1), 4) if years > 0 else 0.0,
        "volatility": round(vol, 4),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(float((value / value.cummax() - 1).min()), 4),
        "final_value": round(float(value.iloc[-1]), 4),
    }
