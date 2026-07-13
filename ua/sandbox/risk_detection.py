"""Risky command detection for sandbox execute tool.

This module provides blacklist-based detection of potentially destructive commands
that should require user confirmation before execution.

IMPORTANT: This is a DEFENSE-IN-DEPTH measure, NOT a primary security boundary.
It uses a blacklist approach which is inherently NOT exhaustive. A sufficiently
obfuscated or unusual command can evade detection. The real safety net is the
disposability of the SSH sandbox host itself.

Patterns detected:
- rm -rf (and variants with -r/-f separated)
- sudo commands
- dd disk operations
- mkfs filesystem operations
- shutdown/reboot/halt commands
- Fork bombs
- Redirects to block devices (> /dev/)
- chmod 777 on root-level paths
- Pipe-to-shell patterns (curl|bash, wget|sh)
- git push --force/-f
"""

from __future__ import annotations

import re


def is_risky_command(command: str) -> tuple[bool, str]:
    """Check if a command matches known-dangerous patterns.

    Args:
        command: The shell command to check.

    Returns:
        Tuple of (is_risky, reason) where reason explains why the command
        was flagged, or empty string if not flagged.

    Note:
        This is a blacklist-based detection system. It cannot catch all
        possible destructive commands. A malicious or sufficiently unusual
        command may evade detection. The disposability of the sandbox host
        is the real safety mechanism.
    """
    if not command or not command.strip():
        return (False, "")

    # Normalize to lowercase for case-insensitive matching
    cmd_lower = command.lower()

    # rm -rf patterns (including variants like rm -r -f, rm -f -r, etc.)
    # Matches: rm -rf, rm -fr, rm -r -f, rm -f -r (followed by path or end)
    rm_rf_patterns = [
        r"\brm\s+-rf",
        r"\brm\s+-fr",
        r"\brm\s+-r\s+-f",
        r"\brm\s+-f\s+-r",
    ]
    for pattern in rm_rf_patterns:
        if re.search(pattern, cmd_lower):
            return (True, "rm -rf pattern detected (recursive force delete)")

    # Also catch bare rm -r or rm -f if they look destructive
    if re.search(r"\brm\s+-r\b", cmd_lower) or re.search(r"\brm\s+-f\b", cmd_lower):
        return (True, "rm with recursive or force flag detected")

    # sudo commands
    if re.search(r"\bsudo\s", cmd_lower):
        return (True, "sudo command detected")

    # dd disk operations
    if re.search(r"\bdd\s", cmd_lower):
        return (True, "dd command detected (disk operation)")

    # mkfs filesystem operations
    if re.search(r"\bmkfs", cmd_lower):
        return (True, "mkfs command detected (filesystem creation)")

    # shutdown/reboot/halt commands (with optional space after)
    if re.search(r"\bshutdown(\s|$)", cmd_lower):
        return (True, "shutdown command detected")
    if re.search(r"\breboot(\s|$)", cmd_lower):
        return (True, "reboot command detected")
    if re.search(r"\bhalt(\s|$)", cmd_lower):
        return (True, "halt command detected")

    # Fork bomb pattern: :(){:|:&};:
    # Look for the structure: :( ... | ... ) with pipe inside braces
    if re.search(r":\(\).*\|", cmd_lower):
        return (True, "fork bomb pattern detected")

    # Redirects to block devices (followed by path)
    if re.search(r">\s*/dev/", cmd_lower):
        return (True, "redirect to block device detected")

    # chmod 777 on root-level paths
    if re.search(r"\bchmod\s+777\s+/", cmd_lower):
        return (True, "chmod 777 on root-level path detected")

    # Pipe-to-shell patterns (curl, wget followed by pipe to shell)
    # curl ... | sh/bash and wget ... | sh patterns
    if re.search(r"curl.*\|\s*(ba)?sh", cmd_lower):
        return (True, "curl pipe to shell detected")
    if re.search(r"wget.*\|.*sh", cmd_lower):
        return (True, "wget pipe to shell detected")

    # git push --force patterns
    if re.search(r"git\s+push\s+.*-f", cmd_lower):
        return (True, "git push --force/-f detected")
    if re.search(r"git\s+push\s+.*--force", cmd_lower):
        return (True, "git push --force/-f detected")

    return (False, "")
