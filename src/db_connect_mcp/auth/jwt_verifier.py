"""JWT Token Verifier for OAuth 2.0 authentication.

This module provides JWT token verification for external identity providers
like Auth0, Okta, Azure AD, Google, etc. It fetches JWKS (JSON Web Key Set)
from the identity provider and validates JWT signatures and claims.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient, PyJWKClientError
from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)


@dataclass
class JWTVerifierConfig:
    """Configuration for JWT token verification.

    Attributes:
        issuer: OAuth issuer URL (e.g., "https://your-tenant.auth0.com/")
        audience: Expected audience claim (your API identifier)
        algorithms: Allowed signing algorithms (default: RS256)
        jwks_cache_ttl: JWKS cache TTL in seconds (default: 3600)
        clock_skew: Allowed clock skew in seconds for exp/iat validation (default: 60)
        required_scopes: Scopes that must be present in the token (optional)
    """

    issuer: str
    audience: str
    algorithms: list[str] = field(default_factory=lambda: ["RS256"])
    jwks_cache_ttl: int = 3600
    clock_skew: int = 60
    required_scopes: list[str] | None = None


class JWTTokenVerifier:
    """JWT Token Verifier implementing the MCP TokenVerifier protocol.

    This verifier fetches JWKS from the identity provider's well-known endpoint
    and validates JWT tokens against those keys. It supports:
    - RSA and EC key algorithms (RS256, RS384, RS512, ES256, ES384, ES512)
    - Automatic JWKS key rotation handling
    - Token expiration validation
    - Issuer and audience claim validation
    - Optional scope validation

    Usage with Auth0:
        config = JWTVerifierConfig(
            issuer="https://your-tenant.auth0.com/",
            audience="https://your-api-identifier",
        )
        verifier = JWTTokenVerifier(config)

    Usage with Azure AD:
        config = JWTVerifierConfig(
            issuer="https://login.microsoftonline.com/{tenant}/v2.0",
            audience="your-client-id",
        )
        verifier = JWTTokenVerifier(config)
    """

    def __init__(self, config: JWTVerifierConfig) -> None:
        self.config = config
        self._jwks_client: PyJWKClient | None = None
        self._jwks_lock = asyncio.Lock()
        self._last_jwks_fetch: float = 0

        # Normalize issuer URL (ensure trailing slash for proper matching)
        self._issuer = config.issuer.rstrip("/") + "/"

    @property
    def jwks_uri(self) -> str:
        """Get the JWKS URI from the OpenID Connect discovery endpoint."""
        # Standard OIDC well-known endpoint for JWKS
        return f"{self._issuer}.well-known/jwks.json"

    async def _get_jwks_client(self) -> PyJWKClient:
        """Get or create the JWKS client with caching."""
        async with self._jwks_lock:
            now = time.time()
            if (
                self._jwks_client is None
                or (now - self._last_jwks_fetch) > self.config.jwks_cache_ttl
            ):
                logger.debug(f"Fetching JWKS from {self.jwks_uri}")
                # PyJWKClient handles caching internally, but we control refresh
                self._jwks_client = PyJWKClient(
                    self.jwks_uri,
                    cache_jwk_set=True,
                    lifespan=self.config.jwks_cache_ttl,
                )
                self._last_jwks_fetch = now
            return self._jwks_client

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a JWT token and return access info if valid.

        This method implements the MCP TokenVerifier protocol.

        Args:
            token: The JWT token string to verify

        Returns:
            AccessToken if the token is valid, None otherwise
        """
        try:
            # Get signing key from JWKS
            jwks_client = await self._get_jwks_client()

            # Get the signing key for this token (runs in thread pool for I/O)
            loop = asyncio.get_event_loop()
            signing_key = await loop.run_in_executor(
                None, jwks_client.get_signing_key_from_jwt, token
            )

            # Decode and verify the token
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=self.config.algorithms,
                audience=self.config.audience,
                issuer=self._issuer,
                leeway=self.config.clock_skew,
                options={
                    "require": ["exp", "iat", "iss", "aud"],
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )

            # Extract scopes (various formats supported)
            scopes = self._extract_scopes(payload)

            # Check required scopes if configured
            if self.config.required_scopes:
                if not all(s in scopes for s in self.config.required_scopes):
                    logger.warning(
                        f"Token missing required scopes. Has: {scopes}, "
                        f"Required: {self.config.required_scopes}"
                    )
                    return None

            # Extract client_id (various claim names supported)
            client_id = self._extract_client_id(payload)

            # Build AccessToken
            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=payload.get("exp"),
                resource=payload.get("aud")
                if isinstance(payload.get("aud"), str)
                else None,
            )

        except jwt.ExpiredSignatureError:
            logger.debug("Token expired")
            return None
        except jwt.InvalidAudienceError:
            logger.debug("Invalid audience")
            return None
        except jwt.InvalidIssuerError:
            logger.debug("Invalid issuer")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug(f"Invalid token: {e}")
            return None
        except PyJWKClientError as e:
            logger.error(f"JWKS client error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error verifying token: {e}")
            return None

    def _extract_scopes(self, payload: dict[str, Any]) -> list[str]:
        """Extract scopes from JWT payload.

        Supports multiple formats:
        - "scope": "read write" (space-separated string - OAuth 2.0 standard)
        - "scp": ["read", "write"] (list - Azure AD format)
        - "permissions": ["read:data"] (Auth0 format)
        - "scopes": ["read"] (alternative)
        """
        scopes: list[str] = []

        # OAuth 2.0 standard: space-separated string
        if "scope" in payload:
            scope_value = payload["scope"]
            if isinstance(scope_value, str):
                scopes = scope_value.split()
            elif isinstance(scope_value, list):
                scopes = scope_value

        # Azure AD format
        elif "scp" in payload:
            scp_value = payload["scp"]
            if isinstance(scp_value, str):
                scopes = scp_value.split()
            elif isinstance(scp_value, list):
                scopes = scp_value

        # Auth0 permissions
        elif "permissions" in payload:
            permissions = payload["permissions"]
            if isinstance(permissions, list):
                scopes = permissions

        # Alternative format
        elif "scopes" in payload:
            scopes_value = payload["scopes"]
            if isinstance(scopes_value, list):
                scopes = scopes_value

        return scopes

    def _extract_client_id(self, payload: dict[str, Any]) -> str:
        """Extract client ID from JWT payload.

        Supports multiple claim names:
        - "azp" (authorized party - OIDC standard for access tokens)
        - "client_id" (OAuth 2.0 token introspection)
        - "cid" (some providers)
        - "sub" (fallback - subject claim)
        """
        for claim in ["azp", "client_id", "cid"]:
            if claim in payload and payload[claim]:
                return str(payload[claim])

        # Fallback to subject
        return str(payload.get("sub", "unknown"))


