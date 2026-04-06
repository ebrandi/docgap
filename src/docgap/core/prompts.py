"""Prompt loading and formatting for LLM stages."""
from pathlib import Path
from typing import Dict, List, Optional

from docgap.config.schema import Config
from docgap.git.fetcher import GitFetcher

# Default detection prompt template
DETECTION_PROMPT = """
You are a FreeBSD documentation triage specialist. Your job is to determine
whether a source code commit requires an update to FreeBSD's official
documentation (manpages, handbook, or other FDP-maintained documents).

Classify the commit as one of:
- NEEDS_DOC: The commit introduces or changes user-visible behavior that
  should be documented. Examples: new command flags, new syscalls, changed
  defaults, new sysctl knobs, new commands/daemons, changed output formats.
- IRRELEVANT: The commit does not affect user-visible behavior. Examples:
  internal refactoring, code style changes, compiler warning fixes,
  performance optimizations with no behavioral change, test additions.
- UNCERTAIN: You cannot confidently determine whether documentation is needed.

Respond with a JSON object:
{{
  "classification": "NEEDS_DOC" | "IRRELEVANT" | "UNCERTAIN",
  "confidence": 0.0-1.0,
  "category": "new_flag" | "new_command" | "changed_default" | "new_syscall" |
               "new_sysctl" | "changed_output" | "new_ioctl" | "api_change" |
               "other" | null,
  "doc_target": "path/to/affected/manpage.N or handbook section" | null,
  "reasoning": "Brief explanation of why this classification was chosen"
}}

IMPORTANT: When in doubt, classify as UNCERTAIN rather than NEEDS_DOC.
False positives damage trust. It is better to miss a change than to
incorrectly flag one.
"""


def load_prompt(template_name: str, default_prompt: str = "") -> str:
    """Load a prompt template from filesystem or use default.
    
    Args:
        template_name: Name of the template (e.g., 'detection')
        default_prompt: Fallback prompt if template not found
        
    Returns:
        Prompt template string
    """
    # Try to load from system config path
    system_path = Path(f"/usr/local/etc/docgap/prompts/{template_name}.txt")
    if system_path.exists():
        return system_path.read_text()
    
    # Try to load from local config
    local_path = Path(__file__).parent.parent.parent / "prompts" / f"{template_name}.txt"
    if local_path.exists():
        return local_path.read_text()
    
    # Return default if template not found
    return default_prompt


def format_classification_prompt(commit_data: Dict[str, any],
                                 diff: str,
                                 prompt_template: str = DETECTION_PROMPT) -> str:
    """Format a classification prompt with commit data and diff.
    
    Args:
        commit_data: Dictionary with commit metadata (hash, author, subject, etc.)
        diff: Full diff text for the commit
        prompt_template: System prompt template
        
    Returns:
        Full prompt string with commit context
    """
    prompt = f"{prompt_template}\n\n---\n\n"
    
    # Add commit metadata
    prompt += "## Commit Metadata\n\n"
    prompt += f"- Hash: {commit_data.get('hash', 'N/A')}\n"
    prompt += f"- Author: {commit_data.get('author', 'N/A')}\n"
    prompt += f"- Subject: {commit_data.get('subject', 'N/A')}\n"
    
    # Add file list
    files = commit_data.get('files', [])
    if files:
        prompt += f"- Files: {', '.join(files[:20])}\n"
        if len(files) > 20:
            prompt += f"- ... and {len(files) - 20} more files\n"
    
    # Add diff
    prompt += "\n---\n\n"
    prompt += "## Diff\n\n"
    prompt += f"```diff\n{diff}\n```\n"
    
    # Add instructions
    prompt += "\n---\n\n"
    prompt += "Based on the above information, classify this commit.\n"
    
    return prompt


def load_prompts(config: Config) -> Dict[str, str]:
    """Load all prompts from config or defaults.
    
    Args:
        config: Configuration object
        
    Returns:
        Dictionary mapping prompt names to template strings
    """
    prompts = {
        "detection": load_prompt("detection", DETECTION_PROMPT),
    }
    
    return prompts
