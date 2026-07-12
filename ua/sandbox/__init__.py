"""SSH-based sandbox execution module.

This module provides SSHSandboxManager for managing SSH connections to remote
sandbox hosts and executing operations within per-project working directories.
"""

from ua.sandbox.manager import SSHSandboxManager

__all__ = ["SSHSandboxManager"]
