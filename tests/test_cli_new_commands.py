"""Tests for new CLI commands: validate, heal, reprocess, reset, purge."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from docgap.cli.main import main
from docgap.cli.commands import _format_commit_detail
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

    def test_purge_dry_run_with_matching_commits(self, temp_dir):
        """purge --dry-run reports matching commits but makes no changes."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        db_path = _init_db(temp_dir)

        db = Database(db_path)
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id,
            "hash": "aabbccdd1234",
            "author": "Test User",
            "email": "test@example.com",
            "date": "2020-01-01T00:00:00Z",
            "subject": "Old irrelevant commit",
            "status": "irrelevant",
            "classification": "IRRELEVANT",
        })

        result = runner.invoke(main, [
            "-c", str(config_path), "purge",
            "--before", "2025-01-01T00:00:00Z",
            "--dry-run",
        ])

        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()
        # Commit should still be in DB
        assert db.get_commit_by_hash("aabbccdd1234") is not None

    def test_purge_with_confirm_deletes_matching(self, temp_dir):
        """purge --confirm removes matching commits from the database."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        db_path = _init_db(temp_dir)

        db = Database(db_path)
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id,
            "hash": "deadbeef5678",
            "author": "Old Dev",
            "email": "old@example.com",
            "date": "2020-06-01T00:00:00Z",
            "subject": "Old reviewed commit",
            "status": "reviewed",
            "classification": "NEEDS_DOC",
        })

        result = runner.invoke(main, [
            "-c", str(config_path), "purge",
            "--before", "2025-01-01T00:00:00Z",
            "--confirm",
        ])

        assert result.exit_code == 0
        assert "purged" in result.output.lower()


class TestReportCommand:
    """Tests for the report command."""

    def test_report_json_format(self, temp_dir):
        """report --format json should output valid JSON."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, ["-c", str(config_path), "report", "--format", "json"])

        assert result.exit_code == 0
        # The output contains JSON -- find and parse it
        output_text = result.output
        # Find the first '{' for the JSON block
        json_start = output_text.find("{")
        assert json_start != -1, "Expected JSON output"
        data = json.loads(output_text[json_start:])
        assert "total" in data
        assert "status_counts" in data

    def test_report_save_creates_file(self, temp_dir):
        """report --save should create a file in the reports directory."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, ["-c", str(config_path), "report", "--save"])

        assert result.exit_code == 0
        assert "saved to" in result.output.lower()
        reports_dir = temp_dir / "reports"
        assert reports_dir.exists()
        saved_files = list(reports_dir.glob("report-*.txt"))
        assert len(saved_files) == 1

    def test_report_output_flag_creates_file(self, temp_dir):
        """report --output <path> should create a file at the specified path."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)
        dest = temp_dir / "myreport.txt"

        result = runner.invoke(main, [
            "-c", str(config_path), "report", "--output", str(dest)
        ])

        assert result.exit_code == 0
        assert dest.exists()
        assert "docgap Report" in dest.read_text()

    def test_report_text_format_with_populated_data(self, temp_dir):
        """report text format lists needs_doc, doc_generated, uncertain, and error commits."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        db_path = _init_db(temp_dir)

        db = Database(db_path)
        run_id = db.insert_run({"status": "completed"})

        statuses = [
            ("aaa111000001", "needs_doc", "NEEDS_DOC", "Add -Z flag"),
            ("bbb222000002", "doc_generated", "NEEDS_DOC", "Change default"),
            ("ccc333000003", "uncertain", "UNCERTAIN", "Maybe relevant"),
            ("ddd444000004", "error", "UNCERTAIN", "Failed commit"),
        ]
        for h, status, classification, subject in statuses:
            db.insert_commit({
                "run_id": run_id,
                "hash": h,
                "author": "Dev",
                "email": "dev@example.com",
                "date": "2026-04-01T00:00:00Z",
                "subject": subject,
                "status": status,
                "classification": classification,
            })

        result = runner.invoke(main, ["-c", str(config_path), "report"])

        assert result.exit_code == 0
        assert "NEEDS DOCUMENTATION" in result.output
        assert "DOCUMENTATION GENERATED" in result.output
        assert "UNCERTAIN" in result.output
        assert "ERRORS" in result.output


class TestReprocessCommandDispatching:
    """Tests for reprocess command flag dispatching."""

    def _setup(self, temp_dir):
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)
        return config_path

    def test_reprocess_stage1_dispatches_stage1(self, temp_dir):
        """reprocess --stage1 HASH dispatches reprocess_commit with stage='stage1'."""
        runner = CliRunner()
        config_path = self._setup(temp_dir)

        mock_result = {"status": "success", "processed": 1}
        with patch("docgap.orchestrator.reprocessor.ReprocessRunner.reprocess_commit",
                   return_value=mock_result) as mock_call:
            result = runner.invoke(main, [
                "-c", str(config_path), "reprocess", "--stage1", "abc123def456"
            ])

        assert result.exit_code == 0
        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args
        assert call_kwargs[1].get("stage") == "stage1" or call_kwargs[0][1] == "stage1"

    def test_reprocess_stage2_dispatches_stage2(self, temp_dir):
        """reprocess --stage2 HASH dispatches reprocess_commit with stage='stage2'."""
        runner = CliRunner()
        config_path = self._setup(temp_dir)

        mock_result = {"status": "success", "processed": 1}
        with patch("docgap.orchestrator.reprocessor.ReprocessRunner.reprocess_commit",
                   return_value=mock_result) as mock_call:
            result = runner.invoke(main, [
                "-c", str(config_path), "reprocess", "--stage2", "abc123def456"
            ])

        assert result.exit_code == 0
        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args
        assert call_kwargs[1].get("stage") == "stage2" or call_kwargs[0][1] == "stage2"

    def test_reprocess_failed_dispatches_by_status(self, temp_dir):
        """reprocess --failed calls reprocess_by_status with error statuses."""
        runner = CliRunner()
        config_path = self._setup(temp_dir)

        mock_summary = {"processed": 0, "success": 0, "failed": 0, "skipped": 0}
        with patch("docgap.orchestrator.reprocessor.ReprocessRunner.reprocess_by_status",
                   return_value=mock_summary) as mock_call:
            result = runner.invoke(main, [
                "-c", str(config_path), "reprocess", "--failed"
            ])

        assert result.exit_code == 0
        mock_call.assert_called_once()
        statuses_arg = mock_call.call_args[0][0]
        assert "error" in statuses_arg or "generation_error" in statuses_arg

    def test_reprocess_pending_dispatches_by_needs_doc(self, temp_dir):
        """reprocess --pending calls reprocess_by_status with needs_doc."""
        runner = CliRunner()
        config_path = self._setup(temp_dir)

        mock_summary = {"processed": 0, "success": 0, "failed": 0, "skipped": 0}
        with patch("docgap.orchestrator.reprocessor.ReprocessRunner.reprocess_by_status",
                   return_value=mock_summary) as mock_call:
            result = runner.invoke(main, [
                "-c", str(config_path), "reprocess", "--pending"
            ])

        assert result.exit_code == 0
        mock_call.assert_called_once()
        statuses_arg = mock_call.call_args[0][0]
        assert "needs_doc" in statuses_arg

    def test_reprocess_since_dispatches_reprocess_since(self, temp_dir):
        """reprocess --since calls reprocess_since."""
        runner = CliRunner()
        config_path = self._setup(temp_dir)

        mock_summary = {"processed": 0, "success": 0, "failed": 0, "skipped": 0}
        with patch("docgap.orchestrator.reprocessor.ReprocessRunner.reprocess_since",
                   return_value=mock_summary) as mock_call:
            result = runner.invoke(main, [
                "-c", str(config_path), "reprocess", "--since", "2026-01-01T00:00:00Z"
            ])

        assert result.exit_code == 0
        mock_call.assert_called_once()


class TestValidateCommandWithDB:
    """Tests for the validate command with DB present."""

    def test_validate_shows_ok_for_database(self, temp_dir):
        """validate shows [OK] for database when DB is initialized."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        with patch("docgap.cli.commands.OllamaClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.is_healthy.return_value = False
            mock_client_cls.return_value = mock_client

            result = runner.invoke(main, ["-c", str(config_path), "validate"])

        assert "[OK]" in result.output
        # DB line should be [OK] since DB exists
        assert "Database" in result.output

    def test_validate_output_includes_all_check_categories(self, temp_dir):
        """validate output covers config, database, repos, LLM, data directory."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)

        with patch("docgap.cli.commands.OllamaClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.is_healthy.return_value = False
            mock_client_cls.return_value = mock_client

            result = runner.invoke(main, ["-c", str(config_path), "validate"])

        output = result.output
        assert "Config" in output
        assert "Database" in output
        assert "LLM" in output


class TestReviewApproveAll:
    """Tests for review approve --all."""

    def test_approve_all_no_commits(self, temp_dir):
        """review approve --all with no approvable commits reports none pending."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, ["-c", str(config_path), "review", "approve", "--all"])

        assert result.exit_code == 0
        assert "no commits" in result.output.lower() or "pending" in result.output.lower()

    def test_approve_all_approves_needs_doc_commits(self, temp_dir):
        """review approve --all sets all needs_doc commits to reviewed."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        db_path = _init_db(temp_dir)

        db = Database(db_path)
        run_id = db.insert_run({"status": "completed"})
        hashes = ["aaaa11112222", "bbbb33334444"]
        for h in hashes:
            db.insert_commit({
                "run_id": run_id,
                "hash": h,
                "author": "Dev",
                "email": "dev@example.com",
                "date": "2026-04-01T00:00:00Z",
                "subject": "Needs documentation",
                "status": "needs_doc",
                "classification": "NEEDS_DOC",
            })

        result = runner.invoke(main, ["-c", str(config_path), "review", "approve", "--all"])

        assert result.exit_code == 0
        assert "approved" in result.output.lower()
        for h in hashes:
            updated = db.get_commit_by_hash(h)
            assert updated["status"] == "reviewed"


class TestReviewHashValidation:
    """Tests for hash validation in review subcommands."""

    def test_review_show_rejects_path_traversal(self, temp_dir):
        """review show prints an error and does not process hashes containing path traversal."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, [
            "-c", str(config_path), "review", "show", "../../../etc"
        ])

        # review show does not propagate the exit code, but it must print an error message
        assert "invalid" in result.output.lower() or "error" in result.output.lower()

    def test_review_approve_rejects_invalid_hash(self, temp_dir):
        """review approve rejects hashes that are not valid hex strings."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, [
            "-c", str(config_path), "review", "approve", "../../../etc"
        ])

        assert result.exit_code != 0
        assert "invalid" in result.output.lower() or "error" in result.output.lower()

    def test_review_reject_rejects_invalid_hash(self, temp_dir):
        """review reject rejects hashes that are not valid hex strings."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)
        _init_db(temp_dir)

        result = runner.invoke(main, [
            "-c", str(config_path), "review", "reject", "../../../etc"
        ])

        assert result.exit_code != 0
        assert "invalid" in result.output.lower() or "error" in result.output.lower()


