"""Tests for CLI commands."""
from click.testing import CliRunner

from docgap.cli.main import main


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


class TestCLIInit:
    """Test the init command."""

    def test_init_command(self, temp_dir):
        """Test initializing the database."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)

        result = runner.invoke(main, [
            "--config", str(config_path),
            "init"
        ])

        assert result.exit_code == 0
        assert "initialized" in result.output.lower()


class TestCLIStatus:
    """Test the status command."""

    def test_status_command_no_db(self, temp_dir):
        """Test status with no database."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)

        result = runner.invoke(main, [
            "--config", str(config_path),
            "status"
        ])

        assert result.exit_code == 1
        assert "not initialized" in result.output.lower()

    def test_status_command_with_db(self, temp_dir):
        """Test status with database."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, temp_dir)

        # First initialize
        runner.invoke(main, ["--config", str(config_path), "init"])

        # Then check status
        result = runner.invoke(main, ["--config", str(config_path), "status"])

        assert result.exit_code == 0
        assert "status" in result.output.lower()


class TestCLIHelp:
    """Test help commands."""

    def test_main_help(self):
        """Test main help output."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "freebsd" in result.output.lower()
        assert "documentation" in result.output.lower()

    def test_run_help(self):
        """Test run command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])

        assert result.exit_code == 0
        assert "pipeline" in result.output.lower()

    def test_review_help(self):
        """Test review command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["review", "--help"])

        assert result.exit_code == 0
        assert "review" in result.output.lower()


class TestCLIConfigShow:
    """Test the config show command."""

    def test_config_show(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--config", str(config_path), "config", "show"])
        assert result.exit_code == 0
        assert "configuration" in result.output.lower()
        assert str(temp_dir) in result.output


class TestCLIDryRun:
    """Test the --dry-run flag on the run command."""

    def test_run_dry_run(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.PipelineRunner") as MockRunner:
            MockRunner.return_value.run_manual.return_value = 0
            result = runner.invoke(main, ["--config", str(config_path), "run", "--dry-run"])
            assert result.exit_code == 0
            assert "dry run" in result.output.lower()
            # Verify dry_run was passed to run_manual
            MockRunner.return_value.run_manual.assert_called_once()
            call_args = MockRunner.return_value.run_manual.call_args
            assert call_args[1].get("dry_run") is True or (
                len(call_args[0]) > 1 and call_args[0][1] is True
            )


class TestCLIStateMachine:
    """Test state machine enforcement on review commands."""

    def test_approve_pending_commit_rejected(self, temp_dir):
        """Cannot approve a commit in 'pending' state."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "bad1", "status": "pending",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test", "files": [],
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "review", "approve", "bad1"])
        assert result.exit_code != 0 or "cannot approve" in result.output.lower()

    def test_reject_irrelevant_commit_rejected(self, temp_dir):
        """Cannot reject a commit in 'irrelevant' state."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "bad2", "status": "irrelevant",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test", "files": [],
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "review", "reject", "bad2"])
        assert result.exit_code != 0 or "cannot reject" in result.output.lower()

    def test_approve_stores_reviewer_info(self, temp_dir):
        """Approving stores reviewer name and timestamp."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "audit1", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test", "files": [],
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "review", "approve", "audit1"])
        assert result.exit_code == 0
        db = Database(str(temp_dir / "docgap.sqlite"))
        commit = db.get_commit_by_hash("audit1")
        assert commit["status"] == "reviewed"
        assert commit["reviewer"] is not None
        assert commit["reviewed_at"] is not None
        db.close()

    def test_reject_stores_feedback(self, temp_dir):
        """Rejecting with --reason stores feedback."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "audit2", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test", "files": [],
        })
        db.close()
        result = runner.invoke(
            main,
            ["--config", str(config_path), "review", "reject", "audit2", "--reason", "not relevant"],
        )
        assert result.exit_code == 0
        db = Database(str(temp_dir / "docgap.sqlite"))
        commit = db.get_commit_by_hash("audit2")
        assert commit["status"] == "false_positive"
        assert commit["feedback"] == "not relevant"
        db.close()


