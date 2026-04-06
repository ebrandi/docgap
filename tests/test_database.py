"""Tests for database operations."""
import tempfile
from pathlib import Path

import pytest

from docgap.db import Database, init_database


class TestDatabaseInitialization:
    """Test database initialization."""

    def test_init_database(self, temp_dir):
        """Test that database initializes correctly."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        assert db_path.exists()
        assert db_path.stat().st_size > 0

    def test_database_schema(self, temp_dir):
        """Test that database has correct schema."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        with db.get_connection() as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
        
        assert "runs" in tables
        assert "commits" in tables
        assert "notifications" in tables


class TestRunOperations:
    """Test run CRUD operations."""

    def test_insert_run(self, temp_dir):
        """Test inserting a run record."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        run_id = db.insert_run({"status": "running"})
        assert run_id is not None

    def test_update_run(self, temp_dir):
        """Test updating a run record."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        run_id = db.insert_run({"status": "running"})
        db.update_run(run_id, {"status": "completed", "commits_processed": 10})
        
        run = db.get_run(run_id)
        assert run["status"] == "completed"
        assert run["commits_processed"] == 10

    def test_get_last_successful_run(self, temp_dir):
        """Test getting the last successful run."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        # Insert a completed run
        run_id = db.insert_run({
            "status": "completed",
            "finished_at": "2026-04-03T12:00:00Z"
        })
        db.update_run(run_id, {"status": "completed"})
        
        last_run = db.get_last_successful_run()
        assert last_run is not None
        assert last_run["status"] == "completed"


class TestCommitOperations:
    """Test commit CRUD operations."""

    def test_insert_commit(self, temp_dir):
        """Test inserting a commit record."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        run_id = db.insert_run({"status": "running"})
        commit_id = db.insert_commit({
            "run_id": run_id,
            "hash": "abc123",
            "author": "Test User",
            "email": "test@example.com",
            "date": "2026-04-03T10:00:00Z",
            "subject": "Test commit",
            "files": '["file1.c"]',
            "status": "pending"
        })
        assert commit_id is not None

    def test_update_commit(self, temp_dir):
        """Test updating a commit record."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        run_id = db.insert_run({"status": "running"})
        commit_id = db.insert_commit({
            "run_id": run_id,
            "hash": "abc123",
            "status": "pending"
        })
        
        db.update_commit(commit_id, {"status": "needs_doc"})
        
        commit = db.get_commit(commit_id)
        assert commit["status"] == "needs_doc"

    def test_get_commit_by_hash(self, temp_dir):
        """Test getting a commit by hash."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        run_id = db.insert_run({"status": "running"})
        db.insert_commit({
            "run_id": run_id,
            "hash": "abc123",
            "status": "pending"
        })
        
        commit = db.get_commit_by_hash("abc123")
        assert commit is not None
        assert commit["hash"] == "abc123"

    def test_get_commits_by_status(self, temp_dir):
        """Test getting commits by status."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        run_id = db.insert_run({"status": "running"})
        db.insert_commit({
            "run_id": run_id,
            "hash": "abc123",
            "status": "pending"
        })
        db.insert_commit({
            "run_id": run_id,
            "hash": "def456",
            "status": "needs_doc"
        })
        
        pending = db.get_commits_by_status("pending")
        needs_doc = db.get_commits_by_status("needs_doc")
        
        assert len(pending) == 1
        assert len(needs_doc) == 1

    def test_update_commit_by_hash(self, temp_dir):
        """Test updating a commit by hash."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))

        run_id = db.insert_run({"status": "running"})
        db.insert_commit({
            "run_id": run_id,
            "hash": "abc123",
            "status": "pending"
        })

        db.update_commit_by_hash("abc123", {"status": "needs_doc"})

        commit = db.get_commit_by_hash("abc123")
        assert commit["status"] == "needs_doc"


class TestSchemaMigration:
    """Test schema upgrade paths."""

    def test_schema_upgrade_v1_to_v2(self):
        from docgap.db.schema import get_schema_upgrade_sql
        success, sql = get_schema_upgrade_sql(1, 2)
        assert success is True
        assert "reviewer" in sql
        assert "reviewed_at" in sql
        assert "feedback" in sql

    def test_schema_upgrade_same_version(self):
        from docgap.db.schema import get_schema_upgrade_sql
        success, sql = get_schema_upgrade_sql(2, 2)
        assert success is True
        assert sql == ""

    def test_schema_downgrade_not_supported(self):
        from docgap.db.schema import get_schema_upgrade_sql
        success, msg = get_schema_upgrade_sql(2, 1)
        assert success is False
        assert "downgrade" in msg.lower()


