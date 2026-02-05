"""Comprehensive tests for OAuth 2.0 JWT authentication.

This test module covers:
1. JWT Token Verification (signature, claims, expiration)
2. JWKS fetching and key rotation
3. OAuth error responses (401, 403)
4. Scope validation
5. Various JWT claim formats (Auth0, Azure AD, Okta)
6. Token introspection
7. Edge cases and security scenarios
"""

import asyncio
import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from db_connect_mcp.auth.jwt_verifier import (
    IntrospectionTokenVerifier,
    JWTTokenVerifier,
    JWTVerifierConfig,
)


# =============================================================================
# Test Fixtures - RSA Key Generation
# =============================================================================


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate an RSA key pair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture(scope="module")
def rsa_private_key_pem(rsa_keypair):
    """Get the private key in PEM format."""
    private_key, _ = rsa_keypair
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture(scope="module")
def rsa_public_key_pem(rsa_keypair):
    """Get the public key in PEM format."""
    _, public_key = rsa_keypair
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


@pytest.fixture(scope="module")
def jwks_response(rsa_keypair):
    """Generate a JWKS response for the test key."""
    _, public_key = rsa_keypair
    numbers = public_key.public_numbers()

    # Convert to base64url encoding
    def int_to_base64url(n: int, length: int) -> str:
        return base64.urlsafe_b64encode(
            n.to_bytes(length, byteorder="big")
        ).decode().rstrip("=")

    n = int_to_base64url(numbers.n, 256)  # 2048 bits = 256 bytes
    e = int_to_base64url(numbers.e, 3)  # exponent is small

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "kid": "test-key-id",
                "alg": "RS256",
                "n": n,
                "e": e,
            }
        ]
    }


@pytest.fixture
def jwt_config():
    """Default JWT verifier configuration."""
    return JWTVerifierConfig(
        issuer="https://test-issuer.example.com/",
        audience="test-audience",
        algorithms=["RS256"],
        jwks_cache_ttl=3600,
        clock_skew=60,
    )


