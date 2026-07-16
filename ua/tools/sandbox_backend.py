"""Sandbox backend selection tool for listing and switching backends."""

from __future__ import annotations

import asyncio

from ua.sandbox.registry import SandboxBackendRegistry
from ua.tools.base import Tool, ToolResult


class SandboxBackendTool(Tool):
    """List available sandbox backends and switch the active one for a user.

    This tool allows users to:
    - List all registered sandbox execution backends with their availability status
    - Switch their active backend preference to a different registered backend

    The tool requires user context (requires_user_context=True) so that backend
    preferences are tied to the trusted user_id, preventing LLM spoofing.
    """

    name = "sandbox_backend"
    requires_user_context = True
    description = (
        "List available sandbox execution backends (e.g. ssh, docker) and which one "
        "is currently active, or switch the active backend for this user. "
        "Use action='list' to see options, action='switch' with backend_name to change."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "switch"],
                "description": "The action to perform: 'list' to show backends, 'switch' to change active backend.",
            },
            "backend_name": {
                "type": "string",
                "description": "Required when action='switch'. Must be one of the registered backend names.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, backend_registry: SandboxBackendRegistry) -> None:
        """Initialize the sandbox backend tool.

        Args:
            backend_registry: A SandboxBackendRegistry instance for backend resolution.
        """
        self._backend_registry = backend_registry

    async def run(
        self,
        action: str,
        backend_name: str | None = None,
        _user_id: str | None = None,
    ) -> ToolResult:
        """Execute the tool action.

        Args:
            action: Either "list" to show backends or "switch" to change active backend.
            backend_name: Required when action='switch'. The backend name to switch to.
            _user_id: Internal parameter for trusted user_id (injected by registry).

        Returns:
            ToolResult with backend information (for list) or switch confirmation.
        """
        if action == "list":
            return await self._list_backends(_user_id or "default")
        elif action == "switch":
            if not backend_name:
                return ToolResult(
                    success=False,
                    output="",
                    error="backend_name is required when action='switch'",
                )
            return await self._switch_backend(_user_id or "default", backend_name)
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown action '{action}'. Use 'list' or 'switch'.",
            )

    async def _list_backends(self, user_id: str) -> ToolResult:
        """List all registered backends with availability status.

        Checks availability on all backends concurrently using asyncio.gather.

        Args:
            user_id: The user identifier for looking up stored preference.

        Returns:
            ToolResult with formatted backend information.
        """
        # Get the user's stored preference (without triggering fallback logic)
        stored_preference = await self._backend_registry.get_stored_preference(user_id)

        # Get all registered backend names
        backend_names = self._backend_registry.registered_backends()

        # Check availability on all backends concurrently
        async def check_availability(name: str) -> tuple[str, bool]:
            backend = self._backend_registry._backends.get(name)
            if backend:
                available = await backend.is_available()
                return (name, available)
            return (name, False)

        # Run all availability checks concurrently
        availability_results = await asyncio.gather(
            *[check_availability(name) for name in backend_names]
        )

        # Build the response
        lines = ["Available sandbox backends:"]
        for name, available in availability_results:
            status = "online" if available else "offline"
            active_marker = " (active)" if name == stored_preference else ""
            lines.append(f"  - {name}: {status}{active_marker}")

        return ToolResult(success=True, output="\n".join(lines))

    async def _switch_backend(self, user_id: str, backend_name: str) -> ToolResult:
        """Switch the user's active backend preference.

        Args:
            user_id: The user identifier.
            backend_name: The backend name to switch to.

        Returns:
            ToolResult with switch confirmation or error.
        """
        try:
            await self._backend_registry.set_active_backend(user_id, backend_name)
        except ValueError as e:
            # Return error with list of valid options
            valid_options = self._backend_registry.registered_backends()
            return ToolResult(
                success=False,
                output="",
                error=f"{e}. Valid options: {valid_options}",
            )

        # Check if the newly selected backend is currently available
        backend = self._backend_registry._backends.get(backend_name)
        is_available = False
        if backend:
            is_available = await backend.is_available()

        if is_available:
            return ToolResult(
                success=True,
                output=f"Switched active sandbox backend to '{backend_name}' (online).",
            )
        else:
            return ToolResult(
                success=True,
                output=f"Switched active sandbox backend to '{backend_name}' (offline). "
                       f"Note: The backend is currently unavailable, but your preference "
                       f"has been saved and will be used when it comes online.",
            )