"""Unit tests for SSH tunnel configuration and URL rewriting."""

import base64
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa
from pydantic import ValidationError

from db_connect_mcp.core.tunnel import (
    KeyFormat,
    SSHTunnelError,
    SSHTunnelManager,
    rewrite_database_url,
)
from db_connect_mcp.models.config import SSHTunnelConfig


# ---------------------------------------------------------------------------
# Helpers: generate keys in various formats for testing
# ---------------------------------------------------------------------------


def _generate_rsa_pem() -> str:
    """Generate a traditional PEM RSA private key."""
    key = paramiko.RSAKey.generate(2048)
    key_io = StringIO()
    key.write_private_key(key_io)
    return key_io.getvalue()


def _generate_rsa_pkcs8() -> bytes:
    """Generate a PKCS#8 PEM RSA private key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _generate_ec_pkcs8() -> bytes:
    """Generate a PKCS#8 PEM EC private key."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _generate_ed25519_pkcs8() -> bytes:
    """Generate a PKCS#8 PEM Ed25519 private key."""
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _generate_encrypted_rsa_pkcs8(passphrase: bytes) -> bytes:
    """Generate an encrypted PKCS#8 PEM RSA private key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase),
    )


def _generate_dsa_pkcs8() -> bytes:
    """Generate a PKCS#8 PEM DSA private key."""
    key = dsa.generate_private_key(key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


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
        assert "[::1]:5433" in result


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
        """Key file should be read and parsed into a PKey object."""
        mock_class, mock_instance = mock_tunnel_forwarder

        # Generate a real key and write it to a temp file
        pem_content = _generate_rsa_pem()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(pem_content)
            key_path = f.name

        try:
            config = SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_username="user",
                ssh_private_key_path=key_path,
            )

            manager = SSHTunnelManager(config)
            manager.start()

            call_kwargs = mock_class.call_args[1]
            # File-based keys are now parsed through our pipeline
            assert isinstance(call_kwargs["ssh_pkey"], paramiko.PKey)
        finally:
            Path(key_path).unlink(missing_ok=True)

    def test_tunnel_start_error_raises_exception(
        self, mock_tunnel_forwarder, valid_config
    ):
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

    def test_ensure_active_restarts_inactive_tunnel(
        self, mock_tunnel_forwarder, valid_config
    ):
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


# ===================================================================
# New tests for key format detection, escape normalization, PKCS#8
# ===================================================================