class TestDatabaseGetRunReturnsNone:
    """Test get_run returns None for non-existent IDs."""

    def test_get_run_returns_none(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        assert db.get_run(9999) is None

    def test_get_last_successful_run_none(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        assert db.get_last_successful_run() is None


class TestDatabaseGetCommitReturnsNone:
    """Test get_commit returns None for non-existent IDs."""

    def test_get_commit_returns_none(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        assert db.get_commit(9999) is None

    def test_get_commit_by_hash_returns_none(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        assert db.get_commit_by_hash("nonexistent") is None


class TestDatabaseGetNotification:
    """Test notification CRUD operations."""

    def test_get_notification_returns_none(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        assert db.get_notification(9999) is None

    def test_insert_and_get_notification(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        nid = db.insert_notification({
            "run_id": run_id,
            "commit_hash": "abc123",
            "recipient": "test@example.com",
            "notification_type": "digest",
            "status": "pending",
        })
        assert nid is not None
        notif = db.get_notification(nid)
        assert notif is not None
        assert notif["recipient"] == "test@example.com"
        assert notif["status"] == "pending"

    def test_update_notification(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        nid = db.insert_notification({
            "run_id": run_id,
            "commit_hash": "abc123",
            "recipient": "test@example.com",
        })
        db.update_notification(nid, {"status": "sent", "sent_at": "2026-04-03T12:00:00Z"})
        notif = db.get_notification(nid)
        assert notif["status"] == "sent"
        assert notif["sent_at"] == "2026-04-03T12:00:00Z"

    def test_update_notification_no_valid_columns(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        nid = db.insert_notification({
            "run_id": run_id,
            "commit_hash": "abc123",
            "recipient": "test@example.com",
        })
        # Should not raise when no valid columns provided
        db.update_notification(nid, {"invalid_column": "value"})
        notif = db.get_notification(nid)
        assert notif["status"] == "pending"


class TestDatabaseUpdateNoValidColumns:
    """Test update methods with no valid columns."""

    def test_update_run_no_valid_columns(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        # Should not raise
        db.update_run(run_id, {"invalid_col": "value"})
        run = db.get_run(run_id)
        assert run["status"] == "running"

    def test_update_commit_no_valid_columns(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        cid = db.insert_commit({
            "run_id": run_id, "hash": "abc123", "status": "pending"
        })
        db.update_commit(cid, {"invalid_col": "value"})
        commit = db.get_commit(cid)
        assert commit["status"] == "pending"

    def test_update_commit_by_hash_no_valid_columns(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        db.insert_commit({
            "run_id": run_id, "hash": "abc123", "status": "pending"
        })
        db.update_commit_by_hash("abc123", {"invalid_col": "value"})
        commit = db.get_commit_by_hash("abc123")
        assert commit["status"] == "pending"


class TestDatabasePendingCommits:
    """Test get_pending_commits."""

    def test_get_pending_commits(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        db.insert_commit({"run_id": run_id, "hash": "p1", "status": "pending"})
        db.insert_commit({"run_id": run_id, "hash": "p2", "status": "pending"})
        db.insert_commit({"run_id": run_id, "hash": "nd1", "status": "needs_doc"})
        pending = db.get_pending_commits()
        assert len(pending) == 2
        assert all(c["status"] == "pending" for c in pending)

    def test_get_pending_commits_with_limit(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        for i in range(5):
            db.insert_commit({"run_id": run_id, "hash": f"p{i}", "status": "pending"})
        pending = db.get_pending_commits(limit=2)
        assert len(pending) == 2

    def test_get_pending_commits_empty(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        pending = db.get_pending_commits()
        assert len(pending) == 0


class TestDatabaseCommitsByRun:
    """Test get_commits_by_run."""

    def test_get_commits_by_run(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run1 = db.insert_run({"status": "running"})
        run2 = db.insert_run({"status": "running"})
        db.insert_commit({"run_id": run1, "hash": "c1", "status": "pending"})
        db.insert_commit({"run_id": run1, "hash": "c2", "status": "pending"})
        db.insert_commit({"run_id": run2, "hash": "c3", "status": "pending"})
        commits_run1 = db.get_commits_by_run(run1)
        assert len(commits_run1) == 2
        commits_run2 = db.get_commits_by_run(run2)
        assert len(commits_run2) == 1

    def test_get_commits_by_run_empty(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        commits = db.get_commits_by_run(run_id)
        assert len(commits) == 0


class TestDatabaseInsertCommitFilesSerialization:
    """Test files JSON serialization in insert/update."""

    def test_insert_commit_with_list_files(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        cid = db.insert_commit({
            "run_id": run_id, "hash": "f1", "status": "pending",
            "files": ["a.c", "b.c"],
        })
        commit = db.get_commit(cid)
        assert commit["files"] == ["a.c", "b.c"]

    def test_insert_commit_with_none_files(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        cid = db.insert_commit({
            "run_id": run_id, "hash": "f2", "status": "pending",
            "files": None,
        })
        commit = db.get_commit(cid)
        assert commit["files"] == []

    def test_update_commit_with_list_files(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        cid = db.insert_commit({
            "run_id": run_id, "hash": "f3", "status": "pending",
        })
        db.update_commit(cid, {"files": ["x.c", "y.c"]})
        commit = db.get_commit(cid)
        assert commit["files"] == ["x.c", "y.c"]

    def test_update_commit_by_hash_with_list_files(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        run_id = db.insert_run({"status": "running"})
        db.insert_commit({
            "run_id": run_id, "hash": "f4", "status": "pending",
        })
        db.update_commit_by_hash("f4", {"files": ["m.c"]})
        commit = db.get_commit_by_hash("f4")
        assert commit["files"] == ["m.c"]


class TestDatabaseContextManager:
    """Test database context manager and close."""

    def test_context_manager(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        with Database(str(db_path)) as db:
            run_id = db.insert_run({"status": "running"})
            assert run_id is not None

    def test_close(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        db.insert_run({"status": "running"})
        db.close()
        # Close again should not raise
        db.close()

    def test_get_connection_context_manager(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        with db.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM runs")
            count = cursor.fetchone()[0]
            assert count == 0

    def test_get_connection_rollback_on_error(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        try:
            with db.get_connection() as conn:
                conn.execute("INSERT INTO runs (started_at, status) VALUES ('2026-01-01', 'running')")
                raise ValueError("test error")
        except ValueError:
            pass
        # The insert should have been rolled back
        with db.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM runs")
            count = cursor.fetchone()[0]
            assert count == 0


class TestSchemaHelpers:
    """Test schema helper functions."""

    def test_get_schema(self):
        from docgap.db.schema import get_schema
        schema = get_schema()
        assert "CREATE TABLE" in schema
        assert "runs" in schema

    def test_get_schema_version(self):
        from docgap.db.schema import get_schema_version
        assert get_schema_version() == 3

    def test_get_create_tables_sql(self):
        from docgap.db.schema import get_create_tables_sql
        sql = get_create_tables_sql()
        assert "CREATE TABLE" in sql

    def test_get_tables(self):
        from docgap.db.schema import get_tables
        tables = get_tables()
        assert "runs" in tables
        assert "commits" in tables
        assert "notifications" in tables

    def test_schema_upgrade_no_path(self):
        from docgap.db.schema import get_schema_upgrade_sql
        success, msg = get_schema_upgrade_sql(2, 5)
        assert success is False
        assert "no upgrade path" in msg.lower()


class TestDatabaseModels:
    """Test database model dataclasses."""

    def test_run_model(self):
        from docgap.db.models import Run
        run = Run(status="running")
        assert run.status == "running"
        assert run.id is None

    def test_commit_model_defaults(self):
        from docgap.db.models import Commit
        commit = Commit()
        assert commit.status == "pending"
        assert commit.files == "[]"

    def test_commit_model_none_status(self):
        from docgap.db.models import Commit
        commit = Commit(status=None)
        assert commit.status == "pending"

    def test_commit_get_files(self):
        from docgap.db.models import Commit
        commit = Commit(files='["a.c", "b.c"]')
        assert commit.get_files() == ["a.c", "b.c"]

    def test_commit_set_files(self):
        from docgap.db.models import Commit
        commit = Commit()
        commit.set_files(["x.c", "y.c"])
        assert commit.get_files() == ["x.c", "y.c"]

    def test_commit_get_files_none(self):
        from docgap.db.models import Commit
        commit = Commit(files=None)
        # __post_init__ sets files to "[]"
        assert commit.get_files() == []

    def test_notification_model(self):
        from docgap.db.models import Notification
        notif = Notification(recipient="test@example.com")
        assert notif.notification_type == "digest"
        assert notif.status == "pending"


class TestInitDatabaseOverwrite:
    """Test init_database overwrites existing database."""

    def test_init_overwrites_existing(self, temp_dir):
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        db.insert_run({"status": "running"})
        db.close()
        # Re-init should overwrite
        init_database(str(db_path))
        db = Database(str(db_path))
        run = db.get_run(1)
        assert run is None
        db.close()
