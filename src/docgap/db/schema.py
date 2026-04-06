"""SQL schema definitions for the database."""
from typing import List, Tuple

# Schema version
SCHEMA_VERSION = 3

# Database schema with tables and indices
SCHEMA = """
-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- Runs table: tracks each pipeline execution
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    commits_processed INTEGER DEFAULT 0,
    commits_flagged INTEGER DEFAULT 0,
    error_message TEXT
);

-- Commits table: stores commit metadata and processing status
CREATE TABLE IF NOT EXISTS commits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    author TEXT,
    email TEXT,
    date TEXT,
    subject TEXT,
    files TEXT,  -- JSON array of file paths
    status TEXT NOT NULL DEFAULT 'pending',
    classification TEXT,
    confidence REAL,
    category TEXT,
    doc_target TEXT,
    reasoning TEXT,
    reviewer TEXT,
    reviewed_at TEXT,
    feedback TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- Notifications table: tracks sent notifications
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    commit_hash TEXT,
    recipient TEXT NOT NULL,
    notification_type TEXT NOT NULL DEFAULT 'digest',
    sent_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_commits_hash ON commits(hash);
CREATE INDEX IF NOT EXISTS idx_commits_status ON commits(status);
CREATE INDEX IF NOT EXISTS idx_commits_run_id ON commits(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
CREATE INDEX IF NOT EXISTS idx_notifications_commit_hash ON notifications(commit_hash);
"""


def get_schema() -> str:
    """Return the full schema SQL."""
    return SCHEMA


def get_schema_version() -> int:
    """Return the current schema version."""
    return SCHEMA_VERSION


def get_create_tables_sql() -> str:
    """Return SQL to create all tables and indices."""
    return SCHEMA


def get_tables() -> List[str]:
    """Return list of table names."""
    return ["runs", "commits", "notifications"]


def get_schema_upgrade_sql(from_version: int, to_version: int) -> Tuple[bool, str]:
    """Get SQL for schema upgrade from one version to another.

    Args:
        from_version: Starting version
        to_version: Target version

    Returns:
        Tuple of (success, sql_or_error_message)
    """
    if from_version == to_version:
        return True, ""

    if from_version > to_version:
        return False, f"Downgrade from v{from_version} to v{to_version} not supported"

    # Build upgrade path step by step
    sql_parts = []
    v = from_version
    while v < to_version:
        if v == 1:
            sql_parts.append(
                "ALTER TABLE commits ADD COLUMN reviewer TEXT;\n"
                "ALTER TABLE commits ADD COLUMN reviewed_at TEXT;\n"
                "ALTER TABLE commits ADD COLUMN feedback TEXT;"
            )
            v = 2
        elif v == 2:
            sql_parts.append(
                "ALTER TABLE commits ADD COLUMN retry_count INTEGER DEFAULT 0;"
            )
            v = 3
        else:
            return False, f"No upgrade path from v{v} to v{to_version}"

    return True, "\n".join(sql_parts)


# Expose get_create_tables_sql as create_tables for convenience
create_tables = get_create_tables_sql
