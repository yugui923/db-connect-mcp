"""Unit tests for SSH tunnel configuration and URL rewriting."""

import base64
from unittest.mock import MagicMock, patch

import paramiko
import pytest
from pydantic import ValidationError

from db_connect_mcp.core.tunnel import (
    SSHTunnelError,
    SSHTunnelManager,
    rewrite_database_url,
)
from db_connect_mcp.models.config import SSHTunnelConfig


class TestSSHTunnelConfig:
    """Test SSH tunnel configuration validation."""

    def test_valid_password_auth(self):
        """Password authentication should be valid."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_password="secret",
        )
        assert config.ssh_password == "secret"
        assert config.ssh_private_key_path is None

    def test_valid_key_auth(self):
        """Private key authentication should be valid."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key_path="/path/to/key",
        )
        assert config.ssh_private_key_path == "/path/to/key"

    def test_valid_key_with_passphrase(self):
        """Private key with passphrase should be valid."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key_path="/path/to/key",
            ssh_private_key_passphrase="keypass",
        )
        assert config.ssh_private_key_passphrase == "keypass"

    def test_both_auth_methods_valid(self):
        """Both password and key auth can be specified."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_password="secret",
            ssh_private_key_path="/path/to/key",
        )
        assert config.ssh_password is not None
        assert config.ssh_private_key_path is not None

    def test_valid_inline_key_auth(self):
        """Inline private key authentication should be valid."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        )
        assert config.ssh_private_key is not None
        assert config.ssh_private_key_path is None
        assert config.ssh_password is None

    def test_no_auth_method_invalid(self):
        """Must provide at least one authentication method."""
        with pytest.raises(ValidationError) as exc_info:
            SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_username="user",
            )
        assert "ssh_password" in str(exc_info.value)

    def test_missing_username_invalid(self):
        """Username is required."""
        with pytest.raises(ValidationError):
            SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_password="secret",
            )

    def test_missing_host_invalid(self):
        """Host is required."""
        with pytest.raises(ValidationError):
            SSHTunnelConfig(
                ssh_username="user",
                ssh_password="secret",
            )

    def test_default_values(self):
        """Default values should be set correctly."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_password="secret",
        )
        assert config.ssh_port == 22
        assert config.remote_host is None
        assert config.remote_port is None
        assert config.local_host == "127.0.0.1"
        assert config.local_port is None
        assert config.tunnel_timeout == 10

    def test_custom_remote_port(self):
        """Custom remote port should be accepted."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_password="secret",
            remote_port=3306,  # MySQL port
        )
        assert config.remote_port == 3306

    def test_invalid_port_range(self):
        """Port must be within valid range."""
        with pytest.raises(ValidationError):
            SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_username="user",
                ssh_password="secret",
                ssh_port=70000,  # Invalid port
            )


class TestURLRewriting:
    """Test database URL rewriting for tunnel."""

    def test_postgresql_url_rewrite(self):
        """PostgreSQL URL should be rewritten correctly."""
        original = "postgresql+asyncpg://user:pass@db.remote.com:5432/mydb"
        result = rewrite_database_url(original, "127.0.0.1", 54321)
        assert result == "postgresql+asyncpg://user:pass@127.0.0.1:54321/mydb"

    def test_mysql_url_rewrite(self):
        """MySQL URL should be rewritten correctly."""
        original = "mysql+aiomysql://root:secret@mysql.internal:3306/app"
        result = rewrite_database_url(original, "localhost", 33060)
        assert result == "mysql+aiomysql://root:secret@localhost:33060/app"

    def test_clickhouse_url_rewrite(self):
        """ClickHouse URL should be rewritten correctly."""
        original = "clickhousedb://default:pass@clickhouse.internal:9000/default"
        result = rewrite_database_url(original, "127.0.0.1", 19000)
        assert result == "clickhousedb://default:pass@127.0.0.1:19000/default"

    def test_url_with_query_params(self):
        """URL with query parameters should preserve them."""
        original = "postgresql+asyncpg://user:pass@host:5432/db?sslmode=require"
        result = rewrite_database_url(original, "127.0.0.1", 5433)
        assert "sslmode=require" in result
        assert "127.0.0.1:5433" in result

    def test_url_without_credentials(self):
        """URL without credentials should work."""
        original = "postgresql://localhost:5432/db"
        result = rewrite_database_url(original, "127.0.0.1", 5433)
        assert result == "postgresql://127.0.0.1:5433/db"

    def test_url_with_special_chars_in_password(self):
        """URL with special characters in password should be preserved."""
        original = "postgresql://user:p%40ss%2Fword@host:5432/db"
        result = rewrite_database_url(original, "127.0.0.1", 5433)
        assert "user:p%40ss%2Fword@" in result
        assert "127.0.0.1:5433" in result

    def test_url_with_ipv6_localhost(self):
        """URL rewriting should work with IPv6 localhost."""
        original = "postgresql://user:pass@host:5432/db"
        result = rewrite_database_url(original, "::1", 5433)
        assert "::1:5433" in result


class TestSSHTunnelManagerMocked:
    """Tests with mocked sshtunnel library."""

    @pytest.fixture
    def mock_tunnel_forwarder(self):
        """Mock SSHTunnelForwarder."""
        with patch("db_connect_mcp.core.tunnel.SSHTunnelForwarder") as mock:
            instance = MagicMock()
            instance.local_bind_port = 54321
            instance.is_active = True
            mock.return_value = instance
            yield mock, instance

    @pytest.fixture
    def valid_config(self):
        """Valid SSH tunnel config."""
        return SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_password="secret",
            remote_port=5432,
        )

    def test_tunnel_start_calls_forwarder(self, mock_tunnel_forwarder, valid_config):
        """Starting tunnel should create and start SSHTunnelForwarder."""
        mock_class, mock_instance = mock_tunnel_forwarder

        manager = SSHTunnelManager(valid_config)
        port = manager.start()

        assert port == 54321
        mock_class.assert_called_once()
        mock_instance.start.assert_called_once()

    def test_tunnel_stop_calls_stop(self, mock_tunnel_forwarder, valid_config):
        """Stopping tunnel should call stop on forwarder."""
        mock_class, mock_instance = mock_tunnel_forwarder

        manager = SSHTunnelManager(valid_config)
        manager.start()
        manager.stop()

        mock_instance.stop.assert_called_once()

    def test_tunnel_is_active_property(self, mock_tunnel_forwarder, valid_config):
        """is_active should reflect tunnel state."""
        mock_class, mock_instance = mock_tunnel_forwarder

        manager = SSHTunnelManager(valid_config)
        assert not manager.is_active

        manager.start()
        assert manager.is_active

        mock_instance.is_active = False
        assert not manager.is_active

    def test_tunnel_local_bind_port_property(self, mock_tunnel_forwarder, valid_config):
        """local_bind_port should return correct port."""
        mock_class, mock_instance = mock_tunnel_forwarder

        manager = SSHTunnelManager(valid_config)
        assert manager.local_bind_port is None

        manager.start()
        assert manager.local_bind_port == 54321

    def test_tunnel_context_manager(self, mock_tunnel_forwarder, valid_config):
        """Tunnel should work as context manager."""
        mock_class, mock_instance = mock_tunnel_forwarder

        with SSHTunnelManager(valid_config) as manager:
            assert manager.is_active
            assert manager.local_bind_port == 54321

        mock_instance.stop.assert_called_once()

    def test_tunnel_passes_password_auth(self, mock_tunnel_forwarder, valid_config):
        """Password auth params should be passed to forwarder."""
        mock_class, mock_instance = mock_tunnel_forwarder

        manager = SSHTunnelManager(valid_config)
        manager.start()

        call_kwargs = mock_class.call_args[1]
        assert call_kwargs["ssh_password"] == "secret"

    def test_tunnel_passes_key_auth(self, mock_tunnel_forwarder):
        """Key auth params should be passed to forwarder."""
        mock_class, mock_instance = mock_tunnel_forwarder

        # Mock path exists - need to mock the Path class properly
        with patch("db_connect_mcp.core.tunnel.Path") as mock_path:
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_instance.__str__ = MagicMock(return_value="/path/to/key")
            mock_path.return_value = mock_path_instance

            config = SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_username="user",
                ssh_private_key_path="/path/to/key",
                ssh_private_key_passphrase="keypass",
            )

            manager = SSHTunnelManager(config)
            manager.start()

            call_kwargs = mock_class.call_args[1]
            assert call_kwargs["ssh_pkey"] == "/path/to/key"
            assert call_kwargs["ssh_private_key_password"] == "keypass"

    def test_tunnel_start_error_raises_exception(self, mock_tunnel_forwarder, valid_config):
        """Tunnel start errors should raise SSHTunnelError."""
        mock_class, mock_instance = mock_tunnel_forwarder
        mock_instance.start.side_effect = Exception("Connection refused")

        manager = SSHTunnelManager(valid_config)

        with pytest.raises(SSHTunnelError) as exc_info:
            manager.start()

        assert "Failed to establish SSH tunnel" in str(exc_info.value)

    def test_tunnel_key_not_found_raises_error(self):
        """Non-existent key file should raise SSHTunnelError."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key_path="/nonexistent/path/to/key",
        )

        manager = SSHTunnelManager(config)

        with pytest.raises(SSHTunnelError) as exc_info:
            manager.start()

        assert "private key not found" in str(exc_info.value).lower()

    def test_ensure_active_restarts_inactive_tunnel(self, mock_tunnel_forwarder, valid_config):
        """ensure_active should restart inactive tunnel."""
        mock_class, mock_instance = mock_tunnel_forwarder

        manager = SSHTunnelManager(valid_config)
        manager.start()

        # Simulate tunnel becoming inactive
        mock_instance.is_active = False

        # Should restart
        result = manager.ensure_active()

        assert result is True
        # Should have been started twice (initial + restart)
        assert mock_instance.start.call_count == 2

    def test_tunnel_passes_inline_key_auth(self, mock_tunnel_forwarder):
        """Inline key auth should parse key and pass PKey object to forwarder."""
        mock_class, mock_instance = mock_tunnel_forwarder

        # Generate a real RSA key for testing
        from io import StringIO

        rsa_key = paramiko.RSAKey.generate(2048)
        key_io = StringIO()
        rsa_key.write_private_key(key_io)
        pem_content = key_io.getvalue()

        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key=pem_content,
        )

        manager = SSHTunnelManager(config)
        manager.start()

        call_kwargs = mock_class.call_args[1]
        assert isinstance(call_kwargs["ssh_pkey"], paramiko.PKey)

    def test_inline_key_takes_precedence_over_file_path(self, mock_tunnel_forwarder):
        """Inline key should take precedence over file path when both are set."""
        mock_class, mock_instance = mock_tunnel_forwarder

        from io import StringIO

        rsa_key = paramiko.RSAKey.generate(2048)
        key_io = StringIO()
        rsa_key.write_private_key(key_io)
        pem_content = key_io.getvalue()

        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key=pem_content,
            ssh_private_key_path="/path/to/key",
        )

        manager = SSHTunnelManager(config)
        manager.start()

        call_kwargs = mock_class.call_args[1]
        # Should be a PKey object (from inline), not a string path
        assert isinstance(call_kwargs["ssh_pkey"], paramiko.PKey)

    def test_invalid_inline_key_raises_error(self, mock_tunnel_forwarder):
        """Invalid inline key content should raise SSHTunnelError."""
        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key="not-a-valid-key",
        )

        manager = SSHTunnelManager(config)

        with pytest.raises(SSHTunnelError):
            manager.start()

    def test_base64_encoded_inline_key(self, mock_tunnel_forwarder):
        """Base64-encoded PEM key should be decoded and parsed."""
        mock_class, mock_instance = mock_tunnel_forwarder

        from io import StringIO

        rsa_key = paramiko.RSAKey.generate(2048)
        key_io = StringIO()
        rsa_key.write_private_key(key_io)
        pem_content = key_io.getvalue()

        # Base64-encode the PEM content
        b64_content = base64.b64encode(pem_content.encode("utf-8")).decode("utf-8")

        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key=b64_content,
        )

        manager = SSHTunnelManager(config)
        manager.start()

        call_kwargs = mock_class.call_args[1]
        assert isinstance(call_kwargs["ssh_pkey"], paramiko.PKey)

    def test_invalid_base64_not_pem_raises_error(self, mock_tunnel_forwarder):
        """Base64 content that doesn't decode to PEM should raise SSHTunnelError."""
        b64_content = base64.b64encode(b"this is not a PEM key").decode("utf-8")

        config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_private_key=b64_content,
        )

        manager = SSHTunnelManager(config)

        with pytest.raises(SSHTunnelError) as exc_info:
            manager.start()

        assert "not a valid PEM" in str(exc_info.value)


class TestDatabaseConfigWithSSHTunnel:
    """Test DatabaseConfig with SSH tunnel integration."""

    def test_database_config_with_ssh_tunnel(self):
        """DatabaseConfig should accept ssh_tunnel parameter."""
        from db_connect_mcp.models.config import DatabaseConfig

        ssh_config = SSHTunnelConfig(
            ssh_host="bastion.example.com",
            ssh_username="user",
            ssh_password="secret",
        )

        db_config = DatabaseConfig(
            url="postgresql://user:pass@db.internal:5432/mydb",
            ssh_tunnel=ssh_config,
        )

        assert db_config.ssh_tunnel is not None
        assert db_config.ssh_tunnel.ssh_host == "bastion.example.com"

    def test_database_config_without_ssh_tunnel(self):
        """DatabaseConfig should work without ssh_tunnel."""
        from db_connect_mcp.models.config import DatabaseConfig

        db_config = DatabaseConfig(
            url="postgresql://user:pass@localhost:5432/mydb",
        )

        assert db_config.ssh_tunnel is None
