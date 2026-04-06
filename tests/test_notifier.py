"""Tests for email notification system."""
from unittest.mock import MagicMock, patch

import pytest

from docgap.core.notifier import Notifier, NotificationResult
from docgap.db import Database, init_database
from docgap.config.schema import (
    AutoSubmitConfig,
    Config,
    DetectionConfig,
    GeneralConfig,
    GenerationConfig,
    LLMConfig,
    NotificationConfig,
    RepositoriesConfig,
    RepositoryConfig,
    ReviewConfig,
)


@pytest.fixture
def notifier_config(temp_dir):
    """Config with notifications enabled."""
    return Config(
        general=GeneralConfig(data_dir=str(temp_dir), log_level="debug"),
        repositories=RepositoriesConfig(
            freebsd_src=RepositoryConfig(path=str(temp_dir / "src"), remote="http://example.com"),
            freebsd_doc=RepositoryConfig(path=str(temp_dir / "doc"), remote="http://example.com"),
        ),
        llm=LLMConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="test",
            temperature=0.1,
            max_context=524288,
            timeout=120,
        ),
        detection=DetectionConfig(
            confidence_threshold_accept=0.80,
            confidence_threshold_reject=0.50,
        ),
        generation=GenerationConfig(
            enabled=True,
            validate_mdoc=False,
            validate_asciidoc=False,
            max_retries=1,
        ),
        review=ReviewConfig(
            auto_submit=AutoSubmitConfig(enabled=False, hold_period_hours=72, categories={}),
        ),
        notification=NotificationConfig(
            enabled=True,
            doceng_recipients=["doceng@test.com"],
            committer_notify=True,
            digest_only_if_findings=True,
            from_address="docgap@test.com",
            smtp_host="localhost",
        ),
    )


@pytest.fixture
def test_db(temp_dir):
    """Initialized test database."""
    db_path = temp_dir / "test.db"
    init_database(str(db_path))
    return Database(str(db_path))


@pytest.fixture
def notifier(notifier_config, test_db):
    """Notifier in test_mode so no real sendmail calls are made."""
    return Notifier(config=notifier_config, database=test_db, test_mode=True)


class TestNotifierInit:
    """Test Notifier initialization."""

    def test_init_sets_from_address(self, notifier_config, test_db):
        n = Notifier(config=notifier_config, database=test_db, test_mode=True)
        assert n.from_address == "docgap@test.com"

    def test_init_sets_recipients(self, notifier_config, test_db):
        n = Notifier(config=notifier_config, database=test_db, test_mode=True)
        assert "doceng@test.com" in n.doceng_recipients

    def test_init_test_mode_false_by_default(self, notifier_config, test_db):
        n = Notifier(config=notifier_config, database=test_db)
        assert n.test_mode is False

    def test_init_stats_zeroed(self, notifier):
        stats = notifier.get_statistics()
        assert stats["digest_sent"] == 0
        assert stats["per_commit_sent"] == 0
        assert stats["digest_failed"] == 0
        assert stats["per_commit_failed"] == 0

    def test_init_committer_notify(self, notifier):
        assert notifier.committer_notify is True


class TestRenderDigest:
    """Test _render_digest email body rendering."""

    def test_render_digest_contains_run_id(self, notifier):
        run_results = {
            "run_id": 42,
            "started_at": "2026-04-03T10:00:00",
            "finished_at": "2026-04-03T10:05:00",
            "total_commits": 5,
            "flagged_commits": 2,
            "uncertain_commits": 1,
            "commits": [],
        }
        body = notifier._render_digest(run_results)
        assert "42" in body

    def test_render_digest_contains_summary(self, notifier):
        run_results = {
            "run_id": 1,
            "total_commits": 10,
            "flagged_commits": 3,
            "uncertain_commits": 2,
            "commits": [],
        }
        body = notifier._render_digest(run_results)
        assert "10" in body
        assert "3" in body
        assert "Summary" in body

    def test_render_digest_lists_commits(self, notifier):
        run_results = {
            "run_id": 1,
            "total_commits": 1,
            "flagged_commits": 1,
            "uncertain_commits": 0,
            "commits": [
                {
                    "hash": "abcdef123456789",
                    "subject": "Add new syscall",
                    "author": "Dev User",
                    "category": "new_feature",
                    "classification": "NEEDS_DOC",
                    "doc_target": "sys/syscall.2",
                    "reasoning": "New API needs man page",
                }
            ],
        }
        body = notifier._render_digest(run_results)
        assert "abcdef123456" in body
        assert "Add new syscall" in body
        assert "Dev User" in body

    def test_render_digest_footer_present(self, notifier):
        run_results = {
            "run_id": 1,
            "total_commits": 0,
            "flagged_commits": 0,
            "uncertain_commits": 0,
            "commits": [],
        }
        body = notifier._render_digest(run_results)
        assert "docgap review show" in body

    def test_render_digest_no_commits_section(self, notifier):
        run_results = {
            "run_id": 1,
            "total_commits": 0,
            "flagged_commits": 0,
            "uncertain_commits": 0,
            "commits": [],
        }
        body = notifier._render_digest(run_results)
        assert "Commits needing documentation" not in body


