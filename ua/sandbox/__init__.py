"""Sandbox backend module for SSH and other backends.

This module provides the SandboxManager abstract interface and SSHSandboxManager
implementation for managing sandbox connections and executing operations within
per-project working directories.
"""

from ua.sandbox.base import SandboxManager
from ua.sandbox.docker_manager import DockerSandboxManager
from ua.sandbox.manager import SSHSandboxManager
from ua.sandbox.registry import SandboxBackendRegistry, SandboxUnavailableError

__all__ = ["SandboxManager", "SSHSandboxManager", "DockerSandboxManager", "SandboxBackendRegistry", "SandboxUnavailableError"]
