"""Deterministic agent-workflow evaluation cases and scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp import ClientSession


@dataclass(frozen=True)
class ToolEvalStep:
    """One expected MCP tool call in an agent trajectory."""

    tool: str
    arguments: dict[str, Any]
    required_paths: tuple[str, ...] = ()
    expect_error: bool = False


@dataclass(frozen=True)
class AgentEvalCase:
    """A prompt-shaped, bounded agent trajectory with contract assertions."""

    name: str
    prompt: str
    max_tool_calls: int
    steps: tuple[ToolEvalStep, ...]


@dataclass(frozen=True)
class AgentEvalResult:
    """Scored outcome for one deterministic agent evaluation."""

    case_name: str
    earned_points: int
    total_points: int
    tool_calls: int
    failures: tuple[str, ...]

    @property
    def score(self) -> float:
        """Return the normalized score from zero to one."""
        return self.earned_points / self.total_points if self.total_points else 1.0


AGENT_EVAL_CASES = (
    AgentEvalCase(
        name="discover_product_schema",
        prompt="Find product-related tables and inspect the products table schema.",
        max_tool_calls=2,
        steps=(
            ToolEvalStep(
                tool="search_objects",
                arguments={
                    "pattern": "%product%",
                    "object_types": ["table"],
                    "detail_level": "summary",
                },
                required_paths=("results", "returned", "total_found"),
            ),
            ToolEvalStep(
                tool="describe_table",
                arguments={"schema": "public", "table": "products"},
                required_paths=("name", "columns", "indexes", "constraints"),
            ),
        ),
    ),
    AgentEvalCase(
        name="answer_bounded_aggregate",
        prompt="Count the products without returning the product rows.",
        max_tool_calls=1,
        steps=(
            ToolEvalStep(
                tool="execute_query",
                arguments={
                    "query": "SELECT COUNT(*) AS product_count FROM products",
                    "limit": 1,
                },
                required_paths=("rows", "row_count", "columns"),
            ),
        ),
    ),
    AgentEvalCase(
        name="reject_write_and_recover",
        prompt="Reject an unsafe write, then prove the connection remains usable.",
        max_tool_calls=2,
        steps=(
            ToolEvalStep(
                tool="execute_query",
                arguments={"query": "DELETE FROM products", "limit": 1},
                required_paths=("error.code", "error.message"),
                expect_error=True,
            ),
            ToolEvalStep(
                tool="execute_query",
                arguments={"query": "SELECT 1 AS healthy", "limit": 1},
                required_paths=("rows", "row_count"),
            ),
        ),
    ),
    AgentEvalCase(
        name="inspect_query_plan",
        prompt="Inspect a products lookup plan without executing the query.",
        max_tool_calls=1,
        steps=(
            ToolEvalStep(
                tool="explain_query",
                arguments={
                    "query": "SELECT * FROM products WHERE product_id = 1",
                    "analyze": False,
                },
                required_paths=("query", "plan", "warnings", "recommendations"),
            ),
        ),
    ),
)


def _has_path(payload: Any, path: str) -> bool:
    current = payload
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False
        current = current[segment]
    return True


async def evaluate_agent_case(
    client: ClientSession, case: AgentEvalCase
) -> AgentEvalResult:
    """Execute and score a deterministic MCP agent trajectory."""
    failures: list[str] = []
    earned_points = 0
    total_points = 0

    available_tools = {tool.name for tool in (await client.list_tools()).tools}
    for step in case.steps:
        total_points += 1
        if step.tool in available_tools:
            earned_points += 1
        else:
            failures.append(f"tool unavailable: {step.tool}")
            continue

        response = await client.call_tool(step.tool, arguments=step.arguments)
        total_points += 1
        if response.is_error is step.expect_error:
            earned_points += 1
        else:
            failures.append(
                f"{step.tool}: expected is_error={step.expect_error}, "
                f"got {response.is_error}"
            )

        payload = response.structured_content
        total_points += 1
        if isinstance(payload, dict):
            earned_points += 1
        else:
            failures.append(f"{step.tool}: missing structured content")

        for path in step.required_paths:
            total_points += 1
            if _has_path(payload, path):
                earned_points += 1
            else:
                failures.append(f"{step.tool}: missing structured path {path}")

    tool_calls = len(case.steps)
    total_points += 1
    if tool_calls <= case.max_tool_calls:
        earned_points += 1
    else:
        failures.append(f"tool budget exceeded: {tool_calls} > {case.max_tool_calls}")

    return AgentEvalResult(
        case_name=case.name,
        earned_points=earned_points,
        total_points=total_points,
        tool_calls=tool_calls,
        failures=tuple(failures),
    )