class TestRenderPerCommit:
    """Test _render_per_commit email body rendering."""

    def test_render_per_commit_contains_hash(self, notifier):
        commit = {
            "hash": "deadbeef123456",
            "subject": "Fix memory leak",
            "author": "Alice",
            "email": "alice@example.com",
        }
        body = notifier._render_per_commit(commit, result=None)
        assert "deadbeef123456"[:12] in body

    def test_render_per_commit_contains_subject(self, notifier):
        commit = {
            "hash": "deadbeef123456",
            "subject": "Fix memory leak in kern",
            "author": "Alice",
            "email": "alice@example.com",
        }
        body = notifier._render_per_commit(commit, result=None)
        assert "Fix memory leak in kern" in body

    def test_render_per_commit_with_result(self, notifier):
        commit = {
            "hash": "deadbeef123456",
            "subject": "Fix memory leak",
            "author": "Alice",
            "email": "alice@example.com",
        }
        result = {
            "classification": "NEEDS_DOC",
            "reasoning": "Changed public API",
        }
        body = notifier._render_per_commit(commit, result=result)
        assert "NEEDS_DOC" in body
        assert "Changed public API" in body

    def test_render_per_commit_review_instructions(self, notifier):
        commit = {
            "hash": "deadbeef123456",
            "subject": "Add flag",
            "author": "Bob",
            "email": "bob@example.com",
        }
        body = notifier._render_per_commit(commit, result=None)
        assert "docgap review show" in body
        assert "docgap review approve" in body
        assert "docgap review reject" in body


class TestBuildEmail:
    """Test _build_email header construction."""

    def test_build_email_from_header(self, notifier):
        msg = notifier._build_email("Test Subject", "Body text", ["to@example.com"])
        assert "From: docgap@test.com" in msg

    def test_build_email_to_header(self, notifier):
        msg = notifier._build_email("Subject", "Body", ["a@x.com", "b@x.com"])
        assert "a@x.com" in msg
        assert "b@x.com" in msg

    def test_build_email_subject_header(self, notifier):
        msg = notifier._build_email("My Subject", "Body", ["r@x.com"])
        assert "Subject: My Subject" in msg

    def test_build_email_body_present(self, notifier):
        msg = notifier._build_email("Subj", "Hello world", ["r@x.com"])
        assert "Hello world" in msg


class TestSendDigest:
    """Test send_digest behavior."""

    def test_send_digest_no_findings_skipped(self, notifier):
        """digest_only_if_findings=True with no commits skips sending."""
        run_results = {"total_commits": 0, "flagged_commits": 0, "commits": []}
        result = notifier.send_digest(run_results)
        assert result.success is True
        assert result.recipients == []

    def test_send_digest_with_findings_test_mode(self, notifier):
        """Send digest in test_mode with findings returns success."""
        run_results = {
            "run_id": 1,
            "started_at": "2026-04-03T10:00:00",
            "finished_at": "2026-04-03T10:05:00",
            "total_commits": 3,
            "flagged_commits": 2,
            "uncertain_commits": 0,
            "commits": [
                {
                    "hash": "abc123def456789",
                    "subject": "Add flag",
                    "author": "Dev",
                    "category": "new_flag",
                    "classification": "NEEDS_DOC",
                }
            ],
        }
        result = notifier.send_digest(run_results)
        assert result.success is True
        assert "doceng@test.com" in result.recipients
        assert "[docgap]" in result.subject

    def test_send_digest_stats_updated(self, notifier_config, test_db):
        """Stats are incremented when sendmail succeeds (non-test_mode)."""
        n = Notifier(config=notifier_config, database=test_db, test_mode=False)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            run_results = {
                "run_id": 1,
                "total_commits": 1,
                "flagged_commits": 1,
                "uncertain_commits": 0,
                "commits": [],
            }
            n.send_digest(run_results)
        assert n.get_statistics()["digest_sent"] == 1

    def test_send_digest_failure_via_sendmail(self, notifier_config, test_db):
        """Sendmail failure increments digest_failed."""
        n = Notifier(config=notifier_config, database=test_db, test_mode=False)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = b"sendmail error"
        with patch("subprocess.run", return_value=mock_proc):
            run_results = {
                "run_id": 1,
                "total_commits": 1,
                "flagged_commits": 1,
                "uncertain_commits": 0,
                "commits": [],
            }
            result = n.send_digest(run_results)
        assert result.success is False
        assert n.get_statistics()["digest_failed"] == 1


