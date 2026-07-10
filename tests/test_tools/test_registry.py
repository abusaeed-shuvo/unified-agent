"""Tests for ToolRegistry auto-discovery and execution."""

from __future__ import annotations

import logging
import pkgutil
import sys
import types
from pathlib import Path

import pytest

from ua.tools.base import Tool, ToolResult
from ua.tools.calculator import CalculatorTool
from ua.tools.filesystem import FilesystemTool
from ua.tools.registry import ToolNotFoundError, ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry() -> ToolRegistry:
    """Create a fresh registry and run discovery."""
    reg = ToolRegistry()
    reg.discover()
    return reg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_discover_registers_calculator_tool():
    """CalculatorTool is registered and findable by name."""
    reg = _make_registry()

    assert "calculator" in reg._tools
    assert isinstance(reg._tools["calculator"], CalculatorTool)
    assert reg.get("calculator") is reg._tools["calculator"]


def test_discover_skips_filesystem_tool_gracefully_with_warning(caplog):
    """FilesystemTool is skipped without crashing; a warning is logged."""
    caplog.set_level(logging.WARNING, logger="ua.tools.registry")

    reg = ToolRegistry()
    reg.discover()

    # FilesystemTool must NOT be registered.
    assert "filesystem" not in reg._tools

    # A warning must have been emitted mentioning FilesystemTool.
    warning_messages = [rec.getMessage() for rec in caplog.records if rec.levelname == "WARNING"]
    assert any("FilesystemTool" in msg or "filesystem" in msg for msg in warning_messages), (
        "Expected a WARNING about FilesystemTool being skipped, but got: "
        + repr(warning_messages)
    )


@pytest.mark.asyncio
async def test_execute_calculator_tool_success():
    """execute() delegates to CalculatorTool.run() and returns the correct result."""
    reg = _make_registry()

    result = await reg.execute("calculator", expression="6 * 7")

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.error is None
    assert result.output == "42"


def test_get_unknown_tool_raises_tool_not_found_error():
    """get() raises ToolNotFoundError for an unregistered tool name."""
    reg = _make_registry()

    with pytest.raises(ToolNotFoundError) as exc_info:
        reg.get("nonexistent_tool")

    assert "nonexistent_tool" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_unknown_tool_raises_tool_not_found_error():
    """execute() raises ToolNotFoundError for an unregistered tool name."""
    reg = _make_registry()

    with pytest.raises(ToolNotFoundError) as exc_info:
        await reg.execute("nonexistent_tool")

    assert "nonexistent_tool" in str(exc_info.value)


def test_all_schemas_returns_expected_shape():
    """all_schemas() returns a list of OpenAI-compatible function schemas."""
    reg = _make_registry()
    schemas = reg.all_schemas()

    # Must be a non-empty list.
    assert isinstance(schemas, list)
    assert len(schemas) >= 1

    # Every entry must match the OpenAI function-tool shape.
    for schema in schemas:
        assert isinstance(schema, dict)
        assert schema.get("type") == "function"
        assert "function" in schema
        fn = schema["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn

    # The calculator schema must be present with the correct name.
    calc_schema = next((s for s in schemas if s["function"]["name"] == "calculator"), None)
    assert calc_schema is not None
    assert calc_schema["function"]["description"] == CalculatorTool.description
    assert calc_schema["function"]["parameters"] == CalculatorTool.parameters


def test_discover_called_twice_is_idempotent_not_erroring(caplog):
    """Calling discover() twice does not duplicate-register or crash."""
    caplog.set_level(logging.DEBUG, logger="ua.tools.registry")

    reg = ToolRegistry()
    reg.discover()
    reg.discover()  # second call

    # Only one calculator entry.
    assert list(reg._tools.keys()).count("calculator") == 1

    # The second discovery should log a debug message about idempotency.
    debug_messages = [rec.getMessage() for rec in caplog.records if rec.levelname == "DEBUG"]
    assert any("already registered" in msg for msg in debug_messages), (
        "Expected a DEBUG message about idempotent re-registration, but got: "
        + repr(debug_messages)
    )


# ---------------------------------------------------------------------------
# Edge-case: name collision between two different Tool classes.
# ---------------------------------------------------------------------------


def test_discover_raises_on_name_collision_between_different_classes():
    """If two different Tool subclasses share the same name, discover() raises."""

    # Create two distinct classes that both claim the name "collision_tool".
    class ToolA(Tool):
        name = "collision_tool"
        description = "First"
        parameters = {}
        enabled = True

        async def run(self, **kwargs):
            return ToolResult(success=True, output="a")

    class ToolB(Tool):
        name = "collision_tool"
        description = "Second"
        parameters = {}
        enabled = True

        async def run(self, **kwargs):
            return ToolResult(success=True, output="b")

    # Inject both classes into a fake module so discover() can find them.
    fake_module = types.ModuleType("ua.tools._fake_collision")
    fake_module.ToolA = ToolA
    fake_module.ToolB = ToolB
    sys.modules["ua.tools._fake_collision"] = fake_module

    original_iter = None
    try:
        reg = ToolRegistry()

        # Patch pkgutil.iter_modules to also yield our fake module.
        original_iter = pkgutil.iter_modules

        def _patched_iter(path):
            for item in original_iter(path):
                yield item
            if Path(path[0]).name == "tools":
                yield (None, "_fake_collision", False)

        pkgutil.iter_modules = _patched_iter
        reg.discover()

        # If we get here without raising, the collision was not detected —
        # but the test expects a ValueError.
        pytest.fail("Expected ValueError due to name collision, but none was raised.")
    except ValueError as exc:
        assert "collision_tool" in str(exc)
        assert "ToolA" in str(exc) or "ToolB" in str(exc)
    finally:
        # Cleanup: remove fake module and restore pkgutil.iter_modules.
        sys.modules.pop("ua.tools._fake_collision", None)
        if original_iter is not None:
            pkgutil.iter_modules = original_iter


# ---------------------------------------------------------------------------
# Edge-case: register_instance escape hatch.
# ---------------------------------------------------------------------------


def test_register_instance_adds_filesystem_tool(tmp_path):
    """register_instance() can add a FilesystemTool that discover() skipped."""
    reg = _make_registry()

    # FilesystemTool should not be in the registry after auto-discovery.
    assert "filesystem" not in reg._tools

    # Manually register one with a sandbox root.
    fs_tool = FilesystemTool(sandbox_root=tmp_path)
    reg.register_instance(fs_tool)

    assert "filesystem" in reg._tools
    assert reg.get("filesystem") is fs_tool


def test_register_instance_raises_on_name_collision():
    """register_instance() raises ValueError if the name is already taken by a different class."""
    reg = _make_registry()
    # calculator is already registered as CalculatorTool.
    # Registering a DIFFERENT class with the same name should raise.
    class OtherCalculator(Tool):
        name = "calculator"
        description = "Other"
        parameters = {}
        enabled = True

        async def run(self, **kwargs):
            return ToolResult(success=True, output="other")

    with pytest.raises(ValueError) as exc_info:
        reg.register_instance(OtherCalculator())

    assert "collision" in str(exc_info.value).lower()
