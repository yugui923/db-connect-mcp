"""Integration tests for SSH private key format detection.

Tests various key formats (traditional PEM, PKCS#8, escaped strings,
base64-encoded) against a real SSH bastion host and tunneled PostgreSQL
database.

Requires the devcontainer SSH infrastructure:
- bastion on localhost:2222
- tunneled PostgreSQL accessible through bastion
- Authorized keys installed (done by conftest setup fixture)
"""

import base64
import os
import tempfile
from io import StringIO
from pathlib import Path

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from sqlalchemy import text

from db_connect_mcp.core import DatabaseConnection
from db_connect_mcp.core.tunnel import SSHTunnelManager
from db_connect_mcp.models.config import DatabaseConfig, SSHTunnelConfig

pytestmark = [pytest.mark.ssh_tunnel, pytest.mark.integration]


# ---------------------------------------------------------------------------
# Fixtures: generate keys and install them on the bastion
# ---------------------------------------------------------------------------


def _install_pubkeys_on_bastion(pubkeys: list[str]) -> None:
    """Install public keys on the bastion via password auth."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        os.getenv("SSH_HOST", "localhost"),
        port=int(os.getenv("SSH_PORT", "2222")),
        username=os.getenv("SSH_USERNAME", "tunneluser"),
        password=os.getenv("SSH_PASSWORD"),
    )

    _, stdout, _ = client.exec_command(
        "mkdir -p /home/tunneluser/.ssh && chmod 700 /home/tunneluser/.ssh"
    )
    assert stdout.channel.recv_exit_status() == 0, "Failed to create .ssh directory"

    # Pipe key content via stdin to avoid shell injection from key strings
    all_keys = "\n".join(pubkeys) + "\n"
    stdin, stdout, _ = client.exec_command(
        "cat > /home/tunneluser/.ssh/authorized_keys "
        "&& chmod 600 /home/tunneluser/.ssh/authorized_keys"
    )
    stdin.write(all_keys)
    stdin.channel.shutdown_write()
    assert stdout.channel.recv_exit_status() == 0, "Failed to write authorized_keys"

    client.close()


@pytest.fixture(scope="module")
def ssh_test_keys() -> dict[str, dict[str, str]]:
    """Generate test keys in various formats and install pubkeys on bastion.

    Returns dict mapping format name to {"private": ..., "public": ...}.
    """
    ssh_host = os.getenv("SSH_HOST")
    ssh_username = os.getenv("SSH_USERNAME")
    if not ssh_host or not ssh_username:
        pytest.skip("SSH tunnel env vars not set")

    keys: dict[str, dict[str, str]] = {}
    pubkeys: list[str] = []

    # 1. RSA traditional PEM
    rsa_pkey = paramiko.RSAKey.generate(2048)
    rsa_io = StringIO()
    rsa_pkey.write_private_key(rsa_io)
    rsa_pub = f"{rsa_pkey.get_name()} {rsa_pkey.get_base64()} test-rsa-trad"
    keys["rsa_traditional"] = {"private": rsa_io.getvalue(), "public": rsa_pub}
    pubkeys.append(rsa_pub)

    # 2. RSA PKCS#8
    rsa_crypto = rsa.generate_private_key(65537, 2048)
    rsa_pkcs8_pem = rsa_crypto.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    rsa_pkcs8_pub = (
        rsa_crypto.public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        .decode()
        + " test-rsa-pkcs8"
    )
    keys["rsa_pkcs8"] = {"private": rsa_pkcs8_pem, "public": rsa_pkcs8_pub}
    pubkeys.append(rsa_pkcs8_pub)

    # 3. Ed25519 PKCS#8
    ed_crypto = ed25519.Ed25519PrivateKey.generate()
    ed_pkcs8_pem = ed_crypto.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    ed_pub = (
        ed_crypto.public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        .decode()
        + " test-ed25519-pkcs8"
    )
    keys["ed25519_pkcs8"] = {"private": ed_pkcs8_pem, "public": ed_pub}
    pubkeys.append(ed_pub)

    # 4. EC PKCS#8
    ec_crypto = ec.generate_private_key(ec.SECP256R1())
    ec_pkcs8_pem = ec_crypto.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    ec_pub = (
        ec_crypto.public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        .decode()
        + " test-ec-pkcs8"
    )
    keys["ec_pkcs8"] = {"private": ec_pkcs8_pem, "public": ec_pub}
    pubkeys.append(ec_pub)

    _install_pubkeys_on_bastion(pubkeys)
    return keys


def _make_tunnel_config(
    private_key: str | None = None,
    private_key_path: str | None = None,
) -> SSHTunnelConfig:
    """Build an SSHTunnelConfig that uses key auth against the bastion."""
    return SSHTunnelConfig(
        ssh_host=os.getenv("SSH_HOST", "localhost"),
        ssh_port=int(os.getenv("SSH_PORT", "2222")),
        ssh_username=os.getenv("SSH_USERNAME", "tunneluser"),
        ssh_private_key=private_key,
        ssh_private_key_path=private_key_path,
        remote_host="postgres-tunneled",
        remote_port=5432,
    )


# =====================================================================
# Tests: tunnel establishment with various key formats
# =====================================================================


class TestKeyFormatTunnelEstablishment:
    """Test that tunnels can be established using each key format."""

    def test_rsa_traditional_pem(self, ssh_test_keys: dict):
        """RSA traditional PEM key should establish a tunnel."""
        key = ssh_test_keys["rsa_traditional"]["private"]
        config = _make_tunnel_config(private_key=key)

        with SSHTunnelManager(config) as manager:
            assert manager.is_active
            assert manager.local_bind_port is not None
            assert manager.local_bind_port > 0

    def test_rsa_pkcs8(self, ssh_test_keys: dict):
        """RSA PKCS#8 key should establish a tunnel."""
        key = ssh_test_keys["rsa_pkcs8"]["private"]
        config = _make_tunnel_config(private_key=key)

        with SSHTunnelManager(config) as manager:
            assert manager.is_active

    def test_ed25519_pkcs8(self, ssh_test_keys: dict):
        """Ed25519 PKCS#8 key should establish a tunnel."""
        key = ssh_test_keys["ed25519_pkcs8"]["private"]
        config = _make_tunnel_config(private_key=key)

        with SSHTunnelManager(config) as manager:
            assert manager.is_active

    def test_ec_pkcs8(self, ssh_test_keys: dict):
        """EC PKCS#8 key should establish a tunnel."""
        key = ssh_test_keys["ec_pkcs8"]["private"]
        config = _make_tunnel_config(private_key=key)

        with SSHTunnelManager(config) as manager:
            assert manager.is_active

    def test_base64_encoded_pkcs8(self, ssh_test_keys: dict):
        """Base64-encoded PKCS#8 key should establish a tunnel."""
        key = ssh_test_keys["rsa_pkcs8"]["private"]
        b64_key = base64.b64encode(key.encode()).decode()
        config = _make_tunnel_config(private_key=b64_key)

        with SSHTunnelManager(config) as manager:
            assert manager.is_active

    def test_escaped_newlines_traditional_pem(self, ssh_test_keys: dict):
        """Traditional PEM key with escaped newlines should work."""
        key = ssh_test_keys["rsa_traditional"]["private"]
        escaped = key.replace("\n", "\\n")
        config = _make_tunnel_config(private_key=escaped)

        with SSHTunnelManager(config) as manager:
            assert manager.is_active

    def test_escaped_newlines_pkcs8(self, ssh_test_keys: dict):
        """PKCS#8 key with escaped newlines should work."""
        key = ssh_test_keys["rsa_pkcs8"]["private"]
        escaped = key.replace("\n", "\\n")
        config = _make_tunnel_config(private_key=escaped)

        with SSHTunnelManager(config) as manager:
            assert manager.is_active

    def test_key_file_path_traditional(self, ssh_test_keys: dict):
        """Key provided via file path should establish a tunnel."""
        key = ssh_test_keys["rsa_traditional"]["private"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(key)
            key_path = f.name

        try:
            config = _make_tunnel_config(private_key_path=key_path)
            with SSHTunnelManager(config) as manager:
                assert manager.is_active
        finally:
            Path(key_path).unlink(missing_ok=True)

    def test_key_file_path_pkcs8(self, ssh_test_keys: dict):
        """PKCS#8 key provided via file path should establish a tunnel."""
        key = ssh_test_keys["rsa_pkcs8"]["private"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(key)
            key_path = f.name

        try:
            config = _make_tunnel_config(private_key_path=key_path)
            with SSHTunnelManager(config) as manager:
                assert manager.is_active
        finally:
            Path(key_path).unlink(missing_ok=True)


# =====================================================================
# Tests: full database access through tunnel with different key formats
# =====================================================================


class TestKeyFormatDatabaseAccess:
    """Test actual database queries through tunnels with various key formats."""

    @pytest.mark.asyncio
    async def test_pg_query_with_pkcs8_key(self, ssh_test_keys: dict):
        """Execute a PostgreSQL query through tunnel using PKCS#8 key."""
        pg_url = os.getenv("PG_TUNNEL_DATABASE_URL")
        if not pg_url:
            pytest.skip("PG_TUNNEL_DATABASE_URL not set")

        key = ssh_test_keys["rsa_pkcs8"]["private"]
        tunnel_config = SSHTunnelConfig(
            ssh_host=os.getenv("SSH_HOST", "localhost"),
            ssh_port=int(os.getenv("SSH_PORT", "2222")),
            ssh_username=os.getenv("SSH_USERNAME", "tunneluser"),
            ssh_private_key=key,
            remote_host="postgres-tunneled",
            remote_port=5432,
        )

        db_config = DatabaseConfig(url=pg_url, ssh_tunnel=tunnel_config)
        connection = DatabaseConnection(db_config)

        try:
            await connection.initialize()
            assert connection.is_tunneled

            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            await connection.dispose()

    @pytest.mark.asyncio
    async def test_pg_query_with_escaped_pkcs8_key(self, ssh_test_keys: dict):
        """Execute a PostgreSQL query using PKCS#8 key with escaped newlines."""
        pg_url = os.getenv("PG_TUNNEL_DATABASE_URL")
        if not pg_url:
            pytest.skip("PG_TUNNEL_DATABASE_URL not set")

        key = ssh_test_keys["ed25519_pkcs8"]["private"]
        escaped = key.replace("\n", "\\n")
        tunnel_config = SSHTunnelConfig(
            ssh_host=os.getenv("SSH_HOST", "localhost"),
            ssh_port=int(os.getenv("SSH_PORT", "2222")),
            ssh_username=os.getenv("SSH_USERNAME", "tunneluser"),
            ssh_private_key=escaped,
            remote_host="postgres-tunneled",
            remote_port=5432,
        )

        db_config = DatabaseConfig(url=pg_url, ssh_tunnel=tunnel_config)
        connection = DatabaseConnection(db_config)

        try:
            await connection.initialize()
            assert connection.is_tunneled

            async with connection.get_connection() as conn:
                result = await conn.execute(text("SELECT COUNT(*) FROM products"))
                count = result.scalar()
                assert count is not None and count > 0
        finally:
            await connection.dispose()
