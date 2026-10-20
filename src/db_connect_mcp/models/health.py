"""PostgreSQL health diagnostic contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthFinding(BaseModel):
    """One bounded, point-in-time PostgreSQL observation."""

    check: str
    severity: Literal["info", "warning", "critical", "unknown"]
    state: Literal["observed", "unavailable", "insufficient_data"]
    observed_value: int | float | None = None
    threshold: int | float | None = None
    unit: str
    observed_at: datetime
    explanation: str


class HealthReport(BaseModel):
    """A snapshot, not a continuous monitoring assessment."""

    observed_at: datetime
    findings: list[HealthFinding] = Field(default_factory=list)
