"""Protocol-level evaluations for common database-agent trajectories."""

import pytest

from db_connect_mcp.models.config import DatabaseConfig

from .agent_eval_cases import AGENT_EVAL_CASES, AgentEvalCase, evaluate_agent_case
from .test_mcp_protocol import MCPProtocolHelper

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.integration,
    pytest.mark.xdist_group(name="agent_evals"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", AGENT_EVAL_CASES, ids=lambda case: case.name)
async def test_agent_workflow_eval(
    pg_config: DatabaseConfig, case: AgentEvalCase
) -> None:
    """Require a perfect score for each bounded agent workflow."""
    server, client = await MCPProtocolHelper.create_test_server_and_client(
        pg_config, use_discovery=True
    )

    try:
        result = await evaluate_agent_case(client, case)

        assert result.score == 1.0, "; ".join(result.failures)
        assert result.tool_calls <= case.max_tool_calls
    finally:
        await server.cleanup()
