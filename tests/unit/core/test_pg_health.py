"""PostgreSQL health evaluation tests."""

from datetime import datetime, timezone

from db_connect_mcp.core.pg_health import evaluate_health


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


def test_evaluate_health_avoids_false_saturation_with_unknown_capacity() -> None:
    findings = evaluate_health({"active_connections": 10, "max_connections": 0})
    by_check = {finding.check: finding for finding in findings}
    assert by_check["connection_utilization"].state == "insufficient_data"