class TestSendPerCommit:
    """Test send_per_commit behavior."""

    def test_send_per_commit_committer_notify_disabled(self, notifier_config, test_db):
        """When committer_notify=False, no email is sent."""
        notifier_config.notification.committer_notify = False
        n = Notifier(config=notifier_config, database=test_db, test_mode=True)
        commit = {"hash": "abc123", "subject": "Feat", "author": "Dev", "email": "dev@example.com"}
        result = n.send_per_commit(commit)
        assert result.success is True
        assert result.recipients == []

    def test_send_per_commit_no_email_skipped(self, notifier):
        """Commit with no email and no author is skipped gracefully."""
        commit = {"hash": "abc123", "subject": "Feat"}
        result = notifier.send_per_commit(commit)
        assert result.success is True
        assert result.recipients == []

    def test_send_per_commit_success(self, notifier):
        """Per-commit send in test_mode returns success."""
        commit = {
            "hash": "abc123def456789",
            "subject": "Add new feature",
            "author": "Dev User",
            "email": "dev@freebsd.org",
        }
        result = notifier.send_per_commit(commit)
        assert result.success is True
        assert "dev@freebsd.org" in result.recipients

    def test_send_per_commit_stats_updated(self, notifier_config, test_db):
        """Stats are incremented when sendmail succeeds (non-test_mode)."""
        n = Notifier(config=notifier_config, database=test_db, test_mode=False)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = b""
        with patch("subprocess.run", return_value=mock_proc):
            commit = {
                "hash": "abc123def456789",
                "subject": "Feat",
                "author": "Dev",
                "email": "dev@freebsd.org",
            }
            n.send_per_commit(commit)
        assert n.get_statistics()["per_commit_sent"] == 1

    def test_send_per_commit_failure_via_sendmail(self, notifier_config, test_db):
        """Sendmail failure increments per_commit_failed."""
        n = Notifier(config=notifier_config, database=test_db, test_mode=False)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = b"error"
        with patch("subprocess.run", return_value=mock_proc):
            commit = {
                "hash": "abc123def456789",
                "subject": "Feat",
                "author": "Dev",
                "email": "dev@freebsd.org",
            }
            result = n.send_per_commit(commit)
        assert result.success is False
        assert n.get_statistics()["per_commit_failed"] == 1


