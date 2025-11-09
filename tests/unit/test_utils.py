"""Test utilities and helpers for MCP server testing."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pytest


class ReportGenerator:
    """Generate comprehensive test reports.

    Note: This class is not a pytest test class despite the utility name.
    It's a helper for generating test reports and documentation.
    """

    def __init__(self, output_dir: str = "test_reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.results = []

    def add_result(
        self,
        tool_name: str,
        test_name: str,
        passed: bool,
        error: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        """Add a test result."""
        self.results.append(
            {
                "tool": tool_name,
                "test": test_name,
                "passed": passed,
                "error": error,
                "details": details or {},
                "timestamp": datetime.now().isoformat(),
            }
        )

    def generate_report(self, database_type: str) -> str:
        """Generate markdown report."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed

        report = f"""# MCP Server Test Report - {database_type}

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Summary

- **Total Tests:** {total}
- **Passed:** {passed} ({passed / total * 100:.1f}%)
- **Failed:** {failed} ({failed / total * 100:.1f}%)

## Results by Tool

"""

        # Group by tool
        tools = {}
        for result in self.results:
            tool = result["tool"]
            if tool not in tools:
                tools[tool] = []
            tools[tool].append(result)

        # Generate tool sections
        for tool_name, tool_results in sorted(tools.items()):
            tool_passed = sum(1 for r in tool_results if r["passed"])
            tool_total = len(tool_results)
            status = "✅" if tool_passed == tool_total else "❌"

            report += f"\n### {status} {tool_name} ({tool_passed}/{tool_total})\n\n"

            for result in tool_results:
                status_icon = "✅" if result["passed"] else "❌"
                report += f"- {status_icon} **{result['test']}**"

                if not result["passed"] and result["error"]:
                    report += f"\n  - Error: `{result['error']}`"

                if result["details"]:
                    report += (
                        f"\n  - Details: {json.dumps(result['details'], indent=2)}"
                    )

                report += "\n"

        report += "\n## Detailed Results\n\n"
        report += "```json\n"
        report += json.dumps(self.results, indent=2)
        report += "\n```\n"

        return report

    def save_report(self, database_type: str) -> Path:
        """Save report to file."""
        filename = (
            f"test_report_{database_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )
        filepath = self.output_dir / filename

        report = self.generate_report(database_type)
        filepath.write_text(report, encoding="utf-8")

        return filepath


class DataTypeTestHelper:
    """Helper for testing various data types."""

    # PostgreSQL data types to test
    PG_DATA_TYPES = {
        "numeric": ["INTEGER", "BIGINT", "NUMERIC", "REAL", "DOUBLE PRECISION"],
        "text": ["TEXT", "VARCHAR(100)", "CHAR(10)"],
        "temporal": ["TIMESTAMP", "DATE", "TIME", "INTERVAL"],
        "network": ["INET", "CIDR", "MACADDR"],
        "special": ["UUID", "JSON", "JSONB", "BYTEA", "BOOLEAN"],
        "geometric": ["POINT", "LINE", "POLYGON"],
        "arrays": ["INTEGER[]", "TEXT[]"],
    }

    @staticmethod
    def get_sample_value(data_type: str) -> str:
        """Get sample SQL value for data type."""
        samples = {
            "INTEGER": "42",
            "BIGINT": "9223372036854775807",
            "NUMERIC": "123.456",
            "REAL": "3.14",
            "DOUBLE PRECISION": "2.718281828",
            "TEXT": "'sample text'",
            "VARCHAR(100)": "'varchar text'",
            "CHAR(10)": "'char text'",
            "TIMESTAMP": "TIMESTAMP '2024-01-15 10:30:00'",
            "DATE": "DATE '2024-01-15'",
            "TIME": "TIME '10:30:00'",
            "INTERVAL": "INTERVAL '1 day'",
            "INET": "'192.168.1.1'::inet",
            "CIDR": "'192.168.1.0/24'::cidr",
            "MACADDR": "'08:00:2b:01:02:03'::macaddr",
            "UUID": "gen_random_uuid()",
            "JSON": '\'{"key": "value"}\'::json',
            "JSONB": '\'{"key": "value"}\'::jsonb',
            "BYTEA": "'\\\\x48656c6c6f'::bytea",
            "BOOLEAN": "true",
            "POINT": "POINT(1, 2)",
            "LINE": "LINE(1, 2, 3)",
            "POLYGON": "POLYGON '((0,0),(1,0),(1,1),(0,1))'",
            "INTEGER[]": "ARRAY[1, 2, 3]",
            "TEXT[]": "ARRAY['a', 'b', 'c']",
        }
        return samples.get(data_type, "NULL")

    @classmethod
    def generate_type_test_query(cls, data_types: list[str]) -> str:
        """Generate SELECT query testing multiple data types."""
        select_parts = []
        for i, dtype in enumerate(data_types):
            value = cls.get_sample_value(dtype)
            select_parts.append(f"{value} as col_{i}")

        return f"SELECT {', '.join(select_parts)}"


def validate_json_serialization(data: Any) -> tuple[bool, Optional[str]]:
    """Validate that data is JSON-serializable."""
    try:
        json.dumps(data)
        return True, None
    except (TypeError, ValueError) as e:
        return False, str(e)


def assert_json_safe(data: Any, context: str = ""):
    """Assert that data is JSON-serializable."""
    is_safe, error = validate_json_serialization(data)
    if not is_safe:
        pytest.fail(f"{context} - Data not JSON-safe: {error}")


def compare_with_baseline(
    current_result: dict[str, Any],
    baseline_file: Path,
) -> tuple[bool, list[str]]:
    """Compare current test results with baseline."""
    if not baseline_file.exists():
        return True, ["No baseline found - creating new baseline"]

    baseline = json.loads(baseline_file.read_text())
    differences = []

    # Compare keys
    if set(current_result.keys()) != set(baseline.keys()):
        differences.append("Different keys in result")

    # Compare values
    for key in current_result.keys():
        if key not in baseline:
            differences.append(f"New key: {key}")
        elif current_result[key] != baseline[key]:
            differences.append(f"Different value for {key}")

    return len(differences) == 0, differences


class PerformanceBenchmark:
    """Track performance metrics for MCP tools."""

    def __init__(self):
        self.metrics = {}

    def record(self, tool_name: str, operation: str, duration_ms: float):
        """Record performance metric."""
        if tool_name not in self.metrics:
            self.metrics[tool_name] = {}

        if operation not in self.metrics[tool_name]:
            self.metrics[tool_name][operation] = []

        self.metrics[tool_name][operation].append(duration_ms)

    def get_stats(self, tool_name: str, operation: str) -> dict[str, float]:
        """Get statistics for a tool/operation."""
        if tool_name not in self.metrics or operation not in self.metrics[tool_name]:
            return {}

        durations = self.metrics[tool_name][operation]
        return {
            "count": len(durations),
            "min": min(durations),
            "max": max(durations),
            "avg": sum(durations) / len(durations),
            "total": sum(durations),
        }

    def generate_report(self) -> str:
        """Generate performance report."""
        report = "# Performance Benchmark Report\n\n"

        for tool_name in sorted(self.metrics.keys()):
            report += f"\n## {tool_name}\n\n"

            for operation in sorted(self.metrics[tool_name].keys()):
                stats = self.get_stats(tool_name, operation)
                report += f"### {operation}\n\n"
                report += f"- Count: {stats['count']}\n"
                report += f"- Min: {stats['min']:.2f}ms\n"
                report += f"- Max: {stats['max']:.2f}ms\n"
                report += f"- Avg: {stats['avg']:.2f}ms\n"
                report += f"- Total: {stats['total']:.2f}ms\n\n"

        return report