class TestKeyFormatDetection:
    """Test _detect_key_format identifies each format correctly."""

    def test_detect_pem_rsa(self):
        assert (
            SSHTunnelManager._detect_key_format(
                "-----BEGIN RSA PRIVATE KEY-----\ndata\n-----END RSA PRIVATE KEY-----"
            )
            == KeyFormat.PEM_RSA
        )

    def test_detect_pem_dsa(self):
        assert (
            SSHTunnelManager._detect_key_format(
                "-----BEGIN DSA PRIVATE KEY-----\ndata\n-----END DSA PRIVATE KEY-----"
            )
            == KeyFormat.PEM_DSA
        )

    def test_detect_pem_ec(self):
        assert (
            SSHTunnelManager._detect_key_format(
                "-----BEGIN EC PRIVATE KEY-----\ndata\n-----END EC PRIVATE KEY-----"
            )
            == KeyFormat.PEM_EC
        )

    def test_detect_pem_openssh(self):
        assert (
            SSHTunnelManager._detect_key_format(
                "-----BEGIN OPENSSH PRIVATE KEY-----\ndata\n"
                "-----END OPENSSH PRIVATE KEY-----"
            )
            == KeyFormat.PEM_OPENSSH
        )

    def test_detect_pem_pkcs8(self):
        assert (
            SSHTunnelManager._detect_key_format(
                "-----BEGIN PRIVATE KEY-----\ndata\n-----END PRIVATE KEY-----"
            )
            == KeyFormat.PEM_PKCS8
        )

    def test_detect_pem_pkcs8_encrypted(self):
        assert (
            SSHTunnelManager._detect_key_format(
                "-----BEGIN ENCRYPTED PRIVATE KEY-----\ndata\n"
                "-----END ENCRYPTED PRIVATE KEY-----"
            )
            == KeyFormat.PEM_PKCS8_ENC
        )

    def test_detect_putty_ppk_v2(self):
        assert (
            SSHTunnelManager._detect_key_format(
                "PuTTY-User-Key-File-2: ssh-rsa\nEncryption: none\n"
            )
            == KeyFormat.PUTTY_PPK
        )

    def test_detect_putty_ppk_v3(self):
        assert (
            SSHTunnelManager._detect_key_format(
                "PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\n"
            )
            == KeyFormat.PUTTY_PPK
        )

    def test_detect_base64_encoded(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----"
        b64 = base64.b64encode(pem.encode()).decode()
        assert SSHTunnelManager._detect_key_format(b64) == KeyFormat.BASE64_ENCODED

    def test_detect_unknown(self):
        assert (
            SSHTunnelManager._detect_key_format("random garbage") == KeyFormat.UNKNOWN
        )

    def test_detect_with_leading_whitespace(self):
        """Leading whitespace should be stripped before detection."""
        assert (
            SSHTunnelManager._detect_key_format(
                "  \n  -----BEGIN RSA PRIVATE KEY-----\ndata\n"
                "-----END RSA PRIVATE KEY-----"
            )
            == KeyFormat.PEM_RSA
        )

    def test_detect_pkcs8_not_confused_with_encrypted(self):
        """ENCRYPTED PRIVATE KEY must be checked before PRIVATE KEY."""
        assert (
            SSHTunnelManager._detect_key_format(
                "-----BEGIN ENCRYPTED PRIVATE KEY-----\ndata\n"
                "-----END ENCRYPTED PRIVATE KEY-----"
            )
            == KeyFormat.PEM_PKCS8_ENC
        )


class TestEscapeNormalization:
    """Test _normalize_escape_sequences handles various string encodings."""

    def test_literal_backslash_n(self):
        """Literal two-char \\n should be replaced with real newline."""
        content = (
            "-----BEGIN RSA PRIVATE KEY-----\\nMIIE\\n-----END RSA PRIVATE KEY-----"
        )
        result = SSHTunnelManager._normalize_escape_sequences(content)
        assert "\\n" not in result
        assert "\n" in result
        assert result.startswith("-----BEGIN RSA PRIVATE KEY-----\n")

    def test_literal_backslash_r_n(self):
        """Literal \\r\\n should be replaced with real newline."""
        content = "line1\\r\\nline2"
        result = SSHTunnelManager._normalize_escape_sequences(content)
        assert result == "line1\nline2"

    def test_already_real_newlines(self):
        """Content with real newlines should be unchanged."""
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
        result = SSHTunnelManager._normalize_escape_sequences(content)
        assert result == content

    def test_json_escaped_key_roundtrip(self):
        """Key that was JSON-stringified then loaded should parse correctly."""
        import json

        original = (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----"
        )
        # Simulate what happens when a key is stored as a JSON string value:
        # json.dumps adds \\n, json.loads converts back to \n
        json_str = json.dumps(original)
        loaded = json.loads(json_str)
        result = SSHTunnelManager._normalize_escape_sequences(loaded)
        # json.loads already converts \\n -> \n, so no change expected
        assert result == original

    def test_env_var_escaped_key(self):
        """Simulate key from env var where newlines are literal \\n strings."""
        pem = _generate_rsa_pem()
        # Simulate env var: replace real newlines with literal \n
        escaped = pem.replace("\n", "\\n")
        result = SSHTunnelManager._normalize_escape_sequences(escaped)
        assert result == pem


class TestPEMNormalization:
    """Test _normalize_pem handles various PEM structures."""

    def test_rewraps_single_line_body(self):
        """Single-line PEM body should be re-wrapped at 64 chars."""
        pem = "-----BEGIN RSA PRIVATE KEY-----AAAA-----END RSA PRIVATE KEY-----"
        result = SSHTunnelManager._normalize_pem(pem)
        assert result.startswith("-----BEGIN RSA PRIVATE KEY-----\n")
        assert "AAAA" in result

    def test_preserves_encrypted_pem_metadata(self):
        """RFC 1421 headers (Proc-Type, DEK-Info) must not be stripped."""
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "Proc-Type: 4,ENCRYPTED\n"
            "DEK-Info: AES-256-CBC,AABBCCDD\n"
            "\n"
            "dGVzdGRhdGE=\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = SSHTunnelManager._normalize_pem(pem)
        assert "Proc-Type: 4,ENCRYPTED" in result
        assert "DEK-Info: AES-256-CBC,AABBCCDD" in result

    def test_returns_non_pem_unchanged(self):
        """Content without PEM structure should be returned as-is."""
        content = "not a PEM key at all"
        assert SSHTunnelManager._normalize_pem(content) == content


class TestPKCS8KeyParsing:
    """Test parsing of PKCS#8 format keys."""

    def test_rsa_pkcs8_inline(self):
        """RSA key in PKCS#8 format should parse successfully."""
        pkcs8_pem = _generate_rsa_pkcs8()
        result = SSHTunnelManager._parse_private_key(pkcs8_pem.decode("utf-8"))
        assert isinstance(result, paramiko.RSAKey)

    def test_ec_pkcs8_inline(self):
        """EC key in PKCS#8 format should parse successfully."""
        pkcs8_pem = _generate_ec_pkcs8()
        result = SSHTunnelManager._parse_private_key(pkcs8_pem.decode("utf-8"))
        assert isinstance(result, paramiko.ECDSAKey)

    def test_ed25519_pkcs8_inline(self):
        """Ed25519 key in PKCS#8 format should parse successfully."""
        pkcs8_pem = _generate_ed25519_pkcs8()
        result = SSHTunnelManager._parse_private_key(pkcs8_pem.decode("utf-8"))
        assert isinstance(result, paramiko.Ed25519Key)

    def test_encrypted_pkcs8_with_passphrase(self):
        """Encrypted PKCS#8 key with correct passphrase should parse."""
        enc_pem = _generate_encrypted_rsa_pkcs8(b"testpass")
        result = SSHTunnelManager._parse_private_key(
            enc_pem.decode("utf-8"), passphrase="testpass"
        )
        assert isinstance(result, paramiko.RSAKey)

    def test_encrypted_pkcs8_wrong_passphrase(self):
        """Encrypted PKCS#8 key with wrong passphrase should raise."""
        enc_pem = _generate_encrypted_rsa_pkcs8(b"testpass")
        with pytest.raises(SSHTunnelError, match="PKCS#8"):
            SSHTunnelManager._parse_private_key(
                enc_pem.decode("utf-8"), passphrase="wrongpass"
            )

    def test_encrypted_pkcs8_no_passphrase(self):
        """Encrypted PKCS#8 key without passphrase should raise."""
        enc_pem = _generate_encrypted_rsa_pkcs8(b"testpass")
        with pytest.raises(SSHTunnelError):
            SSHTunnelManager._parse_private_key(enc_pem.decode("utf-8"))

    def test_base64_encoded_pkcs8(self):
        """Base64-wrapped PKCS#8 key should parse after unwrapping."""
        pkcs8_pem = _generate_rsa_pkcs8()
        b64 = base64.b64encode(pkcs8_pem).decode("utf-8")
        result = SSHTunnelManager._parse_private_key(b64)
        assert isinstance(result, paramiko.RSAKey)

    def test_dsa_pkcs8_inline(self):
        """DSA key in PKCS#8 format should parse successfully."""
        pkcs8_pem = _generate_dsa_pkcs8()
        result = SSHTunnelManager._parse_private_key(pkcs8_pem.decode("utf-8"))
        assert isinstance(result, paramiko.DSSKey)  # type: ignore[attr-defined]


class TestPasswordRequiredDetection:
    """Test that encrypted keys without passphrase give actionable errors."""

    def test_encrypted_traditional_pem_no_passphrase(self):
        """Encrypted traditional PEM key without passphrase should mention passphrase."""
        rsa_key = paramiko.RSAKey.generate(2048)
        key_io = StringIO()
        rsa_key.write_private_key(key_io, password="secret123")
        encrypted_pem = key_io.getvalue()

        with pytest.raises(SSHTunnelError, match="passphrase"):
            SSHTunnelManager._parse_private_key(encrypted_pem)


class TestTimeBudget:
    """Test that the time budget mechanism works."""

    def test_budget_exceeded_raises_error(self):
        """Exceeding the time budget should raise SSHTunnelError."""
        from unittest.mock import patch

        # Make every call to time.monotonic return a value past the budget
        with patch("db_connect_mcp.core.tunnel.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 0.0, 999.0]
            with pytest.raises(SSHTunnelError, match="exceeded time budget"):
                # Use garbage PEM body so decoding succeeds but parsing fails
                SSHTunnelManager._parse_private_key(
                    "-----BEGIN RSA PRIVATE KEY-----\n"
                    "garbage\n"
                    "-----END RSA PRIVATE KEY-----"
                )


class TestPuTTYPPKRejection:
    """Test that PuTTY PPK keys are rejected with clear instructions."""

    def test_ppk_v2_rejected_with_message(self):
        """PPK v2 format should be rejected with conversion instructions."""
        ppk_content = (
            "PuTTY-User-Key-File-2: ssh-rsa\nEncryption: none\nComment: test-key\n"
        )
        with pytest.raises(SSHTunnelError, match="PuTTY PPK format") as exc_info:
            SSHTunnelManager._parse_private_key(ppk_content)
        assert "puttygen" in str(exc_info.value)

    def test_ppk_v3_rejected_with_message(self):
        """PPK v3 format should be rejected with conversion instructions."""
        ppk_content = (
            "PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\nComment: test-key\n"
        )
        with pytest.raises(SSHTunnelError, match="PuTTY PPK format") as exc_info:
            SSHTunnelManager._parse_private_key(ppk_content)
        assert "puttygen" in str(exc_info.value)


class TestEscapedKeyParsing:
    """Test end-to-end parsing of keys with escaped newlines."""

    def test_traditional_pem_with_escaped_newlines(self):
        """PEM key with literal \\n should be parsed correctly."""
        pem = _generate_rsa_pem()
        escaped = pem.replace("\n", "\\n")
        result = SSHTunnelManager._parse_private_key(escaped)
        assert isinstance(result, paramiko.RSAKey)

    def test_pkcs8_with_escaped_newlines(self):
        """PKCS#8 key with literal \\n should be parsed correctly."""
        pkcs8 = _generate_rsa_pkcs8().decode("utf-8")
        escaped = pkcs8.replace("\n", "\\n")
        result = SSHTunnelManager._parse_private_key(escaped)
        assert isinstance(result, paramiko.RSAKey)


class TestFileBasedKeyParsing:
    """Test that file-based keys go through the format detection pipeline."""

    @pytest.fixture
    def mock_tunnel_forwarder(self):
        """Mock SSHTunnelForwarder."""
        with patch("db_connect_mcp.core.tunnel.SSHTunnelForwarder") as mock:
            instance = MagicMock()
            instance.local_bind_port = 54321
            instance.is_active = True
            mock.return_value = instance
            yield mock, instance

    def test_file_path_pkcs8_key(self, mock_tunnel_forwarder):
        """PKCS#8 key file should be parsed through the pipeline."""
        mock_class, _ = mock_tunnel_forwarder
        pkcs8_pem = _generate_rsa_pkcs8()

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False) as f:
            f.write(pkcs8_pem)
            key_path = f.name

        try:
            config = SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_username="user",
                ssh_private_key_path=key_path,
                remote_port=5432,
            )

            manager = SSHTunnelManager(config)
            manager.start()

            call_kwargs = mock_class.call_args[1]
            assert isinstance(call_kwargs["ssh_pkey"], paramiko.RSAKey)
        finally:
            Path(key_path).unlink(missing_ok=True)

    def test_file_path_escaped_key(self, mock_tunnel_forwarder):
        """Key file with escaped newlines should be parsed correctly."""
        mock_class, _ = mock_tunnel_forwarder
        pem = _generate_rsa_pem()
        escaped = pem.replace("\n", "\\n")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(escaped)
            key_path = f.name

        try:
            config = SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_username="user",
                ssh_private_key_path=key_path,
                remote_port=5432,
            )

            manager = SSHTunnelManager(config)
            manager.start()

            call_kwargs = mock_class.call_args[1]
            assert isinstance(call_kwargs["ssh_pkey"], paramiko.RSAKey)
        finally:
            Path(key_path).unlink(missing_ok=True)

    def test_file_path_binary_der_raises_error(self):
        """Binary (DER) key file should raise SSHTunnelError with guidance."""
        # Write raw binary bytes that are not valid UTF-8
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".der", delete=False) as f:
            f.write(b"\x30\x82\x01\x22\x30\x0d\x06\x09\xff\xfe\xfd")
            key_path = f.name

        try:
            config = SSHTunnelConfig(
                ssh_host="bastion.example.com",
                ssh_username="user",
                ssh_private_key_path=key_path,
                remote_port=5432,
            )

            manager = SSHTunnelManager(config)
            with pytest.raises(SSHTunnelError, match="non-UTF-8"):
                manager.start()
        finally:
            Path(key_path).unlink(missing_ok=True)
