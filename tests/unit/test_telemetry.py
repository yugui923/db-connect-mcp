"""Tests for privacy-conscious MCP OpenTelemetry spans."""

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.trace import SpanKind, StatusCode

from db_connect_mcp.telemetry import record_mcp_error, start_mcp_server_span


def _mock_tracer() -> tuple[MagicMock, MagicMock]:
    tracer = MagicMock()
    span = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = span
    tracer.start_as_current_span.return_value = context
    return tracer, span


def test_tool_span_uses_mcp_and_gen_ai_attributes() -> None:
    tracer, _ = _mock_tracer()

    with patch("db_connect_mcp.telemetry._TRACER", tracer):
        with start_mcp_server_span(
            "tools/call",
            target="execute_query",
            protocol_version="2026-07-28",
        ):
            pass

    tracer.start_as_current_span.assert_called_once_with(
        "tools/call execute_query",
        kind=SpanKind.SERVER,
        attributes={
            "mcp.method.name": "tools/call",
            "gen_ai.tool.name": "execute_query",
            "gen_ai.operation.name": "execute_tool",
            "mcp.protocol.version": "2026-07-28",
        },
        record_exception=False,
        set_status_on_exception=False,
    )


def test_resource_span_records_uri_without_using_it_in_name() -> None:
    tracer, _ = _mock_tracer()

    with patch("db_connect_mcp.telemetry._TRACER", tracer):
        with start_mcp_server_span(
            "resources/read",
            resource_uri="db-connect://table/public/products",
        ):
            pass

    call = tracer.start_as_current_span.call_args
    assert call.args == ("resources/read",)
    assert call.kwargs["attributes"]["mcp.resource.uri"] == (
        "db-connect://table/public/products"
    )


def test_exception_marks_span_without_recording_exception_payload() -> None:
    tracer, span = _mock_tracer()

    with patch("db_connect_mcp.telemetry._TRACER", tracer):
        with pytest.raises(RuntimeError, match="sensitive details"):
            with start_mcp_server_span("resources/list"):
                raise RuntimeError("sensitive details")

    span.set_attribute.assert_called_once_with("error.type", "RuntimeError")
    status = span.set_status.call_args.args[0]
    assert status.status_code == StatusCode.ERROR
    assert status.description == "RuntimeError"
    span.record_exception.assert_not_called()


def test_tool_error_uses_low_cardinality_type() -> None:
    span = MagicMock()

    record_mcp_error(span, "tool_error")

    span.set_attribute.assert_called_once_with("error.type", "tool_error")
    status = span.set_status.call_args.args[0]
    assert status.status_code == StatusCode.ERROR
    assert status.description == "tool_error"
