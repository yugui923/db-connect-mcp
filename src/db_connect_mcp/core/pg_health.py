"""Small PostgreSQL health snapshot from bounded catalog/statistics reads."""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from db_connect_mcp.core.connection import DatabaseConnection
from db_connect_mcp.models.health import HealthFinding, HealthReport

# Advisory defaults, not universal operational policy. Values are intentionally explicit.
THRESHOLDS: dict[str, tuple[int | float, int | float, str]] = {
    "xid_age": (100_000_000, 180_000_000, "transactions"),
    "connection_utilization": (80, 95, "percent"),
    "invalid_indexes": (1, 10, "indexes"),
    "unvalidated_constraints": (1, 10, "constraints"),
    "slot_retained_bytes": (1_073_741_824, 10_737_418_240, "bytes"),
}


def evaluate_health(
    values: dict[str, int | float | None], observed_at: datetime | None = None
) -> list[HealthFinding]:
    """Classify observations without interpreting missing metrics as healthy."""
    at = observed_at or datetime.now(timezone.utc)
    maximum = values.get("max_connections")
    connections = values.get("active_connections")
    metrics = dict(values)
    metrics["connection_utilization"] = (
        round(100 * connections / maximum, 2)
        if maximum is not None and maximum > 0 and connections is not None
        else None
    )
    findings = []
    for check, (warning, critical, unit) in THRESHOLDS.items():
        value = metrics.get(check)
        state = "observed" if value is not None else "insufficient_data"
        severity = (
            "unknown"
            if value is None
            else "critical"
            if value >= critical
            else "warning"
            if value >= warning
            else "info"
        )
        findings.append(
            HealthFinding(
                check=check,
                severity=severity,
                state=state,
                observed_value=value,
                threshold=critical if severity == "critical" else warning,
                unit=unit,
                observed_at=at,
                explanation=(
                    "Metric could not be assessed; check access and configuration."
                    if value is None
                    else "Point-in-time observation; threshold is advisory, not a diagnosis."
                ),
            )
        )
    return findings


class PostgresHealthChecker:
    """Collect only aggregate values; never expose slot names or query text."""

    QUERIES = {
        "xid_age": "SELECT max(age(datfrozenxid)) FROM pg_catalog.pg_database WHERE datallowconn",
        "max_connections": "SELECT current_setting('max_connections')::integer",
        "active_connections": (
            "SELECT count(*) FROM pg_catalog.pg_stat_activity "
            "WHERE backend_type = 'client backend'"
        ),
        "invalid_indexes": "SELECT count(*) FROM pg_catalog.pg_index WHERE NOT indisvalid OR NOT indisready",
        "unvalidated_constraints": "SELECT count(*) FROM pg_catalog.pg_constraint WHERE NOT convalidated",
        "slot_retained_bytes": (
            "SELECT max(pg_catalog.pg_wal_lsn_diff(pg_catalog.pg_current_wal_lsn(), "
            "restart_lsn)) FROM pg_catalog.pg_replication_slots WHERE restart_lsn IS NOT NULL"
        ),
    }

    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    async def check(self) -> HealthReport:
        """Return unavailable findings when a catalog read lacks permission."""
        if self.connection.dialect != "postgresql":
            raise ValueError("PostgreSQL health diagnostics require PostgreSQL")
        at = datetime.now(timezone.utc)
        values: dict[str, int | float | None] = {}
        unavailable: set[str] = set()
        for check, query in self.QUERIES.items():
            try:
                async with self.connection.get_connection() as conn:
                    result = await conn.execute(text(query))
                    values[check] = result.scalar_one_or_none()
            except DBAPIError as exc:
                # PostgreSQL insufficient_privilege only; timeouts, failover and
                # connection failures must surface to the caller, not look like ACLs.
                if (
                    getattr(exc.orig, "sqlstate", None) != "42501"
                    and getattr(exc.orig, "pgcode", None) != "42501"
                ):
                    raise
                unavailable.add(check)
        findings = evaluate_health(values, at)
        for finding in findings:
            if finding.check in unavailable or (
                finding.check == "connection_utilization"
                and {"max_connections", "active_connections"} & unavailable
            ):
                finding.state = "unavailable"
                finding.explanation = (
                    "Metric is unavailable under current database permissions."
                )
        return HealthReport(observed_at=at, findings=findings)
