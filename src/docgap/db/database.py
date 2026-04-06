"""Main database class with CRUD operations."""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgap.db.models import Commit, Notification, Run
from docgap.db.schema import SCHEMA, get_schema_upgrade_sql, get_schema_version


class Database:
    """Database connection manager with CRUD operations."""
    
    # Whitelists for column names in UPDATE statements
    RUN_UPDATABLE_COLUMNS = {
        "finished_at", "status", "commits_processed", 
        "commits_flagged", "error_message"
    }
    
    COMMIT_UPDATABLE_COLUMNS = {
        "run_id", "hash", "author", "email", "date", "subject", "files",
        "status", "classification", "confidence", "category",
        "doc_target", "reasoning", "reviewer", "reviewed_at", "feedback",
        "retry_count", "updated_at"
    }
    
    NOTIFICATION_UPDATABLE_COLUMNS = {
        "run_id", "commit_hash", "recipient", "notification_type", 
        "sent_at", "status", "error_message"
    }

    def __init__(self, db_path: str):
        """Initialize database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._local = threading.local()
        self._setup_connection()
    
    def _setup_connection(self) -> None:
        """Set up the database with schema and initial settings."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys=ON")
        
        # Initialize schema
        self._initialize_schema(conn)
        
        self._local.conn = conn
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get the current thread's database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._setup_connection()
        return self._local.conn
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections.
        
        Usage:
            with db.get_connection() as conn:
                conn.execute("SELECT * FROM runs")
        """
        conn = self._get_connection()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
    
    def _initialize_schema(self, conn: sqlite3.Connection) -> None:
        """Initialize database schema if not already set up."""
        cursor = conn.cursor()
        
        # Check if tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
        )
        if not cursor.fetchone():
            # Create all tables
            cursor.executescript(SCHEMA)
            conn.commit()
        
        # Set schema version
        # Note: PRAGMA does not support ? parameter binding in SQLite
        version = int(get_schema_version())
        cursor.execute(f"PRAGMA user_version = {version}")
        conn.commit()

    # ==================== Run Operations ====================
    
    def insert_run(self, run_data: Dict[str, Any]) -> int:
        """Insert a new run and return its ID.
        
        Args:
            run_data: Dictionary with run fields (status, started_at, etc.)
            
        Returns:
            The ID of the inserted run
            
        Raises:
            RuntimeError: If insert fails and no rowid is available
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        run_data.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        run_data.setdefault("status", "running")
        
        cursor.execute(
            """
            INSERT INTO runs (started_at, finished_at, status, commits_processed, commits_flagged, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_data.get("started_at"),
                run_data.get("finished_at"),
                run_data.get("status"),
                run_data.get("commits_processed", 0),
                run_data.get("commits_flagged", 0),
                run_data.get("error_message"),
            ),
        )
        conn.commit()
        rowid = cursor.lastrowid
        if rowid is None:  # pragma: no cover
            raise RuntimeError("Failed to retrieve rowid after insert_run")
        return rowid
    
    def update_run(self, run_id: int, run_data: Dict[str, Any]) -> None:
        """Update a run record.
        
        Args:
            run_id: The ID of the run to update
            run_data: Dictionary with fields to update
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Build dynamic update query with explicit column validation
        updates = []
        values = []
        for key, value in run_data.items():
            if key in self.RUN_UPDATABLE_COLUMNS:
                updates.append(f"{key} = ?")
                values.append(value)
        
        if not updates:
            return
        
        values.append(run_id)
        query = f"UPDATE runs SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()
    
    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Get a run by ID.
        
        Args:
            run_id: The ID of the run to retrieve
            
        Returns:
            Dictionary with run data or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    
    def get_last_successful_run(self) -> Optional[Dict[str, Any]]:
        """Get the last completed run.
        
        Returns:
            Dictionary with run data or None if no successful runs
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM runs 
            WHERE status = 'completed' 
            ORDER BY started_at DESC 
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    
    # ==================== Commit Operations ====================
    
    def insert_commit(self, commit_data: Dict[str, Any]) -> int:
        """Insert a new commit and return its ID.
        
        Args:
            commit_data: Dictionary with commit fields
            
        Returns:
            The ID of the inserted commit
            
        Raises:
            RuntimeError: If insert fails and no rowid is available
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # JSON-serialize files if it's a list, otherwise ensure it's JSON serialized
        files = commit_data.get("files")
        if isinstance(files, list):
            import json
            commit_data["files"] = json.dumps(files)
        elif files is None:
            import json
            commit_data["files"] = json.dumps([])
        
        commit_data.setdefault("status", "pending")
        commit_data.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        
        cursor.execute(
            """
            INSERT INTO commits (
                run_id, hash, author, email, date, subject, files, status,
                classification, confidence, category, doc_target, reasoning,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                commit_data.get("run_id"),
                commit_data.get("hash"),
                commit_data.get("author"),
                commit_data.get("email"),
                commit_data.get("date"),
                commit_data.get("subject"),
                commit_data.get("files"),
                commit_data.get("status"),
                commit_data.get("classification"),
                commit_data.get("confidence"),
                commit_data.get("category"),
                commit_data.get("doc_target"),
                commit_data.get("reasoning"),
                commit_data.get("created_at"),
                commit_data.get("updated_at"),
            ),
        )
        conn.commit()
        rowid = cursor.lastrowid
        if rowid is None:  # pragma: no cover
            raise RuntimeError("Failed to retrieve rowid after insert_commit")
        return rowid
    
    def update_commit(self, commit_id: int, commit_data: Dict[str, Any]) -> None:
        """Update a commit record.
        
        Args:
            commit_id: The ID of the commit to update
            commit_data: Dictionary with fields to update
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # JSON-serialize files if it's a list
        files = commit_data.get("files")
        if isinstance(files, list):
            import json
            commit_data["files"] = json.dumps(files)
        
        commit_data.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        
        # Build dynamic update query with explicit column validation
        updates = []
        values = []
        for key, value in commit_data.items():
            if key in self.COMMIT_UPDATABLE_COLUMNS:
                updates.append(f"{key} = ?")
                values.append(value)
        
        if not updates:  # pragma: no cover
            return

        values.append(commit_id)
        query = f"UPDATE commits SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()
    
    def get_commit(self, commit_id: int) -> Optional[Dict[str, Any]]:
        """Get a commit by ID.
        
        Args:
            commit_id: The ID of the commit to retrieve
            
        Returns:
            Dictionary with commit data or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM commits WHERE id = ?", (commit_id,))
        row = cursor.fetchone()
        if row:
            commit = dict(row)
            # Deserialize files
            if commit.get("files"):
                import json
                commit["files"] = json.loads(commit["files"])
            return commit
        return None
    
    def get_commit_by_hash(self, commit_hash: str) -> Optional[Dict[str, Any]]:
        """Get a commit by its hash.
        
        Args:
            commit_hash: The commit hash to look up
            
        Returns:
            Dictionary with commit data or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM commits WHERE hash = ?", (commit_hash,))
        row = cursor.fetchone()
        if row:
            commit = dict(row)
            # Deserialize files
            if commit.get("files"):
                import json
                commit["files"] = json.loads(commit["files"])
            return commit
        return None
    
    def update_commit_by_hash(self, commit_hash: str, commit_data: Dict[str, Any]) -> None:
        """Update a commit record by its hash.
        
        Args:
            commit_hash: The commit hash to look up
            commit_data: Dictionary with fields to update
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # JSON-serialize files if it's a list
        files = commit_data.get("files")
        if isinstance(files, list):
            import json
            commit_data["files"] = json.dumps(files)
        
        commit_data.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        
        # Build dynamic update query with explicit column validation
        updates = []
        values = []
        for key, value in commit_data.items():
            if key in self.COMMIT_UPDATABLE_COLUMNS:
                updates.append(f"{key} = ?")
                values.append(value)
        
        if not updates:  # pragma: no cover
            return

        query = f"UPDATE commits SET {', '.join(updates)} WHERE hash = ?"
        values.append(commit_hash)
        cursor.execute(query, values)
        conn.commit()
    
    def get_pending_commits(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get pending commits for processing.
        
        Args:
            limit: Maximum number of commits to return
            
        Returns:
            List of commit dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM commits 
            WHERE status = 'pending' 
            ORDER BY created_at ASC 
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        commits = []
        for row in rows:
            commit = dict(row)
            # Deserialize files
            if commit.get("files"):
                import json
                commit["files"] = json.loads(commit["files"])
            commits.append(commit)
        return commits
    
    def get_commits_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get commits by status.
        
        Args:
            status: The status to filter by
            
        Returns:
            List of commit dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM commits WHERE status = ? ORDER BY created_at ASC",
            (status,),
        )
        rows = cursor.fetchall()
        commits = []
        for row in rows:
            commit = dict(row)
            # Deserialize files
            if commit.get("files"):
                import json
                commit["files"] = json.loads(commit["files"])
            commits.append(commit)
        return commits
    
    def get_commits_by_run(self, run_id: int) -> List[Dict[str, Any]]:
        """Get all commits for a run.
        
        Args:
            run_id: The run ID to look up
            
        Returns:
            List of commit dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM commits WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        )
        rows = cursor.fetchall()
        commits = []
        for row in rows:
            commit = dict(row)
            # Deserialize files
            if commit.get("files"):
                import json
                commit["files"] = json.loads(commit["files"])
            commits.append(commit)
        return commits
    
    def get_commits_by_statuses(self, statuses: List[str]) -> List[Dict[str, Any]]:
        """Get commits matching any of the given statuses."""
        if not statuses:
            return []
        conn = self._get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in statuses)
        cursor.execute(
            f"SELECT * FROM commits WHERE status IN ({placeholders}) ORDER BY created_at ASC",
            statuses,
        )
        rows = cursor.fetchall()
        commits = []
        for row in rows:
            commit = dict(row)
            if commit.get("files"):
                import json
                commit["files"] = json.loads(commit["files"])
            commits.append(commit)
        return commits

    def get_stale_runs(self, older_than_hours: int = 24) -> List[Dict[str, Any]]:
        """Get runs stuck in 'running' status older than threshold."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM runs
            WHERE status = 'running'
            AND started_at < datetime('now', ? || ' hours')
            ORDER BY started_at ASC
            """,
            (f"-{older_than_hours}",),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def delete_commit_by_hash(self, commit_hash: str) -> bool:
        """Delete a commit record by hash. Returns True if deleted."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM commits WHERE hash = ?", (commit_hash,))
        conn.commit()
        return cursor.rowcount > 0

    def purge_commits_older_than(self, before_iso: str, statuses: Optional[List[str]] = None) -> int:
        """Delete commits older than date. Returns count deleted."""
        conn = self._get_connection()
        cursor = conn.cursor()
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            cursor.execute(
                f"DELETE FROM commits WHERE date < ? AND status IN ({placeholders})",
                [before_iso] + statuses,
            )
        else:
            cursor.execute(
                "DELETE FROM commits WHERE date < ?",
                (before_iso,),
            )
        conn.commit()
        return cursor.rowcount

    def count_commits_by_status(self) -> Dict[str, int]:
        """Return {status: count} for all statuses."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) as cnt FROM commits GROUP BY status")
        rows = cursor.fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    # ==================== Notification Operations ====================
    
    def insert_notification(self, notification_data: Dict[str, Any]) -> int:
        """Insert a new notification and return its ID.
        
        Args:
            notification_data: Dictionary with notification fields
            
        Returns:
            The ID of the inserted notification
            
        Raises:
            RuntimeError: If insert fails and no rowid is available
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        notification_data.setdefault("status", "pending")
        
        cursor.execute(
            """
            INSERT INTO notifications (
                run_id, commit_hash, recipient, notification_type, sent_at, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification_data.get("run_id"),
                notification_data.get("commit_hash"),
                notification_data.get("recipient"),
                notification_data.get("notification_type", "digest"),
                notification_data.get("sent_at"),
                notification_data.get("status"),
                notification_data.get("error_message"),
            ),
        )
        conn.commit()
        rowid = cursor.lastrowid
        if rowid is None:  # pragma: no cover
            raise RuntimeError("Failed to retrieve rowid after insert_notification")
        return rowid
    
    def update_notification(self, notification_id: int, notification_data: Dict[str, Any]) -> None:
        """Update a notification record.
        
        Args:
            notification_id: The ID of the notification to update
            notification_data: Dictionary with fields to update
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Build dynamic update query with explicit column validation
        updates = []
        values = []
        for key, value in notification_data.items():
            if key in self.NOTIFICATION_UPDATABLE_COLUMNS:
                updates.append(f"{key} = ?")
                values.append(value)
        
        if not updates:
            return
        
        values.append(notification_id)
        query = f"UPDATE notifications SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()
    
    def get_notification(self, notification_id: int) -> Optional[Dict[str, Any]]:
        """Get a notification by ID.
        
        Args:
            notification_id: The ID of the notification to retrieve
            
        Returns:
            Dictionary with notification data or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    
    # ==================== Utility Methods ====================
    
    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False


def init_database(db_path: str) -> None:
    """Initialize a new database at the given path.
    
    Args:
        db_path: Path to the SQLite database file
    """
    # Create parent directories if they don't exist
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Delete existing database if present
    if path.exists():
        path.unlink()

    # Create file with restricted permissions before SQLite opens it
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)

    # Create connection and initialize schema
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    
    cursor = conn.cursor()
    cursor.executescript(SCHEMA)
    
    # Set schema version
    # Note: PRAGMA does not support ? parameter binding in SQLite
    version = int(get_schema_version())
    cursor.execute(f"PRAGMA user_version = {version}")
    
    conn.commit()
    conn.close()