class TestCLIStateMachineDocGenerated:
    """Test state machine with doc_generated state (post-Stage 2 flow)."""

    def test_approve_doc_generated_succeeds(self, temp_dir):
        """Can approve a commit in 'doc_generated' state (the production flow)."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "docgen1", "status": "doc_generated",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test with docs", "files": [],
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "review", "approve", "docgen1"])
        assert result.exit_code == 0
        assert "approved" in result.output.lower()
        db = Database(str(temp_dir / "docgap.sqlite"))
        commit = db.get_commit_by_hash("docgen1")
        assert commit["status"] == "reviewed"
        db.close()

    def test_reject_doc_generated_succeeds(self, temp_dir):
        """Can reject a commit in 'doc_generated' state."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "docgen2", "status": "doc_generated",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test with docs", "files": [],
        })
        db.close()
        result = runner.invoke(main, [
            "--config", str(config_path), "review", "reject", "docgen2",
            "--reason", "not needed",
        ])
        assert result.exit_code == 0
        db = Database(str(temp_dir / "docgap.sqlite"))
        commit = db.get_commit_by_hash("docgen2")
        assert commit["status"] == "false_positive"
        assert commit["feedback"] == "not needed"
        db.close()

    def test_reject_uncertain_succeeds(self, temp_dir):
        """Can reject a commit in 'uncertain' state (human triage)."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "uncertain1", "status": "uncertain",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "maybe needs docs", "files": [],
        })
        db.close()
        result = runner.invoke(main, [
            "--config", str(config_path), "review", "reject", "uncertain1",
        ])
        assert result.exit_code == 0
        db = Database(str(temp_dir / "docgap.sqlite"))
        commit = db.get_commit_by_hash("uncertain1")
        assert commit["status"] == "false_positive"
        db.close()

    def test_approve_reviewed_rejected(self, temp_dir):
        """Cannot approve an already-reviewed commit."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "alreadydone", "status": "reviewed",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "already done", "files": [],
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "review", "approve", "alreadydone"])
        assert result.exit_code != 0 or "cannot approve" in result.output.lower()

    def test_approve_with_reviewer_option(self, temp_dir):
        """--reviewer stores the reviewer name in the database."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "reviewer1", "status": "doc_generated",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test reviewer", "files": [],
        })
        db.close()
        result = runner.invoke(main, [
            "--config", str(config_path), "review", "approve",
            "--reviewer", "john_doe", "reviewer1",
        ])
        assert result.exit_code == 0
        db = Database(str(temp_dir / "docgap.sqlite"))
        commit = db.get_commit_by_hash("reviewer1")
        assert commit["reviewer"] == "john_doe"
        assert commit["reviewed_at"] is not None
        db.close()

    def test_reject_with_reviewer_option(self, temp_dir):
        """--reviewer stores the reviewer name on reject."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "reviewer2", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test reviewer reject", "files": [],
        })
        db.close()
        result = runner.invoke(main, [
            "--config", str(config_path), "review", "reject",
            "--reviewer", "jane_doe", "--reason", "not needed", "reviewer2",
        ])
        assert result.exit_code == 0
        db = Database(str(temp_dir / "docgap.sqlite"))
        commit = db.get_commit_by_hash("reviewer2")
        assert commit["reviewer"] == "jane_doe"
        assert commit["feedback"] == "not needed"
        db.close()


class TestCLILogFilters:
    """Test the log command --status filter."""

    def test_log_with_status_filter(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "log1", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "filtered commit", "files": [],
        })
        db.insert_commit({
            "run_id": run_id, "hash": "log2", "status": "irrelevant",
            "author": "B", "email": "b@b", "date": "2026-04-03",
            "subject": "other commit", "files": [],
        })
        db.close()
        result = runner.invoke(
            main, ["--config", str(config_path), "log", "--status", "needs_doc"]
        )
        assert result.exit_code == 0
        assert "filtered commit" in result.output.lower() or "log1" in result.output


