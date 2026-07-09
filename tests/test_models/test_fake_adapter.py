"""Tests for FakeAdapter."""

import pytest

from ua.models.base import LLMAdapter, LLMResponse, Message, ToolCall
from ua.models.fake_adapter import FakeAdapter


class TestFakeAdapter:
    """Suite of tests for the deterministic FakeAdapter."""

    @pytest.mark.asyncio
    async def test_echo_behavior_default(self):
        """Default (no-arg) adapter echoes the last user message."""
        adapter = FakeAdapter()
        resp = await adapter.generate([Message(role="user", content="hi")])
        assert resp.content == "echo: hi"
        assert resp.tool_calls == []

    @pytest.mark.asyncio
    async def test_fixed_response_always_returned(self):
        """Fixed response is returned unchanged across multiple calls."""
        expected = LLMResponse(content="fixed", tool_calls=[])
        adapter = FakeAdapter(fixed_response=expected)

        resp1 = await adapter.generate([Message(role="user", content="a")])
        resp2 = await adapter.generate([Message(role="user", content="b")])

        assert resp1 is expected
        assert resp2 is expected

    @pytest.mark.asyncio
    async def test_responses_list_consumed_in_order(self):
        """Scripted responses are consumed one per call in order."""
        r1 = LLMResponse(content="first")
        r2 = LLMResponse(content="second")
        adapter = FakeAdapter(responses=[r1, r2])

        resp1 = await adapter.generate([Message(role="user", content="x")])
        resp2 = await adapter.generate([Message(role="user", content="y")])

        assert resp1 is r1
        assert resp2 is r2

    @pytest.mark.asyncio
    async def test_responses_list_exhausted_raises(self):
        """Accessing beyond the scripted list raises RuntimeError."""
        adapter = FakeAdapter(responses=[LLMResponse(content="only")])
        await adapter.generate([Message(role="user", content="x")])
        with pytest.raises(RuntimeError, match="exhausted"):
            await adapter.generate([Message(role="user", content="y")])

    def test_llm_adapter_cannot_be_instantiated_directly(self):
        """LLMAdapter is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            LLMAdapter()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_tool_call_round_trip(self):
        """Tool calls survive a round-trip through fixed_response."""
        tool_calls = [
            ToolCall(id="call_1", name="get_weather", arguments={"city": "London"}),
        ]
        expected = LLMResponse(content="", tool_calls=tool_calls)
        adapter = FakeAdapter(fixed_response=expected)

        resp = await adapter.generate([Message(role="user", content="weather?")])

        assert resp.content == ""
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].id == "call_1"
        assert resp.tool_calls[0].name == "get_weather"
        assert resp.tool_calls[0].arguments == {"city": "London"}
