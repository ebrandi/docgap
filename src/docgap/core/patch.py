"""Patch parsing and formatting utilities."""
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Hunk:
    """A single hunk in a unified diff."""
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: List[str]


@dataclass
class Patch:
    """A parsed unified diff patch."""
    old_file: Optional[str]
    new_file: Optional[str]
    hunks: List[Hunk]


class PatchParser:
    """Parser for unified diff format patches."""
    
    def parse(self, patch_text: str) -> Patch:
        """Parse a unified diff patch.
        
        Args:
            patch_text: Full patch text
            
        Returns:
            Patch object with hunks
        """
        lines = patch_text.split('\n')
        
        old_file: Optional[str] = None
        new_file: Optional[str] = None
        hunks: List[Hunk] = []
        
        current_hunk: Optional[Hunk] = None
        
        for line in lines:
            # Parse file paths
            if line.startswith('--- '):
                # Old file (strip leading 'a/' if present)
                old_file = line[4:].strip()
                if old_file.startswith('a/'):
                    old_file = old_file[2:]
            elif line.startswith('+++ '):
                # New file (strip leading 'b/' if present)
                new_file = line[4:].strip()
                if new_file.startswith('b/'):
                    new_file = new_file[2:]
            
            # Parse hunk headers: @@ -old_start,old_lines +new_start,new_lines @@
            elif line.startswith('@@ '):
                # Check if this is a hunk header
                match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
                if match:
                    if current_hunk:
                        hunks.append(current_hunk)
                    
                    old_start = int(match.group(1))
                    old_lines = int(match.group(2)) if match.group(2) else 1
                    new_start = int(match.group(3))
                    new_lines = int(match.group(4)) if match.group(4) else 1
                    
                    current_hunk = Hunk(
                        old_start=old_start,
                        old_lines=old_lines,
                        new_start=new_start,
                        new_lines=new_lines,
                        lines=[]
                    )
            
            # Parse hunk content lines
            elif current_hunk is not None:
                if line.startswith('+') or line.startswith('-') or line.startswith(' '):
                    current_hunk.lines.append(line)
        
        # Don't forget the last hunk
        if current_hunk:
            hunks.append(current_hunk)
        
        return Patch(
            old_file=old_file,
            new_file=new_file,
            hunks=hunks,
        )
    
    def format_patch(self, patch: Patch) -> str:
        """Format a patch object as unified diff text.
        
        Args:
            patch: Patch object
            
        Returns:
            Patch text
        """
        lines = []
        
        # File paths
        if patch.old_file:
            lines.append(f"--- a/{patch.old_file}")
        if patch.new_file:
            lines.append(f"+++ b/{patch.new_file}")
        
        # Hunks
        for hunk in patch.hunks:
            lines.append(f"@@ -{hunk.old_start},{hunk.old_lines} +{hunk.new_start},{hunk.new_lines} @@")
            for line in hunk.lines:
                lines.append(line)
        
        return '\n'.join(lines)