class IntrospectionTokenVerifier:
    """Token verifier using OAuth 2.0 Token Introspection (RFC 7662).

    This verifier calls the authorization server's introspection endpoint
    to validate tokens. Useful for opaque tokens or when JWKS is not available.

    Usage:
        verifier = IntrospectionTokenVerifier(
            introspection_url="https://auth.example.com/oauth/introspect",
            client_id="your-client-id",
            client_secret="your-client-secret",
        )
    """

    def __init__(
        self,
        introspection_url: str,
        client_id: str,
        client_secret: str,
        required_scopes: list[str] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.introspection_url = introspection_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.required_scopes = required_scopes
        self.timeout = timeout

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a token using the introspection endpoint.

        Args:
            token: The token string to verify

        Returns:
            AccessToken if the token is active, None otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.introspection_url,
                    data={"token": token},
                    auth=(self.client_id, self.client_secret),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=self.timeout,
                )

                if response.status_code != 200:
                    logger.error(f"Introspection failed: {response.status_code}")
                    return None

                data = response.json()

                # Token must be active
                if not data.get("active", False):
                    logger.debug("Token is not active")
                    return None

                # Extract scopes
                scope_str = data.get("scope", "")
                scopes = scope_str.split() if scope_str else []

                # Check required scopes
                if self.required_scopes:
                    if not all(s in scopes for s in self.required_scopes):
                        logger.warning(
                            f"Token missing required scopes. Has: {scopes}, "
                            f"Required: {self.required_scopes}"
                        )
                        return None

                return AccessToken(
                    token=token,
                    client_id=data.get("client_id", data.get("sub", "unknown")),
                    scopes=scopes,
                    expires_at=data.get("exp"),
                    resource=data.get("aud"),
                )

        except httpx.RequestError as e:
            logger.error(f"Introspection request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during introspection: {e}")
            return None
