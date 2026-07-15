"""Auto-discovering tool registry for Unified Agent.

Scans ``ua.tools`` for enabled :class:`~ua.tools.base.Tool` subclasses and
registers them so they can be listed or executed by name.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import time
from pathlib import Path

from ua.config.logging import get_logger
from ua.tools.base import Tool, ToolResult

logger = get_logger(__name__)


class ToolNotFoundError(Exception):
    """Raised when execute()/get() is called with an unknown tool name."""

    pass


class ToolRegistry:
    """Registry that auto-discovers and manages Tool implementations.

    Tools are discovered by scanning the ``ua.tools`` package for modules,
    importing each, and collecting every :class:`~ua.tools.base.Tool` subclass
    whose ``enabled`` class attribute is ``True``.

    Tools that require constructor arguments (e.g. ``FilesystemTool``) are
    skipped with a warning rather than crashing discovery.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def discover(self, package: str = "ua.tools") -> None:
        """Scan *package* for enabled Tool subclasses and register them.

        Parameters
        ----------
        package:
            Dotted package path to scan (default ``"ua.tools"``).
        """
        # Resolve the on-disk path for the package so pkgutil can iterate it.
        # __import__(package) returns the *top-level* package, so we must walk
        # down the dotted path to reach the actual subpackage directory.
        package_parts = package.split(".")
        mod = __import__(package)
        for part in package_parts[1:]:
            mod = getattr(mod, part)
        package_path = Path(mod.__file__).parent

        # Collect module names in the package directory, excluding internals.
        skip_modules = {"base", "registry", "__init__"}

        for _finder, modname, _is_pkg in pkgutil.iter_modules([str(package_path)]):
            if modname in skip_modules:
                continue

            full_module_name = f"{package}.{modname}"

            try:
                module = importlib.import_module(full_module_name)
            except ImportError as exc:
                logger.warning("Failed to import tool module %s: %s", full_module_name, exc)
                continue

            # Find every Tool subclass defined in this module.
            for _name, cls in inspect.getmembers(module, inspect.isclass):
                if not issubclass(cls, Tool) or cls is Tool:
                    continue

                if not getattr(cls, "enabled", True):
                    continue

                tool_name: str = cls.name

                # Guard against double-registration.
                if tool_name in self._tools:
                    existing_cls = type(self._tools[tool_name])
                    if existing_cls is cls:
                        # Same class discovered twice (e.g. re-export) — harmless.
                        logger.debug(
                            "Tool %r already registered (idempotent discovery); skipping.",
                            tool_name,
                        )
                    else:
                        raise ValueError(
                            f"Tool name collision: '{tool_name}' is claimed by both "
                            f"{existing_cls.__module__}.{existing_cls.__qualname__} "
                            f"and {cls.__module__}.{cls.__qualname__}."
                        )
                    continue

                # Attempt instantiation.  Tools that need constructor args
                # (e.g. FilesystemTool(sandbox_root=...)) will raise TypeError;
                # skip them with a clear warning rather than crashing.
                try:
                    instance = cls()
                except TypeError as exc:
                    logger.warning(
                        "Skipping tool %r (%s): cannot be instantiated without "
                        "constructor arguments. %s. "
                        "Use registry.register_instance() to add it manually once "
                        "the required arguments are available.",
                        tool_name,
                        cls.__module__ + "." + cls.__qualname__,
                        exc,
                    )
                    continue

                self._tools[tool_name] = instance
                logger.debug("Registered tool: %s", tool_name)

    def register_instance(self, tool: Tool) -> None:
        """Manually register a pre-constructed tool instance.

        Useful for tools that require constructor arguments (e.g.
        :class:`~ua.tools.filesystem.FilesystemTool`) which cannot be
        auto-discovered.
        """
        tool_name = tool.name
        if tool_name in self._tools:
            existing_cls = type(self._tools[tool_name])
            if existing_cls is type(tool):
                logger.debug("Tool %r already registered; register_instance is a no-op.", tool_name)
                return
            raise ValueError(
                f"Tool name collision: '{tool_name}' is already registered as "
                f"{existing_cls.__module__}.{existing_cls.__qualname__}."
            )
        self._tools[tool_name] = tool
        logger.debug("Registered tool via register_instance: %s", tool_name)

    def get(self, name: str) -> Tool:
        """Return the registered :class:`~ua.tools.base.Tool` instance by name.

        Raises
        ------
        ToolNotFoundError
            If no tool with *name* has been registered.
        """
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFoundError(f"No tool named '{name}' is registered.") from None

    def all_schemas(self) -> list[dict]:
        """Return OpenAI-compatible tool schema list for every registered tool.

        Each entry has the shape::

            {
                "type": "function",
                "function": {
                    "name": "<tool.name>",
                    "description": "<tool.description>",
                    "parameters": <tool.parameters>,
                }
            }

        This matches the ``tools`` parameter accepted by
        :class:`~ua.models.lmstudio_adapter.LMStudioAdapter`,
        :class:`~ua.models.ollama_adapter.OllamaAdapter`, and
        :class:`~ua.models.openai_compat_adapter.OpenAICompatAdapter`.
        """
        schemas: list[dict] = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return schemas

    async def execute(self, name: str, user_id: str | None = None, **kwargs) -> ToolResult:
        """Look up the tool by *name* and await its ``run(**kwargs)``.

        Args:
            name: The tool name to execute.
            user_id: Optional trusted user identifier. If the tool has
                     requires_user_context=True, this value is injected into kwargs
                     as "_user_id" after stripping any LLM-supplied value.
            **kwargs: Arguments to pass to the tool's run() method.

        Raises
        ------
        ToolNotFoundError
            If no tool with *name* has been registered.
        """
        tool = self.get(name)

        # SECURITY: Strip any LLM-supplied _user_id before we possibly inject
        # the trusted value. This prevents the LLM from spoofing another user's
        # sandbox/backend preferences.
        kwargs.pop("_user_id", None)

        # If the tool requires user context, inject the trusted user_id
        if getattr(tool, "requires_user_context", False):
            kwargs["_user_id"] = user_id

        start = time.monotonic()
        try:
            result = await tool.run(**kwargs)
        except Exception:
            # Log duration even on failure, then re-raise.
            duration_ms = (time.monotonic() - start) * 1000
            logger.info(
                f"tool '{name}' executed in {duration_ms:.1f}ms, success=False"
            )
            raise
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            f"tool '{name}' executed in {duration_ms:.1f}ms, "
            f"success={result.success}"
        )
        return result
