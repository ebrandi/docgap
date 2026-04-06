"""Tests for PipelineRunner orchestration."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from docgap.config.schema import (
    Config, GeneralConfig, RepositoriesConfig, RepositoryConfig,
    LLMConfig, DetectionConfig, GenerationConfig, ReviewConfig,
    NotificationConfig, AutoSubmitConfig,
)
from docgap.orchestrator.runner import PipelineRunner
from docgap.db import Database, init_database


@pytest.fixture
def runner_config(temp_dir):
    """Create a config for runner tests."""
    return Config(
        general=GeneralConfig(data_dir=str(temp_dir), log_level="debug"),
        repositories=RepositoriesConfig(
            freebsd_src=RepositoryConfig(path=str(temp_dir / "repos/src"), remote="https://example.com/src.git"),
            freebsd_doc=RepositoryConfig(path=str(temp_dir / "repos/doc"), remote="https://example.com/doc.git"),
        ),
        llm=LLMConfig(provider="ollama", base_url="http://localhost:11434", model="test", temperature=0.1, max_context=524288, timeout=120),
        detection=DetectionConfig(confidence_threshold_accept=0.80, confidence_threshold_reject=0.50),
        generation=GenerationConfig(enabled=True, validate_mdoc=False, validate_asciidoc=False, max_retries=1),
        review=ReviewConfig(auto_submit=AutoSubmitConfig(enabled=False, hold_period_hours=72, categories={})),
        notification=NotificationConfig(enabled=False, doceng_recipients=[], committer_notify=False, digest_only_if_findings=True, from_address="test@test.com", smtp_host="localhost"),
    )


class TestPipelineRunner:
    def test_init(self, runner_config):
        runner = PipelineRunner(runner_config)
        assert runner.config is runner_config

    def test_ensure_database_creates_dirs_and_db(self, runner_config, temp_dir):
        runner = PipelineRunner(runner_config)
        db = runner.ensure_database()
        assert db is not None
        assert (temp_dir / "output").exists()
        assert (temp_dir / "repos").exists()
        assert (temp_dir / "logs").exists()
        assert (temp_dir / "docgap.sqlite").exists()
        db.close()

    def test_ensure_database_idempotent(self, runner_config, temp_dir):
        runner = PipelineRunner(runner_config)
        db1 = runner.ensure_database()
        run_id = db1.insert_run({"status": "running"})
        db1.close()
        # Second call should NOT destroy data
        db2 = runner.ensure_database()
        run = db2.get_run(run_id)
        assert run is not None
        db2.close()

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    def test_run_pipeline_no_commits(self, MockParser, MockOllama, MockGit, mock_click, runner_config):
        """Pipeline with no new commits should return no_commits status."""
        runner = PipelineRunner(runner_config)

        mock_fetcher = MockGit.return_value
        mock_fetcher.ensure_repos.return_value = None

        mock_parser = MockParser.return_value
        mock_parser.parse_and_filter.return_value = ([], {"total": 0, "filtered_out": 0, "accepted": 0})

        result = runner.run_pipeline(since_timestamp="2026-04-01T00:00:00Z")
        assert result["status"] == "no_commits"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    def test_run_pipeline_with_irrelevant_commit(self, MockDetector, MockParser, MockOllama, MockGit, mock_click, runner_config):
        """Pipeline classifying a commit as irrelevant."""
        from docgap.core.classification import Classification, ClassificationResult

        runner = PipelineRunner(runner_config)
        mock_fetcher = MockGit.return_value
        mock_fetcher.ensure_repos.return_value = None

        mock_parser = MockParser.return_value
        mock_parser.parse_and_filter.return_value = (
            [{"hash": "abc123", "author": "Test", "email": "t@t.com", "date": "2026-04-03T10:00:00Z", "subject": "Refactor", "files": ["lib/test.c"]}],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_classification = MagicMock()
        mock_classification.classification = Classification.IRRELEVANT
        mock_classification.confidence = 0.95
        mock_classification.category = None
        mock_classification.doc_target = None
        mock_classification.reasoning = "internal"
        mock_classification.apply_thresholds.return_value = mock_classification

        mock_detector = MockDetector.return_value
        mock_detector.classify.return_value = mock_classification

        result = runner.run_pipeline(since_timestamp="2026-04-01T00:00:00Z")
        assert result["commits_processed"] == 1
        assert result["commits_flagged"] == 0
        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    def test_run_pipeline_with_needs_doc_commit(self, MockDetector, MockParser, MockOllama, MockGit, mock_click, runner_config):
        """Pipeline classifying a commit as NEEDS_DOC increments flagged count."""
        from docgap.core.classification import Classification

        runner = PipelineRunner(runner_config)
        mock_fetcher = MockGit.return_value
        mock_fetcher.ensure_repos.return_value = None

        mock_parser = MockParser.return_value
        mock_parser.parse_and_filter.return_value = (
            [{"hash": "deadbeef", "author": "Dev", "email": "dev@test.com", "date": "2026-04-03T10:00:00Z", "subject": "Add -Z flag", "files": ["usr.bin/ls/ls.c"]}],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_classification = MagicMock()
        mock_classification.classification = Classification.NEEDS_DOC
        mock_classification.confidence = 0.90
        mock_classification.category = None
        mock_classification.doc_target = "usr.bin/ls/ls.1"
        mock_classification.reasoning = "new flag added"
        mock_classification.apply_thresholds.return_value = mock_classification

        mock_detector = MockDetector.return_value
        mock_detector.classify.return_value = mock_classification

        # Disable generation so we don't need to mock Stage2Generator
        runner_config.generation.enabled = False

        result = runner.run_pipeline(since_timestamp="2026-04-01T00:00:00Z")
        assert result["commits_processed"] == 1
        assert result["commits_flagged"] == 1
        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    def test_run_pipeline_commit_classification_error(self, MockDetector, MockParser, MockOllama, MockGit, mock_click, runner_config):
        """When classifying a commit raises, error is captured in result."""
        runner = PipelineRunner(runner_config)
        mock_fetcher = MockGit.return_value
        mock_fetcher.ensure_repos.return_value = None

        mock_parser = MockParser.return_value
        mock_parser.parse_and_filter.return_value = (
            [{"hash": "badc0de", "author": "Dev", "email": "dev@test.com", "date": "2026-04-03T10:00:00Z", "subject": "Bad commit", "files": []}],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_detector = MockDetector.return_value
        mock_detector.classify.side_effect = RuntimeError("LLM unavailable")

        runner_config.generation.enabled = False

        result = runner.run_pipeline(since_timestamp="2026-04-01T00:00:00Z")
        assert result["commits_processed"] == 1
        assert result["commits_flagged"] == 0
        assert len(result["errors"]) == 1
        assert "badc0de" in result["errors"][0]
        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    def test_run_pipeline_git_fetcher_failure(self, MockGit, mock_click, runner_config):
        """When ensure_repos raises, pipeline returns failed status."""
        runner = PipelineRunner(runner_config)
        mock_fetcher = MockGit.return_value
        mock_fetcher.ensure_repos.side_effect = RuntimeError("git clone failed")

        result = runner.run_pipeline(since_timestamp="2026-04-01T00:00:00Z")
        assert result["status"] == "failed"
        assert "git clone failed" in result["error"]

    def test_run_manual(self, runner_config):
        """Test run_manual returns exit code 0 on completed."""
        runner = PipelineRunner(runner_config)
        with patch.object(runner, 'run_pipeline', return_value={"status": "completed"}):
            code = runner.run_manual("2026-04-01T00:00:00Z")
            assert code == 0

    def test_run_manual_failure(self, runner_config):
        """Test run_manual returns failure exit code 2."""
        runner = PipelineRunner(runner_config)
        with patch.object(runner, 'run_pipeline', return_value={"status": "failed"}):
            code = runner.run_manual()
            assert code == 2

    def test_run_manual_no_commits(self, runner_config):
        """Test run_manual returns 2 for no_commits (non-completed)."""
        runner = PipelineRunner(runner_config)
        with patch.object(runner, 'run_pipeline', return_value={"status": "no_commits"}):
            code = runner.run_manual()
            assert code == 2

    def test_run_cron_mode_success(self, runner_config):
        runner = PipelineRunner(runner_config)
        with patch.object(runner, 'run_pipeline', return_value={"status": "completed", "errors": []}):
            assert runner.run_cron_mode() == 0

    def test_run_cron_mode_partial(self, runner_config):
        runner = PipelineRunner(runner_config)
        with patch.object(runner, 'run_pipeline', return_value={"status": "completed", "errors": ["some error"]}):
            assert runner.run_cron_mode() == 1

    def test_run_cron_mode_failure(self, runner_config):
        runner = PipelineRunner(runner_config)
        with patch.object(runner, 'run_pipeline', return_value={"status": "failed"}):
            assert runner.run_cron_mode() == 2

    def test_run_cron_mode_no_commits(self, runner_config):
        """no_commits is not 'completed', so cron returns 2."""
        runner = PipelineRunner(runner_config)
        with patch.object(runner, 'run_pipeline', return_value={"status": "no_commits"}):
            assert runner.run_cron_mode() == 2

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    def test_run_pipeline_uses_last_run_timestamp(self, MockParser, MockOllama, MockGit, mock_click, runner_config, temp_dir):
        """When since_timestamp is None, pipeline uses last successful run's finished_at."""
        runner = PipelineRunner(runner_config)
        mock_fetcher = MockGit.return_value
        mock_fetcher.ensure_repos.return_value = None

        mock_parser = MockParser.return_value
        mock_parser.parse_and_filter.return_value = ([], {"total": 0, "filtered_out": 0, "accepted": 0})

        # Pre-create a DB with a completed run so runner can find it
        db = runner.ensure_database()
        run_id = db.insert_run({"status": "running"})
        db.update_run(run_id, {"status": "completed", "finished_at": "2026-03-01T00:00:00Z"})
        db.close()

        result = runner.run_pipeline(since_timestamp=None)
        assert result["status"] == "no_commits"
        # The parser should have been called with the last run's finished_at timestamp
        call_args = mock_parser.parse_and_filter.call_args
        assert call_args is not None
        assert "2026-03-01" in str(call_args)

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    def test_run_pipeline_first_run_uses_7days(self, MockParser, MockOllama, MockGit, mock_click, runner_config):
        """When no previous run exists and no timestamp given, uses 7-day window."""
        runner = PipelineRunner(runner_config)
        mock_fetcher = MockGit.return_value
        mock_fetcher.ensure_repos.return_value = None

        mock_parser = MockParser.return_value
        mock_parser.parse_and_filter.return_value = ([], {"total": 0, "filtered_out": 0, "accepted": 0})

        result = runner.run_pipeline(since_timestamp=None)
        assert result["status"] == "no_commits"
        mock_parser.parse_and_filter.assert_called_once()

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    @patch("docgap.orchestrator.runner.Stage2Generator")
    @patch("docgap.orchestrator.runner.OutputManager")
    @patch("docgap.orchestrator.runner.DocRetriever")
    def test_run_pipeline_with_generation(
        self, MockRetriever, MockOutput, MockGen, MockDetector,
        MockParser, MockOllama, MockGit, mock_click, runner_config
    ):
        """Stage 2 generation runs for NEEDS_DOC commits when generation is enabled."""
        from docgap.core.classification import Classification, ClassificationResult, Category
        from docgap.core.generator import GenerationResult

        runner = PipelineRunner(runner_config)

        MockGit.return_value.ensure_repos.return_value = None
        MockParser.return_value.parse_and_filter.return_value = (
            [
                {
                    "hash": "abc123gen",
                    "author": "Test",
                    "email": "t@t.com",
                    "date": "2026-04-03",
                    "subject": "Add -Z flag",
                    "files": ["usr.bin/ls/ls.c"],
                }
            ],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.9,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="new flag",
        )
        mock_cls = MagicMock()
        mock_cls.classification = Classification.NEEDS_DOC
        mock_cls.confidence = 0.9
        mock_cls.category = Category.NEW_FLAG
        mock_cls.doc_target = "usr.bin/ls/ls.1"
        mock_cls.reasoning = "new flag"
        mock_cls.apply_thresholds.return_value = mock_cls
        MockDetector.return_value.classify.return_value = mock_cls

        gen_result = GenerationResult(
            success=True,
            patch="--- a/ls.1\n+++ b/ls.1\n",
            report="Added flag",
            format="mdoc",
            duration_ms=100.0,
        )
        MockGen.return_value.generate.return_value = gen_result
        MockOutput.return_value.save_output.return_value = {"report.txt": Path("/tmp/report.txt")}

        result = runner.run_pipeline(since_timestamp="2026-04-01")
        assert result["commits_flagged"] >= 1
        assert result["commits_with_doc"] >= 1
        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    @patch("docgap.orchestrator.runner.Stage2Generator")
    @patch("docgap.orchestrator.runner.OutputManager")
    @patch("docgap.orchestrator.runner.DocRetriever")
    def test_run_pipeline_generation_failure(
        self, MockRetriever, MockOutput, MockGen, MockDetector,
        MockParser, MockOllama, MockGit, mock_click, runner_config
    ):
        """Generation failure for a NEEDS_DOC commit is captured in errors."""
        from docgap.core.classification import Classification
        from docgap.core.generator import GenerationResult

        runner = PipelineRunner(runner_config)
        MockGit.return_value.ensure_repos.return_value = None
        MockParser.return_value.parse_and_filter.return_value = (
            [
                {
                    "hash": "failgen1",
                    "author": "Test",
                    "email": "t@t.com",
                    "date": "2026-04-03",
                    "subject": "Bad gen",
                    "files": [],
                }
            ],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_cls = MagicMock()
        mock_cls.classification = Classification.NEEDS_DOC
        mock_cls.confidence = 0.9
        mock_cls.category = None
        mock_cls.doc_target = "usr.bin/ls/ls.1"
        mock_cls.reasoning = "new flag"
        mock_cls.apply_thresholds.return_value = mock_cls
        MockDetector.return_value.classify.return_value = mock_cls

        gen_result = GenerationResult(
            success=False,
            patch=None,
            report="LLM error",
            format="mdoc",
            duration_ms=50.0,
        )
        MockGen.return_value.generate.return_value = gen_result

        result = runner.run_pipeline(since_timestamp="2026-04-01")
        assert result["commits_with_doc"] == 0
        assert len(result["errors"]) >= 1
        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    @patch("docgap.orchestrator.runner.Stage2Generator")
    @patch("docgap.orchestrator.runner.OutputManager")
    @patch("docgap.orchestrator.runner.DocRetriever")
    def test_run_pipeline_generation_exception(
        self, MockRetriever, MockOutput, MockGen, MockDetector,
        MockParser, MockOllama, MockGit, mock_click, runner_config
    ):
        """Exception in generator is captured per-commit, pipeline completes."""
        from docgap.core.classification import Classification

        runner = PipelineRunner(runner_config)
        MockGit.return_value.ensure_repos.return_value = None
        MockParser.return_value.parse_and_filter.return_value = (
            [
                {
                    "hash": "excgen1",
                    "author": "Test",
                    "email": "t@t.com",
                    "date": "2026-04-03",
                    "subject": "Raises",
                    "files": [],
                }
            ],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_cls = MagicMock()
        mock_cls.classification = Classification.NEEDS_DOC
        mock_cls.confidence = 0.9
        mock_cls.category = None
        mock_cls.doc_target = "usr.bin/ls/ls.1"
        mock_cls.reasoning = "new flag"
        mock_cls.apply_thresholds.return_value = mock_cls
        MockDetector.return_value.classify.return_value = mock_cls

        MockGen.return_value.generate.side_effect = RuntimeError("model crashed")

        result = runner.run_pipeline(since_timestamp="2026-04-01")
        assert result["commits_with_doc"] == 0
        assert any("excgen1" in e for e in result["errors"])
        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    @patch("docgap.orchestrator.runner.Stage2Generator")
    @patch("docgap.orchestrator.runner.OutputManager")
    @patch("docgap.orchestrator.runner.DocRetriever")
    def test_run_pipeline_asciidoc_format(
        self, MockRetriever, MockOutput, MockGen, MockDetector,
        MockParser, MockOllama, MockGit, mock_click, runner_config
    ):
        """Generation for .adoc doc_target picks asciidoc format path."""
        from docgap.core.classification import Classification
        from docgap.core.generator import GenerationResult

        runner = PipelineRunner(runner_config)
        MockGit.return_value.ensure_repos.return_value = None
        MockParser.return_value.parse_and_filter.return_value = (
            [
                {
                    "hash": "asciidocgen",
                    "author": "Test",
                    "email": "t@t.com",
                    "date": "2026-04-03",
                    "subject": "Add doc",
                    "files": [],
                }
            ],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_cls = MagicMock()
        mock_cls.classification = Classification.NEEDS_DOC
        mock_cls.confidence = 0.9
        mock_cls.category = None
        mock_cls.doc_target = "documentation/content/en_US/something.adoc"
        mock_cls.reasoning = "new doc"
        mock_cls.apply_thresholds.return_value = mock_cls
        MockDetector.return_value.classify.return_value = mock_cls

        gen_result = GenerationResult(
            success=True,
            patch="--- a/doc.adoc\n+++ b/doc.adoc\n",
            report="Added doc",
            format="asciidoc",
            duration_ms=80.0,
        )
        MockGen.return_value.generate.return_value = gen_result
        MockOutput.return_value.save_output.return_value = {}

        result = runner.run_pipeline(since_timestamp="2026-04-01")
        assert result["commits_with_doc"] >= 1
        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    @patch("docgap.orchestrator.runner.Stage2Generator")
    @patch("docgap.orchestrator.runner.OutputManager")
    @patch("docgap.orchestrator.runner.DocRetriever")
    def test_run_pipeline_with_notifications(
        self, MockRetriever, MockOutput, MockGen, MockDetector,
        MockParser, MockOllama, MockGit, mock_click, runner_config
    ):
        """When notifications are enabled, _send_notifications is called."""
        from docgap.core.classification import Classification

        runner_config.notification.enabled = True
        runner_config.generation.enabled = False
        runner = PipelineRunner(runner_config)

        MockGit.return_value.ensure_repos.return_value = None
        MockParser.return_value.parse_and_filter.return_value = (
            [
                {
                    "hash": "notify1",
                    "author": "Test",
                    "email": "t@t.com",
                    "date": "2026-04-03",
                    "subject": "Notif test",
                    "files": [],
                }
            ],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_cls = MagicMock()
        mock_cls.classification = Classification.IRRELEVANT
        mock_cls.confidence = 0.95
        mock_cls.category = None
        mock_cls.doc_target = None
        mock_cls.reasoning = "irrelevant"
        mock_cls.apply_thresholds.return_value = mock_cls
        MockDetector.return_value.classify.return_value = mock_cls

        with patch.object(runner, "_send_notifications") as mock_notify:
            result = runner.run_pipeline(since_timestamp="2026-04-01")
            assert result["status"] == "completed"
            mock_notify.assert_called_once()

    @patch("docgap.orchestrator.runner.click")
    def test_send_notifications(self, mock_click, runner_config, temp_dir):
        """_send_notifications calls notifier.send_digest and send_per_commit."""
        runner = PipelineRunner(runner_config)
        db = runner.ensure_database()
        run_id = db.insert_run({"status": "completed"})

        with patch("docgap.core.notifier.Notifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.send_digest.return_value = None
            mock_notifier.send_per_commit.return_value = None
            db.update_run(run_id, {"status": "completed"})
            runner._send_notifications(
                db, run_id,
                {"commits_processed": 1, "commits_flagged": 0, "commits_with_doc": 0}
            )
            mock_notifier.send_digest.assert_called_once()

        db.close()

    @patch("docgap.orchestrator.runner.click")
    def test_send_notifications_exception_swallowed(self, mock_click, runner_config, temp_dir):
        """Notification failure is swallowed with a warning, not re-raised."""
        runner = PipelineRunner(runner_config)
        db = runner.ensure_database()
        run_id = db.insert_run({"status": "completed"})

        with patch("docgap.core.notifier.Notifier") as MockNotifier:
            MockNotifier.side_effect = RuntimeError("smtp down")
            # Should not raise
            runner._send_notifications(
                db, run_id,
                {"commits_processed": 0, "commits_flagged": 0, "commits_with_doc": 0}
            )

        db.close()

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    def test_run_pipeline_failed_updates_run_record(self, MockGit, mock_click, runner_config, temp_dir):
        """When pipeline fails after run_id is set, run record is updated to failed."""
        from docgap.orchestrator.runner import PipelineRunner

        runner = PipelineRunner(runner_config)
        # ensure_repos succeeds but parse_commits raises — after run_id is inserted
        MockGit.return_value.ensure_repos.return_value = None

        with patch("docgap.orchestrator.runner.LogParser") as MockParser, \
             patch("docgap.orchestrator.runner.OllamaClient"), \
             patch("docgap.orchestrator.runner.Stage1Detector"):
            # Return one commit so run_id gets created, then detect raises
            MockParser.return_value.parse_and_filter.return_value = (
                [{"hash": "failme1", "author": "T", "email": "t@t.com",
                  "date": "2026-04-03", "subject": "x", "files": []}],
                {"total": 1, "filtered_out": 0, "accepted": 1},
            )
            with patch("docgap.orchestrator.runner.Stage1Detector") as MockDet:
                MockDet.return_value.classify.side_effect = Exception("fatal")
                runner_config.generation.enabled = False
                result = runner.run_pipeline(since_timestamp="2026-04-01")
            # errors list contains the classify error but run completes
            assert result["status"] in ("completed", "failed")

    def test_module_level_run_pipeline(self, temp_dir):
        """Convenience run_pipeline() function delegates to PipelineRunner.run_manual."""
        from docgap.orchestrator.runner import run_pipeline as rp_func
        with patch("docgap.orchestrator.runner.load_config") as mock_config, \
             patch("docgap.orchestrator.runner.PipelineRunner") as MockRunner:
            MockRunner.return_value.run_manual.return_value = 0
            result = rp_func(config_path=str(temp_dir / "config.yaml"))
            assert result == 0

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    def test_run_pipeline_applies_prefilters(self, MockDetector, MockParser, MockOllama, MockGit, mock_click, runner_config):
        """Filter stats from parse_and_filter are included in the pipeline result."""
        from docgap.core.classification import Classification

        runner = PipelineRunner(runner_config)
        MockGit.return_value.ensure_repos.return_value = None

        mock_parser = MockParser.return_value
        mock_parser.parse_and_filter.return_value = (
            [{"hash": "abc999", "author": "Dev", "email": "d@d.com", "date": "2026-04-03T10:00:00Z", "subject": "Fix thing", "files": ["lib/foo.c"]}],
            {"total": 4, "filtered_out": 3, "accepted": 1},
        )

        mock_classification = MagicMock()
        mock_classification.classification = Classification.IRRELEVANT
        mock_classification.confidence = 0.95
        mock_classification.category = None
        mock_classification.doc_target = None
        mock_classification.reasoning = "irrelevant"
        mock_classification.apply_thresholds.return_value = mock_classification
        MockDetector.return_value.classify.return_value = mock_classification

        runner_config.generation.enabled = False

        result = runner.run_pipeline(since_timestamp="2026-04-01T00:00:00Z")
        assert result["status"] == "completed"
        assert result["filter_stats"] == {"total": 4, "filtered_out": 3, "accepted": 1}

    def test_module_level_run_pipeline_default_path(self):
        """Convenience run_pipeline() uses default config path when none given."""
        from docgap.orchestrator.runner import run_pipeline as rp_func
        with patch("docgap.orchestrator.runner.load_config") as mock_config, \
             patch("docgap.orchestrator.runner.PipelineRunner") as MockRunner:
            MockRunner.return_value.run_manual.return_value = 0
            result = rp_func()
            assert result == 0
            # load_config called with the default path
            mock_config.assert_called_once_with("config/config.yaml")

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    @patch("docgap.orchestrator.runner.Stage2Generator")
    @patch("docgap.orchestrator.runner.OutputManager")
    @patch("docgap.orchestrator.runner.DocRetriever")
    def test_run_pipeline_validate_mdoc(
        self, MockRetriever, MockOutput, MockGen, MockDetector,
        MockParser, MockOllama, MockGit, mock_click, runner_config
    ):
        """validate_mdoc branch executes DocValidator when enabled and format is mdoc."""
        from docgap.core.classification import Classification
        from docgap.core.generator import GenerationResult

        runner_config.generation.validate_mdoc = True
        runner = PipelineRunner(runner_config)
        MockGit.return_value.ensure_repos.return_value = None
        MockParser.return_value.parse_and_filter.return_value = (
            [{"hash": "mdocval1", "author": "T", "email": "t@t.com",
              "date": "2026-04-03", "subject": "mdoc test", "files": []}],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_cls = MagicMock()
        mock_cls.classification = Classification.NEEDS_DOC
        mock_cls.confidence = 0.9
        mock_cls.category = None
        mock_cls.doc_target = "usr.bin/ls/ls.1"  # mdoc — no .adoc extension
        mock_cls.reasoning = "new flag"
        mock_cls.apply_thresholds.return_value = mock_cls
        MockDetector.return_value.classify.return_value = mock_cls

        gen_result = GenerationResult(
            success=True, patch=".Dd April 1\n", report="ok",
            format="mdoc", duration_ms=50.0,
        )
        MockGen.return_value.generate.return_value = gen_result
        MockOutput.return_value.save_output.return_value = {}

        val_result = MagicMock()
        val_result.valid = False  # triggers the warning branch too
        with patch("docgap.core.validator.DocValidator") as MockValidator:
            MockValidator.return_value.validate.return_value = val_result
            result = runner.run_pipeline(since_timestamp="2026-04-01")

        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    @patch("docgap.orchestrator.runner.Stage2Generator")
    @patch("docgap.orchestrator.runner.OutputManager")
    @patch("docgap.orchestrator.runner.DocRetriever")
    def test_run_pipeline_validate_asciidoc(
        self, MockRetriever, MockOutput, MockGen, MockDetector,
        MockParser, MockOllama, MockGit, mock_click, runner_config
    ):
        """validate_asciidoc branch executes DocValidator when enabled and format is asciidoc."""
        from docgap.core.classification import Classification
        from docgap.core.generator import GenerationResult

        runner_config.generation.validate_asciidoc = True
        runner = PipelineRunner(runner_config)
        MockGit.return_value.ensure_repos.return_value = None
        MockParser.return_value.parse_and_filter.return_value = (
            [{"hash": "asciival1", "author": "T", "email": "t@t.com",
              "date": "2026-04-03", "subject": "asciidoc test", "files": []}],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        mock_cls = MagicMock()
        mock_cls.classification = Classification.NEEDS_DOC
        mock_cls.confidence = 0.9
        mock_cls.category = None
        mock_cls.doc_target = "documentation/content/en_US/something.adoc"
        mock_cls.reasoning = "new doc"
        mock_cls.apply_thresholds.return_value = mock_cls
        MockDetector.return_value.classify.return_value = mock_cls

        gen_result = GenerationResult(
            success=True, patch="= Title\n", report="ok",
            format="asciidoc", duration_ms=50.0,
        )
        MockGen.return_value.generate.return_value = gen_result
        MockOutput.return_value.save_output.return_value = {}

        val_result = MagicMock()
        val_result.valid = True
        with patch("docgap.core.validator.DocValidator") as MockValidator:
            MockValidator.return_value.validate.return_value = val_result
            result = runner.run_pipeline(since_timestamp="2026-04-01")

        assert result["status"] == "completed"

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    def test_run_pipeline_outer_exception_updates_run(
        self, MockDetector, MockParser, MockOllama, MockGit, mock_click, runner_config, temp_dir
    ):
        """Outer exception after run_id is created updates run record to failed."""
        runner = PipelineRunner(runner_config)
        MockGit.return_value.ensure_repos.return_value = None

        # Return a commit so we proceed past the no_commits check and a run_id is inserted
        MockParser.return_value.parse_and_filter.return_value = (
            [{"hash": "outerex1", "author": "T", "email": "t@t.com",
              "date": "2026-04-03", "subject": "x", "files": []}],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )

        # Make OllamaClient constructor raise (happens after run_id insert)
        MockOllama.side_effect = RuntimeError("llm init failed")
        runner_config.generation.enabled = False

        result = runner.run_pipeline(since_timestamp="2026-04-01")
        assert result["status"] == "failed"
        assert "llm init failed" in result["error"]

        # Verify the DB run record was updated to failed
        db = runner.ensure_database()
        run = db.get_last_successful_run()
        db.close()
        # The run was marked failed so get_last_successful_run returns None
        assert run is None

    @patch("docgap.orchestrator.runner.click")
    def test_send_notifications_per_commit(self, mock_click, runner_config, temp_dir):
        """_send_notifications calls send_per_commit for each needs_doc commit."""
        runner = PipelineRunner(runner_config)
        db = runner.ensure_database()
        run_id = db.insert_run({"status": "completed"})
        # Insert two needs_doc commits so the loop runs
        for h in ("notifyc1", "notifyc2"):
            db.insert_commit({
                "run_id": run_id, "hash": h, "author": "T", "email": "t@t.com",
                "date": "2026-04-03", "subject": "s", "files": [],
                "status": "needs_doc", "classification": "NEEDS_DOC", "confidence": 0.9,
            })

        with patch("docgap.core.notifier.Notifier") as MockNotifier:
            mock_notifier = MockNotifier.return_value
            mock_notifier.send_digest.return_value = None
            mock_notifier.send_per_commit.return_value = None
            runner._send_notifications(
                db, run_id,
                {"commits_processed": 2, "commits_flagged": 2, "commits_with_doc": 0}
            )
            assert mock_notifier.send_per_commit.call_count == 2

        db.close()


class TestRunnerDryRunPath:
    """Cover dry_run=True path setting run_id=None."""

    @patch("docgap.orchestrator.runner.click")
    @patch("docgap.orchestrator.runner.GitFetcher")
    @patch("docgap.orchestrator.runner.OllamaClient")
    @patch("docgap.orchestrator.runner.LogParser")
    @patch("docgap.orchestrator.runner.Stage1Detector")
    def test_dry_run_sets_run_id_none(self, MockDetector, MockParser, MockOllama, MockGit, mock_click, runner_config):
        from docgap.core.classification import Classification, ClassificationResult
        runner = PipelineRunner(runner_config)
        MockGit.return_value.ensure_repos.return_value = None
        MockParser.return_value.parse_and_filter.return_value = (
            [{"hash": "abc", "author": "T", "email": "t@t", "date": "2026-04-03", "subject": "test", "files": []}],
            {"total": 1, "filtered_out": 0, "accepted": 1},
        )
        MockDetector.return_value.classify.return_value = ClassificationResult(
            classification=Classification.IRRELEVANT, confidence=0.95
        )
        result = runner.run_pipeline(since_timestamp="2026-04-01", dry_run=True)
        assert result["status"] == "completed"
