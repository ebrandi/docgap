"""Tests for new CLI commands: validate, heal, reprocess, reset, purge."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from docgap.cli.main import main
from docgap.db import Database, init_database


def _create_test_config(config_path, data_dir):
    """Create a minimal valid config file for CLI tests."""
    config_path.write_text(f"""
general:
  data_dir: {data_dir}
  log_level: debug

repositories:
  freebsd_src:
    path: {data_dir}/repos/freebsd-src
    remote: https://github.com/freebsd/freebsd-src.git
    branches:
      - main
  freebsd_doc:
    path: {data_dir}/repos/freebsd-doc
    remote: https://github.com/freebsd/freebsd-doc.git

llm:
  provider: ollama
  base_url: http://localhost:11434
  model: test-model
  temperature: 0.1
  max_context: 524288
  timeout: 120

detection:
  confidence_threshold_accept: 0.80
  confidence_threshold_reject: 0.50
  skip_patterns: []
  skip_paths: []
  skip_files: []

generation:
  validate_mdoc: false
  validate_asciidoc: false
  max_retries: 1

review:
  auto_submit:
    enabled: false

notification:
  enabled: false
  from_address: test@example.com
  smtp_host: localhost
""")


def _init_db(data_dir):
    """Initialize the database and return the path."""
    db_path = str(data_dir / "docgap.sqlite")
    init_database(db_path)
    return db_path


class TestValidateCommand:
    """Tests for the validate command."""

    def test_validate_shows_checks(self, temp_dir):
        """validate should show [OK] or [WARN] for each check."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)

        # Mock LLM client so no real network call is made
        with patch("docgap.cli.commands.OllamaClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.is_healthy.return_value = False
            mock_client_cls.return_value = mock_client

            result = runner.invoke(main, ["-c", str(config_path), "validate"])

        assert "[OK]" in result.output or "[WARN]" in result.output


class TestHealCommand:
    """Tests for the heal command."""

    def test_heal_no_issues(self, temp_dir):
        """heal on a clean DB should report no issues / no actions taken."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        mock_heal_result = {
            "stale_runs": [],
            "incomplete_stage2": [],
            "retryable_errors": [],
        }

        with patch("docgap.orchestrator.reprocessor.ReprocessRunner.heal",
                   return_value=mock_heal_result):
            result = runner.invoke(main, ["-c", str(config_path), "heal"])

        assert result.exit_code == 0
        # With no issues, no "issue(s) found" summary line should appear
        assert "issue(s) found" not in result.output

    def test_heal_help(self, temp_dir):
        """heal --help should list --fix and --dry-run options."""
        runner = CliRunner()
        result = runner.invoke(main, ["heal", "--help"])

        assert "--fix" in result.output
        assert "--dry-run" in result.output


class TestReprocessCommand:
    """Tests for the reprocess command."""

    def test_reprocess_no_args(self, temp_dir):
        """reprocess with no args should print an error message."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, ["-c", str(config_path), "reprocess"])

        assert result.exit_code != 0
        assert "Error" in result.output or "provide" in result.output

    def test_reprocess_not_found(self, temp_dir):
        """reprocess with a non-existent hash should exit non-zero."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        with patch("docgap.orchestrator.reprocessor.ReprocessRunner.reprocess_commit",
                   side_effect=Exception("Commit not found: fakehash000")):
            result = runner.invoke(main, [
                "-c", str(config_path), "reprocess", "fakehash000"
            ])

        assert result.exit_code != 0

    def test_reprocess_help(self, temp_dir):
        """reprocess --help should show all major options."""
        runner = CliRunner()
        result = runner.invoke(main, ["reprocess", "--help"])

        assert "--failed" in result.output
        assert "--pending" in result.output
        assert "--stage1" in result.output
        assert "--stage2" in result.output
        assert "--since" in result.output
        assert "--dry-run" in result.output


class TestResetCommand:
    """Tests for the reset command."""

    def test_reset_not_found(self, temp_dir):
        """reset with a hash that does not exist should report not found."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, [
            "-c", str(config_path), "reset", "deadbeef0000", "--confirm"
        ])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_reset_with_confirm(self, temp_dir):
        """reset --confirm on an existing commit should change status to pending."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        db_path = _init_db(temp_dir)

        db = Database(db_path)
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id,
            "hash": "abc123def456",
            "author": "Test User",
            "email": "test@example.com",
            "date": "2026-04-03T10:00:00Z",
            "subject": "Add new feature",
            "status": "needs_doc",
            "classification": "NEEDS_DOC",
        })

        result = runner.invoke(main, [
            "-c", str(config_path), "reset", "abc123def456", "--confirm"
        ])

        assert result.exit_code == 0
        assert "reset" in result.output.lower() or "pending" in result.output.lower()

        updated = db.get_commit_by_hash("abc123def456")
        assert updated["status"] == "pending"


class TestPurgeCommand:
    """Tests for the purge command."""

    def test_purge_no_matches(self, temp_dir):
        """purge --before future date on empty DB should report no matches."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, [
            "-c", str(config_path), "purge",
            "--before", "2030-01-01T00:00:00Z",
            "--confirm",
        ])

        assert result.exit_code == 0
        assert "no commits" in result.output.lower()

    def test_purge_help(self, temp_dir):
        """purge --help should show --before option."""
        runner = CliRunner()
        result = runner.invoke(main, ["purge", "--help"])

        assert "--before" in result.output
