"""Custom exceptions for Git operations."""

import re


def _sanitize_url(url: str) -> str:
    """Remove credentials from URLs to prevent information leakage."""
    return re.sub(r'://[^@]+@', '://***@', url)


class GitError(Exception):
    """Base exception for Git-related errors."""
    pass


class CloneError(GitError):
    """Raised when cloning a repository fails."""
    def __init__(self, repo_url: str, message: str):
        self.repo_url = repo_url
        self.message = message
        safe_url = _sanitize_url(repo_url)
        super().__init__(f"Failed to clone {safe_url}: {message[:500]}")


class FetchError(GitError):
    """Raised when fetching from a repository fails."""
    def __init__(self, repo_path: str, message: str, original_error: Exception | None = None):
        self.repo_path = repo_path
        self.original_error = original_error
        safe_path = _sanitize_url(repo_path)
        super().__init__(f"Failed to fetch from {safe_path}: {message[:500]}")


class PullError(GitError):
    """Raised when pulling from a repository fails."""
    def __init__(self, repo_path: str, message: str):
        self.repo_path = repo_path
        safe_msg = _sanitize_url(message[:500])
        super().__init__(f"Failed to pull from {repo_path}: {safe_msg}")


class CommitNotFoundError(GitError):
    """Raised when a commit is not found in the repository."""
    def __init__(self, commit_hash: str, repo_path: str):
        self.commit_hash = commit_hash
        self.repo_path = repo_path
        super().__init__(f"Commit '{commit_hash}' not found in {repo_path}")


class GitCommandError(GitError):
    """Raised when a git command fails."""
    def __init__(self, command: list[str], returncode: int, stderr: str):
        self.command = [_sanitize_url(c) for c in command]
        self.returncode = returncode
        self.stderr = _sanitize_url(stderr[:500])
        message = f"Git command failed (return code {returncode}): {self.stderr}"
        super().__init__(message)