class TestLogNotification:
    """Test _log_notification writes to the database."""

    def test_log_notification_inserted(self, notifier, test_db):
        """Successful notification is logged to the database."""
        run_id = test_db.insert_run({"status": "completed"})
        notifier._log_notification(
            recipients=["recipient@test.com"],
            subject="Test subject",
            notification_type="digest",
            error=None,
        )
        # Verify at least one notification row exists
        with test_db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM notifications")
            rows = cursor.fetchall()
        assert len(rows) >= 1

    def test_log_notification_failed_status(self, notifier, test_db):
        """Failed notification logs with 'failed' status."""
        notifier._log_notification(
            recipients=["r@test.com"],
            subject="Failing",
            notification_type="digest",
            error="SMTP refused",
        )
        with test_db.get_connection() as conn:
            cursor = conn.execute("SELECT status FROM notifications ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
        assert row is not None
        assert row[0] == "failed"

    def test_log_notification_no_database(self, notifier_config):
        """_log_notification with no database does not raise."""
        n = Notifier(config=notifier_config, database=None, test_mode=True)
        # Should silently return
        n._log_notification(["r@x.com"], "Sub", "digest", None)

    def test_log_notification_multiple_recipients(self, notifier, test_db):
        """Each recipient gets its own notification row."""
        notifier._log_notification(
            recipients=["a@test.com", "b@test.com"],
            subject="Multi",
            notification_type="digest",
            error=None,
        )
        with test_db.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM notifications")
            count = cursor.fetchone()[0]
        assert count >= 2


class TestGetStatistics:
    """Test get_statistics returns a copy."""

    def test_get_statistics_returns_dict(self, notifier):
        stats = notifier.get_statistics()
        assert isinstance(stats, dict)

    def test_get_statistics_is_copy(self, notifier):
        stats = notifier.get_statistics()
        stats["digest_sent"] = 999
        assert notifier.get_statistics()["digest_sent"] == 0


class TestNotificationResult:
    """Test NotificationResult dataclass."""

    def test_success_result(self):
        r = NotificationResult(
            success=True,
            recipients=["a@b.com"],
            subject="Test",
            sent_at="2026-04-03T10:00:00",
        )
        assert r.success is True
        assert r.error is None

    def test_failure_result(self):
        r = NotificationResult(
            success=False,
            recipients=["a@b.com"],
            subject="Test",
            sent_at="2026-04-03T10:00:00",
            error="Connection refused",
        )
        assert r.success is False
        assert r.error == "Connection refused"


class TestSendEmailExceptionPath:
    """Test _send_email when subprocess.run raises an exception."""

    def test_send_email_exception_digest_increments_failed(self, notifier_config, test_db):
        """Exception in subprocess.run increments digest_failed and returns failure."""
        n = Notifier(config=notifier_config, database=test_db, test_mode=False)
        with patch("subprocess.run", side_effect=OSError("sendmail not found")):
            run_results = {
                "run_id": 1,
                "total_commits": 1,
                "flagged_commits": 1,
                "uncertain_commits": 0,
                "commits": [],
            }
            result = n.send_digest(run_results)
        assert result.success is False
        assert n.get_statistics()["digest_failed"] == 1
        assert "sendmail not found" in result.error

    def test_send_email_exception_per_commit_increments_failed(self, notifier_config, test_db):
        """Exception in subprocess.run increments per_commit_failed."""
        n = Notifier(config=notifier_config, database=test_db, test_mode=False)
        with patch("subprocess.run", side_effect=OSError("sendmail not found")):
            commit = {
                "hash": "abc123def456789",
                "subject": "Feat",
                "author": "Dev",
                "email": "dev@freebsd.org",
            }
            result = n.send_per_commit(commit)
        assert result.success is False
        assert n.get_statistics()["per_commit_failed"] == 1


class TestEmailValidation:
    """Test _validate_email rejects header-injection attempts."""

    def test_email_with_crlf_bcc_injection_returns_false(self):
        """_validate_email returns False for email with CRLF Bcc injection."""
        from docgap.core.notifier import _validate_email
        assert _validate_email("user@evil.com\r\nBcc: x@x.com") is False

    def test_email_with_bare_newline_returns_false(self):
        """_validate_email returns False for email containing a bare newline."""
        from docgap.core.notifier import _validate_email
        assert _validate_email("user@evil.com\nX-Injected: yes") is False

    def test_email_with_bare_carriage_return_returns_false(self):
        """_validate_email returns False for email containing a bare carriage return."""
        from docgap.core.notifier import _validate_email
        assert _validate_email("user@evil.com\rX-Injected: yes") is False

    def test_valid_email_returns_true(self):
        """_validate_email returns True for a clean valid email address."""
        from docgap.core.notifier import _validate_email
        assert _validate_email("user@freebsd.org") is True

    def test_invalid_email_format_returns_false(self):
        """_validate_email returns False for an address missing the @ symbol."""
        from docgap.core.notifier import _validate_email
        assert _validate_email("notanemail") is False


class TestEmailRateLimit:
    """Test that send_per_commit enforces max_emails_per_run."""

    def test_send_per_commit_blocked_after_max_reached(self, notifier_config, test_db):
        """send_per_commit returns failure once max_emails_per_run is exhausted."""
        n = Notifier(config=notifier_config, database=test_db, test_mode=True)
        # Manually exhaust the per-commit counter
        n._stats["per_commit_sent"] = n.max_emails_per_run

        commit = {
            "hash": "abc123def456789",
            "subject": "Blocked commit",
            "author": "Dev",
            "email": "dev@freebsd.org",
        }
        result = n.send_per_commit(commit)

        assert result.success is False
        assert result.error == "max_emails_per_run limit reached"
        assert result.recipients == []

    def test_send_per_commit_allowed_before_max_reached(self, notifier_config, test_db):
        """send_per_commit succeeds while under the rate limit."""
        n = Notifier(config=notifier_config, database=test_db, test_mode=True)
        n._stats["per_commit_sent"] = n.max_emails_per_run - 1

        commit = {
            "hash": "abc123def456789",
            "subject": "Under limit",
            "author": "Dev",
            "email": "dev@freebsd.org",
        }
        result = n.send_per_commit(commit)

        assert result.success is True
        assert "dev@freebsd.org" in result.recipients
