"""SSH tunnel management for secure database connections."""

import base64
import binascii
import enum
import logging
import re
import threading
import time
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa

from db_connect_mcp.core.ssh_forwarder import (
    ParamikoTunnelForwarder,
    SSHTunnelError,
    SSHTunnelErrorCode,
)
from db_connect_mcp.models.config import SSHTunnelConfig

logger = logging.getLogger(__name__)

# Maximum time allowed for the entire key parsing pipeline (seconds).
# Leaves ~1s headroom within the user's expected 5s connection time.
_KEY_PARSE_BUDGET_SECONDS = 4.0


class KeyFormat(enum.Enum):
    """Detected SSH private key format."""

    PEM_RSA = "pem_rsa"
    PEM_DSA = "pem_dsa"
    PEM_EC = "pem_ec"
    PEM_OPENSSH = "pem_openssh"
    PEM_PKCS8 = "pem_pkcs8"
    PEM_PKCS8_ENC = "pem_pkcs8_enc"
    PUTTY_PPK = "putty_ppk"
    BASE64_ENCODED = "base64_encoded"
    UNKNOWN = "unknown"


class SSHTunnelManager:
    """Manages SSH tunnel lifecycle for database connections."""

    def __init__(self, config: SSHTunnelConfig):
        """
        Initialize tunnel manager with configuration.

        Args:
            config: SSH tunnel configuration
        """
        self.config = config
        self._tunnel: ParamikoTunnelForwarder | None = None
        self._local_bind_port: int | None = None
        self._lifecycle_lock = threading.RLock()

    def start(self) -> int:
        """
        Start the SSH tunnel.

        Returns:
            Local port number where tunnel is listening

        Raises:
            SSHTunnelError: If tunnel fails to start
        """
        with self._lifecycle_lock:
            if self._tunnel is not None:
                if self._tunnel.is_active:
                    if self._local_bind_port is None:
                        raise SSHTunnelError(
                            "Tunnel is active but its listener port is unavailable",
                            code=SSHTunnelErrorCode.LISTENER,
                        )
                    return self._local_bind_port
                self._tunnel.stop()
                self._tunnel = None

            try:
                password, pkey = self._build_auth_params()
                tunnel = ParamikoTunnelForwarder(
                    self.config,
                    password=password,
                    pkey=pkey,
                )
                try:
                    local_port = tunnel.start()
                except Exception:
                    # The manager does not publish the forwarder until startup is
                    # complete, so clean up a partially started instance directly.
                    try:
                        tunnel.stop()
                    except Exception as cleanup_exc:
                        logger.warning(
                            "Error cleaning up failed SSH tunnel startup: %s",
                            type(cleanup_exc).__name__,
                        )
                    raise
                self._tunnel = tunnel
                self._local_bind_port = local_port
                logger.info("SSH tunnel established on local port %d", local_port)
                return local_port
            except SSHTunnelError:
                self._cleanup()
                raise
            except Exception as exc:
                self._cleanup()
                raise SSHTunnelError(
                    "Failed to establish the SSH tunnel",
                    code=SSHTunnelErrorCode.UNKNOWN,
                ) from exc

    def stop(self) -> None:
        """Stop the SSH tunnel."""
        with self._lifecycle_lock:
            self._cleanup()

    def _cleanup(self) -> None:
        """Clean up tunnel resources."""
        tunnel = self._tunnel
        self._tunnel = None
        self._local_bind_port = None
        if tunnel is not None:
            try:
                tunnel.stop()
                logger.info("SSH tunnel stopped")
            except Exception as exc:
                logger.warning("Error stopping SSH tunnel: %s", type(exc).__name__)

    def _build_auth_params(self) -> tuple[str | None, paramiko.PKey | None]:
        """
        Build explicit authentication parameters for the native forwarder.

        Returns:
            Password and parsed private key

        Raises:
            SSHTunnelError: If private key file not found or cannot be parsed
        """
        password = self.config.ssh_password
        pkey: paramiko.PKey | None = None

        if self.config.ssh_private_key:
            # Inline key takes precedence over file path
            passphrase = self.config.ssh_private_key_passphrase
            pkey = self._parse_private_key(self.config.ssh_private_key, passphrase)
        elif self.config.ssh_private_key_path:
            key_path = Path(self.config.ssh_private_key_path)
            if not key_path.exists():
                raise SSHTunnelError(
                    f"SSH private key not found: {self.config.ssh_private_key_path}"
                )
            # Read file and parse through our format-detection pipeline
            # so that PKCS#8, OpenSSH, and escaped keys in files all work.
            try:
                key_content = key_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                raise SSHTunnelError(
                    f"SSH private key file '{self.config.ssh_private_key_path}' "
                    "contains non-UTF-8 content. It may be a binary (DER) "
                    "encoded key. Please convert to PEM format: "
                    "openssl pkey -inform DER -in key.der -outform PEM -o key.pem"
                ) from e
            except OSError as e:
                raise SSHTunnelError(
                    f"Cannot read SSH private key file "
                    f"'{self.config.ssh_private_key_path}': {e}. "
                    "Check file permissions (should be 600) and that "
                    "the path points to a regular file."
                ) from e
            passphrase = self.config.ssh_private_key_passphrase
            pkey = self._parse_private_key(key_content, passphrase)

        return password, pkey

    # ------------------------------------------------------------------
    # Key format detection and parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_key_format(content: str) -> KeyFormat:
        """Detect the SSH private key format from its content prefix."""
        stripped = content.strip()

        if stripped.startswith("-----BEGIN RSA PRIVATE KEY-----"):
            return KeyFormat.PEM_RSA
        if stripped.startswith("-----BEGIN DSA PRIVATE KEY-----"):
            return KeyFormat.PEM_DSA
        if stripped.startswith("-----BEGIN EC PRIVATE KEY-----"):
            return KeyFormat.PEM_EC
        if stripped.startswith("-----BEGIN OPENSSH PRIVATE KEY-----"):
            return KeyFormat.PEM_OPENSSH
        if stripped.startswith("-----BEGIN ENCRYPTED PRIVATE KEY-----"):
            return KeyFormat.PEM_PKCS8_ENC
        if stripped.startswith("-----BEGIN PRIVATE KEY-----"):
            return KeyFormat.PEM_PKCS8
        if stripped.startswith("PuTTY-User-Key-File-"):
            return KeyFormat.PUTTY_PPK

        # Check if this is base64-encoded content that decodes to a known format
        try:
            decoded = base64.b64decode(stripped).decode("utf-8")
            if decoded.strip().startswith("-----BEGIN"):
                return KeyFormat.BASE64_ENCODED
        except (binascii.Error, UnicodeDecodeError):
            pass  # Not base64 or not text — expected for non-base64 keys

        return KeyFormat.UNKNOWN

    @staticmethod
    def _normalize_escape_sequences(content: str) -> str:
        """Replace literal two-char escape sequences with real characters.

        Handles keys from environment variables or JSON config where newlines
        are stored as literal backslash-n (``\\n``) instead of real newlines.
        """
        # Replace literal \r\n, \r, and \n with real newlines
        content = content.replace("\\r\\n", "\n")
        content = content.replace("\\r", "\r")
        content = content.replace("\\n", "\n")
        return content

    @staticmethod
    def _normalize_pem(pem: str) -> str:
        """Ensure PEM content has proper line breaks (64-char body lines).

        Handles PEM that was concatenated into a single line.
        Preserves RFC 1421 encapsulated headers (e.g. Proc-Type, DEK-Info)
        found in encrypted traditional PEM keys.
        """
        pem = pem.strip()
        # Match header, body, footer — allowing missing newlines
        m = re.match(
            r"(-----BEGIN [A-Z ]+-----)\s*(.*?)\s*(-----END [A-Z ]+-----)",
            pem,
            re.DOTALL,
        )
        if not m:
            logger.debug(
                "PEM normalization skipped: content does not match PEM structure"
            )
            return pem  # Not valid PEM structure, return as-is for error handling later

        header, body, footer = m.group(1), m.group(2), m.group(3)

        # Detect RFC 1421 metadata headers (e.g. "Proc-Type: 4,ENCRYPTED").
        # These appear as "Key: Value" lines before a blank line separator.
        # If present, return the PEM as-is to avoid corrupting the metadata.
        body_stripped = body.strip()
        if body_stripped and re.match(r"[A-Za-z][A-Za-z0-9-]*:\s", body_stripped):
            return header + "\n" + body_stripped + "\n" + footer

        # Strip all whitespace from body and re-wrap at 64 chars
        body_clean = re.sub(r"\s+", "", body)
        lines = [body_clean[i : i + 64] for i in range(0, len(body_clean), 64)]
        return header + "\n" + "\n".join(lines) + "\n" + footer

    @staticmethod
    def _decode_key_content(key_content: str) -> tuple[str, KeyFormat]:
        """Decode key content with full format detection.

        Normalizes escape sequences, detects the key format, unwraps base64
        encoding, and normalizes PEM line formatting.

        Returns:
            Tuple of (normalized content, detected format).

        Raises:
            SSHTunnelError: If the key content cannot be decoded or is in an
                unsupported format (PuTTY PPK).
        """
        # Step 1: normalize escape sequences from env vars / JSON
        content = SSHTunnelManager._normalize_escape_sequences(key_content)
        stripped = content.strip()

        # Step 2: detect format
        fmt = SSHTunnelManager._detect_key_format(stripped)

        # Step 3: reject PuTTY PPK early with clear guidance
        if fmt == KeyFormat.PUTTY_PPK:
            raise SSHTunnelError(
                "SSH private key is in PuTTY PPK format, which is not directly supported. "
                "Please convert to OpenSSH format using: "
                "puttygen key.ppk -O private-openssh -o key.pem"
            )

        # Step 4: unwrap base64 encoding
        if fmt == KeyFormat.BASE64_ENCODED:
            try:
                decoded = base64.b64decode(stripped).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as e:
                raise SSHTunnelError(
                    f"SSH private key could not be base64-decoded: {e}"
                ) from e
            stripped = decoded.strip()
            fmt = SSHTunnelManager._detect_key_format(stripped)

        # Step 5: normalize PEM if it's a PEM format
        if fmt in (
            KeyFormat.PEM_RSA,
            KeyFormat.PEM_DSA,
            KeyFormat.PEM_EC,
            KeyFormat.PEM_OPENSSH,
            KeyFormat.PEM_PKCS8,
            KeyFormat.PEM_PKCS8_ENC,
        ):
            stripped = SSHTunnelManager._normalize_pem(stripped)

        # Step 6: for UNKNOWN format, try legacy base64 decode as last resort
        if fmt == KeyFormat.UNKNOWN:
            try:
                decoded = base64.b64decode(stripped).decode("utf-8")
                if decoded.strip().startswith("-----BEGIN"):
                    stripped = SSHTunnelManager._normalize_pem(decoded.strip())
                    fmt = SSHTunnelManager._detect_key_format(stripped)
                else:
                    raise SSHTunnelError(
                        "SSH private key: base64-decoded content is not a valid PEM key"
                    )
            except SSHTunnelError:
                raise
            except Exception as e:
                raise SSHTunnelError(
                    f"SSH private key is not valid PEM and could not be "
                    f"base64-decoded: {e}"
                ) from e

        return stripped, fmt

    @staticmethod
    def _convert_crypto_key_to_paramiko(
        private_key: (
            rsa.RSAPrivateKey
            | ec.EllipticCurvePrivateKey
            | ed25519.Ed25519PrivateKey
            | dsa.DSAPrivateKey
        ),
    ) -> paramiko.PKey:
        """Convert a ``cryptography`` private key to a paramiko PKey.

        RSA, EC, and DSA keys are serialized to TraditionalOpenSSL PEM.
        Ed25519 keys use OpenSSH PEM (no traditional format exists).
        """
        if isinstance(private_key, rsa.RSAPrivateKey):
            pem = private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
            return paramiko.RSAKey.from_private_key(StringIO(pem.decode("utf-8")))

        if isinstance(private_key, ec.EllipticCurvePrivateKey):
            pem = private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
            return paramiko.ECDSAKey.from_private_key(StringIO(pem.decode("utf-8")))

        if isinstance(private_key, ed25519.Ed25519PrivateKey):
            # Ed25519 has no TraditionalOpenSSL format — use OpenSSH PEM
            pem = private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            )
            return paramiko.Ed25519Key.from_private_key(StringIO(pem.decode("utf-8")))

        if isinstance(private_key, dsa.DSAPrivateKey):
            dss_key_class = getattr(paramiko, "DSSKey", None)
            if dss_key_class is None:
                raise SSHTunnelError(
                    "DSA private keys are not supported by this Paramiko version."
                )
            pem = private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
            return dss_key_class.from_private_key(StringIO(pem.decode("utf-8")))

        raise SSHTunnelError(
            f"Unsupported key type for conversion: {type(private_key).__name__}"
        )

    @staticmethod
    def _parse_pkcs8_key(
        pem_bytes: bytes, passphrase: str | None = None
    ) -> paramiko.PKey:
        """Parse a PKCS#8 PEM key via the ``cryptography`` library.

        Loads the key with ``load_pem_private_key``, detects the algorithm,
        and converts to a paramiko PKey object.
        """
        pw = passphrase.encode("utf-8") if passphrase else None
        try:
            private_key = serialization.load_pem_private_key(pem_bytes, password=pw)
        except Exception as e:
            raise SSHTunnelError(f"Failed to load PKCS#8 private key: {e}") from e
        try:
            return SSHTunnelManager._convert_crypto_key_to_paramiko(private_key)  # type: ignore[arg-type]
        except SSHTunnelError:
            raise
        except Exception as e:
            raise SSHTunnelError(
                f"PKCS#8 key loaded but conversion to paramiko failed: {e}"
            ) from e

    @staticmethod
    def _parse_private_key(
        key_content: str, passphrase: str | None = None
    ) -> paramiko.PKey:
        """Parse a private key string into a paramiko PKey object.

        Supports PEM (PKCS#1), OpenSSH, PKCS#8 (encrypted and unencrypted),
        base64-encoded variants of all the above, and keys with escaped
        newlines from environment variables or JSON config.

        PuTTY PPK keys are detected and rejected with conversion instructions.

        A 4-second time budget prevents pathological fallback chains from
        blocking the connection flow.

        Raises:
            SSHTunnelError: If the key cannot be parsed as any supported type
        """
        start = time.monotonic()

        def _check_budget() -> None:
            if time.monotonic() - start > _KEY_PARSE_BUDGET_SECONDS:
                raise SSHTunnelError(
                    "SSH key parsing exceeded time budget "
                    f"({_KEY_PARSE_BUDGET_SECONDS:.0f}s). "
                    "The key may be corrupt or in an unsupported format."
                )

        # Decode, normalize, and detect format
        pem, fmt = SSHTunnelManager._decode_key_content(key_content)
        _check_budget()
        logger.debug("Detected SSH key format: %s", fmt.value)

        # Collect errors from each attempt for diagnostic output
        errors: list[tuple[str, Exception]] = []

        # --- PKCS#8 fast path (paramiko cannot handle this natively) ---
        if fmt in (KeyFormat.PEM_PKCS8, KeyFormat.PEM_PKCS8_ENC):
            try:
                logger.debug("Attempting PKCS#8 fast path for format: %s", fmt.value)
                pkey = SSHTunnelManager._parse_pkcs8_key(
                    pem.encode("utf-8"), passphrase
                )
                logger.debug("Key parsed as %s via PKCS#8", pkey.get_name())
                return pkey
            except SSHTunnelError:
                raise
            except Exception as e:
                logger.warning(
                    "PKCS#8 parsing raised unexpected %s: %s; "
                    "falling back to brute-force",
                    type(e).__name__,
                    e,
                )
                errors.append(("PKCS#8", e))
                _check_budget()
                # Fall through to brute-force as last resort

        # --- Traditional PEM / OpenSSH path ---
        # Map detected format to the most likely paramiko class
        dss_key_class = getattr(paramiko, "DSSKey", None)
        _format_to_classes: dict[KeyFormat, list[type[paramiko.PKey]]] = {
            KeyFormat.PEM_RSA: [paramiko.RSAKey],
            KeyFormat.PEM_DSA: [dss_key_class] if dss_key_class is not None else [],
            KeyFormat.PEM_EC: [paramiko.ECDSAKey],
            KeyFormat.PEM_OPENSSH: [
                paramiko.Ed25519Key,
                paramiko.RSAKey,
                paramiko.ECDSAKey,
                *([dss_key_class] if dss_key_class is not None else []),
            ],
        }

        all_classes: list[type[paramiko.PKey]] = [
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
        ]
        if dss_key_class is not None:
            all_classes.append(dss_key_class)

        preferred = _format_to_classes.get(fmt, [])
        tried: set[type[paramiko.PKey]] = set()

        # Try preferred class(es) first, then remaining
        for key_class in [*preferred, *all_classes]:
            if key_class in tried:
                continue
            _check_budget()
            tried.add(key_class)
            try:
                logger.debug("Trying paramiko %s", key_class.__name__)
                pkey = key_class.from_private_key(StringIO(pem), password=passphrase)
                logger.debug("Key parsed as %s", pkey.get_name())
                return pkey
            except paramiko.PasswordRequiredException as e:
                raise SSHTunnelError(
                    "SSH private key is encrypted but no passphrase was "
                    "provided. Set ssh_private_key_passphrase in your "
                    "configuration."
                ) from e
            except Exception as e:
                logger.debug("%s failed: %s", key_class.__name__, e)
                errors.append((key_class.__name__, e))
                continue

        # Last resort: attempt PKCS#8 conversion for unrecognized PEM headers
        if fmt not in (KeyFormat.PEM_PKCS8, KeyFormat.PEM_PKCS8_ENC):
            _check_budget()
            try:
                logger.debug("Trying last-resort PKCS#8 conversion")
                pkey = SSHTunnelManager._parse_pkcs8_key(
                    pem.encode("utf-8"), passphrase
                )
                logger.debug("Key parsed as %s via PKCS#8 last resort", pkey.get_name())
                return pkey
            except SSHTunnelError as e:
                logger.debug("Last-resort PKCS#8 failed: %s", e)
                errors.append(("PKCS#8 (last resort)", e))
            except Exception as e:
                logger.warning(
                    "Last-resort PKCS#8 raised unexpected %s: %s",
                    type(e).__name__,
                    e,
                )
                errors.append(("PKCS#8 (last resort)", e))

        details = "; ".join(f"{name}: {err}" for name, err in errors[-3:])
        supported_key_types = "RSA, ECDSA, Ed25519"
        if getattr(paramiko, "DSSKey", None) is not None:
            supported_key_types += ", DSA"
        raise SSHTunnelError(
            f"Failed to parse SSH private key. Last errors: {details}. "
            f"Supported key types: {supported_key_types} in PEM, "
            "OpenSSH, or PKCS#8 encoding. PuTTY PPK keys must be converted "
            "first (puttygen key.ppk -O private-openssh -o key.pem)."
        )

    def ensure_active(self) -> bool:
        """
        Ensure tunnel is active, attempting restart if needed.

        Returns:
            True if tunnel is active (possibly after restart)

        Raises:
            SSHTunnelError: If tunnel cannot be restarted
        """
        with self._lifecycle_lock:
            if self._tunnel is None:
                self.start()
                return True
            try:
                return self._tunnel.ensure_active()
            except SSHTunnelError:
                raise
            except Exception as exc:
                raise SSHTunnelError(
                    "SSH tunnel health recovery failed",
                    code=SSHTunnelErrorCode.CONNECT,
                ) from exc

    @property
    def is_active(self) -> bool:
        """Check if tunnel is active."""
        return self._tunnel is not None and self._tunnel.is_active

    @property
    def local_bind_port(self) -> int | None:
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

    # Wrap IPv6 addresses in brackets per RFC 3986
    host_str = f"[{local_host}]" if ":" in local_host else local_host

    # Handle credentials in URL
    if "@" in netloc:
        credentials, _ = netloc.rsplit("@", 1)
        new_netloc = f"{credentials}@{host_str}:{local_port}"
    else:
        new_netloc = f"{host_str}:{local_port}"

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
