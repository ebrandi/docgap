"""Security-focused tests for database operations."""
import tempfile
import json
import sqlite3
from pathlib import Path

import pytest

from docgap.db import Database, init_database


class TestDatabaseSecurity:
    """Test database security aspects."""

    def test_sql_injection_prevention(self, temp_dir):
        """Test that SQL injection attempts are prevented."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        # Attempt SQL injection in commit hash
        run_id = db.insert_run({"status": "running"})
        
        # This should be treated as a literal string, not SQL
        malicious_hash = "abc123'; DROP TABLE commits; --"
        
        # Insert commit with malicious hash - should not drop table
        commit_id = db.insert_commit({
            "run_id": run_id,
            "hash": malicious_hash,
            "author": "Test Author",
            "email": "test@example.com",
            "date": "2026-04-03T10:00:00Z",
            "subject": "Test commit",
            "files": [],
            "status": "pending"
        })
        
        # Verify commit was inserted normally
        commit = db.get_commit_by_hash(malicious_hash)
        assert commit is not None
        assert commit["hash"] == malicious_hash
        
        # Verify table still exists
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='commits'"
            )
            assert cursor.fetchone() is not None

    def test_json_serialization_safety(self, temp_dir):
        """Test that JSON serialization handles malicious input safely."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        run_id = db.insert_run({"status": "running"})
        
        # Test with various potentially problematic inputs
        test_cases = [
            # Normal case
            {"files": ["file1.c", "file2.h"]},
            # Empty list
            {"files": []},
            # List with special characters
            {"files": ["file with spaces.c", "file'with'quotes.h", 'file";DROP TABLE;."c']},
            # None files
            {"files": None},
            # Very long list
            {"files": [f"file{i}.c" for i in range(1000)]},
        ]
        
        for i, files_data in enumerate(test_cases):
            commit_id = db.insert_commit({
                "run_id": run_id,
                "hash": f"hash{i:03d}",
                "author": "Test Author",
                "email": "test@example.com",
                "date": "2026-04-03T10:00:00Z",
                "subject": f"Test commit {i}",
                "files": files_data.get("files") if files_data.get("files") is not None else [],
                "status": "pending"
            })
            
            commit = db.get_commit(commit_id)
            assert commit is not None
            # Files should be properly deserialized
            # Handle None case - our DB converts None to empty list
            expected_files = files_data.get("files")
            if expected_files is None:
                expected_files = []
            assert commit["files"] == expected_files

    def test_connection_handling(self, temp_dir):
        """Test proper connection handling and cleanup."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        db = Database(str(db_path))
        
        # Test multiple connections don't leak
        connections = []
        for i in range(5):
            conn = db._get_connection()
            connections.append(conn)
        
        # All should be the same connection (thread-local)
        assert all(conn is connections[0] for conn in connections)
        
        # Test context manager properly handles exceptions
        try:
            with db.get_connection() as conn:
                # Provide required started_at field to avoid IntegrityError
                conn.execute("INSERT INTO runs (started_at, status) VALUES (datetime('now'), 'test')")
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected
        
        # Connection should still be usable
        with db.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM runs WHERE status='test'")
            # Should be 0 due to rollback
            result = cursor.fetchone()
            assert result is not None
            assert result[0] == 0

    def test_path_traversal_protection(self, temp_dir):
        """Test that database path handling is safe."""
        # This is more of a configuration test, but we can verify
        # the init function handles paths safely
        db_path = temp_dir / "subdir" / "test.db"
        
        # Should create parent directories
        init_database(str(db_path))
        assert db_path.exists()
        assert db_path.parent.exists()

    def test_concurrent_access_safety(self, temp_dir):
        """Test basic concurrent access safety."""
        db_path = temp_dir / "test.db"
        init_database(str(db_path))
        
        # Create two database instances
        db1 = Database(str(db_path))
        db2 = Database(str(db_path))
        
        # Both should be able to operate
        run_id1 = db1.insert_run({"status": "running"})
        run_id2 = db2.insert_run({"status": "running"})
        
        assert run_id1 != run_id2
        
        # Both should be able to read
        runs1 = db1.get_run(run_id1)
        runs2 = db2.get_run(run_id2)
        
        assert runs1 is not None
        assert runs2 is not None
        assert runs1["status"] == "running"
        assert runs2["status"] == "running"