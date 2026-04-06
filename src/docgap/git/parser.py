"""Log parser for extracting commit metadata from git log output."""
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgap.config.schema import Config
from docgap.git.fetcher import GitFetcher
from docgap.git.filters import CommitFilter, default_filter


class LogParser:
    """Parse git log output and apply pre-filters."""
    
    def __init__(self, git_fetcher: GitFetcher, config: Optional[Config] = None):
        """Initialize the parser.
        
        Args:
            git_fetcher: GitFetcher instance for git operations
            config: Configuration with filter patterns (optional)
        """
        self.git_fetcher = git_fetcher
        self.config = config
        
        # Initialize filter with config patterns
        skip_patterns = []
        skip_paths = ['contrib/', 'sys/contrib/', '.github/']
        skip_files = ['Makefile', '.gitignore', 'UPDATING', 'ObsoleteFiles.inc']
        skip_bots = []
        
        if config and config.detection:
            skip_patterns = config.detection.skip_patterns or []
            skip_paths = config.detection.skip_paths or skip_paths
            skip_files = config.detection.skip_files or skip_files
            # We might add bot detection in future config
        
        self.filter = CommitFilter(
            skip_patterns=skip_patterns,
            skip_paths=skip_paths,
            skip_files=skip_files,
            skip_bots=skip_bots
        )
        
        # Statistics tracking
        self._stats: Dict[str, Any] = {
            'total_parsed': 0,
            'filtered_out': 0,
            'accepted': 0,
            'merge_skipped': 0,
            'vendor_import_skipped': 0,
            'mfc_skipped': 0,
            'skip_files_skipped': 0,
            'bot_skipped': 0,
            'error': None,  # Will be a string on error
        }
    
    def _parse_git_log_line(self, line: str) -> Optional[Dict[str, str]]:
        """Parse a single git log line.
        
        Format: %H|%an|%ae|%aI|%s
        Returns: Dict with hash, author, email, date, subject or None if malformed
        """
        if not line.strip():
            return None
        
        parts = line.split('|', 4)
        if len(parts) < 5:
            return None
        
        return {
            'hash': parts[0],
            'author': parts[1],
            'email': parts[2],
            'date': parts[3],
            'subject': parts[4],
        }
    
    def _get_files_for_commit(self, commit_hash: str, repo_path: Optional[Path] = None) -> List[str]:
        """Get the list of files changed in a commit."""
        try:
            cwd = str(repo_path) if repo_path else str(self.git_fetcher.src_path)
            result = subprocess.run(
                ['git', '-c', f'safe.directory={cwd}',
                 'diff-tree', '--no-commit-id', '--name-only', '-r', commit_hash],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            if result.returncode != 0:
                return []
            
            files = [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
            return files
            
        except (subprocess.TimeoutExpired, OSError):
            return []
    
    def parse_commits(self, since_timestamp: Optional[str] = None,
                      branch: str = 'main') -> List[Dict[str, Any]]:
        """Parse commits since a given timestamp.
        
        Args:
            since_timestamp: ISO 8601 timestamp to start from (optional)
            branch: Branch to parse from
            
        Returns:
            List of commit dictionaries with metadata and files
        """
        # Build git log command
        src_path = str(self.git_fetcher.src_path)
        cmd = ['git', '-c', f'safe.directory={src_path}', '-C', src_path, 'log']
        
        if since_timestamp:
            cmd.extend(['--since', since_timestamp])
        
        # Bare repos store branches as refs/heads/<branch>, not
        # refs/remotes/origin/<branch>, so use the branch name directly.
        ref = branch if self.git_fetcher.bare else f'origin/{branch}'
        cmd.extend([
            '--format=%H|%an|%ae|%aI|%s',
            '--name-only',
            ref,
        ])
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            if result.returncode != 0:
                # Handle errors gracefully
                if 'UNKNOWN REVISION' in result.stderr.upper():
                    return []
                raise RuntimeError(f"Git log failed: {result.stderr}")
            
            # Parse the output
            commits = []
            current_commit: Optional[Dict[str, Any]] = None
            files: List[str] = []
            
            lines = result.stdout.strip().split('\n')
            
            for line in lines:
                if not line.strip():
                    continue
                
                # Check if this is a commit metadata line (5 pipe-separated parts)
                parts = line.split('|', 4)
                if len(parts) == 5:
                    # Save previous commit if exists
                    if current_commit is not None:
                        current_commit['files'] = files
                        commits.append(current_commit)
                    
                    # Start new commit
                    current_commit = self._parse_git_log_line(line)
                    files = []
                else:
                    # This is a file path
                    if line.strip():
                        files.append(line.strip())
            
            # Don't forget the last commit
            if current_commit is not None:
                current_commit['files'] = files
                commits.append(current_commit)
            
            # Update stats
            self._stats['total_parsed'] += len(commits)
            
            return commits
            
        except subprocess.TimeoutExpired:
            import click
            click.echo("WARNING: Git log timed out", err=True)
            return []
        except Exception as e:
            import click
            click.echo(f"WARNING: Git log failed: {e}", err=True)
            self._stats['error'] = str(e)
            return []
    
    def filter_commits(self, commits: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Filter a list of commits and track statistics.
        
        Args:
            commits: List of commit dictionaries
            
        Returns:
            Tuple of (filtered_commits, statistics)
        """
        # Reset filter stats
        self._stats = {
            'total_parsed': 0,
            'filtered_out': 0,
            'accepted': 0,
            'merge_skipped': 0,
            'vendor_import_skipped': 0,
            'mfc_skipped': 0,
            'skip_files_skipped': 0,
            'bot_skipped': 0,
            'error': None,  # Reset error
        }
        
        filtered = []
        
        for commit in commits:
            should_skip, reason = self.filter.should_skip(commit)
            
            if should_skip:
                commit['skip_reason'] = reason
                commit['filtered'] = True
                self._stats['filtered_out'] += 1
                self._stats[f'{reason}_skipped'] += 1
            else:
                commit['filtered'] = False
                self._stats['accepted'] += 1
                filtered.append(commit)
        
        statistics = self._stats.copy()
        statistics['total'] = len(commits)
        
        return filtered, statistics
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get current filtering statistics.
        
        Returns:
            Dictionary with statistics. Note: 'error' key may be a string if an error occurred.
        """
        return self._stats.copy()
    
    def parse_and_filter(self, since_timestamp: Optional[str] = None,
                         branch: str = 'main') -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Parse and filter commits in one step.
        
        Args:
            since_timestamp: ISO 8601 timestamp (optional)
            branch: Branch to parse from
            
        Returns:
            Tuple of (filtered_commits, statistics)
        """
        commits = self.parse_commits(since_timestamp, branch)
        return self.filter_commits(commits)
