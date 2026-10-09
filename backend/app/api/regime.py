"""Regime endpoints (public, read-only, cached for 5 minutes)."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.schemas import Episodes, ErrorBody, History, Label, RegimeToday
from app.core.config import get_settings
from app.services import regime

router = APIRouter(prefix="/v1/regime", tags=["regime"])

ERRORS = {422: {"model": ErrorBody}, 503: {"model": ErrorBody}}


@router.get("/today", response_model=RegimeToday, responses=ERRORS)
def get_today(response: Response, settings=Depends(get_settings)):
    """Today's regime card: label, confidence, days in regime, signals, brief and NIFTY stats."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return regime.today(settings)


@router.get("/history", response_model=History, responses=ERRORS)
def get_history(response: Response, range: Literal["60d", "1y", "5y", "max"] = Query("1y")):  # noqa: A002
    """Daily confirmed label, confidence and NIFTY close for the chart (at most 500 points)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return regime.history(range)


@router.get("/episodes", response_model=Episodes, responses=ERRORS)
def get_episodes(
    response: Response,
    regime_: Label | None = Query(None, alias="regime"),
    limit: int = Query(20, ge=1, le=100),
):
    """Past stretches of the same confirmed regime, most recent first."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return regime.episode_list(regime_, limit)
