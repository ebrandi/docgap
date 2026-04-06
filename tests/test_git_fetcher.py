"""Tests for Git fetcher (mocked)."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docgap.git import GitFetcher


class TestGitFetcher:
    """Test Git fetcher operations."""

    @pytest.fixture
    def fetcher(self, temp_dir):
        """Create a test fetcher."""
        return GitFetcher(
            src_path=str(temp_dir / "src"),
            src_remote="https://github.com/test/test.git",
            bare=True,
            timeout=60
        )

    def test_fetcher_initialization(self, temp_dir):
        """Test fetcher initialization."""
        fetcher = GitFetcher(
            src_path=str(temp_dir / "src"),
            src_remote="https://github.com/test/test.git",
            bare=True,
            timeout=300
        )

        assert fetcher.src_path == Path(str(temp_dir / "src"))
        assert fetcher.src_remote == "https://github.com/test/test.git"
        assert fetcher.bare is True

    @patch("subprocess.run")
    def test_ensure_repos_creates_directories(self, mock_run, fetcher, temp_dir):
        """Test that ensure_repos creates directories."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        (temp_dir / "src").mkdir(parents=True, exist_ok=True)
        fetcher.ensure_repos()

        assert (temp_dir / "src").exists()
        mock_run.assert_called()

    @patch("subprocess.run")
    def test_fetch_src(self, mock_run, fetcher):
        """Test the fetch_src method."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        fetcher.fetch_src()

        mock_run.assert_called()

    @patch("subprocess.run")
    def test_pull_doc(self, mock_run):
        """Test the pull_doc method."""
        fetcher = GitFetcher(
            src_path="/tmp/src",
            doc_path="/tmp/doc",
            doc_remote="https://github.com/test/doc.git",
            bare=False,
            timeout=60
        )

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        with patch.object(fetcher, '_repo_exists', return_value=True):
            fetcher.pull_doc()

        mock_run.assert_called()

    @patch("subprocess.run")
    def test_get_commit_info(self, mock_run):
        """Test getting commit info."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123|Test User|test@example.com|2026-04-03T10:00:00Z|Test commit"
        mock_run.return_value = mock_result

        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
            bare=True,
            timeout=60
        )

        with patch.object(fetcher, '_repo_exists', return_value=True):
            info = fetcher.get_commit_info("abc123")

        assert info is not None
        assert info["hash"] == "abc123"

    @patch("subprocess.run")
    def test_get_diff(self, mock_run):
        """Test getting diff for a commit."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "diff --git a/file.c b/file.c"
        mock_run.return_value = mock_result

        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
            bare=True,
            timeout=60
        )

        with patch.object(fetcher, '_repo_exists', return_value=True):
            diff = fetcher.get_diff("abc123")

        assert diff is not None
        assert "diff" in diff


class TestGitFetcherAuthToken:
    """Test auth token URL building."""

    def test_auth_token_url(self):
        """Auth token must NOT be embedded in URL (passed via credential helper instead)."""
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
            auth_token="mytoken123",
        )
        # Token must not appear in the URL (prevents /proc/cmdline leakage)
        assert "mytoken123" not in fetcher.src_remote_url
        assert fetcher.src_remote_url == "https://github.com/test/test.git"
        # Token is stored for credential helper use
        assert fetcher.auth_token == "mytoken123"

    def test_no_auth_token(self):
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        assert fetcher.src_remote_url == "https://github.com/test/test.git"

    def test_doc_path_init(self):
        fetcher = GitFetcher(
            src_path="/tmp/src",
            doc_path="/tmp/doc",
            doc_remote="https://github.com/test/doc.git",
        )
        assert fetcher.doc_path == Path("/tmp/doc")


class TestGitFetcherRunGitRetries:
    """Test _run_git timeout/OSError retries."""

    @patch("subprocess.run")
    def test_run_git_timeout_retries(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd=["git"], timeout=60)
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
            max_retries=2,
            retry_delay=0.0,
        )
        from docgap.git.exceptions import FetchError
        with pytest.raises(FetchError, match="timed out"):
            fetcher._run_git(["status"], repo_path=Path("/tmp/src"))
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_run_git_oserror_retries(self, mock_run):
        mock_run.side_effect = OSError("No such file")
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
            max_retries=2,
            retry_delay=0.0,
        )
        from docgap.git.exceptions import FetchError
        with pytest.raises(FetchError):
            fetcher._run_git(["status"], repo_path=Path("/tmp/src"))
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_run_git_check_raises_command_error(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: not a git repository"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import GitCommandError
        with pytest.raises(GitCommandError):
            fetcher._run_git(["status"], repo_path=Path("/tmp/src"), check=True)


class TestGitFetcherCloneRepo:
    """Test _clone_repo error handling."""

    @patch("subprocess.run")
    def test_clone_repo_error(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: repo not found"
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import CloneError
        with pytest.raises(CloneError):
            fetcher._clone_repo(Path("/tmp/newrepo"), "https://github.com/test/test.git")

    @patch("subprocess.run")
    def test_clone_repo_bare_shallow(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
            shallow_depth=1,
        )
        fetcher._clone_repo(Path("/tmp/newrepo"), "https://github.com/test/test.git", bare=True, shallow_depth=1)
        call_args = mock_run.call_args[0][0]
        assert "--bare" in call_args
        assert "--depth" in call_args
        assert "1" in call_args
        assert "--progress" in call_args


class TestGitFetcherFetchSrcError:
    """Test fetch_src error handling."""

    @patch("subprocess.run")
    def test_fetch_src_error(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: could not fetch"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import FetchError
        with pytest.raises(FetchError):
            fetcher.fetch_src()


class TestGitFetcherPullDocPaths:
    """Test pull_doc all error paths."""

    def test_pull_doc_no_doc_path(self):
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import GitError
        with pytest.raises(GitError, match="No doc repository"):
            fetcher.pull_doc()

    def test_pull_doc_repo_not_found(self):
        fetcher = GitFetcher(
            src_path="/tmp/src",
            doc_path="/tmp/nonexistent_doc",
            doc_remote="https://github.com/test/doc.git",
        )
        from docgap.git.exceptions import GitError
        with pytest.raises(GitError, match="not found"):
            fetcher.pull_doc()

    @patch("subprocess.run")
    def test_pull_doc_command_error(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: could not pull"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            doc_path="/tmp/doc",
            doc_remote="https://github.com/test/doc.git",
        )
        from docgap.git.exceptions import PullError
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(PullError):
                fetcher.pull_doc()


class TestGitFetcherGetCommitInfoErrors:
    """Test get_commit_info error paths."""

    def test_get_commit_info_repo_not_found(self):
        fetcher = GitFetcher(
            src_path="/tmp/nonexistent_src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import GitError
        with pytest.raises(GitError, match="not found"):
            fetcher.get_commit_info("abc123")

    @patch("subprocess.run")
    def test_get_commit_info_bad_revision(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: bad revision 'abc123'"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import CommitNotFoundError
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(CommitNotFoundError):
                fetcher.get_commit_info("abc123")

    @patch("subprocess.run")
    def test_get_commit_info_empty_output(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import CommitNotFoundError
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(CommitNotFoundError):
                fetcher.get_commit_info("abc123")

    @patch("subprocess.run")
    def test_get_commit_info_malformed_output(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123|Test User"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import CommitNotFoundError
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(CommitNotFoundError):
                fetcher.get_commit_info("abc123")


class TestGitFetcherGetDiffErrors:
    """Test get_diff error paths."""

    def test_get_diff_repo_not_found(self):
        fetcher = GitFetcher(
            src_path="/tmp/nonexistent_src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import GitError
        with pytest.raises(GitError, match="not found"):
            fetcher.get_diff("abc123")

    @patch("subprocess.run")
    def test_get_diff_bad_revision(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: bad revision"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
        )
        from docgap.git.exceptions import CommitNotFoundError
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(CommitNotFoundError):
                fetcher.get_diff("abc123")


class TestGitFetcherGetFileContentAtCommit:
    """Test get_file_content_at_commit."""

    @patch("subprocess.run")
    def test_get_file_content_success(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "file content here"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        with patch.object(fetcher, '_repo_exists', return_value=True):
            content = fetcher.get_file_content_at_commit("usr.bin/ls/ls.c", "abc123")
        assert content == "file content here"

    def test_get_file_content_repo_not_found(self):
        fetcher = GitFetcher(src_path="/tmp/nonexistent_src", src_remote="https://github.com/test/test.git")
        from docgap.git.exceptions import GitError
        with pytest.raises(GitError, match="not found"):
            fetcher.get_file_content_at_commit("file.c", "abc123")

    @patch("subprocess.run")
    def test_get_file_content_file_not_found(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "exists on disk, but not in"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(FileNotFoundError):
                fetcher.get_file_content_at_commit("nonexistent.c", "abc123")

    @patch("subprocess.run")
    def test_get_file_content_bad_revision(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: bad revision"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        from docgap.git.exceptions import CommitNotFoundError
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(CommitNotFoundError):
                fetcher.get_file_content_at_commit("file.c", "abc123")


class TestGitFetcherGetBranches:
    """Test get_branches."""

    @patch("subprocess.run")
    def test_get_branches_success(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "* main\n  feature-branch\n  bugfix\n"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        with patch.object(fetcher, '_repo_exists', return_value=True):
            branches = fetcher.get_branches()
        assert "main" in branches
        assert "feature-branch" in branches
        assert "bugfix" in branches

    @patch("subprocess.run")
    def test_get_branches_remote(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  origin/main\n  origin/develop\n"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        with patch.object(fetcher, '_repo_exists', return_value=True):
            branches = fetcher.get_branches(remote=True)
        assert len(branches) == 2

    def test_get_branches_repo_not_found(self):
        fetcher = GitFetcher(src_path="/tmp/nonexistent_src", src_remote="https://github.com/test/test.git")
        from docgap.git.exceptions import GitError
        with pytest.raises(GitError, match="not found"):
            fetcher.get_branches()

    @patch("subprocess.run")
    def test_get_branches_failure_returns_empty(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        with patch.object(fetcher, '_repo_exists', return_value=True):
            branches = fetcher.get_branches()
        assert branches == []


class TestGitFetcherGetFileListAtCommit:
    """Test get_file_list_at_commit."""

    @patch("subprocess.run")
    def test_get_file_list_success(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "usr.bin/ls/ls.c\nusr.bin/ls/ls.1\n"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        with patch.object(fetcher, '_repo_exists', return_value=True):
            files = fetcher.get_file_list_at_commit("abc123")
        assert files == ["usr.bin/ls/ls.c", "usr.bin/ls/ls.1"]

    def test_get_file_list_repo_not_found(self):
        fetcher = GitFetcher(src_path="/tmp/nonexistent_src", src_remote="https://github.com/test/test.git")
        from docgap.git.exceptions import GitError
        with pytest.raises(GitError, match="not found"):
            fetcher.get_file_list_at_commit("abc123")

    @patch("subprocess.run")
    def test_get_file_list_bad_revision(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: bad revision"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        from docgap.git.exceptions import CommitNotFoundError
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(CommitNotFoundError):
                fetcher.get_file_list_at_commit("abc123")


class TestGitFetcherGetLatestCommitHash:
    """Test get_latest_commit_hash."""

    @patch("subprocess.run")
    def test_get_latest_commit_hash_success(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123def456789\n"
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        with patch.object(fetcher, '_repo_exists', return_value=True):
            h = fetcher.get_latest_commit_hash()
        assert h == "abc123def456789"

    def test_get_latest_commit_hash_repo_not_found(self):
        fetcher = GitFetcher(src_path="/tmp/nonexistent_src", src_remote="https://github.com/test/test.git")
        from docgap.git.exceptions import GitError
        with pytest.raises(GitError, match="not found"):
            fetcher.get_latest_commit_hash()

    @patch("subprocess.run")
    def test_get_latest_commit_hash_failure(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: bad ref"
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        fetcher = GitFetcher(src_path="/tmp/src", src_remote="https://github.com/test/test.git")
        from docgap.git.exceptions import GitCommandError
        with patch.object(fetcher, '_repo_exists', return_value=True):
            with pytest.raises(GitCommandError):
                fetcher.get_latest_commit_hash()


class TestGitFetcherRepoExists:
    """Test _repo_exists."""

    def test_repo_exists_bare(self, temp_dir):
        (temp_dir / "bare_repo").mkdir()
        (temp_dir / "bare_repo" / "HEAD").write_text("ref: refs/heads/main\n")
        fetcher = GitFetcher(src_path=str(temp_dir / "bare_repo"), src_remote="https://example.com/test.git")
        assert fetcher._repo_exists(temp_dir / "bare_repo") is True

    def test_repo_exists_non_bare(self, temp_dir):
        (temp_dir / "non_bare").mkdir()
        (temp_dir / "non_bare" / ".git").mkdir()
        fetcher = GitFetcher(src_path=str(temp_dir / "non_bare"), src_remote="https://example.com/test.git")
        assert fetcher._repo_exists(temp_dir / "non_bare") is True

    def test_repo_not_exists(self, temp_dir):
        fetcher = GitFetcher(src_path=str(temp_dir / "nope"), src_remote="https://example.com/test.git")
        assert fetcher._repo_exists(temp_dir / "nope") is False

    def test_repo_exists_empty_dir(self, temp_dir):
        (temp_dir / "empty").mkdir()
        fetcher = GitFetcher(src_path=str(temp_dir / "empty"), src_remote="https://example.com/test.git")
        assert fetcher._repo_exists(temp_dir / "empty") is False


class TestGitFetcherEnsureRepos:
    """Test ensure_repos."""

    @patch("subprocess.run")
    def test_ensure_repos_with_doc(self, mock_run, temp_dir):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        fetcher = GitFetcher(
            src_path=str(temp_dir / "src"),
            doc_path=str(temp_dir / "doc"),
            doc_remote="https://github.com/test/doc.git",
            src_remote="https://github.com/test/src.git",
        )
        # src dir exists but no HEAD or .git
        (temp_dir / "src").mkdir()
        (temp_dir / "doc").mkdir()
        fetcher.ensure_repos()
        assert mock_run.call_count >= 2  # At least clone for both repos


class TestGetDiffNonZeroReturn:
    """Cover get_diff returncode != 0 path."""

    def test_get_diff_nonzero_returncode(self, temp_dir):
        from docgap.git.exceptions import CommitNotFoundError
        fetcher = GitFetcher(src_path=str(temp_dir), src_remote="", bare=False)
        with patch.object(fetcher, '_repo_exists', return_value=True), \
             patch.object(fetcher, '_run_git', return_value=(1, "", "")):
            with pytest.raises(CommitNotFoundError):
                fetcher.get_diff("badcommit")


class TestGitFetcherAuthTokenCredentialHelper:
    """Test that auth_token causes _run_git to pass credential helper args and env."""

    @patch("subprocess.run")
    def test_run_git_includes_credential_helper_and_env(self, mock_run):
        """When auth_token is set, git command includes credential.helper and GIT_AUTH_TOKEN env."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123\n"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
            auth_token="supersecret",
            max_retries=1,
        )

        fetcher._run_git(["rev-parse", "HEAD"], repo_path=Path("/tmp/src"))

        assert mock_run.called
        call_kwargs = mock_run.call_args
        cmd = call_kwargs[0][0]
        env = call_kwargs[1].get("env") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("env")
        # credential.helper must be in the command
        assert "credential.helper" in " ".join(cmd)
        # GIT_AUTH_TOKEN must be in the environment
        assert env is not None
        assert env.get("GIT_AUTH_TOKEN") == "supersecret"

    @patch("subprocess.run")
    def test_run_git_no_auth_token_has_no_credential_helper(self, mock_run):
        """When no auth_token is set, git command does not include credential.helper."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123\n"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        fetcher = GitFetcher(
            src_path="/tmp/src",
            src_remote="https://github.com/test/test.git",
            max_retries=1,
        )

        fetcher._run_git(["rev-parse", "HEAD"], repo_path=Path("/tmp/src"))

        cmd = mock_run.call_args[0][0]
        assert "credential.helper" not in " ".join(cmd)
        # env should be None (no override)
        env = mock_run.call_args[1].get("env")
        assert env is None


class TestGetLatestCommitHashInvalidBranch:
    """Test branch name validation in get_latest_commit_hash."""

    def test_invalid_branch_raises_value_error(self, temp_dir):
        """get_latest_commit_hash raises ValueError for branch names with shell-special chars."""
        fetcher = GitFetcher(
            src_path=str(temp_dir),
            src_remote="https://github.com/test/test.git",
        )
        # Branch validation runs before _run_git; mock both to isolate the check.
        # The regex [a-zA-Z0-9_./-]+ disallows semicolons, spaces, etc.
        with patch.object(fetcher, '_repo_exists', return_value=True), \
             patch.object(fetcher, '_run_git', return_value=(0, "abc123\n", "")):
            with pytest.raises(ValueError, match="Invalid branch name"):
                fetcher.get_latest_commit_hash(branch="main; echo pwned")

    def test_invalid_branch_with_spaces(self, temp_dir):
        """get_latest_commit_hash raises ValueError for branch names containing spaces."""
        fetcher = GitFetcher(
            src_path=str(temp_dir),
            src_remote="https://github.com/test/test.git",
        )
        with patch.object(fetcher, '_repo_exists', return_value=True), \
             patch.object(fetcher, '_run_git', return_value=(0, "abc123\n", "")):
            with pytest.raises(ValueError, match="Invalid branch name"):
                fetcher.get_latest_commit_hash(branch="main branch")
