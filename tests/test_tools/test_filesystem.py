"""Tests for FilesystemTool."""

import pytest

from ua.tools.filesystem import FilesystemTool


@pytest.mark.asyncio
async def test_read_file_inside_sandbox_succeeds(tmp_path):
    """Test reading a file that exists inside the sandbox succeeds."""
    # Create a sandbox directory with a file inside
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    test_file = sandbox / "test.txt"
    test_file.write_text("Hello, World!")

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="read", path="test.txt")

    assert result.success is True
    assert result.output == "Hello, World!"
    assert result.error is None


@pytest.mark.asyncio
async def test_list_directory_inside_sandbox_succeeds(tmp_path):
    """Test listing a directory inside the sandbox succeeds."""
    # Create a sandbox directory with some entries
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "file1.txt").write_text("content1")
    (sandbox / "file2.txt").write_text("content2")
    (sandbox / "subdir").mkdir()

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="list", path=".")

    assert result.success is True
    entries = result.output.split("\n")
    assert "file1.txt" in entries
    assert "file2.txt" in entries
    assert "subdir" in entries


@pytest.mark.asyncio
async def test_relative_traversal_rejected(tmp_path):
    """Test that path traversal via '../' is rejected.

    We create a file OUTSIDE the sandbox and verify that attempting to read it
    via '../' traversal is blocked.
    """
    # Create sandbox and a file outside it
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("SECRET DATA - SHOULD NOT BE ACCESSIBLE")

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="read", path="../outside.txt")

    assert result.success is False
    assert result.error is not None
    assert "outside the sandbox" in result.error.lower()
    # Verify the secret content was NOT returned
    assert "SECRET DATA" not in result.output


@pytest.mark.asyncio
async def test_absolute_path_outside_sandbox_rejected(tmp_path):
    """Test that absolute paths outside the sandbox are rejected."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="read", path="/etc/passwd")

    assert result.success is False
    assert result.error is not None
    assert "outside the sandbox" in result.error.lower()


@pytest.mark.asyncio
async def test_symlink_escaping_sandbox_rejected(tmp_path):
    """Test that symlinks pointing outside the sandbox are detected and rejected.

    This is the critical security test - a symlink inside the sandbox that
    points to a file outside must be caught and blocked.
    """
    # Create sandbox and a file outside it
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("SECRET - SHOULD NOT BE ACCESSIBLE")

    # Create a symlink inside the sandbox pointing to the outside file
    symlink_inside = sandbox / "escape_link"
    symlink_inside.symlink_to(outside_file)

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="read", path="escape_link")

    assert result.success is False
    assert result.error is not None
    assert "outside the sandbox" in result.error.lower()
    # Verify the secret content was NOT returned
    assert "SECRET" not in result.output


@pytest.mark.asyncio
async def test_read_nonexistent_file_handled_gracefully(tmp_path):
    """Test reading a nonexistent file returns success=False, not an exception."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="read", path="nonexistent.txt")

    assert result.success is False
    assert result.error is not None
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_list_nonexistent_directory_handled_gracefully(tmp_path):
    """Test listing a nonexistent directory returns success=False, not an exception."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="list", path="nonexistent_dir")

    assert result.success is False
    assert result.error is not None
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_list_on_a_file_path_rejected_gracefully(tmp_path):
    """Test listing a path that is a file (not a directory) returns success=False."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    test_file = sandbox / "test.txt"
    test_file.write_text("content")

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="list", path="test.txt")

    assert result.success is False
    assert result.error is not None
    assert "not a directory" in result.error.lower()


@pytest.mark.asyncio
async def test_read_on_a_directory_path_rejected_gracefully(tmp_path):
    """Test reading a path that is a directory returns success=False."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "subdir").mkdir()

    tool = FilesystemTool(sandbox_root=sandbox.resolve())
    result = await tool.run(action="read", path="subdir")

    assert result.success is False
    assert result.error is not None
    assert "not a file" in result.error.lower() or "directory" in result.error.lower()
