"""Unit tests for server utility functions."""

import os
from unittest.mock import MagicMock, patch

import pytest

from db_connect_mcp.server import _load_ssh_tunnel_config, _parse_int_env


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
