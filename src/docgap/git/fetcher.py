"""Git repository management for FreeBSD."""
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from docgap.git.exceptions import (
    CloneError,
    CommitNotFoundError,
    FetchError,
    GitCommandError,
    GitError,
    PullError,
)


class GitFetcher:
    """Manage FreeBSD source and documentation repositories.
    
    This class handles:
    - Initial repository cloning (bare for src, working tree for doc)
    - Updating repositories (fetch for src, pull for doc)
    - Retrieving commit information, diffs, and file contents
    """
    
    def __init__(
        self,
        src_path: Optional[str] = None,
        doc_path: Optional[str] = None,
        src_remote: str = "https://github.com/freebsd/freebsd-src.git",
        doc_remote: Optional[str] = "https://github.com/freebsd/freebsd-doc.git",
        bare: bool = True,
        shallow_depth: Optional[int] = None,
        auth_token: Optional[str] = None,
        timeout: int = 60,
        clone_timeout: int = 7200,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """Initialize GitFetcher.
        
        Args:
            src_path: Path to the freebsd-src repository
            doc_path: Path to the freebsd-doc repository (optional)
            src_remote: URL for the src remote repository
            doc_remote: URL for the doc remote repository
            bare: Whether to create a bare clone for src (default True)
            shallow_depth: If provided, create shallow clone with this many commits
            auth_token: Optional git authentication token for HTTPS
            timeout: Timeout for git operations in seconds
            clone_timeout: Timeout for clone operations in seconds
            max_retries: Maximum number of retry attempts for network operations
            retry_delay: Delay between retry attempts in seconds
        """
        self.src_path = Path(src_path) if src_path else None
        self.doc_path = Path(doc_path) if doc_path else None
        self.src_remote = src_remote
        self.doc_remote = doc_remote
        self.bare = bare
        self.shallow_depth = shallow_depth
        self.auth_token = auth_token
        self.timeout = timeout
        self.clone_timeout = clone_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Update remote URLs if auth token is provided
        self.src_remote_url = self._build_remote_url(self.src_remote) if src_path else None
        self.doc_remote_url = self._build_remote_url(self.doc_remote or "")
    
    def _build_remote_url(self, url: str) -> str:
        """Build remote URL -- returns clean URL without embedded credentials.

        Authentication is handled via credential.helper in _run_git() to avoid
        leaking tokens in /proc/<pid>/cmdline or process listings.
        """
        return url
    
    def _run_git(
        self,
        args: List[str],
        repo_path: Optional[Path] = None,
        timeout: Optional[int] = None,
        check: bool = True,
        capture_output: bool = True,
    ) -> Tuple[int, str, str]:
        """Run a git command with retry logic.
        
        Args:
            args: Git command arguments
            repo_path: Path to the repository (uses working_dir)
            timeout: Command timeout in seconds
            check: Whether to raise on non-zero exit code
            capture_output: Whether to capture stdout and stderr
            
        Returns:
            Tuple of (returncode, stdout, stderr)
            
        Raises:
            GitCommandError: If command fails and check=True
        """
        # Add safe.directory config to avoid "dubious ownership" errors
        # when the repo was cloned by a different user (e.g., root via sudo)
        safe_dir = str(repo_path) if repo_path else "."
        cmd = ["git", "-c", f"safe.directory={safe_dir}"]

        # Pass auth token via credential helper to avoid leaking in /proc/cmdline
        # Use minimal environment to limit blast radius
        env = None
        if self.auth_token:
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
                "HOME": os.environ.get("HOME", "/"),
                "USER": os.environ.get("USER", ""),
                "LANG": os.environ.get("LANG", "C"),
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTH_TOKEN": self.auth_token,
            }
            cmd.extend(["-c", "credential.helper=!f() { echo \"password=$GIT_AUTH_TOKEN\"; }; f"])

        cmd.extend(args)

        workdir = str(repo_path) if repo_path else None
        cmd_timeout = timeout if timeout is not None else self.timeout

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=capture_output,
                    text=True,
                    cwd=workdir,
                    timeout=cmd_timeout,
                    check=False,
                    env=env,
                )
                
                if check and result.returncode != 0:
                    raise GitCommandError(
                        command=cmd,
                        returncode=result.returncode,
                        stderr=result.stderr.strip() if result.stderr else "",
                    )
                
                return result.returncode, result.stdout or "", result.stderr or ""
                
            except subprocess.TimeoutExpired as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise FetchError(
                        repo_path=str(repo_path) if repo_path else "unknown",
                        message=f"Command timed out after {cmd_timeout}s",
                    ) from e
                    
            except (OSError, subprocess.SubprocessError) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise FetchError(
                        repo_path=str(repo_path) if repo_path else "unknown",
                        message=str(e),
                    ) from e
        
        # Should not reach here, but just in case
        if last_error:  # pragma: no cover
            raise last_error

        return 0, "", ""  # pragma: no cover
    
    def _repo_exists(self, path: Path) -> bool:
        """Check if a git repository exists at the given path.
        
        For bare repos, check for HEAD file in the root.
        For non-bare repos, check for .git directory.
        """
        if path.exists():
            # Check for bare repo (has HEAD file)
            if (path / "HEAD").exists():
                return True
            # Check for non-bare repo (has .git directory)
            if (path / ".git").exists():
                return True
        return False
    
    def _clone_repo(
        self,
        repo_path: Path,
        remote_url: str,
        bare: bool = False,
        shallow_depth: Optional[int] = None,
    ) -> None:
        """Clone a repository with retry logic.
        
        Args:
            repo_path: Target path for the clone
            remote_url: Source repository URL
            bare: Whether to create a bare clone
            shallow_depth: If provided, create shallow clone with this depth
        """
        cmd = ["clone", "--progress"]

        if bare:
            cmd.append("--bare")

        if shallow_depth:
            cmd.extend(["--depth", str(shallow_depth)])

        cmd.extend([remote_url, str(repo_path)])

        # Show progress to terminal unless auth token is configured
        show_progress = not self.auth_token

        returncode, stdout, stderr = self._run_git(
            cmd,
            timeout=self.clone_timeout,
            check=False,
            capture_output=not show_progress,
        )
        
        if returncode != 0:
            raise CloneError(
                repo_url=remote_url,
                message=stderr.strip() if stderr else "Unknown error",
            )
    
    def ensure_repos(self) -> None:
        """Cloning repositories if they don't exist.
        
        Creates both src and doc repositories if their directories don't
        contain a valid .git directory.
        """
        # Clone src repo if needed
        if self.src_path and not self._repo_exists(self.src_path):
            print(f"Cloning freebsd-src to {self.src_path}...")
            self._clone_repo(
                self.src_path,
                self.src_remote_url,
                bare=self.bare,
                shallow_depth=self.shallow_depth,
            )
        
        # Clone doc repo if provided and doesn't exist
        if self.doc_path and not self._repo_exists(self.doc_path):
            print(f"Cloning freebsd-doc to {self.doc_path}...")
            self._clone_repo(
                self.doc_path,
                self.doc_remote_url,
                bare=False,
                shallow_depth=self.shallow_depth,
            )
    
    def fetch_src(self, remote: str = "origin") -> None:
        """Fetch updates from the src repository.
        
        Args:
            remote: Remote name to fetch from
        """
        try:
            self._run_git(
                ["fetch", remote, "--prune"],
                repo_path=self.src_path,
                timeout=self.timeout,
            )
        except GitCommandError as e:
            raise FetchError(
                repo_path=str(self.src_path),
                message=str(e),
                original_error=e,
            ) from e
    
    def pull_doc(self, remote: str = "origin", branch: str = "main") -> None:
        """Pull updates for the doc repository.
        
        Args:
            remote: Remote name to pull from
            branch: Branch to pull
        """
        if not self.doc_path:
            raise GitError("No doc repository configured")
        
        if not self._repo_exists(self.doc_path):
            raise GitError(f"Repository not found: {self.doc_path}")
        
        try:
            self._run_git(
                ["pull", "--ff-only", remote, branch],
                repo_path=self.doc_path,
                timeout=self.timeout,
            )
        except GitCommandError as e:
            raise PullError(
                repo_path=str(self.doc_path),
                message=str(e),
            ) from e
    
    def get_commit_info(self, commit_hash: str, repo_path: Optional[Path] = None) -> Dict[str, str]:
        """Get commit metadata.
        
        Args:
            commit_hash: Commit hash to look up
            repo_path: Path to repository (uses src_path by default)
            
        Returns:
            Dictionary with commit metadata
            
        Raises:
            CommitNotFoundError: If commit not found
        """
        if repo_path is None:
            repo_path = self.src_path
        
        if not self._repo_exists(repo_path):
            raise GitError(f"Repository not found: {repo_path}")
        
        try:
            returncode, stdout, stderr = self._run_git(
                [
                    "log",
                    "-1",
                    "--format=%H|%an|%ae|%aI|%s",
                    commit_hash,
                    "--",
                ],
                repo_path=repo_path,
            )
            
            if returncode != 0 or not stdout.strip():
                raise CommitNotFoundError(commit_hash, str(repo_path))
            
            # Parse the output: hash|author|email|date|subject
            parts = stdout.strip().split("|", 4)
            if len(parts) < 5:
                raise CommitNotFoundError(commit_hash, str(repo_path))
            
            return {
                "hash": parts[0],
                "author": parts[1],
                "email": parts[2],
                "date": parts[3],
                "subject": parts[4],
            }
            
        except GitCommandError as e:
            if "bad revision" in e.stderr.lower() or "unknown revision" in e.stderr.lower():
                raise CommitNotFoundError(commit_hash, str(repo_path)) from e
            raise  # pragma: no cover

    def get_diff(self, commit_hash: str, repo_path: Optional[Path] = None) -> str:
        """Get the full diff for a commit.
        
        Args:
            commit_hash: Commit hash to diff
            repo_path: Path to repository (uses src_path by default)
            
        Returns:
            The full diff as a string
            
        Raises:
            CommitNotFoundError: If commit not found
        """
        if repo_path is None:
            repo_path = self.src_path
        
        if not self._repo_exists(repo_path):
            raise GitError(f"Repository not found: {repo_path}")
        
        try:
            returncode, stdout, stderr = self._run_git(
                ["diff", f"{commit_hash}^..{commit_hash}", "--"],
                repo_path=repo_path,
            )
            
            if returncode != 0:
                raise CommitNotFoundError(commit_hash, str(repo_path))
            
            return stdout
            
        except GitCommandError as e:
            if "bad revision" in e.stderr.lower() or "unknown revision" in e.stderr.lower():
                raise CommitNotFoundError(commit_hash, str(repo_path)) from e
            raise  # pragma: no cover

    def get_file_content_at_commit(
        self,
        path: str,
        commit_hash: str,
        repo_path: Optional[Path] = None,
    ) -> str:
        """Get the content of a file at a specific commit.
        
        Args:
            path: File path relative to repository root
            commit_hash: Commit hash
            repo_path: Path to repository (uses src_path by default)
            
        Returns:
            File content as a string
            
        Raises:
            CommitNotFoundError: If commit not found
            FileNotFoundError: If file not found at that commit
        """
        if repo_path is None:
            repo_path = self.src_path
        
        if not self._repo_exists(repo_path):
            raise GitError(f"Repository not found: {repo_path}")
        
        try:
            returncode, stdout, stderr = self._run_git(
                ["show", f"{commit_hash}:{path}"],
                repo_path=repo_path,
            )
            
            if returncode != 0:  # pragma: no cover
                if "exists on disk, but not in" in stderr:  # pragma: no cover
                    raise FileNotFoundError(f"File {path} not found at commit {commit_hash}")  # pragma: no cover
                raise CommitNotFoundError(commit_hash, str(repo_path))  # pragma: no cover

            return stdout

        except GitCommandError as e:
            if "exists on disk, but not in" in e.stderr:
                raise FileNotFoundError(f"File {path} not found at commit {commit_hash}") from e
            if "bad revision" in e.stderr.lower() or "unknown revision" in e.stderr.lower():
                raise CommitNotFoundError(commit_hash, str(repo_path)) from e
            raise  # pragma: no cover
    
    def get_branches(self, repo_path: Optional[Path] = None, remote: bool = False) -> List[str]:
        """Get list of branches in a repository.
        
        Args:
            repo_path: Path to repository (uses src_path by default)
            remote: Whether to list remote branches
            
        Returns:
            List of branch names
        """
        if repo_path is None:
            repo_path = self.src_path
        
        if not self._repo_exists(repo_path):
            raise GitError(f"Repository not found: {repo_path}")
        
        cmd = ["branch"]
        if remote:
            cmd.append("-r")
        
        returncode, stdout, stderr = self._run_git(
            cmd,
            repo_path=repo_path,
        )
        
        if returncode != 0:  # pragma: no cover
            return []  # pragma: no cover

        branches = []
        for line in stdout.strip().split("\n"):
            # Remove leading indicators (*, +, etc.)
            branch = re.sub(r"^[*\+ ]*\s*", "", line.strip())
            if branch:
                branches.append(branch)
        
        return branches
    
    def get_file_list_at_commit(
        self,
        commit_hash: str,
        repo_path: Optional[Path] = None,
    ) -> List[str]:
        """Get list of files changed in a commit.
        
        Args:
            commit_hash: Commit hash
            repo_path: Path to repository (uses src_path by default)
            
        Returns:
            List of file paths
        """
        if repo_path is None:
            repo_path = self.src_path
        
        if not self._repo_exists(repo_path):
            raise GitError(f"Repository not found: {repo_path}")
        
        try:
            returncode, stdout, stderr = self._run_git(
                ["diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash, "--"],
                repo_path=repo_path,
            )
            
            if returncode != 0:  # pragma: no cover
                raise CommitNotFoundError(commit_hash, str(repo_path))  # pragma: no cover

            files = [f.strip() for f in stdout.strip().split("\n") if f.strip()]
            return files

        except GitCommandError as e:
            if "bad revision" in e.stderr.lower() or "unknown revision" in e.stderr.lower():
                raise CommitNotFoundError(commit_hash, str(repo_path)) from e
            raise  # pragma: no cover
    
    def get_latest_commit_hash(self, repo_path: Optional[Path] = None, branch: str = "main") -> str:
        """Get the latest commit hash from a branch.
        
        Args:
            repo_path: Path to repository (uses src_path by default)
            branch: Branch name
            
        Returns:
            Commit hash
        """
        if repo_path is None:
            repo_path = self.src_path
        
        if not self._repo_exists(repo_path):
            raise GitError(f"Repository not found: {repo_path}")

        if not re.fullmatch(r"[a-zA-Z0-9_./-]+", branch):
            raise ValueError(f"Invalid branch name: {branch}")

        returncode, stdout, stderr = self._run_git(
            ["rev-parse", f"origin/{branch}"],
            repo_path=repo_path,
        )
        
        if returncode != 0:  # pragma: no cover
            raise GitError(f"Failed to get latest commit for {branch}: {stderr}")  # pragma: no cover

        return stdout.strip()
