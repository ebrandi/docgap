"""Dataclasses for database entities."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Run:
    """Represents a pipeline run."""
    id: Optional[int] = None
    started_at: Optional[str] = None  # ISO 8601
    finished_at: Optional[str] = None  # ISO 8601
    status: str = "running"  # running, completed, failed
    commits_processed: int = 0
    commits_flagged: int = 0
    error_message: Optional[str] = None


@dataclass
class Commit:
    """Represents a commit being processed."""
    id: Optional[int] = None
    run_id: Optional[int] = None
    hash: Optional[str] = None
    author: Optional[str] = None
    email: Optional[str] = None
    date: Optional[str] = None  # ISO 8601
    subject: Optional[str] = None
    files: Optional[str] = None  # JSON string
    status: str = "pending"  # pending, irrelevant, needs_doc, uncertain, doc_generated, reviewed, submitted, false_positive
    classification: Optional[str] = None  # NEEDS_DOC, IRRELEVANT, UNCERTAIN
    confidence: Optional[float] = None
    category: Optional[str] = None  # new_flag, new_command, etc.
    doc_target: Optional[str] = None
    reasoning: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[str] = None  # ISO 8601
    updated_at: Optional[str] = None  # ISO 8601

    def __post_init__(self) -> None:
        """Ensure status is always a string."""
        if self.status is None:
            self.status = "pending"
        if self.files is None:
            self.files = "[]"

    def get_files(self) -> List[str]:
        """Parse and return files list."""
        import json
        if self.files:
            return json.loads(self.files)
        return []  # pragma: no cover

    def set_files(self, files: List[str]) -> None:
        """Serialize files list to JSON string."""
        import json
        self.files = json.dumps(files)


@dataclass
class Notification:
    """Represents a notification sent to a recipient."""
    id: Optional[int] = None
    run_id: Optional[int] = None
    commit_hash: Optional[str] = None
    recipient: Optional[str] = None
    notification_type: str = "digest"  # digest, per_commit
    sent_at: Optional[str] = None  # ISO 8601
    status: str = "pending"  # pending, sent, failed
    error_message: Optional[str] = None
