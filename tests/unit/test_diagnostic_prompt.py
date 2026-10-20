"""Agent-facing diagnostic prompt contract."""

import pytest
from mcp.types import GetPromptRequestParams

from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import DatabaseMCPServer


@pytest.mark.asyncio
async def test_diagnostic_prompt_is_discoverable_and_read_only() -> None:
    server = DatabaseMCPServer(
        DatabaseConfig(url="postgresql+asyncpg://user:pass@localhost/db")
    )

    listing = await server._list_prompts(None, None)
    assert [prompt.name for prompt in listing.prompts] == ["diagnose_query"]
    assert listing.prompts[0].arguments is not None
    assert listing.prompts[0].arguments[0].name == "problem"
    assert listing.prompts[0].arguments[0].required
    argument_description = listing.prompts[0].arguments[0].description
    assert argument_description is not None
    assert "Before entering" in argument_description
    assert "host" in argument_description and "model" in argument_description
    assert "redact" in argument_description.lower()
    assert "SQL" in argument_description and "table" in argument_description
    assert "incident" in argument_description

    result = await server._get_prompt(
        None,
        GetPromptRequestParams(
            name="diagnose_query", arguments={"problem": "slow report"}
        ),
    )
    assert len(result.messages) == 1
    message = result.messages[0]
    assert message.role == "user"
    assert message.content.type == "text"
    text = message.content.text
    assert "slow report" in text
    assert text.index("may receive this problem") < text.index("slow report")
    assert "redact" in text[: text.index("slow report")]
    for step in (
        "search_objects",
        "get_database_info",
        "describe_table",
        "explain_query",
    ):
        assert step in text
    assert "PostgreSQL" in text and "MySQL" in text and "ClickHouse" in text
    assert "EXPLAIN ANALYZE" in text
    assert "do not" in text.lower()
    assert "tools/list" not in text
    assert "tools your MCP host exposes" in text
    assert "refresh tool discovery" in text
    assert "server does not make external model calls" in text
    assert "host or model provider may receive tool results" in text
    assert "verify your host's data egress" in text


@pytest.mark.asyncio
async def test_diagnostic_prompt_rejects_unknown_name_and_missing_problem() -> None:
    server = DatabaseMCPServer(
        DatabaseConfig(url="mysql+aiomysql://user:pass@localhost/db")
    )
    with pytest.raises(ValueError, match="Unknown prompt"):
        await server._get_prompt(None, GetPromptRequestParams(name="other"))
    with pytest.raises(ValueError, match="problem"):
        await server._get_prompt(None, GetPromptRequestParams(name="diagnose_query"))
