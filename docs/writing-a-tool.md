# Writing a Tool

A tool is an action the LLM can invoke. This guide shows you how to add one.

## The Tool Contract

Every tool extends `ua/tools/base.py::Tool`:

```python
from ua.tools.base import Tool, ToolResult

class MyTool(Tool):
    name: ClassVar[str]           # Unique identifier
    description: ClassVar[str]    # Sent to LLM for tool-calling
    parameters: ClassVar[dict]    # JSON Schema for arguments

    async def run(self, **kwargs) -> ToolResult: ...
```

- `name`: Must be unique across all registered tools
- `description`: Clear and concise — this is read by the LLM
- `parameters`: JSON Schema dict (OpenAI-compatible format)
- `run()`: Executes the tool logic and returns `ToolResult(success, output, error)`

See `ua/tools/calculator.py` for a simple example with no constructor args.

## Canonical Example

The reference implementation is `examples/custom_tool_example.py`:

```python
class ReverseStringTool(Tool):
    name = "reverse_string"
    description = "Reverses the provided text string"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to reverse"}
        },
        "required": ["text"],
    }

    async def run(self, text: str) -> ToolResult:
        reversed_text = text[::-1]
        return ToolResult(success=True, output=f"Reversed: {reversed_text}")
```

This file demonstrates:
1. Tool definition as a subclass
2. Manual registration via `registry.register_instance()`
3. Usage in a chat session

## Auto-Discovery vs. register_instance()

**Auto-discovery** (the default): `ToolRegistry.discover()` scans `ua/tools/` for `Tool` subclasses and instantiates them with `cls()`. This works for tools like `CalculatorTool` that have no required constructor arguments.

**register_instance()** (when you need constructor args): Some tools require configuration at instantiation, like `FilesystemTool(sandbox_root=...)`. Auto-discovery will skip these with a warning because `cls()` fails with `TypeError`. Use `register_instance()` to register a pre-constructed instance:

```python
# ua/tools/registry.py lines 100-115 explains why
try:
    instance = cls()
except TypeError as exc:
    logger.warning(
        "Skipping tool %r ... cannot be instantiated without "
        "constructor arguments. Use registry.register_instance() ...", ...
    )
    continue
```

The `FilesystemTool` (lines 39-47 in `ua/tools/filesystem.py`) is the canonical example:

```python
def __init__(self, sandbox_root: Path):
    self.sandbox_root = sandbox_root
```

It must be registered manually because the sandbox root is required.

## Registration Flow

For tools in `ua/tools/`:
1. Add your `.py` file with the `Tool` subclass
2. Set `enabled = True` (or omit, defaults to `True`)
3. `ToolRegistry.discover()` will find and register it automatically

For tools outside the core package (like in `examples/`):
1. Instantiate your tool: `custom_tool = ReverseStringTool()`
2. Register it: `tool_registry.register_instance(custom_tool)`

See `examples/custom_tool_example.py` lines 133-138 for the full pattern.

## Plugin Rules

Refer to Contributing.md §5 for complete plugin conventions:
- Side-effect safety requirements
- Testing expectations (test file, success/failure cases)
- Documentation standards