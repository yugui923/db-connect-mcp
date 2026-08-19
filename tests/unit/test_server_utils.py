"""Unit tests for server utility functions."""

import os
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import CallToolRequestParams, TextContent

from db_connect_mcp.models.capabilities import DatabaseCapabilities
from db_connect_mcp.models.config import DatabaseConfig
from db_connect_mcp.server import (
    DatabaseMCPServer,
    _load_ssh_tunnel_config,
    _parse_bool_env,
    _parse_int_env,
    _structured_tool_result,
)


class TestParseIntEnv:
    """Tests for _parse_int_env helper function."""

    def test_parse_valid_integer(self):
        """Test parsing a valid integer string."""
        result = _parse_int_env("TEST_VAR", "42")
        assert result == 42

    def test_parse_zero(self):
        """Test parsing zero."""
        result = _parse_int_env("TEST_VAR", "0")
        assert result == 0

    def test_parse_negative_integer(self):
        """Test parsing a negative integer."""
        result = _parse_int_env("TEST_VAR", "-10")
        assert result == -10

    def test_none_value_returns_default(self):
        """Test that None value returns default."""
        result = _parse_int_env("TEST_VAR", None, default=100)
        assert result == 100

    def test_none_value_no_default_returns_none(self):
        """Test that None value with no default returns None."""
        result = _parse_int_env("TEST_VAR", None)
        assert result is None

    def test_invalid_value_raises_error(self):
        """Test that invalid value raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            _parse_int_env("TEST_VAR", "not-an-integer")

        assert "TEST_VAR must be an integer" in str(exc_info.value)
        assert "not-an-integer" in str(exc_info.value)

    def test_float_value_raises_error(self):
        """Test that float value raises ValueError."""
        with pytest.raises(ValueError):
            _parse_int_env("FLOAT_VAR", "3.14")

    def test_empty_string_raises_error(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError):
            _parse_int_env("EMPTY_VAR", "")

    def test_whitespace_string_raises_error(self):
        """Test that whitespace-only string raises ValueError."""
        with pytest.raises(ValueError):
            _parse_int_env("SPACE_VAR", "   ")


class TestParseBoolEnv:
    """Tests for strict boolean environment parsing."""

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_parse_true_values(self, value: str) -> None:
        assert _parse_bool_env("TEST_BOOL", value, default=False) is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off"])
    def test_parse_false_values(self, value: str) -> None:
        assert _parse_bool_env("TEST_BOOL", value, default=True) is False

    def test_parse_default(self) -> None:
        assert _parse_bool_env("TEST_BOOL", None, default=True) is True

    def test_invalid_value_names_variable(self) -> None:
        with pytest.raises(ValueError, match="TEST_BOOL"):
            _parse_bool_env("TEST_BOOL", "sometimes", default=False)


class TestMCPToolDispatch:
    """Tests for MCP v2 tool availability and argument validation."""

    @pytest.fixture
    def server_without_optional_capabilities(self) -> DatabaseMCPServer:
        """Create an uninitialized server with every optional tool disabled."""
        server = DatabaseMCPServer(
            DatabaseConfig(url="clickhousedb://default@localhost/default")
        )
        server.adapter = MagicMock()
        server.adapter.capabilities = DatabaseCapabilities(
            foreign_keys=False,
            advanced_stats=False,
            explain_plans=False,
        )
        return server

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name",
        ["get_table_relationships", "analyze_column", "explain_query"],
    )
    async def test_unavailable_tools_cannot_be_called_directly(
        self,
        server_without_optional_capabilities: DatabaseMCPServer,
        tool_name: str,
    ):
        """Capability-gated tools should reject direct calls when unavailable."""
        result = await server_without_optional_capabilities._call_tool(
            MagicMock(),
            CallToolRequestParams(name=tool_name, arguments={}),
        )

        assert result.is_error
        assert "unavailable" in str(result.content)
        assert result.structured_content == {
            "error": {
                "code": "tool_unavailable",
                "message": f"Unknown or unavailable tool: {tool_name}",
            }
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("arguments", "expected_error"),
        [
            ({}, "required property"),
            ({"table": 123}, "not of type"),
        ],
    )
    async def test_arguments_are_validated_before_dispatch(
        self,
        server_without_optional_capabilities: DatabaseMCPServer,
        arguments: dict[str, object],
        expected_error: str,
    ):
        """Invalid tool arguments should return model-visible errors."""
        result = await server_without_optional_capabilities._call_tool(
            MagicMock(),
            CallToolRequestParams(name="describe_table", arguments=arguments),
        )

        assert result.is_error
        assert expected_error in str(result.content)
        assert result.structured_content["error"]["code"] == "invalid_arguments"

    @pytest.mark.asyncio
    async def test_unknown_arguments_are_rejected(
        self,
        server_without_optional_capabilities: DatabaseMCPServer,
    ) -> None:
        """Input contracts should reject undeclared properties."""
        result = await server_without_optional_capabilities._call_tool(
            MagicMock(),
            CallToolRequestParams(
                name="get_database_info", arguments={"unexpected": True}
            ),
        )

        assert result.is_error
        assert result.structured_content["error"]["code"] == "invalid_arguments"


class TestStructuredToolResults:
    """Tests for converting legacy JSON text into structured tool results."""

    def test_object_result_preserves_shape(self) -> None:
        content = [TextContent(type="text", text='{"dialect": "postgresql"}')]

        result, is_error = _structured_tool_result("get_database_info", content)

        assert result == {"dialect": "postgresql"}
        assert is_error is False

    def test_list_result_uses_items_envelope(self) -> None:
        content = [TextContent(type="text", text='[{"name": "public"}]')]

        result, is_error = _structured_tool_result("list_schemas", content)

        assert result == {"items": [{"name": "public"}]}
        assert is_error is False

    def test_truncated_list_moves_metadata_beside_items(self) -> None:
        content = [
            TextContent(
                type="text",
                text=(
                    '{"data": [{"name": "public"}], "_truncation_info": '
                    '{"truncated": true}}'
                ),
            )
        ]

        result, is_error = _structured_tool_result("list_schemas", content)

        assert result == {
            "items": [{"name": "public"}],
            "_truncation_info": {"truncated": True},
        }
        assert is_error is False


class TestLoadSSHTunnelConfig:
    """Tests for _load_ssh_tunnel_config function."""

    def test_no_ssh_host_returns_none(self):
        """Test that missing SSH_HOST returns None."""
        with patch.dict(os.environ, {}, clear=True):
            result = _load_ssh_tunnel_config()
            assert result is None

    def test_empty_ssh_host_returns_none(self):
        """Test that empty SSH_HOST returns None."""
        with patch.dict(os.environ, {"SSH_HOST": ""}, clear=True):
            result = _load_ssh_tunnel_config()
            assert result is None

    def test_missing_username_raises_error(self):
        """Test that SSH_HOST without SSH_USERNAME raises error."""
        env = {"SSH_HOST": "bastion.example.com"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="SSH_USERNAME must be set"):
                _load_ssh_tunnel_config()

    def test_valid_password_auth_config(self):
        """Test valid password authentication configuration."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

            assert result is not None
            assert result.ssh_host == "bastion.example.com"
            assert result.ssh_username == "user"
            assert result.ssh_password == "secret"
            assert result.ssh_port == 22  # default

    def test_custom_ssh_port(self):
        """Test custom SSH port configuration."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PASSWORD": "secret",
            "SSH_PORT": "2222",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

            assert result is not None
            assert result.ssh_port == 2222

    def test_private_key_path_config(self):
        """Test private key path configuration."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PRIVATE_KEY_PATH": "/path/to/key",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

            assert result is not None
            assert result.ssh_private_key_path == "/path/to/key"

    def test_inline_private_key_config(self):
        """Test inline private key configuration."""
        key_content = (
            "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
        )
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PRIVATE_KEY": key_content,
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

            assert result is not None
            assert result.ssh_private_key == key_content

    def test_remote_host_and_port(self):
        """Test remote host and port configuration."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PASSWORD": "secret",
            "SSH_REMOTE_HOST": "db.internal",
            "SSH_REMOTE_PORT": "5432",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

            assert result is not None
            assert result.remote_host == "db.internal"
            assert result.remote_port == 5432

    def test_local_bind_config(self):
        """Test local bind configuration."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PASSWORD": "secret",
            "SSH_LOCAL_HOST": "0.0.0.0",
            "SSH_LOCAL_PORT": "15432",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

            assert result is not None
            assert result.local_host == "0.0.0.0"
            assert result.local_port == 15432

    def test_tunnel_timeout_config(self):
        """Test tunnel timeout configuration."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PASSWORD": "secret",
            "SSH_TUNNEL_TIMEOUT": "30",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

            assert result is not None
            assert result.tunnel_timeout == 30
            assert result.connect_timeout == 30
            assert result.banner_timeout == 30
            assert result.auth_timeout == 30
            assert result.channel_timeout == 30

    def test_specific_tunnel_settings_override_defaults(self) -> None:
        """Stage timeouts and policies should map from their environment names."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PASSWORD": "secret",
            "SSH_TUNNEL_TIMEOUT": "30",
            "SSH_CONNECT_TIMEOUT": "11",
            "SSH_BANNER_TIMEOUT": "12",
            "SSH_AUTH_TIMEOUT": "13",
            "SSH_CHANNEL_TIMEOUT": "14",
            "SSH_KEEPALIVE_INTERVAL": "0",
            "SSH_TARGET_PREFLIGHT": "false",
            "SSH_STRICT_HOST_KEY": "true",
            "SSH_KNOWN_HOSTS_PATH": "/run/secrets/known_hosts",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

        assert result is not None
        assert result.connect_timeout == 11
        assert result.banner_timeout == 12
        assert result.auth_timeout == 13
        assert result.channel_timeout == 14
        assert result.keepalive_interval == 0
        assert result.target_preflight is False
        assert result.strict_host_key is True
        assert result.known_hosts_path == "/run/secrets/known_hosts"

    def test_invalid_boolean_names_environment_variable(self) -> None:
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PASSWORD": "secret",
            "SSH_TARGET_PREFLIGHT": "maybe",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="SSH_TARGET_PREFLIGHT"):
                _load_ssh_tunnel_config()

    def test_passphrase_config(self):
        """Test private key passphrase configuration."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PRIVATE_KEY_PATH": "/path/to/key",
            "SSH_PRIVATE_KEY_PASSPHRASE": "keypass",
        }
        with patch.dict(os.environ, env, clear=True):
            result = _load_ssh_tunnel_config()

            assert result is not None
            assert result.ssh_private_key_passphrase == "keypass"

    def test_invalid_port_raises_error(self):
        """Test that invalid port value raises error."""
        env = {
            "SSH_HOST": "bastion.example.com",
            "SSH_USERNAME": "user",
            "SSH_PASSWORD": "secret",
            "SSH_PORT": "invalid",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="SSH_PORT must be an integer"):
                _load_ssh_tunnel_config()


class TestMCPASGIApp:
    """Tests for _MCPASGIApp class."""

    @pytest.fixture
    def mock_session_manager(self):
        """Create a mock session manager."""
        manager = MagicMock()
        manager.handle_request = MagicMock()
        return manager

    @pytest.mark.asyncio
    async def test_no_auth_passes_through(self, mock_session_manager):
        """Test request without auth token passes through."""
        from db_connect_mcp.server import _MCPASGIApp

        app = _MCPASGIApp(mock_session_manager, auth_token=None)

        scope = {"type": "http", "headers": []}
        receive = MagicMock()
        send = MagicMock()

        # Make handle_request a coroutine
        async def mock_handle(*args):
            pass

        mock_session_manager.handle_request = mock_handle

        await app(scope, receive, send)

    @pytest.mark.asyncio
    async def test_valid_auth_token_passes_through(self, mock_session_manager):
        """Test request with valid auth token passes through."""
        from db_connect_mcp.server import _MCPASGIApp

        app = _MCPASGIApp(mock_session_manager, auth_token="valid-token")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer valid-token")],
        }
        receive = MagicMock()
        send = MagicMock()

        async def mock_handle(*args):
            pass

        mock_session_manager.handle_request = mock_handle

        await app(scope, receive, send)

    @pytest.mark.asyncio
    async def test_invalid_auth_token_returns_401(self, mock_session_manager):
        """Test request with invalid auth token returns 401."""
        from db_connect_mcp.server import _MCPASGIApp

        app = _MCPASGIApp(mock_session_manager, auth_token="valid-token")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer wrong-token")],
        }

        receive = MagicMock()
        sent_responses = []

        async def mock_send(message):
            sent_responses.append(message)

        await app(scope, receive, mock_send)

        # Check that 401 was sent
        assert any(
            msg.get("status") == 401 for msg in sent_responses if "status" in msg
        )

    @pytest.mark.asyncio
    async def test_missing_auth_header_returns_401(self, mock_session_manager):
        """Test request with missing auth header returns 401."""
        from db_connect_mcp.server import _MCPASGIApp

        app = _MCPASGIApp(mock_session_manager, auth_token="valid-token")

        scope = {
            "type": "http",
            "headers": [],
        }

        receive = MagicMock()
        sent_responses = []

        async def mock_send(message):
            sent_responses.append(message)

        await app(scope, receive, mock_send)

        # Check that 401 was sent
        assert any(
            msg.get("status") == 401 for msg in sent_responses if "status" in msg
        )

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self, mock_session_manager):
        """Test non-HTTP scopes pass through without auth check."""
        from db_connect_mcp.server import _MCPASGIApp

        app = _MCPASGIApp(mock_session_manager, auth_token="valid-token")

        scope = {"type": "websocket", "headers": []}
        receive = MagicMock()
        send = MagicMock()

        async def mock_handle(*args):
            pass

        mock_session_manager.handle_request = mock_handle

        await app(scope, receive, send)
