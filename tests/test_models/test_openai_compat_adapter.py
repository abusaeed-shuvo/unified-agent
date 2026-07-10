"""Tests for OpenAICompatAdapter."""

from __future__ import annotations

import json

import httpx
import pytest

from ua.models.base import LLMAdapterError, LLMResponse, Message, ToolCall
from ua.models.openai_compat_adapter import OpenAICompatAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(handler):
    """Build an AsyncClient backed by MockTransport with the given handler."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _success_handler_no_tools(request: httpx.Request) -> httpx.Response:
    """Return a plain-text completion response (no tool calls)."""
    payload = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! How can I help you today?",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
        },
    }
    return httpx.Response(200, json=payload)


def _success_handler_with_tools(request: httpx.Request) -> httpx.Response:
    """Return a response that includes tool_calls."""
    payload = {
        "id": "chatcmpl-456",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": json.dumps({
                                    "location": "San Francisco, CA",
                                    "unit": "celsius",
                                }),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 15,
            "total_tokens": 35,
        },
    }
    return httpx.Response(200, json=payload)


def _connect_error_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Connection refused")


def _server_error_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text="Internal Server Error")


def _malformed_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"error": "missing choices key"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_success_plain_text():
    """Plain-text response is parsed correctly."""
    client = _make_client(_success_handler_no_tools)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    response = await adapter.generate(messages)

    assert isinstance(response, LLMResponse)
    assert response.content == "Hello! How can I help you today?"
    assert response.tool_calls == []
    assert response.raw is not None
    assert response.raw["choices"][0]["message"]["content"] == "Hello! How can I help you today?"


@pytest.mark.asyncio
async def test_generate_success_with_tool_calls():
    """Response with tool_calls is parsed into ToolCall objects."""
    client = _make_client(_success_handler_with_tools)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="What's the weather?")]
    response = await adapter.generate(messages)

    assert isinstance(response, LLMResponse)
    assert response.content == ""
    assert len(response.tool_calls) == 1

    tc = response.tool_calls[0]
    assert isinstance(tc, ToolCall)
    assert tc.id == "call_abc123"
    assert tc.name == "get_weather"
    assert tc.arguments == {
        "location": "San Francisco, CA",
        "unit": "celsius",
    }


@pytest.mark.asyncio
async def test_generate_connection_error_raises_llm_adapter_error():
    """ConnectError is normalised to LLMAdapterError."""
    client = _make_client(_connect_error_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "Could not connect to OpenAI-compatible endpoint" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


@pytest.mark.asyncio
async def test_generate_non_2xx_status_raises_llm_adapter_error():
    """Non-2xx HTTP status is normalised to LLMAdapterError."""
    client = _make_client(_server_error_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "HTTP 500" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


@pytest.mark.asyncio
async def test_generate_malformed_response_raises_llm_adapter_error():
    """Response missing 'choices' key raises LLMAdapterError, not KeyError."""
    client = _make_client(_malformed_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "Unexpected response shape" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


@pytest.mark.asyncio
async def test_no_auth_header_when_api_key_not_set():
    """No Authorization header is sent when api_key is None."""
    captured: dict = {}

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return _success_handler_no_tools(request)

    client = _make_client(capturing_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    await adapter.generate(messages)

    assert "Authorization" not in captured["headers"], (
        "Authorization header should not be present when api_key is not set"
    )


@pytest.mark.asyncio
async def test_auth_header_included_when_api_key_set():
    """Authorization header is sent with Bearer token when api_key is set."""
    captured: dict = {}

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        # httpx normalizes headers to lowercase
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return _success_handler_no_tools(request)

    client = _make_client(capturing_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        api_key="sk-test123",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    await adapter.generate(messages)

    assert "authorization" in captured["headers"], (
        "Authorization header should be present when api_key is set"
    )
    assert captured["headers"]["authorization"] == "Bearer sk-test123"


@pytest.mark.asyncio
async def test_generate_timeout_raises_llm_adapter_error():
    """TimeoutException is normalised to LLMAdapterError."""

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Request timed out")

    client = _make_client(timeout_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "timed out" in str(exc_info.value).lower()
    assert exc_info.value.__cause__ is not None


@pytest.mark.asyncio
async def test_generate_invalid_json_raises_llm_adapter_error():
    """Non-JSON response body raises LLMAdapterError."""

    def invalid_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    client = _make_client(invalid_json_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "invalid json" in str(exc_info.value).lower()
    assert exc_info.value.__cause__ is not None


@pytest.mark.asyncio
async def test_generate_malformed_tool_call_raises_llm_adapter_error():
    """A tool_call missing required fields raises LLMAdapterError."""

    def bad_tool_call_handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "id": "chatcmpl-789",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                # Missing 'id' and 'function' keys
                                "type": "function",
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        return httpx.Response(200, json=payload)

    client = _make_client(bad_tool_call_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "Malformed tool_call" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


@pytest.mark.asyncio
async def test_generate_tool_call_arguments_invalid_json_raises_llm_adapter_error():
    """tool_call arguments that are not valid JSON raise LLMAdapterError."""

    def invalid_args_handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "id": "chatcmpl-999",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "type": "function",
                                "function": {
                                    "name": "foo",
                                    "arguments": "not valid json {{{",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        return httpx.Response(200, json=payload)

    client = _make_client(invalid_args_handler)
    adapter = OpenAICompatAdapter(
        base_url="http://localhost:1234",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "Malformed tool_call" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
