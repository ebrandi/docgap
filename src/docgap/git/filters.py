"""Pre-filter logic for commit analysis."""
import logging
import re
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class CommitFilter:
    """Filter commits based on heuristics to skip irrelevant ones."""
    
    def __init__(self, skip_patterns: Optional[List[str]] = None,
                 skip_paths: Optional[List[str]] = None,
                 skip_files: Optional[List[str]] = None,
                 skip_bots: Optional[List[str]] = None):
        """Initialize the filter.
        
        Args:
            skip_patterns: Regex patterns to skip (match against subject)
            skip_paths: Path prefixes to skip (match against file paths)
            skip_files: Specific filenames to skip
            skip_bots: Email patterns to skip (match against author email)
        """
        self.skip_patterns = skip_patterns or []
        self.skip_paths = skip_paths or ['contrib/', 'sys/contrib/', '.github/']
        self.skip_files = skip_files or ['Makefile', '.gitignore', 'UPDATING', 'ObsoleteFiles.inc']
        self.skip_bots = skip_bots or []
        
        # Compile regex patterns
        self._pattern_regexes = []
        for pattern in self.skip_patterns:
            try:
                self._pattern_regexes.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                logger.warning("Invalid skip pattern ignored: %s: %s", pattern, e)
        
        # Bot email patterns (exact match)
        self._bot_patterns = [p.lower() for p in self.skip_bots]
    
    def should_skip(self, commit: Dict[str, any]) -> tuple[bool, str]:
        """Determine if a commit should be skipped.
        
        Args:
            commit: Dictionary with commit data (hash, subject, files, author, email)
            
        Returns:
            Tuple of (should_skip, reason)
        """
        subject = commit.get('subject', '')
        files = commit.get('files', [])
        author = commit.get('author', '')
        email = commit.get('email', '')
        
        # Check subject patterns
        for regex in self._pattern_regexes:
            if regex.search(subject):
                return True, 'subject_pattern'
        
        # Check for merge commits (subject starts with "Merge" or has multiple parents)
        if subject.startswith('Merge'):
            return True, 'merge_commit'
        
        # Check for vendor imports (path starts with contrib/ or sys/contrib/)
        for file_path in files or []:
            if file_path.startswith('contrib/') or file_path.startswith('sys/contrib/'):
                return True, 'vendor_import'
        
        # Check for MFC commits
        if 'MFC' in subject or 'MFS' in subject:
            return True, 'mfc_commit'
        
        # Check for commits only touching skip files
        if files:
            # Filter out files that are in skip_files
            non_skip_files = [f for f in files if f not in self.skip_files]
            if not non_skip_files:
                return True, 'skip_files_only'
        
        # Check for bot commits
        email_lower = email.lower() if email else ''
        for bot_pattern in self._bot_patterns:
            if bot_pattern in email_lower:
                return True, 'bot_author'
        
        return False, 'none'
    
    def filter_commits(self, commits: List[Dict[str, any]]) -> tuple[List[Dict], Dict[str, int]]:
        """Filter a list of commits.
        
        Args:
            commits: List of commit dictionaries
            
        Returns:
            Tuple of (filtered_commits, statistics)
            where statistics contains: total, skipped, accepted
        """
        filtered = []
        stats = {'total': len(commits), 'skipped': 0, 'accepted': 0}
        
        for commit in commits:
            should_skip, reason = self.should_skip(commit)
            if should_skip:
                commit['skip_reason'] = reason
                commit['filtered'] = True
                stats['skipped'] += 1
            else:
                commit['filtered'] = False
                stats['accepted'] += 1
                filtered.append(commit)
        
        return filtered, stats


def default_filter() -> CommitFilter:
    """Return a CommitFilter with default patterns from architecture spec."""
    skip_patterns = ['^Merge ', '^MFC ', '^MFS ', '^Revert ']
    skip_paths = ['contrib/', 'sys/contrib/', '.github/']
    skip_files = ['Makefile', '.gitignore', 'UPDATING', 'ObsoleteFiles.inc']
    
    return CommitFilter(
        skip_patterns=skip_patterns,
        skip_paths=skip_paths,
        skip_files=skip_files
    )