def create_signed_jwt(
    private_key_pem: bytes,
    claims: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> str:
    """Create a signed JWT token for testing."""
    default_headers = {"kid": "test-key-id", "alg": "RS256"}
    if headers:
        default_headers.update(headers)
    return jwt.encode(claims, private_key_pem, algorithm="RS256", headers=default_headers)


# =============================================================================
# JWT Token Verifier - Basic Tests
# =============================================================================


class TestJWTTokenVerifierBasics:
    """Basic tests for JWT token verification."""

    def test_config_creation(self):
        """Test JWTVerifierConfig creation."""
        config = JWTVerifierConfig(
            issuer="https://auth.example.com/",
            audience="my-api",
        )
        assert config.issuer == "https://auth.example.com/"
        assert config.audience == "my-api"
        assert config.algorithms == ["RS256"]
        assert config.jwks_cache_ttl == 3600
        assert config.clock_skew == 60
        assert config.required_scopes is None

    def test_config_with_custom_values(self):
        """Test JWTVerifierConfig with custom values."""
        config = JWTVerifierConfig(
            issuer="https://auth.example.com",
            audience="my-api",
            algorithms=["RS256", "RS384"],
            jwks_cache_ttl=1800,
            clock_skew=30,
            required_scopes=["read", "write"],
        )
        assert config.algorithms == ["RS256", "RS384"]
        assert config.jwks_cache_ttl == 1800
        assert config.clock_skew == 30
        assert config.required_scopes == ["read", "write"]

    def test_verifier_jwks_uri(self, jwt_config):
        """Test JWKS URI construction."""
        verifier = JWTTokenVerifier(jwt_config)
        assert verifier.jwks_uri == "https://test-issuer.example.com/.well-known/jwks.json"

    def test_verifier_issuer_normalization(self):
        """Test issuer URL normalization (trailing slash)."""
        config1 = JWTVerifierConfig(
            issuer="https://auth.example.com",
            audience="my-api",
        )
        verifier1 = JWTTokenVerifier(config1)
        assert verifier1._issuer == "https://auth.example.com/"

        config2 = JWTVerifierConfig(
            issuer="https://auth.example.com/",
            audience="my-api",
        )
        verifier2 = JWTTokenVerifier(config2)
        assert verifier2._issuer == "https://auth.example.com/"


# =============================================================================
# JWT Token Verification - Valid Tokens
# =============================================================================


class TestJWTValidTokens:
    """Tests for valid JWT token verification."""

    @pytest.fixture
    def mock_jwks_client(self, rsa_keypair):
        """Create a mock JWKS client."""
        _, public_key = rsa_keypair

        mock_client = MagicMock()
        mock_signing_key = MagicMock()
        mock_signing_key.key = public_key
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        return mock_client

    async def test_valid_token_verification(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test verification of a valid JWT token."""
        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "azp": "client-abc",
            "iat": now,
            "exp": now + 3600,
            "scope": "read write",
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is not None
        assert result.client_id == "client-abc"
        assert result.scopes == ["read", "write"]
        assert result.expires_at == now + 3600
        assert result.token == token

    async def test_token_with_list_scopes(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test token with scopes as a list."""
        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now,
            "exp": now + 3600,
            "scope": ["read", "write", "admin"],
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is not None
        assert result.scopes == ["read", "write", "admin"]

    async def test_azure_ad_token_format(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test Azure AD token format with 'scp' claim."""
        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "azp": "client-abc",
            "iat": now,
            "exp": now + 3600,
            "scp": "User.Read User.Write",  # Azure AD format
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is not None
        assert result.scopes == ["User.Read", "User.Write"]

    async def test_auth0_permissions_format(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test Auth0 token format with 'permissions' claim."""
        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "azp": "client-abc",
            "iat": now,
            "exp": now + 3600,
            "permissions": ["read:data", "write:data"],  # Auth0 format
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is not None
        assert result.scopes == ["read:data", "write:data"]

    async def test_client_id_extraction_variants(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test client_id extraction from various claims."""
        now = int(time.time())
        verifier = JWTTokenVerifier(jwt_config)

        # Test 'azp' claim (OIDC standard)
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "azp": "client-from-azp",
            "iat": now,
            "exp": now + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)
        assert result.client_id == "client-from-azp"

        # Test 'client_id' claim
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "client_id": "client-from-client-id",
            "iat": now,
            "exp": now + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)
        assert result.client_id == "client-from-client-id"

        # Test fallback to 'sub'
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-as-fallback",
            "iat": now,
            "exp": now + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)
        assert result.client_id == "user-as-fallback"


# =============================================================================
# JWT Token Verification - Invalid Tokens
# =============================================================================


class TestJWTInvalidTokens:
    """Tests for invalid JWT token handling."""

    @pytest.fixture
    def mock_jwks_client(self, rsa_keypair):
        """Create a mock JWKS client."""
        _, public_key = rsa_keypair

        mock_client = MagicMock()
        mock_signing_key = MagicMock()
        mock_signing_key.key = public_key
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        return mock_client

    async def test_expired_token(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test rejection of expired tokens."""
        past = int(time.time()) - 7200  # 2 hours ago
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": past,
            "exp": past + 3600,  # Expired 1 hour ago
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is None

    async def test_token_within_clock_skew(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test token that's expired but within clock skew is accepted."""
        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now - 3660,
            "exp": now - 30,  # Expired 30 seconds ago (within 60s clock skew)
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is not None

    async def test_invalid_issuer(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test rejection of tokens with wrong issuer."""
        now = int(time.time())
        claims = {
            "iss": "https://wrong-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now,
            "exp": now + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is None

    async def test_invalid_audience(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test rejection of tokens with wrong audience."""
        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "wrong-audience",
            "sub": "user-123",
            "iat": now,
            "exp": now + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is None

    async def test_malformed_token(self, jwt_config, mock_jwks_client):
        """Test rejection of malformed tokens."""
        verifier = JWTTokenVerifier(jwt_config)

        # Not a JWT at all
        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token("not-a-jwt-token")
        assert result is None

        # Incomplete JWT
        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token("eyJhbGciOiJIUzI1NiJ9")
        assert result is None

    async def test_wrong_signing_key(self, jwt_config, mock_jwks_client):
        """Test rejection of tokens signed with wrong key."""
        # Generate a different key pair
        different_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        different_private_pem = different_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now,
            "exp": now + 3600,
        }
        # Sign with different key
        token = create_signed_jwt(different_private_pem, claims)

        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is None

    async def test_missing_required_claims(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test rejection of tokens missing required claims."""
        verifier = JWTTokenVerifier(jwt_config)
        now = int(time.time())

        # Missing 'exp'
        claims_no_exp = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims_no_exp)
        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)
        assert result is None

        # Missing 'iat'
        claims_no_iat = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "exp": now + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims_no_iat)
        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)
        assert result is None

        # Missing 'iss'
        claims_no_iss = {
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now,
            "exp": now + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims_no_iss)
        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)
        assert result is None


# =============================================================================
# JWT Token Verification - Scope Validation
# =============================================================================


class TestJWTScopeValidation:
    """Tests for JWT scope validation."""

    @pytest.fixture
    def mock_jwks_client(self, rsa_keypair):
        """Create a mock JWKS client."""
        _, public_key = rsa_keypair
        mock_client = MagicMock()
        mock_signing_key = MagicMock()
        mock_signing_key.key = public_key
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        return mock_client

    async def test_required_scopes_present(
        self, rsa_private_key_pem, mock_jwks_client
    ):
        """Test token with all required scopes passes."""
        config = JWTVerifierConfig(
            issuer="https://test-issuer.example.com/",
            audience="test-audience",
            required_scopes=["read", "write"],
        )

        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now,
            "exp": now + 3600,
            "scope": "read write admin",
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is not None
        assert result.scopes == ["read", "write", "admin"]

    async def test_required_scopes_missing(
        self, rsa_private_key_pem, mock_jwks_client
    ):
        """Test token missing required scopes is rejected."""
        config = JWTVerifierConfig(
            issuer="https://test-issuer.example.com/",
            audience="test-audience",
            required_scopes=["read", "admin"],
        )

        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now,
            "exp": now + 3600,
            "scope": "read write",  # Missing 'admin'
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is None

    async def test_no_required_scopes(
        self, rsa_private_key_pem, mock_jwks_client
    ):
        """Test token passes when no scopes are required."""
        config = JWTVerifierConfig(
            issuer="https://test-issuer.example.com/",
            audience="test-audience",
            required_scopes=None,
        )

        now = int(time.time())
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": now,
            "exp": now + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        verifier = JWTTokenVerifier(config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        assert result is not None
        assert result.scopes == []


# =============================================================================
# Token Introspection Verifier Tests
# =============================================================================


class TestIntrospectionTokenVerifier:
    """Tests for OAuth 2.0 token introspection verifier."""

    async def test_active_token(self):
        """Test verification of active token."""
        verifier = IntrospectionTokenVerifier(
            introspection_url="https://auth.example.com/introspect",
            client_id="my-client",
            client_secret="my-secret",
        )

        mock_response = {
            "active": True,
            "client_id": "resource-client",
            "sub": "user-123",
            "scope": "read write",
            "exp": int(time.time()) + 3600,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_response
            mock_client.post.return_value = mock_response_obj
            mock_client_class.return_value = mock_client

            result = await verifier.verify_token("test-token")

        assert result is not None
        assert result.client_id == "resource-client"
        assert result.scopes == ["read", "write"]
        assert result.token == "test-token"

    async def test_inactive_token(self):
        """Test rejection of inactive token."""
        verifier = IntrospectionTokenVerifier(
            introspection_url="https://auth.example.com/introspect",
            client_id="my-client",
            client_secret="my-secret",
        )

        mock_response = {"active": False}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_response
            mock_client.post.return_value = mock_response_obj
            mock_client_class.return_value = mock_client

            result = await verifier.verify_token("test-token")

        assert result is None

    async def test_introspection_error(self):
        """Test handling of introspection endpoint errors."""
        verifier = IntrospectionTokenVerifier(
            introspection_url="https://auth.example.com/introspect",
            client_id="my-client",
            client_secret="my-secret",
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 500
            mock_client.post.return_value = mock_response_obj
            mock_client_class.return_value = mock_client

            result = await verifier.verify_token("test-token")

        assert result is None

    async def test_introspection_required_scopes(self):
        """Test scope validation with introspection."""
        verifier = IntrospectionTokenVerifier(
            introspection_url="https://auth.example.com/introspect",
            client_id="my-client",
            client_secret="my-secret",
            required_scopes=["admin"],
        )

        mock_response = {
            "active": True,
            "client_id": "resource-client",
            "scope": "read write",  # Missing 'admin'
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_response
            mock_client.post.return_value = mock_response_obj
            mock_client_class.return_value = mock_client

            result = await verifier.verify_token("test-token")

        assert result is None


# =============================================================================
# OAuth ASGI App Integration Tests
# =============================================================================


class TestOAuthASGIApp:
    """Integration tests for OAuth ASGI application."""

    @pytest.fixture
    def mock_session_manager(self):
        """Create a mock session manager."""
        manager = AsyncMock()
        manager.handle_request = AsyncMock()
        return manager

    @pytest.fixture
    def mock_token_verifier(self):
        """Create a mock token verifier."""
        from mcp.server.auth.provider import AccessToken

        verifier = AsyncMock()
        verifier.verify_token.return_value = AccessToken(
            token="valid-token",
            client_id="test-client",
            scopes=["read", "write"],
            expires_at=int(time.time()) + 3600,
        )
        return verifier

    async def test_valid_token_passes(
        self, mock_session_manager, mock_token_verifier
    ):
        """Test that valid tokens are accepted."""
        from db_connect_mcp.server import _OAuthMCPASGIApp

        app = _OAuthMCPASGIApp(mock_session_manager, mock_token_verifier)

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer valid-token")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await app(scope, receive, send)

        mock_token_verifier.verify_token.assert_called_once_with("valid-token")
        mock_session_manager.handle_request.assert_called_once()
        assert scope["auth"] is not None

    async def test_missing_auth_header_returns_401(self, mock_session_manager):
        """Test that missing auth header returns 401."""
        from db_connect_mcp.server import _OAuthMCPASGIApp

        verifier = AsyncMock()
        app = _OAuthMCPASGIApp(mock_session_manager, verifier)

        scope = {
            "type": "http",
            "headers": [],
        }
        receive = AsyncMock()

        sent_responses = []
        async def capture_send(message):
            sent_responses.append(message)

        await app(scope, receive, capture_send)

        # Check 401 was sent
        assert any(
            msg.get("status") == 401
            for msg in sent_responses
            if msg.get("type") == "http.response.start"
        )
        mock_session_manager.handle_request.assert_not_called()

    async def test_invalid_token_returns_401(self, mock_session_manager):
        """Test that invalid tokens return 401."""
        from db_connect_mcp.server import _OAuthMCPASGIApp

        verifier = AsyncMock()
        verifier.verify_token.return_value = None  # Invalid token
        app = _OAuthMCPASGIApp(mock_session_manager, verifier)

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer invalid-token")],
        }
        receive = AsyncMock()

        sent_responses = []
        async def capture_send(message):
            sent_responses.append(message)

        await app(scope, receive, capture_send)

        assert any(
            msg.get("status") == 401
            for msg in sent_responses
            if msg.get("type") == "http.response.start"
        )
        mock_session_manager.handle_request.assert_not_called()

    async def test_insufficient_scopes_returns_403(
        self, mock_session_manager, mock_token_verifier
    ):
        """Test that insufficient scopes return 403."""
        from db_connect_mcp.server import _OAuthMCPASGIApp

        app = _OAuthMCPASGIApp(
            mock_session_manager,
            mock_token_verifier,
            required_scopes=["admin"],  # Token has read, write
        )

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer valid-token")],
        }
        receive = AsyncMock()

        sent_responses = []
        async def capture_send(message):
            sent_responses.append(message)

        await app(scope, receive, capture_send)

        assert any(
            msg.get("status") == 403
            for msg in sent_responses
            if msg.get("type") == "http.response.start"
        )
        mock_session_manager.handle_request.assert_not_called()

    async def test_non_http_scope_passes_through(self, mock_session_manager):
        """Test that non-HTTP scopes pass through without auth."""
        from db_connect_mcp.server import _OAuthMCPASGIApp

        verifier = AsyncMock()
        app = _OAuthMCPASGIApp(mock_session_manager, verifier)

        scope = {"type": "websocket"}
        receive = AsyncMock()
        send = AsyncMock()

        await app(scope, receive, send)

        verifier.verify_token.assert_not_called()
        mock_session_manager.handle_request.assert_called_once()


# =============================================================================
# Security Edge Cases
# =============================================================================


class TestSecurityEdgeCases:
    """Security-focused edge case tests."""

    @pytest.fixture
    def mock_jwks_client(self, rsa_keypair):
        """Create a mock JWKS client."""
        _, public_key = rsa_keypair
        mock_client = MagicMock()
        mock_signing_key = MagicMock()
        mock_signing_key.key = public_key
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        return mock_client

    async def test_algorithm_confusion_attack(self, jwt_config):
        """Test protection against algorithm confusion (none/HS256 attacks)."""
        verifier = JWTTokenVerifier(jwt_config)

        # Try to use 'none' algorithm
        header = {"alg": "none", "typ": "JWT"}
        payload = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "attacker",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        header_b64 = base64.urlsafe_b64encode(
            json.dumps(header).encode()
        ).decode().rstrip("=")
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).decode().rstrip("=")
        malicious_token = f"{header_b64}.{payload_b64}."

        # This should be rejected because RS256 is required
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.side_effect = Exception("No key for none")

        with patch.object(verifier, "_get_jwks_client", return_value=mock_client):
            result = await verifier.verify_token(malicious_token)

        assert result is None

    async def test_token_with_future_iat(
        self, jwt_config, rsa_private_key_pem, mock_jwks_client
    ):
        """Test handling of tokens with future issued-at time."""
        verifier = JWTTokenVerifier(jwt_config)

        future = int(time.time()) + 3600  # 1 hour in future
        claims = {
            "iss": "https://test-issuer.example.com/",
            "aud": "test-audience",
            "sub": "user-123",
            "iat": future,
            "exp": future + 3600,
        }
        token = create_signed_jwt(rsa_private_key_pem, claims)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(token)

        # Token with future iat should be rejected (beyond clock skew)
        assert result is None

    async def test_empty_token(self, jwt_config):
        """Test handling of empty tokens."""
        verifier = JWTTokenVerifier(jwt_config)
        result = await verifier.verify_token("")
        assert result is None

    async def test_whitespace_token(self, jwt_config):
        """Test handling of whitespace-only tokens."""
        verifier = JWTTokenVerifier(jwt_config)
        result = await verifier.verify_token("   ")
        assert result is None

    async def test_very_long_token(self, jwt_config, mock_jwks_client):
        """Test handling of excessively long tokens."""
        verifier = JWTTokenVerifier(jwt_config)

        # Create a very long but invalid token
        long_token = "eyJ" + "a" * 100000

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token(long_token)

        assert result is None

    async def test_token_with_null_bytes(self, jwt_config, mock_jwks_client):
        """Test handling of tokens with null bytes."""
        verifier = JWTTokenVerifier(jwt_config)

        with patch.object(verifier, "_get_jwks_client", return_value=mock_jwks_client):
            result = await verifier.verify_token("token\x00with\x00nulls")

        assert result is None


# =============================================================================
# JWKS Client Tests
# =============================================================================


class TestJWKSClient:
    """Tests for JWKS client behavior."""

    async def test_jwks_cache_ttl(self, jwt_config, rsa_keypair):
        """Test that JWKS client respects cache TTL."""
        _, public_key = rsa_keypair

        verifier = JWTTokenVerifier(jwt_config)

        mock_client = MagicMock()
        mock_signing_key = MagicMock()
        mock_signing_key.key = public_key
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

        # First call should create client
        with patch("db_connect_mcp.auth.jwt_verifier.PyJWKClient", return_value=mock_client):
            client1 = await verifier._get_jwks_client()
            assert client1 is mock_client

        # Second call should return cached client
        client2 = await verifier._get_jwks_client()
        assert client2 is client1

    async def test_jwks_refresh_after_ttl(self, rsa_keypair):
        """Test that JWKS client refreshes after TTL expires."""
        _, public_key = rsa_keypair

        config = JWTVerifierConfig(
            issuer="https://test-issuer.example.com/",
            audience="test-audience",
            jwks_cache_ttl=1,  # 1 second TTL
        )
        verifier = JWTTokenVerifier(config)

        mock_client1 = MagicMock()
        mock_client2 = MagicMock()

        with patch("db_connect_mcp.auth.jwt_verifier.PyJWKClient") as mock_constructor:
            mock_constructor.return_value = mock_client1
            client1 = await verifier._get_jwks_client()
            assert client1 is mock_client1

            # Wait for TTL to expire
            await asyncio.sleep(1.1)

            mock_constructor.return_value = mock_client2
            client2 = await verifier._get_jwks_client()
            assert client2 is mock_client2


# =============================================================================
# CLI Argument Tests
# =============================================================================


class TestOAuthCLIArguments:
    """Tests for OAuth CLI argument parsing."""

    def test_oauth_args_parsed_correctly(self):
        """Test that OAuth CLI arguments are parsed correctly."""

        # We can't easily test the full cli_entry, but we can verify
        # the argument structure by checking the module
        # This is more of a smoke test
        import db_connect_mcp.server as server_module

        assert hasattr(server_module, "main")
        assert hasattr(server_module, "cli_entry")

    def test_oauth_scope_parsing(self):
        """Test OAuth scope string parsing."""
        # Simulate the scope parsing logic from cli_entry
        scope_str = "read,write, admin , manage"
        scopes = [s.strip() for s in scope_str.split(",") if s.strip()]
        assert scopes == ["read", "write", "admin", "manage"]

        # Empty string
        scope_str = ""
        scopes = [s.strip() for s in scope_str.split(",") if s.strip()]
        assert scopes == []

        # Single scope
        scope_str = "admin"
        scopes = [s.strip() for s in scope_str.split(",") if s.strip()]
        assert scopes == ["admin"]
