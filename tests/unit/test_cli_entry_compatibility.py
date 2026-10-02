"""Exercise the real CLI parser without starting a database server."""

import sys
from unittest.mock import patch

import pytest

from db_connect_mcp.server import cli_entry


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], ("stdio", "0.0.0.0", 8000)),
        (
            ["--transport", "streamable-http", "--port", "9000"],
            ("streamable-http", "0.0.0.0", 9000),
        ),
    ],
)
def test_cli_preserves_transport_defaults_and_flags(
    args: list[str], expected: tuple[str, str, int]
) -> None:
    async def capture_main(**kwargs: object) -> None:
        assert (kwargs["transport"], kwargs["host"], kwargs["port"]) == expected

    with (
        patch.object(sys, "argv", ["db-connect-mcp", *args]),
        patch("db_connect_mcp.server.main", new=capture_main),
    ):
        cli_entry()
