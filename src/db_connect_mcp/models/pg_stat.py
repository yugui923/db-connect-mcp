"""Bounded PostgreSQL statement statistics output models."""

from typing import Literal

from pydantic import BaseModel


class TopQuery(BaseModel):
    """Aggregated metrics for a normalized statement."""

    query_id: int | None
    calls: int
    total_exec_time_ms: float
    mean_exec_time_ms: float
    rows: int
    query: str | None


class TopQueriesReport(BaseModel):
    """Availability and top statements for the current database."""

    status: Literal[
        "available",
        "extension_not_installed",
        "extension_not_loaded",
        "permission_denied",
        "unsupported_version",
    ]
    queries: list[TopQuery]
