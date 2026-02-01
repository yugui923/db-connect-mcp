"""SSH tunnel management for secure database connections."""

import base64
import logging
from io import StringIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

import paramiko
from sshtunnel import SSHTunnelForwarder

from db_connect_mcp.models.config import SSHTunnelConfig

logger = logging.getLogger(__name__)


class SSHTunnelError(Exception):
    """SSH tunnel-related errors."""

    pass


class SSHTunnelManager:
    """Manages SSH tunnel lifecycle for database connections."""

    def __init__(self, config: SSHTunnelConfig):
        """
        Initialize tunnel manager with configuration.

        Args:
            config: SSH tunnel configuration
        """
        self.config = config
        self._tunnel: Optional[SSHTunnelForwarder] = None
        self._local_bind_port: Optional[int] = None

    def start(self) -> int:
        """
        Start the SSH tunnel.

        Returns:
            Local port number where tunnel is listening

        Raises:
            SSHTunnelError: If tunnel fails to start
        """
        if self._tunnel is not None and self._tunnel.is_active:
            if self._local_bind_port is None:
                raise SSHTunnelError("Tunnel is active but local bind port is unknown")
            return self._local_bind_port

        try:
            # Build authentication parameters
            auth_params = self._build_auth_params()

            remote_host = self.config.remote_host or "127.0.0.1"
            remote_port = self.config.remote_port or 5432

            # Create tunnel
            tunnel = SSHTunnelForwarder(
                ssh_address_or_host=(self.config.ssh_host, self.config.ssh_port),
                ssh_username=self.config.ssh_username,
                remote_bind_address=(remote_host, remote_port),
                local_bind_address=(
                    self.config.local_host,
                    self.config.local_port or 0,  # 0 = auto-assign
                ),
                set_keepalive=30,  # Send keepalive every 30 seconds
                **auth_params,
            )

            # Start tunnel
            tunnel.start()
            self._tunnel = tunnel

            # Get actual local port (may be auto-assigned)
            self._local_bind_port = tunnel.local_bind_port

            logger.info(
                f"SSH tunnel established: {self.config.local_host}:{self._local_bind_port} -> "
                f"{self.config.ssh_host}:{self.config.ssh_port} -> "
                f"{self.config.remote_host}:{self.config.remote_port}"
            )

            if self._local_bind_port is None:
                raise SSHTunnelError("Tunnel started but local bind port is not set")

            return self._local_bind_port

        except SSHTunnelError:
            self._cleanup()
            raise
        except Exception as e:
            self._cleanup()
            raise SSHTunnelError(f"Failed to establish SSH tunnel: {e}") from e

    def stop(self) -> None:
        """Stop the SSH tunnel."""
        self._cleanup()

    def _cleanup(self) -> None:
        """Clean up tunnel resources."""
        if self._tunnel is not None:
            try:
                self._tunnel.stop()
                logger.info("SSH tunnel stopped")
            except Exception as e:
                logger.warning(f"Error stopping SSH tunnel: {e}")
            finally:
                self._tunnel = None
                self._local_bind_port = None

    def _build_auth_params(self) -> dict:
        """
        Build authentication parameters for SSHTunnelForwarder.

        Returns:
            Dictionary of authentication parameters

        Raises:
            SSHTunnelError: If private key file not found
        """
        params = {}

        if self.config.ssh_password:
            params["ssh_password"] = self.config.ssh_password

        if self.config.ssh_private_key:
            # Inline key takes precedence over file path
            passphrase = self.config.ssh_private_key_passphrase
            pkey = self._parse_private_key(self.config.ssh_private_key, passphrase)
            params["ssh_pkey"] = pkey
            if passphrase:
                params["ssh_private_key_password"] = passphrase
        elif self.config.ssh_private_key_path:
            key_path = Path(self.config.ssh_private_key_path)
            if not key_path.exists():
                raise SSHTunnelError(
                    f"SSH private key not found: {self.config.ssh_private_key_path}"
                )
            params["ssh_pkey"] = str(key_path)

            if self.config.ssh_private_key_passphrase:
                params["ssh_private_key_password"] = (
                    self.config.ssh_private_key_passphrase
                )

        return params

    @staticmethod
    def _decode_key_content(key_content: str) -> str:
        """
        Decode key content, handling both raw PEM and base64-encoded PEM.

        If the content starts with '-----BEGIN', it is treated as raw PEM.
        Otherwise, it is base64-decoded first.

        Raises:
            SSHTunnelError: If base64 decoding fails
        """
        stripped = key_content.strip()
        if stripped.startswith("-----BEGIN"):
            return stripped
        try:
            decoded = base64.b64decode(stripped).decode("utf-8")
        except Exception as e:
            raise SSHTunnelError(
                f"SSH private key is not valid PEM and could not be base64-decoded: {e}"
            ) from e
        if not decoded.strip().startswith("-----BEGIN"):
            raise SSHTunnelError(
                "SSH private key: base64-decoded content is not a valid PEM key"
            )
        return decoded.strip()

    @staticmethod
    def _parse_private_key(
        key_content: str, passphrase: Optional[str] = None
    ) -> paramiko.PKey:
        """
        Parse a private key string into a paramiko PKey object.

        Accepts raw PEM or base64-encoded PEM content.
        Tries RSA, Ed25519, ECDSA, and DSS key types in order.

        Raises:
            SSHTunnelError: If the key cannot be parsed as any supported type
        """
        pem = SSHTunnelManager._decode_key_content(key_content)
        key_classes = [
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
            paramiko.DSSKey,
        ]
        for key_class in key_classes:
            try:
                return key_class.from_private_key(StringIO(pem), password=passphrase)
            except Exception:
                continue
        raise SSHTunnelError(
            "Failed to parse inline SSH private key: unsupported key type or invalid key content"
        )

    def ensure_active(self) -> bool:
        """
        Ensure tunnel is active, attempting restart if needed.

        Returns:
            True if tunnel is active (possibly after restart)

        Raises:
            SSHTunnelError: If tunnel cannot be restarted
        """
        if self.is_active:
            return True

        logger.warning("SSH tunnel inactive, attempting restart...")

        # Clean up old tunnel
        self._cleanup()

        # Attempt restart
        try:
            self.start()
            return True
        except SSHTunnelError:
            raise SSHTunnelError("SSH tunnel lost and could not be restarted")

    @property
    def is_active(self) -> bool:
        """Check if tunnel is active."""
        return self._tunnel is not None and self._tunnel.is_active

    @property
    def local_bind_port(self) -> Optional[int]:
        """Get the local port where tunnel is listening."""
        return self._local_bind_port

    def __enter__(self) -> "SSHTunnelManager":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()


def rewrite_database_url(original_url: str, local_host: str, local_port: int) -> str:
    """
    Rewrite database URL to use SSH tunnel endpoint.

    Args:
        original_url: Original database URL (e.g., postgresql://user:pass@db.remote.com:5432/mydb)
        local_host: Local tunnel host (usually 127.0.0.1)
        local_port: Local tunnel port

    Returns:
        Rewritten URL pointing to tunnel endpoint

    Example:
        Input:  postgresql://user:pass@db.remote.com:5432/mydb
        Output: postgresql://user:pass@127.0.0.1:54321/mydb
    """
    parsed = urlparse(original_url)

    # Replace host and port with tunnel endpoint
    # Format: scheme://user:pass@host:port/path
    netloc = parsed.netloc

    # Handle credentials in URL
    if "@" in netloc:
        credentials, _ = netloc.rsplit("@", 1)
        new_netloc = f"{credentials}@{local_host}:{local_port}"
    else:
        new_netloc = f"{local_host}:{local_port}"

    # Rebuild URL with new netloc
    rewritten = urlunparse(
        (
            parsed.scheme,
            new_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )

    logger.debug(f"Rewrote database URL to use tunnel: *****@{local_host}:{local_port}")

    return rewritten
