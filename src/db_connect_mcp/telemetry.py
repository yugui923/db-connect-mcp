"""Privacy-conscious OpenTelemetry spans for MCP server operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from db_connect_mcp import __version__

_TRACER = trace.get_tracer("db_connect_mcp.mcp", __version__)


@contextmanager
def start_mcp_server_span(
    method: str,
    *,
    target: str | None = None,
    protocol_version: str | None = None,
    resource_uri: str | None = None,
) -> Iterator[Span]:
    """Create an MCP server span without capturing arguments or result data."""
    attributes: dict[str, str] = {"mcp.method.name": method}
    if target is not None:
        attributes["gen_ai.tool.name"] = target
        attributes["gen_ai.operation.name"] = "execute_tool"
    if protocol_version is not None:
        attributes["mcp.protocol.version"] = protocol_version
    if resource_uri is not None:
        attributes["mcp.resource.uri"] = resource_uri

    span_name = f"{method} {target}" if target is not None else method
    with _TRACER.start_as_current_span(
        span_name,
        kind=SpanKind.SERVER,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as exc:
            record_mcp_error(span, type(exc).__qualname__)
            raise


def record_mcp_error(span: Span, error_type: str) -> None:
    """Mark an MCP operation as failed using low-cardinality error metadata."""
    span.set_attribute("error.type", error_type)
    span.set_status(Status(StatusCode.ERROR, error_type))
