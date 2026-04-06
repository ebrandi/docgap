"""Security-focused tests for Git operations."""
import tempfile
import os
from pathlib import Path
import subprocess

import pytest

from docgap.git.fetcher import GitFetcher
from docgap.git.exceptions import GitError, CommitNotFoundError


class TestGitSecurity:
    """Test Git security aspects."""

    def test_path_traversal_in_file_content(self, temp_dir):
        """Test that path traversal attempts in file paths are handled safely."""
        # Create a test repo
        src_path = temp_dir / "src"
        src_path.mkdir()
        
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=src_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=src_path, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=src_path, check=True)
        
        # Create a test file
        test_file = src_path / "test.c"
        test_file.write_text("int main() { return 0; }")
        
        # Commit the file
        subprocess.run(["git", "add", "test.c"], cwd=src_path, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=src_path, check=True)
        
        # Get the commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], 
            cwd=src_path, 
            check=True, 
            capture_output=True, 
            text=True
        )
        commit_hash = result.stdout.strip()
        
        fetcher = GitFetcher(
            src_path=str(src_path),
            src_remote="",  # Not used for local path
            bare=False
        )
        
        # Test normal file access
        content = fetcher.get_file_content_at_commit("test.c", commit_hash)
        assert "int main()" in content
        
        # Test path traversal attempts - these should be handled safely
        malicious_paths = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\drivers\\etc\\hosts",
            "test.c/../../../etc/passwd",
            "./test.c",
            "../src/../test.c",
        ]
        
        for path in malicious_paths:
            try:
                content = fetcher.get_file_content_at_commit(path, commit_hash)
                # If it doesn't raise an exception, content should be None or empty
                # or not contain sensitive system files
                assert content is None or ("root:" not in content and "[drivers]" not in content)
            except (FileNotFoundError, GitError):
                # These exceptions are expected for invalid paths
                pass

    def test_command_injection_in_git_args(self, temp_dir):
        """Test that git command arguments are properly sanitized."""
        src_path = temp_dir / "src"
        src_path.mkdir()
        
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=src_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=src_path, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=src_path, check=True)
        
        # Create and commit a test file
        test_file = src_path / "test.c"
        test_file.write_text("int main() { return 0; }")
        subprocess.run(["git", "add", "test.c"], cwd=src_path, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=src_path, check=True)
        
        fetcher = GitFetcher(
            src_path=str(src_path),
            src_remote="",  # Not used
            bare=False
        )
        
        # Test that malicious arguments in commit hash are handled
        # The commit hash should be treated as a single argument
        malicious_hashes = [
            "HEAD; rm -rf /",
            "HEAD && ls",
            "HEAD || echo 'hacked'",
            "$(id)",
            "`id`",
        ]
        
        for malicious_hash in malicious_hashes:
            try:
                # This should either fail gracefully or treat the whole string as a hash
                fetcher.get_commit_info(malicious_hash)
                # If it succeeds, it should not have executed the malicious command
            except (CommitNotFoundError, GitError):
                # Expected for invalid hashes
                pass
            except Exception as e:
                # Should not be command injection related
                assert "command not found" not in str(e).lower()
                assert "permission denied" not in str(e).lower()

    def test_subprocess_safety(self, temp_dir):
        """Test that subprocess calls are safe."""
        fetcher = GitFetcher(
            src_path=str(temp_dir / "nonexistent"),
            src_remote="https://example.com/repo.git"
        )
        
        # Test that repo existence check doesn't allow path traversal
        # This is mainly testing the _repo_exists method
        assert not fetcher._repo_exists(Path("/etc/passwd"))
        assert not fetcher._repo_exists(Path("../../etc/passwd"))