class TestCLIConfigShowError:
    """Test config show error path."""

    def test_config_show_error(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        config_path.write_text("invalid: yaml: [")
        result = runner.invoke(main, ["--config", str(config_path), "config", "show"])
        # Should show error
        assert result.exit_code != 0 or "error" in result.output.lower()


class TestCLIRunCommand:
    """Test the run command."""

    def test_run_with_since(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.PipelineRunner") as MockRunner:
            MockRunner.return_value.run_manual.return_value = 0
            result = runner.invoke(main, [
                "--config", str(config_path), "run",
                "--since", "2026-04-01T00:00:00Z"
            ])
            assert result.exit_code == 0
            assert "2026-04-01" in result.output
            MockRunner.return_value.run_manual.assert_called_once()


class TestCLIReviewShowWithFiles:
    """Test review show with output files."""

    def test_review_show_commit_found(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "show1", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test commit", "files": [],
            "classification": "NEEDS_DOC", "confidence": 0.85,
            "category": "new_flag", "reasoning": "Added flag",
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "review", "show", "show1"])
        assert result.exit_code == 0
        assert "show1" in result.output
        assert "NEEDS_DOC" in result.output

    def test_review_show_commit_not_found(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        result = runner.invoke(main, ["--config", str(config_path), "review", "show", "nonexistent"])
        assert "not found" in result.output.lower()


class TestCLIReportFormat:
    """Test the --format flag on report command."""

    def test_report_json_format(self, temp_dir):
        """Test report with --format json output."""
        import json
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])

        result = runner.invoke(main, ["--config", str(config_path), "report", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "status_counts" in data
        assert "total" in data

    def test_report_txt_format(self, temp_dir):
        """Test report with --format txt (default)."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])

        result = runner.invoke(main, ["--config", str(config_path), "report", "--format", "txt"])
        assert result.exit_code == 0
        assert "docgap Report" in result.output

    def test_report_default_format_is_txt(self, temp_dir):
        """Test report defaults to txt format."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])

        result = runner.invoke(main, ["--config", str(config_path), "report"])
        assert result.exit_code == 0
        assert "docgap Report" in result.output


class TestCLIBulkApproval:
    """Test bulk approval functionality."""

    def test_approve_all(self, temp_dir):
        """Test approving all pending commits."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])

        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        for i in range(3):
            db.insert_commit({
                "run_id": run_id, "hash": f"bulkhash{i}", "status": "needs_doc",
                "author": "A", "email": "a@a", "date": "2026-04-03T10:00:00Z",
                "subject": f"test commit {i}", "files": [],
            })
        db.close()

        result = runner.invoke(main, [
            "--config", str(config_path), "review", "approve", "--all",
        ])
        assert result.exit_code == 0
        assert "3" in result.output

        db = Database(str(temp_dir / "docgap.sqlite"))
        for i in range(3):
            commit = db.get_commit_by_hash(f"bulkhash{i}")
            assert commit["status"] == "reviewed"
        db.close()

    def test_approve_all_with_since(self, temp_dir):
        """Test approving commits with --since filter."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])

        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "oldhash", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-01-01T00:00:00Z",
            "subject": "old commit", "files": [],
        })
        db.insert_commit({
            "run_id": run_id, "hash": "newhash", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03T10:00:00Z",
            "subject": "new commit", "files": [],
        })
        db.close()

        result = runner.invoke(main, [
            "--config", str(config_path), "review", "approve",
            "--all", "--since", "2026-04-01T00:00:00Z",
        ])
        assert result.exit_code == 0
        assert "1" in result.output

        db = Database(str(temp_dir / "docgap.sqlite"))
        old = db.get_commit_by_hash("oldhash")
        assert old["status"] == "needs_doc"  # not approved
        new = db.get_commit_by_hash("newhash")
        assert new["status"] == "reviewed"  # approved
        db.close()

    def test_approve_all_no_pending(self, temp_dir):
        """Test approve --all with no pending commits."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])

        result = runner.invoke(main, [
            "--config", str(config_path), "review", "approve", "--all",
        ])
        assert result.exit_code == 0
        assert "no commits" in result.output.lower()

    def test_approve_no_hash_no_all_errors(self, temp_dir):
        """Test approve with neither hash nor --all shows error."""
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))

        result = runner.invoke(main, [
            "--config", str(config_path), "review", "approve",
        ])
        assert result.exit_code != 0

    def test_review_show_with_output_files(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "showfiles", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test", "files": [],
            "reasoning": "Added stuff",
        })
        db.close()
        # Create output files
        output_dir = temp_dir / "output" / "showfiles"
        output_dir.mkdir(parents=True)
        (output_dir / "report.txt").write_text("This is the report content")
        (output_dir / "manpage.patch").write_text("--- a/file\n+++ b/file\n")
        result = runner.invoke(main, ["--config", str(config_path), "review", "show", "showfiles"])
        assert result.exit_code == 0
        assert "report" in result.output.lower()
        assert "patch" in result.output.lower()

    def test_review_show_no_db(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--config", str(config_path), "review", "show", "abc"])
        assert "not initialized" in result.output.lower()


class TestCLIReviewList:
    """Test review list command."""

    def test_review_list_no_db(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--config", str(config_path), "review", "list"])
        assert "not initialized" in result.output.lower()

    def test_review_list_empty(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        result = runner.invoke(main, ["--config", str(config_path), "review", "list"])
        assert result.exit_code == 0
        assert "no commits need review" in result.output.lower()

    def test_review_list_with_commits(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "revlist1", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test review list", "files": [],
            "classification": "NEEDS_DOC", "confidence": 0.9,
            "category": "new_flag",
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "review", "list"])
        assert result.exit_code == 0
        assert "revlist1" in result.output


class TestCLIReviewApproveReject:
    """Test review approve/reject edge cases."""

    def test_approve_no_db(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--config", str(config_path), "review", "approve", "abc"])
        assert "not initialized" in result.output.lower()

    def test_approve_commit_not_found(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        result = runner.invoke(main, ["--config", str(config_path), "review", "approve", "nonexistent"])
        assert "not found" in result.output.lower()

    def test_reject_no_db(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--config", str(config_path), "review", "reject", "abc"])
        assert "not initialized" in result.output.lower()

    def test_reject_commit_not_found(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        result = runner.invoke(main, ["--config", str(config_path), "review", "reject", "nonexistent"])
        assert "not found" in result.output.lower()

    def test_reject_without_reason(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "rejnoreason", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test", "files": [],
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "review", "reject", "rejnoreason"])
        assert result.exit_code == 0
        db = Database(str(temp_dir / "docgap.sqlite"))
        commit = db.get_commit_by_hash("rejnoreason")
        assert commit["status"] == "false_positive"
        assert commit.get("feedback") is None
        db.close()


class TestCLILogCommand:
    """Test log command paths."""

    def test_log_no_db(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--config", str(config_path), "log"])
        assert "not initialized" in result.output.lower()

    def test_log_empty(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        result = runner.invoke(main, ["--config", str(config_path), "log"])
        assert result.exit_code == 0
        assert "no commits" in result.output.lower()

    def test_log_with_since_filter(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "logsince1", "status": "pending",
            "author": "A", "email": "a@a", "date": "2026-04-03T10:00:00Z",
            "subject": "recent commit", "files": [],
        })
        db.insert_commit({
            "run_id": run_id, "hash": "logsince2", "status": "pending",
            "author": "B", "email": "b@b", "date": "2025-01-01T10:00:00Z",
            "subject": "old commit", "files": [],
        })
        db.close()
        result = runner.invoke(main, [
            "--config", str(config_path), "log",
            "--since", "2026-01-01T00:00:00Z"
        ])
        assert result.exit_code == 0
        assert "logsince1" in result.output

    def test_log_with_invalid_since(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "loginvsince", "status": "pending",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test", "files": [],
        })
        db.close()
        result = runner.invoke(main, [
            "--config", str(config_path), "log",
            "--since", "not-a-date"
        ])
        assert result.exit_code == 0


class TestCLIReportCommand:
    """Test report command."""

    def test_report_no_db(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--config", str(config_path), "report"])
        assert "not initialized" in result.output.lower()

    def test_report_with_data(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "rpt1", "status": "needs_doc",
            "author": "A", "email": "a@a", "date": "2026-04-03",
            "subject": "test", "files": [],
        })
        db.insert_commit({
            "run_id": run_id, "hash": "rpt2", "status": "irrelevant",
            "author": "B", "email": "b@b", "date": "2026-04-03",
            "subject": "test2", "files": [],
        })
        db.close()
        result = runner.invoke(main, ["--config", str(config_path), "report"])
        assert result.exit_code == 0
        assert "report" in result.output.lower()
        assert "needs_doc" in result.output


class TestCLIInitCommand:
    """Test init command error path."""

    def test_init_error(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        # Config that points to unwritable dir
        config_path.write_text("invalid yaml: [")
        result = runner.invoke(main, ["--config", str(config_path), "init"])
        assert result.exit_code != 0 or "error" in result.output.lower()


class TestCLIStatusWithOutput:
    """Test status with output directory."""

    def test_status_no_last_run(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from unittest.mock import patch
        with patch("docgap.cli.commands.OllamaClient") as MockClient:
            MockClient.return_value.is_healthy.return_value = False
            result = runner.invoke(main, ["--config", str(config_path), "status"])
        assert result.exit_code == 0
        assert "no runs recorded" in result.output.lower()

    def test_status_with_output_dir(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        # Create some output files
        output_dir = temp_dir / "output"
        output_dir.mkdir(exist_ok=True)
        (output_dir / "testfile.txt").write_text("test")
        from unittest.mock import patch
        with patch("docgap.cli.commands.OllamaClient") as MockClient:
            MockClient.return_value.is_healthy.return_value = True
            result = runner.invoke(main, ["--config", str(config_path), "status"])
        assert result.exit_code == 0
        assert "files:" in result.output.lower()


class TestCLIVerbose:
    """Test verbose flag."""

    def test_verbose_flag(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--verbose", "--config", str(config_path), "init"])
        assert result.exit_code == 0


class TestCLIStatusWithLastRun:
    """Test status showing last run details."""

    def test_status_with_last_run(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed", "started_at": "2026-04-03T12:00:00Z"})
        db.update_run(run_id, {
            "status": "completed",
            "commits_processed": 10,
            "commits_flagged": 3,
        })
        db.close()
        from unittest.mock import patch
        with patch("docgap.cli.commands.OllamaClient") as MockClient:
            MockClient.return_value.is_healthy.return_value = True
            result = runner.invoke(main, ["--config", str(config_path), "status"])
        assert result.exit_code == 0
        assert "last run" in result.output.lower()

    def test_status_no_output_dir(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        # Remove output dir if exists
        import shutil
        output_dir = temp_dir / "output"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        from unittest.mock import patch
        with patch("docgap.cli.commands.OllamaClient") as MockClient:
            MockClient.return_value.is_healthy.return_value = False
            result = runner.invoke(main, ["--config", str(config_path), "status"])
        assert result.exit_code == 0
        assert "not yet created" in result.output.lower()

    def test_status_exception(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.get_config", side_effect=Exception("config error")):
            result = runner.invoke(main, ["--config", str(config_path), "status"])
        # Should handle error gracefully
        assert "error" in result.output.lower()


class TestCLILogSinceFiltering:
    """Test log --since date filtering edge cases."""

    def test_log_since_with_empty_commit_date(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "emptydate", "status": "pending",
            "author": "A", "email": "a@a", "date": "",
            "subject": "empty date commit", "files": [],
        })
        db.close()
        result = runner.invoke(main, [
            "--config", str(config_path), "log",
            "--since", "2026-01-01T00:00:00Z"
        ])
        assert result.exit_code == 0

    def test_log_since_with_unparseable_commit_date(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        runner.invoke(main, ["--config", str(config_path), "init"])
        from docgap.db import Database
        db = Database(str(temp_dir / "docgap.sqlite"))
        run_id = db.insert_run({"status": "completed"})
        db.insert_commit({
            "run_id": run_id, "hash": "baddate", "status": "pending",
            "author": "A", "email": "a@a", "date": "not-a-date",
            "subject": "bad date commit", "files": [],
        })
        db.close()
        result = runner.invoke(main, [
            "--config", str(config_path), "log",
            "--since", "2026-01-01T00:00:00Z"
        ])
        assert result.exit_code == 0


class TestCLIReviewListError:
    """Test review list exception handler."""

    def test_review_list_exception(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.get_config", side_effect=Exception("broken")):
            result = runner.invoke(main, ["--config", str(config_path), "review", "list"])
        assert "error" in result.output.lower()


class TestCLIReviewShowError:
    """Test review show exception handler."""

    def test_review_show_exception(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.get_config", side_effect=Exception("broken")):
            result = runner.invoke(main, ["--config", str(config_path), "review", "show", "abc"])
        assert "error" in result.output.lower()


class TestCLIReviewApproveError:
    """Test review approve exception handler."""

    def test_review_approve_exception(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.get_config", side_effect=Exception("broken")):
            result = runner.invoke(main, ["--config", str(config_path), "review", "approve", "abc"])
        assert "error" in result.output.lower()


class TestCLIReviewRejectError:
    """Test review reject exception handler."""

    def test_review_reject_exception(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.get_config", side_effect=Exception("broken")):
            result = runner.invoke(main, ["--config", str(config_path), "review", "reject", "abc"])
        assert "error" in result.output.lower()


class TestCLILogError:
    """Test log exception handler."""

    def test_log_exception(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.get_config", side_effect=Exception("broken")):
            result = runner.invoke(main, ["--config", str(config_path), "log"])
        assert "error" in result.output.lower()


class TestCLIInitError:
    """Test init exception handler."""

    def test_init_exception(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.get_config", side_effect=Exception("broken")):
            result = runner.invoke(main, ["--config", str(config_path), "init"])
        assert "error" in result.output.lower()


class TestCLIReportError:
    """Test report exception handler."""

    def test_report_exception(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        from unittest.mock import patch
        with patch("docgap.cli.commands.get_config", side_effect=Exception("broken")):
            result = runner.invoke(main, ["--config", str(config_path), "report"])
        assert "error" in result.output.lower()


class TestCLIConfigShowNonDict:
    """Test config show with non-dict section value."""

    def test_config_show_non_dict_section(self, temp_dir):
        runner = CliRunner()
        config_path = temp_dir / "config.yaml"
        _create_test_config(config_path, str(temp_dir))
        result = runner.invoke(main, ["--config", str(config_path), "config", "show"])
        assert result.exit_code == 0
        # Config has nested dataclasses so some values will be dicts, but
        # the output should display all sections
        assert "configuration" in result.output.lower()
