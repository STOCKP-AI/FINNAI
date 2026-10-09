"""Response and request models: they define the OpenAPI contract the frontend codes against."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Label = Literal["Bull", "Sideways", "Crisis"]
ChipId = Literal["today", "why", "history", "after_crisis", "vix"]


class Probabilities(BaseModel):
    bull: float
    sideways: float
    crisis: float


class Regime(BaseModel):
    label: Label = Field(description="Regime shown to users (changes after 2 consecutive days)")
    raw_label: Label = Field(description="Most likely regime today; may differ during a change")
    confidence: float = Field(description="Model probability of `label` (0-1); overconfident by design")
    probabilities: Probabilities
    days_in_regime: int
    since: date


class Signal(BaseModel):
    feature: str
    name: str
    value: float
    direction: Literal["up", "down"]
    text: str
    contribution: float
    percentile: float | None = None


class Brief(BaseModel):
    text: str
    what_changed: str | None
    source: Literal["llm", "template"]


class NiftyStats(BaseModel):
    as_of: date
    close: float
    change_pct: float | None
    high_52w: float
    low_52w: float
    from_high_pct: float
    ytd_pct: float | None


class ModelInfo(BaseModel):
    version: str
    status: Literal["validated", "experimental", "retired"]


class RegimeToday(BaseModel):
    as_of: date
    is_stale: bool
    regime: Regime
    signals: list[Signal]
    signals_approximate: bool = Field(description="True when the explanation model disagrees today")
    brief: Brief
    nifty: NiftyStats
    model: ModelInfo | None
    disclaimer: str
    warnings: list[str] = []


class HistoryPoint(BaseModel):
    date: date
    label: Label
    confidence: float
    close: float


class History(BaseModel):
    range: Literal["60d", "1y", "5y", "max"]
    as_of: date
    points: list[HistoryPoint]


class Episode(BaseModel):
    regime: Label
    start: date
    end: date
    days: int
    nifty_change_pct: float
    max_drawdown_pct: float
    ongoing: bool


class Episodes(BaseModel):
    regime: Label | None
    as_of: date
    episodes: list[Episode]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID | None = Field(None, description="Omit to start a new conversation")
    message: str = Field(min_length=1, max_length=2000)
    chip_id: ChipId | None = Field(None, description="A suggestion chip; its fixed question is used")


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID = Field(description="The session_id from the chat's done event")
    message_id: int = Field(ge=1, description="The message_id from the chat's done event")
    rating: Literal["up", "down"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorBody(BaseModel):
    error: ErrorDetail


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, str]
