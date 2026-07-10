"""Tests for Tool ABC and ToolResult."""

import asyncio

import pytest

from ua.tools.base import Tool, ToolResult


def test_tool_cannot_be_instantiated_directly():
    """Tool ABC cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Tool()


def test_subclass_without_run_cannot_be_instantiated():
    """A subclass that does not implement run() cannot be instantiated."""

    class IncompleteTool(Tool):
        name = "incomplete"
        description = "Missing run method"
        parameters = {"type": "object", "properties": {}}

    with pytest.raises(TypeError):
        IncompleteTool()


def test_minimal_concrete_subclass_works():
    """A minimal concrete subclass that implements run() can be instantiated and run() awaited."""

    class DummyTool(Tool):
        name = "dummy"
        description = "A dummy tool for testing"
        parameters = {"type": "object", "properties": {}}

        async def run(self, **kwargs) -> ToolResult:
            return ToolResult(success=True, output="dummy ran")

    tool = DummyTool()
    result = asyncio.run(tool.run())

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.output == "dummy ran"
    assert result.error is None


def test_tool_result_defaults_error_to_none():
    """ToolResult can be constructed with just success and output (error defaults to None)."""
    result = ToolResult(success=True, output="test output")

    assert result.success is True
    assert result.output == "test output"
    assert result.error is None


def test_tool_enabled_defaults_to_true():
    """Tool's enabled class attribute defaults to True."""

    class DummyTool(Tool):
        name = "dummy"
        description = "A dummy tool for testing"
        parameters = {"type": "object", "properties": {}}

        async def run(self, **kwargs) -> ToolResult:
            return ToolResult(success=True, output="dummy ran")

    tool = DummyTool()
    assert tool.enabled is True
