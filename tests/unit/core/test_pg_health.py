"""PostgreSQL health evaluation tests."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from db_connect_mcp.core.pg_health import PostgresHealthChecker, evaluate_health


def test_evaluate_health_reports_threshold_and_insufficient_data() -> None:
    observed = datetime.now(timezone.utc)
    findings = evaluate_health(
        {
            "xid_age": 150_000_000,
            "max_connections": 100,
            "active_connections": 90,
            "invalid_indexes": 2,
            "unvalidated_constraints": 0,
            "slot_retained_bytes": None,
        },
        observed,
    )
    by_check = {finding.check: finding for finding in findings}
    assert by_check["xid_age"].severity == "warning"
    assert by_check["xid_age"].threshold == 100_000_000
    assert by_check["connection_utilization"].observed_value == 90.0
    assert by_check["invalid_indexes"].severity == "warning"
    assert by_check["slot_retained_bytes"].state == "insufficient_data"
    assert all(finding.observed_at == observed for finding in findings)


@pytest.mark.asyncio
async def test_health_propagates_non_permission_database_failure() -> None:
    connection = MagicMock()
    connection.dialect = "postgresql"
    connection.get_connection.return_value.__aenter__ = AsyncMock(
        side_effect=OperationalError("timeout", {}, Exception("timeout"))
    )
    with pytest.raises(OperationalError):
        await PostgresHealthChecker(connection).check()


@pytest.mark.asyncio
async def test_health_classifies_permission_denial_as_unavailable() -> None:
    connection = MagicMock()
    connection.dialect = "postgresql"
    original = Exception("permission denied")
    original.sqlstate = "42501"  # type: ignore[attr-defined]
    denied = ProgrammingError("query", {}, original)
    connection.get_connection.return_value.__aenter__ = AsyncMock(side_effect=denied)
    report = await PostgresHealthChecker(connection).check()
    assert all(finding.state == "unavailable" for finding in report.findings)


def test_evaluate_health_avoids_false_saturation_with_unknown_capacity() -> None:
    findings = evaluate_health({"active_connections": 10, "max_connections": 0})
    by_check = {finding.check: finding for finding in findings}
    assert by_check["connection_utilization"].state == "insufficient_data"
