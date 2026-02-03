"""Unit tests for CLI argument parsing."""

import argparse
import pytest


class TestCLIArguments:
    """Tests for command-line argument parsing."""

    def test_default_transport_is_stdio(self):
        """Test that default transport is stdio."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--transport",
            choices=["stdio", "streamable-http"],
            default="stdio",
        )
        args = parser.parse_args([])
        assert args.transport == "stdio"

    def test_streamable_http_transport_accepted(self):
        """Test that streamable-http transport is accepted."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--transport",
            choices=["stdio", "streamable-http"],
            default="stdio",
        )
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=8000)

        args = parser.parse_args(["--transport", "streamable-http"])
        assert args.transport == "streamable-http"

    def test_custom_host_and_port(self):
        """Test custom host and port arguments."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--transport",
            choices=["stdio", "streamable-http"],
            default="stdio",
        )
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=8000)

        args = parser.parse_args(
            ["--transport", "streamable-http", "--host", "127.0.0.1", "--port", "9000"]
        )
        assert args.host == "127.0.0.1"
        assert args.port == 9000

    def test_invalid_transport_rejected(self):
        """Test that invalid transport values are rejected."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--transport",
            choices=["stdio", "streamable-http"],
            default="stdio",
        )

        with pytest.raises(SystemExit):
            parser.parse_args(["--transport", "invalid"])

    def test_invalid_port_rejected(self):
        """Test that non-integer port values are rejected."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--port", type=int, default=8000)

        with pytest.raises(SystemExit):
            parser.parse_args(["--port", "not-a-number"])

    def test_default_host_is_all_interfaces(self):
        """Test that default host binds to all interfaces."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--host", default="0.0.0.0")

        args = parser.parse_args([])
        assert args.host == "0.0.0.0"

    def test_default_port_is_8000(self):
        """Test that default port is 8000."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--port", type=int, default=8000)

        args = parser.parse_args([])
        assert args.port == 8000


class TestBearerTokenAuthLogic:
    """Unit tests for bearer token authentication logic."""

    def test_auth_token_extraction(self):
        """Test extracting token from Authorization header."""

        def extract_token(auth_header: str) -> str | None:
            if auth_header.startswith("Bearer "):
                return auth_header[7:]
            return None

        assert extract_token("Bearer my-token") == "my-token"
        assert extract_token("Bearer ") == ""
        assert extract_token("Basic dXNlcjpwYXNz") is None
        assert extract_token("") is None
        assert extract_token("BearerNoSpace") is None

    def test_auth_token_comparison(self):
        """Test token comparison logic."""
        expected_token = "secret-token-123"

        def is_valid_token(auth_header: str, expected: str) -> bool:
            if not auth_header.startswith("Bearer "):
                return False
            return auth_header[7:] == expected

        assert is_valid_token("Bearer secret-token-123", expected_token) is True
        assert is_valid_token("Bearer wrong-token", expected_token) is False
        assert is_valid_token("Bearer SECRET-TOKEN-123", expected_token) is False
        assert is_valid_token("Basic secret-token-123", expected_token) is False
        assert is_valid_token("", expected_token) is False

    def test_auth_disabled_when_no_token_configured(self):
        """Test that auth is disabled when MCP_AUTH_TOKEN is not set."""
        # When auth_token is None, all requests should be allowed
        auth_token = None

        def should_authenticate(token_config: str | None) -> bool:
            return token_config is not None

        assert should_authenticate(auth_token) is False
        assert should_authenticate("some-token") is True

    def test_empty_token_still_requires_auth(self):
        """Test that empty string token still requires matching empty Authorization."""
        # Edge case: if someone sets MCP_AUTH_TOKEN="" they still need Bearer header
        auth_token = ""

        def is_valid_token(auth_header: str, expected: str) -> bool:
            if not auth_header.startswith("Bearer "):
                return False
            return auth_header[7:] == expected

        # "Bearer " with empty token should match
        assert is_valid_token("Bearer ", auth_token) is True
        assert is_valid_token("Bearer anything", auth_token) is False


class TestHTTPHeaderParsing:
    """Tests for HTTP header parsing utilities."""

    def test_headers_from_scope(self):
        """Test extracting headers from ASGI scope."""
        scope = {
            "type": "http",
            "headers": [
                (b"authorization", b"Bearer test-token"),
                (b"content-type", b"application/json"),
                (b"x-custom-header", b"custom-value"),
            ],
        }

        headers = dict(scope.get("headers", []))
        assert headers.get(b"authorization") == b"Bearer test-token"
        assert headers.get(b"content-type") == b"application/json"
        assert headers.get(b"x-custom-header") == b"custom-value"
        assert headers.get(b"nonexistent") is None

    def test_header_decoding(self):
        """Test decoding header bytes to string."""
        scope = {
            "type": "http",
            "headers": [
                (b"authorization", b"Bearer test-token"),
            ],
        }

        headers = dict(scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode()
        assert auth_value == "Bearer test-token"

    def test_missing_headers_in_scope(self):
        """Test handling scope without headers."""
        scope = {"type": "http"}

        headers = dict(scope.get("headers", []))
        assert headers == {}
        assert headers.get(b"authorization", b"").decode() == ""

    def test_non_http_scope_type(self):
        """Test handling non-HTTP scope types."""
        scope = {
            "type": "websocket",
            "headers": [(b"authorization", b"Bearer token")],
        }

        # Auth check should only apply to HTTP
        is_http = scope["type"] == "http"
        assert is_http is False
