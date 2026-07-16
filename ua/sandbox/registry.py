"""SandboxBackendRegistry for per-user backend selection with fallback.

This module provides SandboxBackendRegistry which holds all available SandboxManager
backends, resolves which one a given user is actively using (persisted per user_id),
and falls back automatically if the selected backend becomes unavailable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ua.memory.manager import MemoryManager
    from ua.sandbox.base import SandboxManager


class SandboxUnavailableError(Exception):
    """Raised when no sandbox backend in the fallback order is available."""

    pass


class SandboxBackendRegistry:
    """Registry that holds all available SandboxManager backends.

    Manages:
    - Per-user backend preference persistence via MemoryManager
    - Automatic fallback when the preferred backend is unavailable
    - Safe backend resolution that can't be spoofed by LLM-supplied arguments
    """

    def __init__(
        self,
        backends: dict[str, SandboxManager],
        memory: MemoryManager,
        settings,  # Avoid circular import - type is Settings
    ) -> None:
        """Initialize the registry with backend managers and dependencies.

        Args:
            backends: Dict mapping backend_name to SandboxManager instance.
                       Expected keys: "ssh", "docker" (or any future backends).
            memory: MemoryManager for persisting/retrieving per-user preferences.
            settings: Settings object for default_backend and fallback_order config.
        """
        self._backends = backends
        self._memory = memory
        self._settings = settings

    async def resolve(self, user_id: str) -> SandboxManager:
        """Return the SandboxManager this user should use right now.

        Resolution order:
        1. Look up the user's stored preference via memory.get_fact(user_id, "active_sandbox_backend").
           If none stored, use settings.sandbox_default_backend.
        2. Check is_available() on that backend. If available, return it.
        3. If NOT available, walk settings.sandbox_fallback_order (skipping the one
           that just failed) and return the first one whose is_available() is True.
        4. If NONE are available, raise SandboxUnavailableError.

        Does NOT persist a fallback choice automatically — the user's stored preference
        should only change via an explicit set_active_backend call, so that when their
        original backend comes back online, resolve() goes back to using it.

        Args:
            user_id: The user identifier to resolve a backend for.

        Returns:
            The SandboxManager instance this user should use.

        Raises:
            SandboxUnavailableError: If no backend in the fallback order is available.
        """
        # Step 1: Get the user's preferred backend (or default)
        stored_preference = await self._memory.get_fact(user_id, "active_sandbox_backend")
        preferred_name = stored_preference or self._settings.sandbox_default_backend

        # Step 2: Check if preferred backend is available
        if preferred_name in self._backends:
            preferred_backend = self._backends[preferred_name]
            if await preferred_backend.is_available():
                return preferred_backend

        # Step 3: Walk fallback order, skipping the failed preferred backend
        tried: list[str] = [preferred_name] if preferred_name in self._backends else []

        for backend_name in self._settings.sandbox_fallback_order:
            # Skip the one that just failed
            if backend_name == preferred_name:
                continue

            if backend_name in self._backends:
                backend = self._backends[backend_name]
                if await backend.is_available():
                    return backend
                tried.append(backend_name)

        # Step 4: No backend available
        tried.extend(
            bn
            for bn in self._backends
            if bn not in tried and bn != preferred_name
        )

        raise SandboxUnavailableError(
            f"No sandbox backend available. Tried: {tried}. "
            f"None responded."
        )

    async def set_active_backend(self, user_id: str, backend_name: str) -> None:
        """Persist the user's active backend preference.

        Validates that backend_name is registered before persisting. Does NOT check
        is_available() - a user should be able to select a backend that's currently
        offline, in case it comes back.

        Args:
            user_id: The user identifier.
            backend_name: The backend name to set as active (e.g., "ssh" or "docker").

        Raises:
            ValueError: If backend_name isn't a registered backend.
        """
        if backend_name not in self._backends:
            raise ValueError(
                f"Unknown sandbox backend '{backend_name}'. "
                f"Registered backends: {self.registered_backends()}"
            )

        await self._memory.remember_fact(user_id, "active_sandbox_backend", backend_name)

    async def get_stored_preference(self, user_id: str) -> str:
        """Return the user's stored backend preference without fallback logic.

        This is the same lookup resolve() does internally for the first step,
        but factored out so tools can show the user's actual preference without
        invoking fallback logic.

        Args:
            user_id: The user identifier.

        Returns:
            The stored backend name, or the default if none is stored.
        """
        stored = await self._memory.get_fact(user_id, "active_sandbox_backend")
        return stored or self._settings.sandbox_default_backend

    def registered_backends(self) -> list[str]:
        """Return the list of registered backend_name values.

        Returns:
            List of backend name strings (e.g., ["ssh", "docker"]).
        """
        return list(self._backends.keys())