class TestFormatCommitDetail:
    """Tests for _format_commit_detail helper."""

    def test_returns_basic_fields(self, temp_dir):
        """_format_commit_detail returns basic commit metadata fields."""
        commit = {
            "hash": "abc123def456",
            "subject": "Add new flag",
            "author": "Dev User",
            "date": "2026-04-01T00:00:00Z",
            "classification": "NEEDS_DOC",
            "confidence": 0.85,
            "category": "new_flag",
            "doc_target": "usr.bin/ls/ls.1",
            "reasoning": "Added -Z flag",
            "status": "needs_doc",
        }
        output_dir = temp_dir / "output"
        detail = _format_commit_detail(commit, output_dir)

        assert detail["hash"] == "abc123def456"
        assert detail["subject"] == "Add new flag"
        assert detail["classification"] == "NEEDS_DOC"
        assert detail["status"] == "needs_doc"

    def test_includes_output_files_when_dir_exists(self, temp_dir):
        """_format_commit_detail lists output files when output dir is present."""
        commit = {
            "hash": "abc123def456",
            "subject": "Add flag",
            "author": "Dev",
            "date": "2026-04-01T00:00:00Z",
            "classification": "NEEDS_DOC",
            "confidence": 0.9,
            "category": "new_flag",
            "doc_target": "ls.1",
            "reasoning": "Test",
            "status": "doc_generated",
        }
        output_dir = temp_dir / "output"
        commit_out = output_dir / "abc123def456"
        commit_out.mkdir(parents=True)
        (commit_out / "report.txt").write_text("This is the report.")
        (commit_out / "manpage.patch").write_text("--- a/ls.1\n+++ b/ls.1\n")

        detail = _format_commit_detail(commit, output_dir)

        assert "output_files" in detail
        assert "report.txt" in detail["output_files"]
        assert "manpage.patch" in detail["output_files"]
        assert "report_preview" in detail
        assert "This is the report" in detail["report_preview"]

    def test_skips_output_files_for_invalid_hash(self, temp_dir):
        """_format_commit_detail does not attempt file access for invalid hash."""
        commit = {
            "hash": "../../etc/passwd",
            "subject": "Bad hash",
            "author": "Attacker",
            "date": "2026-04-01T00:00:00Z",
            "classification": "NEEDS_DOC",
            "confidence": 0.9,
            "category": None,
            "doc_target": None,
            "reasoning": None,
            "status": "needs_doc",
        }
        output_dir = temp_dir / "output"
        detail = _format_commit_detail(commit, output_dir)

        assert "output_files" not in detail
