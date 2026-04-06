"""Tests for git exceptions."""
import pytest

from docgap.git.exceptions import (
    CloneError,
    CommitNotFoundError,
    FetchError,
    GitCommandError,
    GitError,
    PullError,
    _sanitize_url,
)


class TestSanitizeUrl:
    def test_sanitizes_credentials(self):
        url = "https://user:pass@github.com/repo.git"
        assert _sanitize_url(url) == "https://***@github.com/repo.git"

    def test_sanitizes_token_only(self):
        url = "https://mytoken123@github.com/repo.git"
        assert _sanitize_url(url) == "https://***@github.com/repo.git"

    def test_no_credentials_unchanged(self):
        url = "https://github.com/repo.git"
        assert _sanitize_url(url) == "https://github.com/repo.git"

    def test_ssh_url_unchanged(self):
        url = "git@github.com:user/repo.git"
        assert _sanitize_url(url) == "git@github.com:user/repo.git"


class TestGitError:
    def test_base_exception(self):
        e = GitError("base error")
        assert str(e) == "base error"
        assert isinstance(e, Exception)


class TestCloneError:
    def test_message_contains_sanitized_url(self):
        e = CloneError("https://user:pass@github.com/repo.git", "failed")
        assert "***@" in str(e)
        assert "user:pass" not in str(e)

    def test_message_contains_failure_reason(self):
        e = CloneError("https://github.com/repo.git", "connection refused")
        assert "connection refused" in str(e)

    def test_attributes_set(self):
        e = CloneError("https://github.com/repo.git", "failed")
        assert e.repo_url == "https://github.com/repo.git"
        assert e.message == "failed"

    def test_long_message_truncated(self):
        long_msg = "x" * 1000
        e = CloneError("https://github.com/repo.git", long_msg)
        assert len(str(e)) < 1100  # truncated in super().__init__

    def test_isinstance_git_error(self):
        e = CloneError("https://github.com/repo.git", "fail")
        assert isinstance(e, GitError)


class TestFetchError:
    def test_message_contains_path(self):
        e = FetchError("/path/to/repo", "network error")
        assert "/path/to/repo" in str(e)

    def test_original_error_none_by_default(self):
        e = FetchError("/path", "msg")
        assert e.original_error is None

    def test_original_error_stored(self):
        orig = ValueError("original")
        e = FetchError("/path", "msg", original_error=orig)
        assert e.original_error is orig

    def test_repo_path_attribute(self):
        e = FetchError("/path/to/repo", "msg")
        assert e.repo_path == "/path/to/repo"

    def test_isinstance_git_error(self):
        e = FetchError("/path", "msg")
        assert isinstance(e, GitError)

    def test_url_with_credentials_sanitized(self):
        e = FetchError("https://token@github.com/repo", "msg")
        assert "token" not in str(e)
        assert "***@" in str(e)


class TestPullError:
    def test_message_contains_pull(self):
        e = PullError("/path/to/repo", "ff-only failed")
        assert "pull" in str(e).lower()

    def test_message_contains_reason(self):
        e = PullError("/path/to/repo", "ff-only failed")
        assert "ff-only failed" in str(e)

    def test_repo_path_attribute(self):
        e = PullError("/path/to/repo", "msg")
        assert e.repo_path == "/path/to/repo"

    def test_isinstance_git_error(self):
        e = PullError("/path", "msg")
        assert isinstance(e, GitError)


class TestCommitNotFoundError:
    def test_message_contains_commit_hash(self):
        e = CommitNotFoundError("abc123", "/repo")
        assert "abc123" in str(e)

    def test_message_contains_repo_path(self):
        e = CommitNotFoundError("abc123", "/repo/path")
        assert "/repo/path" in str(e)

    def test_attributes_set(self):
        e = CommitNotFoundError("abc123", "/repo")
        assert e.commit_hash == "abc123"
        assert e.repo_path == "/repo"

    def test_isinstance_git_error(self):
        e = CommitNotFoundError("abc123", "/repo")
        assert isinstance(e, GitError)


class TestGitCommandError:
    def test_message_contains_returncode(self):
        e = GitCommandError(["git", "status"], 1, "some error")
        assert "1" in str(e)

    def test_stderr_truncated_to_500(self):
        long_stderr = "x" * 1000
        e = GitCommandError(["git", "status"], 1, long_stderr)
        assert len(e.stderr) <= 500

    def test_stderr_short_not_truncated(self):
        e = GitCommandError(["git", "status"], 1, "short error")
        assert e.stderr == "short error"

    def test_attributes_set(self):
        e = GitCommandError(["git", "log"], 128, "fatal error")
        assert e.command == ["git", "log"]
        assert e.returncode == 128

    def test_isinstance_git_error(self):
        e = GitCommandError(["git", "status"], 1, "err")
        assert isinstance(e, GitError)

    def test_stderr_exactly_500_not_truncated(self):
        exactly_500 = "y" * 500
        e = GitCommandError(["git", "status"], 1, exactly_500)
        assert len(e.stderr) == 500
