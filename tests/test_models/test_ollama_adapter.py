"""Tests for OllamaAdapter."""

from __future__ import annotations

import json

import httpx
import pytest

from ua.models.base import LLMAdapterError, LLMResponse, Message, ToolCall
from ua.models.ollama_adapter import OllamaAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(handler):
    """Build an AsyncClient backed by MockTransport with the given handler."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _success_handler_no_tools(request: httpx.Request) -> httpx.Response:
    """Return a plain-text completion response (no tool calls)."""
    payload = {
        "model": "test-model",
        "created_at": "2023-12-12T14:13:43.416799Z",
        "message": {
            "role": "assistant",
            "content": "Hello! How can I help you today?",
        },
        "done": True,
        "total_duration": 5191566416,
        "load_duration": 2154458,
        "prompt_eval_count": 26,
        "prompt_eval_duration": 383809000,
        "eval_count": 298,
        "eval_duration": 4799921000,
    }
    return httpx.Response(200, json=payload)


def _success_handler_with_tools(request: httpx.Request) -> httpx.Response:
    """Return a response that includes tool_calls (arguments as a dict)."""
    payload = {
        "model": "test-model",
        "created_at": "2025-07-07T20:32:53.844124Z",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "Tokyo", "format": "celsius"},
                    }
                }
            ],
        },
        "done_reason": "stop",
        "done": True,
        "total_duration": 3244883583,
        "load_duration": 2969184542,
        "prompt_eval_count": 169,
        "prompt_eval_duration": 141656333,
        "eval_count": 18,
        "eval_duration": 133293625,
    }
    return httpx.Response(200, json=payload)


def _connect_error_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Connection refused")


def _server_error_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text="Internal Server Error")


def _malformed_handler(request: httpx.Request) -> httpx.Response:
    # Missing the top-level "message" key that Ollama always returns.
    return httpx.Response(200, json={"done": True, "error": "missing message key"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_success_plain_text():
    """Plain-text response is parsed correctly from the top-level 'message'."""
    client = _make_client(_success_handler_no_tools)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    response = await adapter.generate(messages)

    assert isinstance(response, LLMResponse)
    assert response.content == "Hello! How can I help you today?"
    assert response.tool_calls == []
    assert response.raw is not None
    assert response.raw["message"]["content"] == "Hello! How can I help you today?"


@pytest.mark.asyncio
async def test_generate_success_with_tool_calls():
    """Response with tool_calls is parsed into ToolCall objects.

    Ollama returns arguments as an already-parsed dict (not a JSON string),
    and provides no 'id' on the tool call — we synthesise one.
    """
    client = _make_client(_success_handler_with_tools)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434",
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
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "Tokyo", "format": "celsius"}
    # Ollama provides no id; we synthesise a uuid4 string.
    assert isinstance(tc.id, str) and len(tc.id) > 0


@pytest.mark.asyncio
async def test_generate_connection_error_raises_llm_adapter_error():
    """ConnectError is normalised to LLMAdapterError."""
    client = _make_client(_connect_error_handler)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "Could not connect to Ollama" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


@pytest.mark.asyncio
async def test_generate_non_2xx_status_raises_llm_adapter_error():
    """Non-2xx HTTP status is normalised to LLMAdapterError."""
    client = _make_client(_server_error_handler)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434",
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
    """Response missing the 'message' key raises LLMAdapterError, not KeyError."""
    client = _make_client(_malformed_handler)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    with pytest.raises(LLMAdapterError) as exc_info:
        await adapter.generate(messages)

    assert "Unexpected response shape" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


@pytest.mark.asyncio
async def test_request_payload_matches_ollama_shape():
    """The request sent to /api/chat matches Ollama's documented shape."""
    captured: dict = {}

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _success_handler_no_tools(request)

    client = _make_client(capturing_handler)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434",
        model="test-model",
        client=client,
    )

    messages = [Message(role="user", content="Hi")]
    await adapter.generate(messages)

    # URL path must be /api/chat (not /chat/completions)
    assert captured["url"].endswith("/api/chat")

    body = captured["body"]
    # Required Ollama fields
    assert body["model"] == "test-model"
    assert body["messages"] == [{"role": "user", "content": "Hi"}]
    assert body["stream"] is False
    # Ollama does NOT use the OpenAI "tools" key when no tools are passed
    assert "tools" not in body
    # Ollama does NOT nest under "choices"
    assert "choices" not in body


@pytest.mark.asyncio
async def test_request_payload_includes_tools_when_provided():
    """The 'tools' key IS present in the payload when tools are supplied."""
    captured: dict = {}

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _success_handler_no_tools(request)

    client = _make_client(capturing_handler)
    adapter = OllamaAdapter(
        base_url="http://localhost:11434",
        model="test-model",
        client=client,
    )

    tools = [{"type": "function", "function": {"name": "foo", "parameters": {}}}]
    messages = [Message(role="user", content="Hi")]
    await adapter.generate(messages, tools=tools)

    assert captured["body"]["tools"] == tools


@pytest.mark.asyncio
async def test_serialise_message_tool_role_uses_tool_name():
    """tool-role messages serialise with 'tool_name' (Ollama's field)."""
    adapter = OllamaAdapter(
        base_url="http://localhost:11434",
        model="test-model",
    )

    msg = Message(role="tool", content="22C", tool_call_id="get_weather")
    assert adapter._serialise_message(msg) == {
        "role": "tool",
        "content": "22C",
        "tool_name": "get_weather",
    }

    # Non-tool messages should not get a tool_name key.
    user_msg = Message(role="user", content="Hi")
    assert adapter._serialise_message(user_msg) == {
        "role": "user",
        "content": "Hi",
    }
