"""Tests for new DB methods and ReprocessRunner."""
from datetime import datetime, timedelta, timezone

import pytest

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
