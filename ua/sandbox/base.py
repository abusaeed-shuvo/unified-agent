"""Abstract interface for sandbox backends.

This module provides the SandboxManager abstract base class that all sandbox
backends (SSH, Docker, Kubernetes) must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SandboxManager(ABC):
    """Abstract interface all sandbox backends (SSH, Docker, future Kubernetes) implement."""

    @abstractmethod
    async def ensure_project_dir(self, project_id: str) -> str:
        """Ensure the project workspace exists. Returns its absolute path/identifier."""

    @abstractmethod
    async def write_file(self, project_id: str, relative_path: str, content: str) -> None:
        """Write a file into the project workspace."""

    @abstractmethod
    async def execute(
        self, project_id: str, command: str, timeout: float = 60.0
    ) -> tuple[int, str, str]:
        """Execute a command in the project workspace. Returns (exit_code, stdout, stderr)."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Health check — can this backend currently be used? Must not raise; return False on any failure."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short identifier for this backend, e.g. 'ssh', 'docker'."""