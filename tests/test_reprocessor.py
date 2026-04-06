"""Tests for new DB methods and ReprocessRunner."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from docgap.core.classification import Category, Classification, ClassificationResult
from docgap.core.generator import GenerationResult
from docgap.db import Database, init_database
from docgap.orchestrator.reprocessor import ReprocessRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(temp_dir):
    db_path = temp_dir / "test.db"
    init_database(str(db_path))
    return Database(str(db_path))


def _get_or_create_run_id(db):
    run_id = db.insert_run({"status": "completed"})
    return run_id


def _insert_commit(db, hash_, status, date="2026-01-01T00:00:00Z", retry_count=0, run_id=None):
    if run_id is None:
        run_id = _get_or_create_run_id(db)
    db.insert_commit({
        "run_id": run_id,
        "hash": hash_,
        "author": "Test User",
        "email": "test@example.com",
        "date": date,
        "subject": f"Commit {hash_}",
        "files": [],
        "status": status,
    })
    if retry_count:
        db.update_commit_by_hash(hash_, {"retry_count": retry_count})


# ---------------------------------------------------------------------------
# DB method tests
# ---------------------------------------------------------------------------

class TestGetCommitsByStatuses:
    def test_returns_matching_statuses(self, temp_dir):
        db = _make_db(temp_dir)
        _insert_commit(db, "aaa", "needs_doc")
        _insert_commit(db, "bbb", "error")
        _insert_commit(db, "ccc", "irrelevant")

        results = db.get_commits_by_statuses(["needs_doc", "error"])
        hashes = {r["hash"] for r in results}

        assert hashes == {"aaa", "bbb"}

    def test_empty_list_returns_empty(self, temp_dir):
        db = _make_db(temp_dir)
        _insert_commit(db, "aaa", "needs_doc")

        assert db.get_commits_by_statuses([]) == []


class TestGetStaleRuns:
    def test_finds_old_running_run(self, temp_dir):
        db = _make_db(temp_dir)
        old_time = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).strftime("%Y-%m-%d %H:%M:%S")

        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (old_time,),
            )
            conn.commit()

        stale = db.get_stale_runs(older_than_hours=24)
        assert len(stale) == 1

    def test_ignores_recent_running_run(self, temp_dir):
        db = _make_db(temp_dir)
        recent_time = datetime.now(timezone.utc).isoformat()

        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (recent_time,),
            )
            conn.commit()

        assert db.get_stale_runs(older_than_hours=24) == []


class TestDeleteCommitByHash:
    def test_delete_removes_commit(self, temp_dir):
        db = _make_db(temp_dir)
        _insert_commit(db, "deadbeef", "pending")

        deleted = db.delete_commit_by_hash("deadbeef")

        assert deleted is True
        assert db.get_commit_by_hash("deadbeef") is None

    def test_delete_missing_returns_false(self, temp_dir):
        db = _make_db(temp_dir)
        assert db.delete_commit_by_hash("nonexistent") is False


class TestPurgeCommitsOlderThan:
    def test_purges_old_commits(self, temp_dir):
        db = _make_db(temp_dir)
        _insert_commit(db, "old1", "irrelevant", date="2020-01-01T00:00:00Z")
        _insert_commit(db, "old2", "irrelevant", date="2021-06-15T00:00:00Z")
        _insert_commit(db, "new1", "irrelevant", date="2026-01-01T00:00:00Z")

        count = db.purge_commits_older_than("2025-01-01T00:00:00Z")

        assert count == 2
        assert db.get_commit_by_hash("new1") is not None

    def test_purge_with_status_filter(self, temp_dir):
        db = _make_db(temp_dir)
        _insert_commit(db, "old_err", "error", date="2020-01-01T00:00:00Z")
        _insert_commit(db, "old_irr", "irrelevant", date="2020-01-01T00:00:00Z")

        count = db.purge_commits_older_than("2025-01-01T00:00:00Z", statuses=["error"])

        assert count == 1
        assert db.get_commit_by_hash("old_err") is None
        assert db.get_commit_by_hash("old_irr") is not None


class TestCountCommitsByStatus:
    def test_returns_correct_counts(self, temp_dir):
        db = _make_db(temp_dir)
        _insert_commit(db, "a1", "needs_doc")
        _insert_commit(db, "a2", "needs_doc")
        _insert_commit(db, "b1", "irrelevant")

        counts = db.count_commits_by_status()

        assert counts["needs_doc"] == 2
        assert counts["irrelevant"] == 1

    def test_empty_db_returns_empty(self, temp_dir):
        db = _make_db(temp_dir)
        assert db.count_commits_by_status() == {}


# ---------------------------------------------------------------------------
# ReprocessRunner unit tests
# ---------------------------------------------------------------------------

class TestReprocessRunner:
    def _make_runner(self, test_config, temp_dir):
        db_path = temp_dir / "docgap.sqlite"
        init_database(str(db_path))
        return ReprocessRunner(test_config)

    def test_reprocess_commit_not_found(self, test_config, temp_dir):
        runner = self._make_runner(test_config, temp_dir)

        result = runner.reprocess_commit("nonexistent123", dry_run=True)

        assert result["status"] == "not_found"
        assert "not found" in result["error"].lower()

    def test_reprocess_commit_max_retries_exceeded(self, test_config, temp_dir):
        runner = self._make_runner(test_config, temp_dir)
        db = Database(str(temp_dir / "docgap.sqlite"))
        _insert_commit(db, "retried123", "error", retry_count=5)

        result = runner.reprocess_commit("retried123", dry_run=True, max_retries=3)

        assert result["status"] == "skipped"
        assert "max_retries" in result["error"]

    def test_heal_no_issues(self, test_config, temp_dir):
        runner = self._make_runner(test_config, temp_dir)

        result = runner.heal(fix=False, dry_run=True)

        assert result["stale_runs"] == []
        assert result["incomplete_stage2"] == []
        assert result["retryable_errors"] == []
        assert result["actions_taken"] == []


# ---------------------------------------------------------------------------
# Fixtures and helpers for pipeline tests
# ---------------------------------------------------------------------------

def _make_classification(classification=Classification.NEEDS_DOC, confidence=0.90):
    return ClassificationResult(
        classification=classification,
        confidence=confidence,
        category=Category.NEW_FLAG,
        doc_target="usr.bin/ls/ls.1",
        reasoning="Test reasoning",
    )


def _make_generation_result(success=True):
    return GenerationResult(
        success=success,
        patch="--- a/ls.1\n+++ b/ls.1\n@@ -1 +1 @@\n+new line",
        report="Generated successfully" if success else "LLM returned empty patch",
        format="mdoc",
        duration_ms=42.0,
    )


def _make_runner_with_mocks(test_config, temp_dir):
    """Return (runner, db, mock_detector, mock_generator, mock_output_manager)."""
    db_path = temp_dir / "docgap.sqlite"
    init_database(str(db_path))
    db = Database(str(db_path))

    runner = ReprocessRunner(test_config)

    mock_llm = MagicMock()
    mock_fetcher = MagicMock()
    mock_fetcher.get_diff.return_value = "diff text"

    mock_detector = MagicMock()
    mock_detector.classify.return_value = _make_classification()

    mock_generator = MagicMock()
    mock_generator.generate.return_value = _make_generation_result(success=True)

    mock_output_manager = MagicMock()
    mock_output_manager.load_output.return_value = None  # no output by default

    runner._llm_client = mock_llm
    runner._src_fetcher = mock_fetcher
    runner._detector = mock_detector
    runner._generator = mock_generator
    runner._output_manager = mock_output_manager

    return runner, db, mock_detector, mock_generator, mock_output_manager


# ---------------------------------------------------------------------------
# Lazy initializer tests
# ---------------------------------------------------------------------------

class TestLazyInitializers:
    def _make_runner(self, test_config, temp_dir):
        db_path = temp_dir / "docgap.sqlite"
        init_database(str(db_path))
        return ReprocessRunner(test_config)

    def test_get_llm_client_creates_and_caches_instance(self, test_config, temp_dir):
        runner = self._make_runner(test_config, temp_dir)
        with patch("docgap.orchestrator.reprocessor.OllamaClient") as MockOllama:
            MockOllama.return_value = MagicMock()
            client1 = runner._get_llm_client()
            client2 = runner._get_llm_client()

        assert client1 is client2
        assert MockOllama.call_count == 1

    def test_get_src_fetcher_creates_and_caches_instance(self, test_config, temp_dir):
        runner = self._make_runner(test_config, temp_dir)
        with patch("docgap.orchestrator.reprocessor.GitFetcher") as MockFetcher:
            MockFetcher.return_value = MagicMock()
            fetcher1 = runner._get_src_fetcher()
            fetcher2 = runner._get_src_fetcher()

        assert fetcher1 is fetcher2
        assert MockFetcher.call_count == 1

    def test_get_detector_creates_and_caches_instance(self, test_config, temp_dir):
        runner = self._make_runner(test_config, temp_dir)
        runner._llm_client = MagicMock()
        runner._src_fetcher = MagicMock()
        with patch("docgap.orchestrator.reprocessor.Stage1Detector") as MockDetector:
            MockDetector.return_value = MagicMock()
            det1 = runner._get_detector()
            det2 = runner._get_detector()

        assert det1 is det2
        assert MockDetector.call_count == 1

    def test_get_generator_creates_and_caches_instance(self, test_config, temp_dir):
        runner = self._make_runner(test_config, temp_dir)
        runner._llm_client = MagicMock()
        runner._src_fetcher = MagicMock()
        with patch("docgap.orchestrator.reprocessor.GitFetcher") as MockFetcher, \
             patch("docgap.orchestrator.reprocessor.DocRetriever") as MockRetriever, \
             patch("docgap.orchestrator.reprocessor.Stage2Generator") as MockGen:
            MockFetcher.return_value = MagicMock()
            MockRetriever.return_value = MagicMock()
            MockGen.return_value = MagicMock()
            gen1 = runner._get_generator()
            gen2 = runner._get_generator()

        assert gen1 is gen2
        assert MockGen.call_count == 1

    def test_get_output_manager_creates_and_caches_instance(self, test_config, temp_dir):
        runner = self._make_runner(test_config, temp_dir)
        with patch("docgap.orchestrator.reprocessor.OutputManager") as MockOM:
            MockOM.return_value = MagicMock()
            om1 = runner._get_output_manager()
            om2 = runner._get_output_manager()

        assert om1 is om2
        assert MockOM.call_count == 1


# ---------------------------------------------------------------------------
# reprocess_commit() pipeline tests
# ---------------------------------------------------------------------------

class TestReprocessCommitPipeline:
    def test_stage1_only_classifies_and_updates_db(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, _ = _make_runner_with_mocks(
            test_config, temp_dir
        )
        _insert_commit(db, "aabbcc111", "pending")

        result = runner.reprocess_commit("aabbcc111", stage="stage1", dry_run=False)

        assert result["status"] == "success"
        assert result["stage1_result"] is not None
        assert result["stage1_result"]["classification"] == "NEEDS_DOC"
        mock_detector.classify.assert_called_once()
        mock_generator.generate.assert_not_called()

        updated = db.get_commit_by_hash("aabbcc111")
        assert updated["status"] == "needs_doc"
        assert updated["classification"] == "NEEDS_DOC"

    def test_stage2_only_generates_docs_for_needs_doc_commit(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, mock_output_manager = (
            _make_runner_with_mocks(test_config, temp_dir)
        )
        _insert_commit(db, "bbccdd222", "needs_doc")
        # Seed classification on the DB row so stage2-only can read it
        db.update_commit_by_hash("bbccdd222", {
            "classification": "NEEDS_DOC",
            "confidence": 0.90,
        })

        result = runner.reprocess_commit("bbccdd222", stage="stage2", dry_run=False)

        assert result["status"] == "success"
        assert result["stage2_result"] is not None
        assert result["stage2_result"]["success"] is True
        mock_detector.classify.assert_not_called()
        mock_generator.generate.assert_called_once()
        mock_output_manager.save_output.assert_called_once()

        updated = db.get_commit_by_hash("bbccdd222")
        assert updated["status"] == "doc_generated"

    def test_both_stages_runs_full_pipeline(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, mock_output_manager = (
            _make_runner_with_mocks(test_config, temp_dir)
        )
        _insert_commit(db, "ccddee333", "pending")

        result = runner.reprocess_commit("ccddee333", stage="both", dry_run=False)

        assert result["status"] == "success"
        assert result["stage1_result"] is not None
        assert result["stage2_result"] is not None
        mock_detector.classify.assert_called_once()
        mock_generator.generate.assert_called_once()
        mock_output_manager.save_output.assert_called_once()

        updated = db.get_commit_by_hash("ccddee333")
        assert updated["status"] == "doc_generated"

    def test_stage2_skipped_when_classification_is_not_needs_doc(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, _ = _make_runner_with_mocks(
            test_config, temp_dir
        )
        mock_detector.classify.return_value = _make_classification(
            classification=Classification.IRRELEVANT, confidence=0.95
        )
        _insert_commit(db, "ddeeff444", "pending")

        result = runner.reprocess_commit("ddeeff444", stage="both", dry_run=False)

        assert result["status"] == "success"
        assert result["stage1_result"]["classification"] == "IRRELEVANT"
        assert result["stage2_result"] is None
        mock_generator.generate.assert_not_called()

    def test_dry_run_does_not_write_to_db(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, mock_output_manager = (
            _make_runner_with_mocks(test_config, temp_dir)
        )
        _insert_commit(db, "eeffgg555", "pending")

        result = runner.reprocess_commit("eeffgg555", stage="both", dry_run=True)

        assert result["status"] == "success"
        # DB row must be unchanged
        unchanged = db.get_commit_by_hash("eeffgg555")
        assert unchanged["status"] == "pending"
        mock_output_manager.save_output.assert_not_called()

    def test_generation_failure_sets_status_to_generation_error(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, mock_output_manager = (
            _make_runner_with_mocks(test_config, temp_dir)
        )
        mock_generator.generate.return_value = _make_generation_result(success=False)
        _insert_commit(db, "ffgghh666", "needs_doc")
        db.update_commit_by_hash("ffgghh666", {
            "classification": "NEEDS_DOC",
            "confidence": 0.90,
        })

        result = runner.reprocess_commit("ffgghh666", stage="both", dry_run=False)

        assert result["status"] == "failed"
        assert result["stage2_result"]["success"] is False
        assert "Generation failed" in result["error"]
        mock_output_manager.save_output.assert_not_called()

        updated = db.get_commit_by_hash("ffgghh666")
        assert updated["status"] == "generation_error"

    def test_exception_during_processing_sets_error_status_and_increments_retry(
        self, test_config, temp_dir
    ):
        runner, db, mock_detector, mock_generator, _ = _make_runner_with_mocks(
            test_config, temp_dir
        )
        mock_detector.classify.side_effect = RuntimeError("LLM timeout")
        _insert_commit(db, "gghhii777", "pending", retry_count=0)

        result = runner.reprocess_commit("gghhii777", stage="both", dry_run=False)

        assert result["status"] == "failed"
        assert "LLM timeout" in result["error"]

        updated = db.get_commit_by_hash("gghhii777")
        assert updated["status"] == "error"
        assert (updated.get("retry_count") or 0) >= 1

    def test_exception_dry_run_does_not_update_db(self, test_config, temp_dir):
        runner, db, mock_detector, _, _ = _make_runner_with_mocks(test_config, temp_dir)
        mock_detector.classify.side_effect = RuntimeError("boom")
        _insert_commit(db, "hhiijj888", "pending")

        result = runner.reprocess_commit("hhiijj888", stage="both", dry_run=True)

        assert result["status"] == "failed"
        unchanged = db.get_commit_by_hash("hhiijj888")
        assert unchanged["status"] == "pending"

    def test_stage1_run_record_created_and_completed_in_db(self, test_config, temp_dir):
        runner, db, _, _, _ = _make_runner_with_mocks(test_config, temp_dir)
        _insert_commit(db, "iijjkk999", "pending")

        runner.reprocess_commit("iijjkk999", stage="stage1", dry_run=False)

        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE status = 'completed'"
            ).fetchall()
        # At least one completed reprocess run was recorded
        assert any(dict(r).get("commits_processed") == 1 for r in rows)

    def test_stage2_only_with_uncertain_classification_skips_generation(
        self, test_config, temp_dir
    ):
        runner, db, mock_detector, mock_generator, _ = _make_runner_with_mocks(
            test_config, temp_dir
        )
        _insert_commit(db, "jjkkll000", "uncertain")
        db.update_commit_by_hash("jjkkll000", {
            "classification": "UNCERTAIN",
            "confidence": 0.65,
        })

        result = runner.reprocess_commit("jjkkll000", stage="stage2", dry_run=False)

        assert result["status"] == "success"
        mock_generator.generate.assert_not_called()


# ---------------------------------------------------------------------------
# reprocess_by_status() tests
# ---------------------------------------------------------------------------

class TestReprocessByStatus:
    def test_bulk_reprocess_returns_correct_counts(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, _ = _make_runner_with_mocks(
            test_config, temp_dir
        )
        _insert_commit(db, "bulk001", "error")
        _insert_commit(db, "bulk002", "error")

        summary = runner.reprocess_by_status(["error"], dry_run=False)

        assert summary["total"] == 2
        assert summary["succeeded"] == 2
        assert summary["failed"] == 0
        assert len(summary["details"]) == 2

    def test_bulk_reprocess_empty_status_list_returns_zero_total(
        self, test_config, temp_dir
    ):
        runner, db, _, _, _ = _make_runner_with_mocks(test_config, temp_dir)
        _insert_commit(db, "bulk010", "needs_doc")

        summary = runner.reprocess_by_status([], dry_run=True)

        assert summary["total"] == 0
        assert summary["succeeded"] == 0

    def test_bulk_reprocess_counts_skipped_when_max_retries_exceeded(
        self, test_config, temp_dir
    ):
        runner, db, _, _, _ = _make_runner_with_mocks(test_config, temp_dir)
        _insert_commit(db, "bulk020", "error", retry_count=10)

        summary = runner.reprocess_by_status(["error"], dry_run=True, max_retries=3)

        assert summary["total"] == 1
        assert summary["skipped"] == 1
        assert summary["succeeded"] == 0

    def test_bulk_reprocess_mixed_results_tally_correctly(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, _ = _make_runner_with_mocks(
            test_config, temp_dir
        )
        # One that will succeed, one whose classify raises
        _insert_commit(db, "bulk030", "error")
        _insert_commit(db, "bulk031", "error")

        call_count = [0]
        original_classify = mock_detector.classify

        def classify_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("classify failed")
            return _make_classification()

        mock_detector.classify.side_effect = classify_side_effect

        summary = runner.reprocess_by_status(["error"], dry_run=False)

        assert summary["total"] == 2
        assert summary["succeeded"] == 1
        assert summary["failed"] == 1


# ---------------------------------------------------------------------------
# reprocess_since() tests
# ---------------------------------------------------------------------------

class TestReprocessSince:
    def test_reprocess_since_picks_up_commits_after_date(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, _ = _make_runner_with_mocks(
            test_config, temp_dir
        )
        _insert_commit(db, "since001", "pending", date="2026-03-01T00:00:00Z")
        _insert_commit(db, "since002", "pending", date="2026-04-01T00:00:00Z")
        _insert_commit(db, "since003", "pending", date="2026-04-05T00:00:00Z")

        summary = runner.reprocess_since("2026-04-01T00:00:00Z", dry_run=True)

        assert summary["total"] == 2
        hashes = {d["hash"] for d in summary["details"]}
        assert "since002" in hashes
        assert "since003" in hashes
        assert "since001" not in hashes

    def test_reprocess_since_returns_zero_when_no_commits_match(
        self, test_config, temp_dir
    ):
        runner, db, _, _, _ = _make_runner_with_mocks(test_config, temp_dir)
        _insert_commit(db, "since010", "pending", date="2025-01-01T00:00:00Z")

        summary = runner.reprocess_since("2026-01-01T00:00:00Z", dry_run=True)

        assert summary["total"] == 0

    def test_reprocess_since_succeeds_for_qualifying_commits(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, _ = _make_runner_with_mocks(
            test_config, temp_dir
        )
        mock_detector.classify.return_value = _make_classification(
            classification=Classification.IRRELEVANT, confidence=0.95
        )
        _insert_commit(db, "since020", "pending", date="2026-04-04T00:00:00Z")

        summary = runner.reprocess_since("2026-04-01T00:00:00Z", dry_run=False)

        assert summary["total"] == 1
        assert summary["succeeded"] == 1


# ---------------------------------------------------------------------------
# heal() tests
# ---------------------------------------------------------------------------

class TestHeal:
    def _make_stale_run(self, db, hours_ago=25):
        old_time = (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).strftime("%Y-%m-%d %H:%M:%S")
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (old_time,),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_heal_finds_stale_runs(self, test_config, temp_dir):
        runner, db, _, _, mock_output_manager = _make_runner_with_mocks(
            test_config, temp_dir
        )
        stale_id = self._make_stale_run(db)

        result = runner.heal(fix=False, dry_run=False)

        assert stale_id in result["stale_runs"]
        assert result["actions_taken"] == []  # fix=False

    def test_heal_fix_true_marks_stale_runs_as_failed(self, test_config, temp_dir):
        runner, db, _, _, mock_output_manager = _make_runner_with_mocks(
            test_config, temp_dir
        )
        stale_id = self._make_stale_run(db)

        result = runner.heal(fix=True, dry_run=False)

        assert stale_id in result["stale_runs"]
        assert any("stale" in action for action in result["actions_taken"])

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM runs WHERE id = ?", (stale_id,)
            ).fetchone()
        assert row["status"] == "failed"

    def test_heal_finds_needs_doc_without_output(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, mock_output_manager = (
            _make_runner_with_mocks(test_config, temp_dir)
        )
        mock_output_manager.load_output.return_value = None  # no output file
        _insert_commit(db, "heal001", "needs_doc")
        db.update_commit_by_hash("heal001", {
            "classification": "NEEDS_DOC",
            "confidence": 0.90,
        })

        result = runner.heal(fix=False, dry_run=False)

        assert "heal001" in result["incomplete_stage2"]
        assert result["actions_taken"] == []

    def test_heal_fix_true_reprocesses_incomplete_stage2(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, mock_output_manager = (
            _make_runner_with_mocks(test_config, temp_dir)
        )
        mock_output_manager.load_output.return_value = None
        _insert_commit(db, "heal002", "needs_doc")
        db.update_commit_by_hash("heal002", {
            "classification": "NEEDS_DOC",
            "confidence": 0.90,
        })

        result = runner.heal(fix=True, dry_run=False)

        assert "heal002" in result["incomplete_stage2"]
        assert any("heal002" in action for action in result["actions_taken"])
        mock_generator.generate.assert_called()

    def test_heal_finds_retryable_error_commits(self, test_config, temp_dir):
        runner, db, _, _, mock_output_manager = _make_runner_with_mocks(
            test_config, temp_dir
        )
        # max_retries in test_config is 1; insert with retry_count=0 → retryable
        _insert_commit(db, "heal010", "error", retry_count=0)

        result = runner.heal(fix=False, dry_run=False)

        assert "heal010" in result["retryable_errors"]
        assert result["actions_taken"] == []

    def test_heal_fix_true_reprocesses_retryable_errors(self, test_config, temp_dir):
        runner, db, mock_detector, mock_generator, mock_output_manager = (
            _make_runner_with_mocks(test_config, temp_dir)
        )
        mock_output_manager.load_output.return_value = MagicMock()  # has output
        _insert_commit(db, "heal011", "error", retry_count=0)

        result = runner.heal(fix=True, dry_run=False)

        assert "heal011" in result["retryable_errors"]
        assert any("heal011" in action for action in result["actions_taken"])

    def test_heal_excludes_commits_at_max_retries_from_retryable(
        self, test_config, temp_dir
    ):
        runner, db, _, _, mock_output_manager = _make_runner_with_mocks(
            test_config, temp_dir
        )
        # retry_count=1 == max_retries=1 → not retryable
        _insert_commit(db, "heal020", "error", retry_count=1)

        result = runner.heal(fix=False, dry_run=False)

        assert "heal020" not in result["retryable_errors"]

    def test_heal_dry_run_fix_does_not_mark_stale_runs(self, test_config, temp_dir):
        runner, db, _, _, mock_output_manager = _make_runner_with_mocks(
            test_config, temp_dir
        )
        stale_id = self._make_stale_run(db)

        result = runner.heal(fix=True, dry_run=True)

        assert stale_id in result["stale_runs"]
        # dry_run=True means no DB writes even with fix=True
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM runs WHERE id = ?", (stale_id,)
            ).fetchone()
        assert row["status"] == "running"
