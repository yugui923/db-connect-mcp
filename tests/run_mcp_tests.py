#!/usr/bin/env python
"""Comprehensive MCP Server Test Runner

Run all MCP server tests against real databases and generate detailed reports.

Usage:
    python tests/run_mcp_tests.py                    # Run all tests
    python tests/run_mcp_tests.py --database pg      # Run PostgreSQL tests only
    python tests/run_mcp_tests.py --report-only      # Generate report from last run
    python tests/run_mcp_tests.py --verbose          # Verbose output
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

load_dotenv()


class MCPTestRunner:
    """Orchestrate MCP server testing."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results_dir = Path("test_reports")
        self.results_dir.mkdir(exist_ok=True)

    def check_environment(self, database: str = "all") -> dict[str, bool]:
        """Check if database URLs are configured."""
        databases = {
            "postgresql": "PG_TEST_DATABASE_URL",
            "mysql": "MYSQL_TEST_DATABASE_URL",
            "clickhouse": "CH_TEST_DATABASE_URL",
        }

        if database != "all":
            databases = {k: v for k, v in databases.items() if k.startswith(database)}

        availability = {}
        for db_name, env_var in databases.items():
            url = os.getenv(env_var)
            availability[db_name] = url is not None
            if self.verbose:
                status = "✅" if url else "❌"
                print(f"{status} {db_name}: {env_var} {'set' if url else 'NOT SET'}")

        return availability

    def run_tests(self, database: str = "all", markers: str = None) -> int:
        """Run pytest with appropriate markers."""
        print("\n" + "=" * 70)
        print("MCP SERVER COMPREHENSIVE TEST SUITE")
        print("=" * 70)

        # Check environment
        print("\n📋 Checking Environment...")
        availability = self.check_environment(database)

        if not any(availability.values()):
            print("\n❌ ERROR: No database URLs configured!")
            print("\nPlease set at least one of these environment variables:")
            print(
                "  - PG_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db"
            )
            print("  - MYSQL_TEST_DATABASE_URL=mysql+aiomysql://user:pass@host:port/db")
            print("  - CH_TEST_DATABASE_URL=clickhouse+asynch://user:pass@host:port/db")
            return 1

        # Build pytest args
        pytest_args = [
            "tests/test_mcp_tools.py",
            "-v",  # Verbose
            "--tb=short",  # Short traceback
            "--color=yes",  # Colored output
        ]

        # Add database-specific markers
        if database != "all":
            pytest_args.extend(["-m", database])
        elif markers:
            pytest_args.extend(["-m", markers])

        # Add extra verbosity
        if self.verbose:
            pytest_args.append("-vv")

        # Generate JSON report
        report_file = (
            self.results_dir
            / f"pytest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        pytest_args.extend(
            [
                "--json-report",
                f"--json-report-file={report_file}",
            ]
        )

        print("\n🧪 Running Tests...")
        print(f"Command: pytest {' '.join(pytest_args)}")
        print()

        # Run pytest
        exit_code = pytest.main(pytest_args)

        print("\n" + "=" * 70)
        if exit_code == 0:
            print("✅ ALL TESTS PASSED")
        else:
            print(f"❌ TESTS FAILED (exit code: {exit_code})")
        print("=" * 70)

        return exit_code

    def generate_comprehensive_report(self):
        """Generate comprehensive test report from pytest results."""
        print("\n📊 Generating Comprehensive Report...")

        # Find latest pytest report
        json_reports = sorted(self.results_dir.glob("pytest_report_*.json"))
        if not json_reports:
            print("❌ No test results found. Run tests first.")
            return

        latest_report = json_reports[-1]
        print(f"Reading: {latest_report}")

        # Parse pytest JSON report
        with open(latest_report) as f:
            pytest_data = json.load(f)

        # Generate markdown report
        report = self._generate_markdown_report(pytest_data)

        # Save report
        report_file = (
            self.results_dir
            / f"mcp_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )
        report_file.write_text(report, encoding="utf-8")

        print(f"✅ Report saved: {report_file}")
        print("\n" + "=" * 70)
        print(report)
        print("=" * 70)

    def _generate_markdown_report(self, pytest_data: dict) -> str:
        """Generate markdown report from pytest data."""
        summary = pytest_data.get("summary", {})

        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        skipped = summary.get("skipped", 0)

        report = f"""# 🔬 MCP Server Comprehensive Test Report

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Duration:** {pytest_data.get("duration", 0):.2f} seconds

## Executive Summary

| Metric | Count | Percentage |
|--------|-------|------------|
| **Total Tests** | {total} | 100% |
| **✅ Passed** | {passed} | {passed / total * 100:.1f}% |
| **❌ Failed** | {failed} | {failed / total * 100:.1f}% |
| **⏭️ Skipped** | {skipped} | {skipped / total * 100:.1f}% |

"""

        # Group tests by MCP tool
        tests_by_tool = {}
        for test in pytest_data.get("tests", []):
            nodeid = test.get("nodeid", "")

            # Extract tool name from test name
            if "test_get_database_info" in nodeid:
                tool = "Tool 1: get_database_info"
            elif "test_list_schemas" in nodeid:
                tool = "Tool 2: list_schemas"
            elif "test_list_tables" in nodeid:
                tool = "Tool 3: list_tables"
            elif "test_describe_table" in nodeid:
                tool = "Tool 4: describe_table"
            elif "test_execute_query" in nodeid:
                tool = "Tool 5: execute_query"
            elif "test_sample_data" in nodeid:
                tool = "Tool 6: sample_data"
            elif "test_get_table_relationships" in nodeid:
                tool = "Tool 7: get_table_relationships"
            elif "test_analyze_column" in nodeid:
                tool = "Tool 8: analyze_column"
            elif "test_explain_query" in nodeid:
                tool = "Tool 9: explain_query"
            elif "test_profile_database" in nodeid:
                tool = "Tool 10: profile_database"
            else:
                tool = "Other Tests"

            if tool not in tests_by_tool:
                tests_by_tool[tool] = []

            tests_by_tool[tool].append(test)

        # Generate tool sections
        report += "\n## 🔧 Results by MCP Tool\n\n"

        for tool_name in sorted(tests_by_tool.keys()):
            tool_tests = tests_by_tool[tool_name]
            tool_passed = sum(1 for t in tool_tests if t.get("outcome") == "passed")
            tool_failed = sum(1 for t in tool_tests if t.get("outcome") == "failed")
            tool_skipped = sum(1 for t in tool_tests if t.get("outcome") == "skipped")
            tool_total = len(tool_tests)

            status = "✅" if tool_failed == 0 and tool_skipped == 0 else "❌"

            report += f"\n### {status} {tool_name}\n\n"
            report += f"**Status:** {tool_passed} passed, {tool_failed} failed, {tool_skipped} skipped out of {tool_total}\n\n"

            for test in tool_tests:
                outcome = test.get("outcome", "unknown")
                test_name = test.get("nodeid", "").split("::")[-1]
                duration = test.get("duration", 0)

                if outcome == "passed":
                    icon = "✅"
                elif outcome == "failed":
                    icon = "❌"
                elif outcome == "skipped":
                    icon = "⏭️"
                else:
                    icon = "❓"

                report += f"- {icon} **{test_name}** ({duration:.2f}s)\n"

                # Add failure details
                if outcome == "failed":
                    call = test.get("call", {})
                    longrepr = call.get("longrepr", "")
                    if longrepr:
                        # Extract just the error message
                        error_lines = longrepr.split("\n")
                        for line in error_lines[-5:]:  # Last 5 lines
                            if line.strip():
                                report += f"  - `{line.strip()}`\n"

                # Add skip reason
                if outcome == "skipped":
                    setup = test.get("setup", {})
                    longrepr = setup.get("longrepr", "")
                    if "Skipped:" in longrepr:
                        reason = longrepr.split("Skipped:")[-1].strip()
                        report += f"  - Reason: {reason}\n"

        # Add recommendations
        report += "\n## 💡 Recommendations\n\n"

        if failed > 0:
            report += "### ⚠️ Failed Tests\n\n"
            report += "The following tests failed. These indicate bugs that need to be fixed:\n\n"

            for tool_name, tool_tests in tests_by_tool.items():
                failed_tests = [t for t in tool_tests if t.get("outcome") == "failed"]
                if failed_tests:
                    report += f"**{tool_name}:**\n"
                    for test in failed_tests:
                        test_name = test.get("nodeid", "").split("::")[-1]
                        report += f"- Fix `{test_name}`\n"
                    report += "\n"

        if skipped > 0:
            report += "### ℹ️ Skipped Tests\n\n"
            report += "These tests were skipped. Configure the missing databases to run them:\n\n"
            report += "- Set `PG_TEST_DATABASE_URL` for PostgreSQL tests\n"
            report += "- Set `MYSQL_TEST_DATABASE_URL` for MySQL tests\n"
            report += "- Set `CH_TEST_DATABASE_URL` for ClickHouse tests\n\n"

        if passed == total:
            report += "### 🎉 Perfect Score!\n\n"
            report += "All tests passed! The MCP server is working correctly.\n\n"

        return report


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run comprehensive MCP server tests")
    parser.add_argument(
        "--database",
        "-d",
        choices=["all", "pg", "postgresql", "mysql", "clickhouse", "ch"],
        default="all",
        help="Database to test (default: all)",
    )
    parser.add_argument(
        "--report-only",
        "-r",
        action="store_true",
        help="Generate report from last test run without running tests",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--markers",
        "-m",
        help="Pytest markers to filter tests (e.g., 'integration')",
    )

    args = parser.parse_args()

    # Normalize database name
    db_map = {"pg": "postgresql", "ch": "clickhouse"}
    database = db_map.get(args.database, args.database)

    runner = MCPTestRunner(verbose=args.verbose)

    if args.report_only:
        runner.generate_comprehensive_report()
        return 0

    # Run tests
    exit_code = runner.run_tests(database=database, markers=args.markers)

    # Generate report
    if exit_code == 0 or True:  # Generate report even on failure
        runner.generate_comprehensive_report()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
