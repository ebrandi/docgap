"""Email notification system using sendmail."""
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgap.config.schema import Config
from docgap.core.templates import TemplateEngine
from docgap.db.database import Database


@dataclass
class NotificationResult:
    """Result of sending an email."""
    success: bool
    recipients: List[str]
    subject: str
    sent_at: str
    error: Optional[str] = None


class Notifier:
    """Send email notifications via sendmail."""
    
    def __init__(self,
                 config: Config,
                 database: Database,
                 test_mode: bool = False):
        """Initialize the notifier.
        
        Args:
            config: Configuration object
            database: Database for logging notifications
            test_mode: If True, don't actually send emails
        """
        self.config = config
        self.database = database
        self.test_mode = test_mode
        
        # Get notification settings from config
        self.from_address = config.notification.from_address
        self.doceng_recipients = config.notification.doceng_recipients
        self.committer_notify = config.notification.committer_notify
        self.digest_only_if_findings = config.notification.digest_only_if_findings
        self.max_emails_per_run = 50
        self._template_engine = TemplateEngine()

        # Statistics
        self._stats = {
            'digest_sent': 0,
            'per_commit_sent': 0,
            'digest_failed': 0,
            'per_commit_failed': 0,
        }
    
    def _build_email(self,
                     subject: str,
                     body: str,
                     recipients: List[str]) -> str:
        """Build an email message with proper headers.
        
        Args:
            subject: Email subject
            body: Email body text
            recipients: List of recipient email addresses
            
        Returns:
            Full email message string
        """
        headers = [
            f"From: {self.from_address}",
            f"To: {', '.join(recipients)}",
            f"Subject: {subject}",
            "Content-Type: text/plain; charset=utf-8",
            f"Date: {datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S UTC')}",
        ]
        
        return '\n'.join(headers) + '\n\n' + body
    
    def send_digest(self,
                    run_results: Dict[str, Any]) -> NotificationResult:
        """Send a digest email to Doceng team.
        
        Args:
            run_results: Dictionary with run summary and commits
            
        Returns:
            NotificationResult
        """
        # Check if we should send (has findings)
        if self.digest_only_if_findings:
            total_commits = run_results.get('total_commits', 0)
            flagged = run_results.get('flagged_commits', 0)
            if total_commits == 0 and flagged == 0:
                return NotificationResult(
                    success=True,
                    recipients=[],
                    subject="[docgap] No findings this run",
                    sent_at=datetime.now(timezone.utc).isoformat(),
                )
        
        # Build email body
        body = self._render_digest(run_results)
        
        # Build email
        subject = f"[docgap] {run_results.get('flagged_commits', 0)} commits need documentation attention"
        email = self._build_email(subject, body, self.doceng_recipients)
        
        return self._send_email(email, self.doceng_recipients, subject, 'digest')
    
    def send_per_commit(self,
                        commit: Dict[str, Any],
                        commit_results: Optional[Dict[str, Any]] = None) -> NotificationResult:
        """Send a per-commit notification to the author.
        
        Args:
            commit: Commit metadata
            commit_results: Results from Stage 1/2
            
        Returns:
            NotificationResult
        """
        if not self.committer_notify:
            return NotificationResult(
                success=True,
                recipients=[],
                subject="",
                sent_at=datetime.now(timezone.utc).isoformat(),
            )
        
        # Get author email
        author_email = commit.get('email', commit.get('author'))
        if not author_email:
            return NotificationResult(
                success=True,
                recipients=[],
                subject="",
                sent_at=datetime.now(timezone.utc).isoformat(),
            )
        
        # Build email body
        body = self._render_per_commit(commit, commit_results)
        
        # Build email
        subject = f"[docgap] Your commit {commit.get('hash', 'N/A')[:12]} may need documentation"
        email = self._build_email(subject, body, [author_email])
        
        return self._send_email(email, [author_email], subject, 'per-commit')
    
    def _send_email(self,
                    email: str,
                    recipients: List[str],
                    subject: str,
                    notification_type: str) -> NotificationResult:
        """Actually send an email via sendmail.
        
        Args:
            email: Full email message
            recipients: List of recipients
            subject: Email subject
            notification_type: 'digest' or 'per-commit'
            
        Returns:
            NotificationResult
        """
        try:
            if self.test_mode:
                # Don't actually send, just log
                self._log_notification(recipients, subject, notification_type, None)
                return NotificationResult(
                    success=True,
                    recipients=recipients,
                    subject=subject,
                    sent_at=datetime.now(timezone.utc).isoformat(),
                )
            
            # Run sendmail
            process = subprocess.run(
                ['/usr/sbin/sendmail', '-t'],
                input=email.encode('utf-8'),
                capture_output=True,
                timeout=30,
            )
            
            if process.returncode != 0:
                error = process.stderr.decode('utf-8') if process.stderr else 'Unknown error'
                self._log_notification(recipients, subject, notification_type, error)
                
                if notification_type == 'digest':
                    self._stats['digest_failed'] += 1
                else:
                    self._stats['per_commit_failed'] += 1
                
                return NotificationResult(
                    success=False,
                    recipients=recipients,
                    subject=subject,
                    sent_at=datetime.now(timezone.utc).isoformat(),
                    error=error,
                )
            
            # Log successful send
            self._log_notification(recipients, subject, notification_type, None)
            
            if notification_type == 'digest':
                self._stats['digest_sent'] += 1
            else:
                self._stats['per_commit_sent'] += 1
            
            return NotificationResult(
                success=True,
                recipients=recipients,
                subject=subject,
                sent_at=datetime.now(timezone.utc).isoformat(),
            )
            
        except Exception as e:
            error = str(e)
            self._log_notification(recipients, subject, notification_type, error)
            
            if notification_type == 'digest':
                self._stats['digest_failed'] += 1
            else:
                self._stats['per_commit_failed'] += 1
            
            return NotificationResult(
                success=False,
                recipients=recipients,
                subject=subject,
                sent_at=datetime.now(timezone.utc).isoformat(),
                error=error,
            )
    
    def _log_notification(self,
                          recipients: List[str],
                          subject: str,
                          notification_type: str,
                          error: Optional[str] = None) -> None:
        """Log notification to database.
        
        Args:
            recipients: List of recipients
            subject: Email subject
            notification_type: 'digest' or 'per-commit'
            error: Error message if failed
        """
        if not self.database:
            return
        
        # Get latest run
        run = self.database.get_last_successful_run()
        run_id = run.get('id') if run else None
        
        for recipient in recipients:
            self.database.insert_notification({
                'run_id': run_id,
                'recipient': recipient,
                'notification_type': notification_type,
                'status': 'sent' if error is None else 'failed',
                'error_message': error,
            })
    
    def _render_digest(self, run_results: Dict[str, Any]) -> str:
        """Render digest email body.

        Args:
            run_results: Run summary data

        Returns:
            Email body text
        """
        commits = run_results.get('commits', [])

        # Build flagged_list block
        if commits:
            commit_lines = ["Commits needing documentation:", "-" * 50]
            for i, commit in enumerate(commits, 1):
                commit_lines.append(
                    f"{i}. {commit.get('hash', 'N/A')[:12]} - {commit.get('subject', 'N/A')}"
                )
                commit_lines.append(f"   Author: {commit.get('author', 'N/A')}")
                commit_lines.append(f"   Category: {commit.get('category', 'N/A')}")
                commit_lines.append(f"   Classification: {commit.get('classification', 'N/A')}")
                if commit.get('doc_target'):
                    commit_lines.append(f"   Doc target: {commit.get('doc_target')}")
                if commit.get('reasoning'):
                    commit_lines.append(f"   Reasoning: {commit.get('reasoning')}")
                commit_lines.append(f"   Review: docgap review show {commit.get('hash', 'N/A')}")
                commit_lines.append("")
            flagged_list = '\n'.join(commit_lines)
        else:
            flagged_list = ""

        variables = {
            'run_id': str(run_results.get('run_id', 'N/A')),
            'total_commits': str(run_results.get('total_commits', 0)),
            'flagged_count': str(run_results.get('flagged_commits', 0)),
            'uncertain_count': str(run_results.get('uncertain_commits', 0)),
            'started_at': str(run_results.get('started_at', 'N/A')),
            'finished_at': str(run_results.get('finished_at', 'N/A')),
            'flagged_list': flagged_list,
        }

        return self._template_engine.render("email/digest.txt", variables)
    
    def _render_per_commit(self,
                           commit: Dict[str, Any],
                           result: Optional[Dict[str, Any]]) -> str:
        """Render per-commit email body.

        Args:
            commit: Commit metadata
            result: Results from Stage 1/2

        Returns:
            Email body text
        """
        commit_hash = commit.get('hash', 'N/A')
        commit_hash_short = commit_hash[:12]

        category = 'N/A'
        reasoning_line = ''
        if result:
            category = result.get('classification', 'N/A')
            if result.get('reasoning'):
                reasoning_line = f"Reasoning: {result.get('reasoning')}"

        variables = {
            'commit_hash': commit_hash,
            'commit_hash_short': commit_hash_short,
            'subject': str(commit.get('subject', 'N/A')),
            'author': str(commit.get('author', 'N/A')),
            'category': str(category),
            'reasoning_line': reasoning_line,
        }

        return self._template_engine.render("email/per-commit.txt", variables)
    
    def get_statistics(self) -> Dict[str, int]:
        """Get notification statistics."""
        return self._stats.copy()
