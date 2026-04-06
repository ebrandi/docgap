"""Tests for prompt loading and formatting."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from docgap.core.prompts import (
    load_prompt,
    format_classification_prompt,
    load_prompts,
    DETECTION_PROMPT,
)


class TestLoadPrompt:
    """Test load_prompt filesystem loading."""

    def test_returns_default_when_not_found(self):
        result = load_prompt("__nonexistent_prompt_xyz__", default_prompt="default content")
        assert result == "default content"

    def test_returns_empty_string_when_no_default(self):
        result = load_prompt("__nonexistent_prompt_xyz__")
        assert result == ""

    def test_reads_from_system_path_when_exists(self, tmp_path):
        """load_prompt reads from system path when it exists."""
        content = "system prompt content"
        system_file = tmp_path / "detection.txt"
        system_file.write_text(content)

        mock_system = MagicMock()
        mock_system.exists.return_value = True
        mock_system.read_text.return_value = content

        call_count = [0]

        def path_factory(arg):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_system
            return Path(arg)

        with patch("docgap.core.prompts.Path", side_effect=path_factory):
            result = load_prompt("detection", default_prompt="fallback")

        assert result == content

    def test_reads_from_local_path_when_system_missing(self, tmp_path):
        """load_prompt reads from local path when system path doesn't exist."""
        content = "local prompt content"

        # Write a real prompt file to the package's prompts directory sibling
        import docgap.core.prompts as prompts_module
        prompts_dir = Path(prompts_module.__file__).parent.parent.parent / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        target = prompts_dir / "__test_local_prompt__.txt"
        target.write_text(content)
        try:
            # System path won't exist; local path will
            result = load_prompt("__test_local_prompt__", default_prompt="fallback")
            assert result == content
        finally:
            target.unlink(missing_ok=True)


class TestFormatClassificationPrompt:
    """Test format_classification_prompt output."""

    def test_contains_commit_hash(self):
        commit_data = {"hash": "abc123", "author": "Dev", "subject": "Fix bug", "files": []}
        result = format_classification_prompt(commit_data, "diff content")
        assert "abc123" in result

    def test_contains_author(self):
        commit_data = {"hash": "abc123", "author": "Test Author", "subject": "Fix", "files": []}
        result = format_classification_prompt(commit_data, "diff")
        assert "Test Author" in result

    def test_contains_subject(self):
        commit_data = {"hash": "abc123", "author": "Dev", "subject": "Add new flag", "files": []}
        result = format_classification_prompt(commit_data, "diff")
        assert "Add new flag" in result

    def test_contains_diff(self):
        commit_data = {"hash": "abc123", "author": "Dev", "subject": "Fix", "files": []}
        result = format_classification_prompt(commit_data, "+int new_flag;")
        assert "+int new_flag;" in result

    def test_contains_files_list(self):
        commit_data = {
            "hash": "abc123",
            "author": "Dev",
            "subject": "Fix",
            "files": ["usr.bin/ls/ls.c", "usr.bin/ls/ls.h"],
        }
        result = format_classification_prompt(commit_data, "diff")
        assert "usr.bin/ls/ls.c" in result

    def test_truncates_long_file_list(self):
        commit_data = {
            "hash": "abc123",
            "author": "Dev",
            "subject": "Fix",
            "files": [f"file{i}.c" for i in range(30)],
        }
        result = format_classification_prompt(commit_data, "diff")
        assert "more files" in result

    def test_uses_custom_template(self):
        commit_data = {"hash": "abc123", "author": "Dev", "subject": "Fix", "files": []}
        custom_template = "CUSTOM_SYSTEM_PROMPT"
        result = format_classification_prompt(commit_data, "diff", prompt_template=custom_template)
        assert "CUSTOM_SYSTEM_PROMPT" in result

    def test_no_files_key(self):
        commit_data = {"hash": "abc123", "author": "Dev", "subject": "Fix"}
        result = format_classification_prompt(commit_data, "diff")
        assert "abc123" in result


class TestLoadPrompts:
    """Test load_prompts returns complete dict."""

    def test_returns_detection_key(self, test_config):
        prompts = load_prompts(test_config)
        assert "detection" in prompts

    def test_detection_prompt_non_empty(self, test_config):
        prompts = load_prompts(test_config)
        assert len(prompts["detection"]) > 0

    def test_default_prompt_contains_classification_values(self, test_config):
        prompts = load_prompts(test_config)
        assert "NEEDS_DOC" in prompts["detection"]
        assert "IRRELEVANT" in prompts["detection"]
        assert "UNCERTAIN" in prompts["detection"]
