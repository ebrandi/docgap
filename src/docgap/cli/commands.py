"""CLI command implementations for docgap."""
import dataclasses
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

import click

from docgap.config import load_config, Config
from docgap.orchestrator import PipelineRunner
from docgap.core.output import OutputManager
from docgap.core.classification import Classification, Category
from docgap.core.detector import Stage1Detector
from docgap.core.generator import Stage2Generator
from docgap.git import GitFetcher, LogParser
from docgap.llm import OllamaClient
from docgap.db import Database, init_database


def get_config(cli_obj) -> Config:
    """Load configuration from CLI context."""
    if cli_obj.config is None:
        cli_obj.config = load_config(cli_obj.config_path)
    return cli_obj.config


_REDACTED_PATTERN = re.compile(r"(?i)(password|secret|token|key|credential)")


def config_show_command(cli_obj) -> int:
    """Display all configuration sections."""
    try:
        config = get_config(cli_obj)
        click.echo("=== docgap Configuration ===")
        click.echo()
        for section_name, section_value in dataclasses.asdict(config).items():
            click.echo(f"[{section_name}]")
            if isinstance(section_value, dict):
                for key, value in section_value.items():
                    if _REDACTED_PATTERN.search(key):
                        click.echo(f"  {key}: [REDACTED]")
                    else:
                        click.echo(f"  {key}: {value}")
            else:  # pragma: no cover
                click.echo(f"  {section_value}")
            click.echo()
        return 0
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def run_pipeline(cli_obj, since_timestamp: Optional[str] = None, dry_run: bool = False) -> int:
    """Run the full detection and generation pipeline via orchestrator."""
    config = get_config(cli_obj)

    # Use the new orchestrator for full pipeline
    runner = PipelineRunner(config)

    if dry_run:
        click.echo("DRY RUN MODE")

    if since_timestamp:
        click.echo(f"Running pipeline from: {since_timestamp}")

    return runner.run_manual(since_timestamp, dry_run=dry_run)


def status_command(cli_obj) -> int:
    """Show system status and pipeline health."""
    try:
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))

        # Get last run
        last_run = db.get_last_successful_run()

        click.echo("=== docgap Status ===")
        click.echo()

        if last_run:
            click.echo(f"Last run: {last_run.get('started_at', 'Unknown')}")
            click.echo(f"Status: {last_run.get('status', 'Unknown')}")
            click.echo(f"Commits processed: {last_run.get('commits_processed', 0)}")
            click.echo(f"Commits flagged: {last_run.get('commits_flagged', 0)}")
        else:
            click.echo("No runs recorded yet")

        click.echo()
        click.echo("Commit statuses:")

        # Get counts
        for status in ["pending", "needs_doc", "irrelevant", "uncertain"]:
            count = len(db.get_commits_by_status(status))
            click.echo(f"  {status}: {count}")

        click.echo()
        click.echo("Output directory:")
        output_dir = Path(config.general.data_dir) / "output"
        if output_dir.exists():
            files = list(output_dir.rglob("*"))
            click.echo(f"  Files: {len([f for f in files if f.is_file()])}")
        else:
            click.echo("  Not yet created")

        click.echo()
        click.echo("LLM connection:")
        client = OllamaClient(
            base_url=config.llm.base_url,
            model=config.llm.model,
        )
        if client.is_healthy():
            click.echo("  Status: OK")
            click.echo(f"  Model: {config.llm.model}")
        else:
            click.echo("  Status: UNREACHABLE")

        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def log_command(cli_obj, since: Optional[str] = None, status: Optional[str] = None) -> int:
    """Query commit logs."""
    try:
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))

        # Get commits by status
        if status is not None:
            commits = db.get_commits_by_status(status)
        else:
            commits = db.get_commits_by_status("pending")
            commits += db.get_commits_by_status("needs_doc")

        # Filter by date if --since provided
        if since is not None:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                filtered = []
                for c in commits:
                    commit_date = c.get("date", "")
                    if commit_date:
                        try:
                            c_dt = datetime.fromisoformat(str(commit_date).replace("Z", "+00:00"))
                            if c_dt >= since_dt:
                                filtered.append(c)
                        except ValueError:
                            filtered.append(c)
                    else:
                        filtered.append(c)
                commits = filtered
            except ValueError:
                pass

        if not commits:
            click.echo("No commits in log.")
            return 0

        click.echo("=== docgap Log ===")
        click.echo()

        for commit in commits[:50]:  # Limit output
            click.echo(f"{commit['hash'][:12]} | {commit['subject']}")
            click.echo(f"  Status: {commit['status']}")
            click.echo(f"  Classification: {commit['classification']}")
            click.echo(f"  Confidence: {commit.get('confidence', 'N/A')}")
            click.echo()

        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def review_list(cli_obj) -> int:
    """List commits needing review."""
    try:
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))

        # Get commits awaiting review (needs_doc and doc_generated)
        commits = db.get_commits_by_status("needs_doc")
        commits += db.get_commits_by_status("doc_generated")

        if not commits:
            click.echo("No commits need review.")
            return 0

        click.echo("=== Commits Needing Review ===")
        click.echo()

        for commit in commits[:20]:  # Limit output
            click.echo(f"  {commit['hash'][:12]} | {commit['subject']}")
            click.echo(f"    Classification: {commit.get('classification', 'N/A')}")
            click.echo(f"    Confidence: {commit.get('confidence', 'N/A')}")
            click.echo(f"    Category: {commit.get('category', 'N/A')}")
            click.echo()

        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def review_show(cli_obj, commit_hash: str) -> int:
    """Show review details for a commit."""
    try:
        if not validate_commit_hash(commit_hash):
            click.echo(f"Error: invalid commit hash: {commit_hash}", err=True)
            return 1
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"
        output_path = Path(config.general.data_dir) / "output" / commit_hash

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))

        # Get commit from database
        commit = db.get_commit_by_hash(commit_hash)

        if not commit:
            click.echo(f"Commit {commit_hash} not found.")
            return 1

        click.echo("=== Commit Review ===")
        click.echo()
        click.echo(f"Hash: {commit['hash']}")
        click.echo(f"Subject: {commit['subject']}")
        click.echo(f"Classification: {commit['classification']}")
        click.echo(f"Confidence: {commit.get('confidence', 'N/A')}")
        click.echo(f"Category: {commit.get('category', 'N/A')}")

        if commit.get("reasoning"):
            click.echo()
            click.echo("Reasoning:")
            click.echo(commit["reasoning"])

        # Show output files if they exist
        if output_path.exists() and output_path.is_dir():
            click.echo()
            click.echo("Output files:")

            report_path = output_path / "report.txt"
            if report_path.exists():
                click.echo()
                click.echo("Report:")
                click.echo("-" * 50)
                click.echo(report_path.read_text()[:2000])

            for patch_name in ("manpage.patch", "handbook.patch"):
                patch_path = output_path / patch_name
                if patch_path.exists():
                    click.echo()
                    click.echo(f"Patch ({patch_name}):")
                    click.echo("-" * 50)
                    click.echo(patch_path.read_text())
                    break

        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def review_approve(cli_obj, commit_hash: str, reviewer: Optional[str] = None) -> int:
    """Approve a commit for documentation update."""
    try:
        if not validate_commit_hash(commit_hash):
            click.echo(f"Error: invalid commit hash: {commit_hash}", err=True)
            return 1
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))

        commit = db.get_commit_by_hash(commit_hash)
        if not commit:
            click.echo(f"Commit {commit_hash} not found.", err=True)
            return 1

        # State machine: approve from needs_doc or doc_generated
        approvable_states = {"needs_doc", "doc_generated"}
        if commit["status"] not in approvable_states:
            click.echo(
                f"Cannot approve commit {commit_hash}: status is '{commit['status']}' "
                f"(must be one of: {', '.join(sorted(approvable_states))})",
                err=True,
            )
            return 1

        reviewer_name = reviewer or os.environ.get("USER", "unknown")
        db.update_commit_by_hash(commit_hash, {
            "status": "reviewed",
            "reviewer": reviewer_name,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })

        click.echo(f"Commit {commit_hash} approved for documentation update.")
        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def review_reject(cli_obj, commit_hash: str, reason: Optional[str] = None, reviewer: Optional[str] = None) -> int:
    """Reject a commit - no documentation needed."""
    try:
        if not validate_commit_hash(commit_hash):
            click.echo(f"Error: invalid commit hash: {commit_hash}", err=True)
            return 1
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))

        commit = db.get_commit_by_hash(commit_hash)
        if not commit:
            click.echo(f"Commit {commit_hash} not found.", err=True)
            return 1

        # State machine: reject from needs_doc, doc_generated, or uncertain
        rejectable_states = {"needs_doc", "doc_generated", "uncertain"}
        if commit["status"] not in rejectable_states:
            click.echo(
                f"Cannot reject commit {commit_hash}: status is '{commit['status']}' "
                f"(must be one of: {', '.join(sorted(rejectable_states))})",
                err=True,
            )
            return 1

        reviewer_name = reviewer or os.environ.get("USER", "unknown")
        update_data: Dict[str, Any] = {
            "status": "false_positive",
            "reviewer": reviewer_name,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        if reason is not None:
            update_data["feedback"] = reason

        db.update_commit_by_hash(commit_hash, update_data)

        click.echo(f"Commit {commit_hash} rejected - no documentation needed.")
        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def init_command(cli_obj) -> int:
    """Initialize the database and output directories."""
    try:
        config = get_config(cli_obj)
        data_dir = Path(config.general.data_dir)

        # Create directories with restricted permissions
        data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(str(data_dir), 0o700)
        (data_dir / "output").mkdir(exist_ok=True)
        os.chmod(str(data_dir / "output"), 0o700)
        (data_dir / "repos").mkdir(exist_ok=True)
        os.chmod(str(data_dir / "repos"), 0o700)

        # Initialize database
        db_path = data_dir / "docgap.sqlite"
        init_database(str(db_path))

        click.echo(f"docgap initialized at {data_dir}")
        click.echo(f"Database: {db_path}")

        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def _format_commit_detail(commit: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
    """Build a detail dict for a commit, including output file info."""
    detail: Dict[str, Any] = {
        "hash": commit.get("hash", ""),
        "subject": commit.get("subject", ""),
        "author": commit.get("author", ""),
        "date": commit.get("date", ""),
        "classification": commit.get("classification", ""),
        "confidence": commit.get("confidence"),
        "category": commit.get("category"),
        "doc_target": commit.get("doc_target"),
        "reasoning": commit.get("reasoning"),
        "status": commit.get("status", ""),
    }
    # Check for output files (re-validate hash from DB for defense-in-depth)
    commit_hash_val = commit.get("hash", "")
    if not validate_commit_hash(commit_hash_val):
        return detail
    commit_output = output_dir / commit_hash_val
    if commit_output.is_dir():
        detail["output_files"] = [f.name for f in sorted(commit_output.iterdir()) if f.is_file()]
        report_file = commit_output / "report.txt"
        if report_file.exists():
            detail["report_preview"] = report_file.read_text()[:500]
    return detail


def report_command(cli_obj, output_format: str = "txt", output_file: Optional[str] = None, save: bool = False) -> int:
    """Generate documentation reports."""
    try:
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))
        output_dir = Path(config.general.data_dir) / "output"

        # Statistics
        total = 0
        status_counts = {}
        for status in ["pending", "needs_doc", "doc_generated", "irrelevant", "uncertain", "reviewed", "false_positive", "submitted", "error", "generation_error"]:
            count = len(db.get_commits_by_status(status))
            status_counts[status] = count
            total += count

        # Get last run info
        last_run = db.get_last_successful_run()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Gather detailed commit lists
        needs_doc = db.get_commits_by_status("needs_doc")
        doc_generated = db.get_commits_by_status("doc_generated")
        uncertain = db.get_commits_by_status("uncertain")
        errors = db.get_commits_by_statuses(["error", "generation_error"])

        if output_format == "json":
            report_data: Dict[str, Any] = {
                "generated_at": timestamp,
                "status_counts": {k: v for k, v in status_counts.items() if v > 0},
                "total": total,
                "last_run": {
                    "started_at": last_run.get("started_at") if last_run else None,
                    "finished_at": last_run.get("finished_at") if last_run else None,
                    "status": last_run.get("status") if last_run else None,
                    "commits_processed": last_run.get("commits_processed", 0) if last_run else 0,
                    "commits_flagged": last_run.get("commits_flagged", 0) if last_run else 0,
                },
                "needs_doc": [_format_commit_detail(c, output_dir) for c in needs_doc],
                "doc_generated": [_format_commit_detail(c, output_dir) for c in doc_generated],
                "uncertain": [_format_commit_detail(c, output_dir) for c in uncertain],
                "errors": [_format_commit_detail(c, output_dir) for c in errors],
            }
            content = json.dumps(report_data, indent=2, default=str)
        else:
            lines: List[str] = []
            lines.append("=" * 72)
            lines.append("docgap Report")
            lines.append(f"Generated: {timestamp}")
            lines.append("=" * 72)
            lines.append("")

            # Last run info
            if last_run:
                lines.append(f"Last successful run: {last_run.get('started_at', 'N/A')}")
                lines.append(f"  Status: {last_run.get('status', 'N/A')}")
                lines.append(f"  Commits processed: {last_run.get('commits_processed', 0)}")
                lines.append(f"  Commits flagged: {last_run.get('commits_flagged', 0)}")
                lines.append("")

            # Statistics
            lines.append("--- Statistics ---")
            for status, count in status_counts.items():
                if count > 0:
                    lines.append(f"  {status}: {count}")
            lines.append(f"  TOTAL: {total}")
            lines.append("")

            # Commits needing documentation (awaiting Stage 2)
            if needs_doc:
                lines.append("-" * 72)
                lines.append(f"NEEDS DOCUMENTATION ({len(needs_doc)} commits awaiting generation)")
                lines.append("-" * 72)
                for c in needs_doc:
                    lines.append(f"  {c['hash'][:12]}  {c.get('subject', 'N/A')}")
                    lines.append(f"    Author: {c.get('author', 'N/A')} | Date: {c.get('date', 'N/A')}")
                    lines.append(f"    Category: {c.get('category', 'N/A')} | Confidence: {c.get('confidence', 'N/A')}")
                    if c.get("doc_target"):
                        lines.append(f"    Doc target: {c['doc_target']}")
                    if c.get("reasoning"):
                        lines.append(f"    Reasoning: {c['reasoning'][:200]}")
                    lines.append("")

            # Commits with generated docs (ready for review)
            if doc_generated:
                lines.append("-" * 72)
                lines.append(f"DOCUMENTATION GENERATED ({len(doc_generated)} commits ready for review)")
                lines.append("-" * 72)
                for c in doc_generated:
                    commit_hash = c.get("hash", "")
                    lines.append(f"  {commit_hash[:12]}  {c.get('subject', 'N/A')}")
                    lines.append(f"    Author: {c.get('author', 'N/A')} | Date: {c.get('date', 'N/A')}")
                    lines.append(f"    Category: {c.get('category', 'N/A')} | Confidence: {c.get('confidence', 'N/A')}")
                    if c.get("doc_target"):
                        lines.append(f"    Doc target: {c['doc_target']}")
                    if c.get("reasoning"):
                        lines.append(f"    Reasoning: {c['reasoning'][:200]}")
                    # Show output files (validate hash before path construction)
                    if not validate_commit_hash(commit_hash):
                        lines.append("")
                        continue
                    commit_output = output_dir / commit_hash
                    if commit_output.is_dir():
                        out_files = [f.name for f in sorted(commit_output.iterdir()) if f.is_file()]
                        lines.append(f"    Output files: {', '.join(out_files)}")
                        # Include report preview
                        report_file = commit_output / "report.txt"
                        if report_file.exists():
                            preview = report_file.read_text().strip()[:300]
                            lines.append(f"    Report preview:")
                            for rline in preview.split("\n"):
                                lines.append(f"      {rline}")
                    lines.append("")

            # Uncertain commits (need triage)
            if uncertain:
                lines.append("-" * 72)
                lines.append(f"UNCERTAIN ({len(uncertain)} commits need human triage)")
                lines.append("-" * 72)
                for c in uncertain:
                    lines.append(f"  {c['hash'][:12]}  {c.get('subject', 'N/A')}")
                    lines.append(f"    Confidence: {c.get('confidence', 'N/A')}")
                    if c.get("reasoning"):
                        lines.append(f"    Reasoning: {c['reasoning'][:200]}")
                    lines.append("")

            # Errors
            if errors:
                lines.append("-" * 72)
                lines.append(f"ERRORS ({len(errors)} commits with processing errors)")
                lines.append("-" * 72)
                for c in errors:
                    lines.append(f"  {c['hash'][:12]}  {c.get('subject', 'N/A')}")
                    lines.append(f"    Status: {c.get('status', 'N/A')} | Retry count: {c.get('retry_count', 0)}")
                    if c.get("reasoning"):
                        lines.append(f"    Error: {c['reasoning'][:200]}")
                    lines.append("")

            if not needs_doc and not doc_generated and not uncertain and not errors:
                lines.append("No actionable commits found.")
                lines.append("")

            lines.append("=" * 72)
            lines.append("Commands:")
            lines.append("  docgap review show <hash>     View full details for a commit")
            lines.append("  docgap review approve <hash>  Approve for documentation")
            lines.append("  docgap review reject <hash>   Reject as false positive")
            lines.append("  docgap reprocess --failed      Retry failed commits")
            lines.append("=" * 72)

            content = "\n".join(lines)

        # Print to stdout
        click.echo(content)

        # Determine output file path
        dest = None
        if output_file:
            dest = Path(output_file)
        elif save:
            reports_dir = Path(config.general.data_dir) / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            ext = "json" if output_format == "json" else "txt"
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            dest = reports_dir / f"report-{ts}.{ext}"

        if dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Write with restricted permissions (reports may contain PII)
            fd = os.open(str(dest), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(content + "\n")
            click.echo(f"\nReport saved to: {dest}")

        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def review_approve_bulk(cli_obj, since: Optional[str] = None, reviewer: Optional[str] = None) -> int:
    """Approve all commits pending review, optionally filtered by --since."""
    try:
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))

        # Get all approvable commits
        approvable_states = ["needs_doc", "doc_generated"]
        commits = []
        for status in approvable_states:
            commits.extend(db.get_commits_by_status(status))

        # Filter by --since if provided
        if since is not None:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                filtered = []
                for c in commits:
                    commit_date = c.get("date", "")
                    if commit_date:
                        try:
                            c_dt = datetime.fromisoformat(str(commit_date).replace("Z", "+00:00"))
                            if c_dt >= since_dt:
                                filtered.append(c)
                        except ValueError:
                            filtered.append(c)
                    else:
                        filtered.append(c)
                commits = filtered
            except ValueError:
                pass

        if not commits:
            click.echo("No commits pending approval.")
            return 0

        reviewer_name = reviewer or os.environ.get("USER", "unknown")
        approved_count = 0

        for commit in commits:
            db.update_commit_by_hash(commit["hash"], {
                "status": "reviewed",
                "reviewer": reviewer_name,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            })
            approved_count += 1

        click.echo(f"Approved {approved_count} commits for documentation update.")
        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def reprocess_command(
    cli_obj,
    commit_hash: Optional[str] = None,
    failed: bool = False,
    pending: bool = False,
    stage1_hash: Optional[str] = None,
    stage2_hash: Optional[str] = None,
    since: Optional[str] = None,
    dry_run: bool = False,
    max_retries: int = 3,
) -> int:
    """Reprocess failed or incomplete commits through the pipeline."""
    try:
        config = get_config(cli_obj)
        if commit_hash and not validate_commit_hash(commit_hash):
            click.echo(f"Error: invalid commit hash: {commit_hash}", err=True)
            return 1
        if stage1_hash and not validate_commit_hash(stage1_hash):
            click.echo(f"Error: invalid commit hash: {stage1_hash}", err=True)
            return 1
        if stage2_hash and not validate_commit_hash(stage2_hash):
            click.echo(f"Error: invalid commit hash: {stage2_hash}", err=True)
            return 1
        from docgap.orchestrator.reprocessor import ReprocessRunner
        runner = ReprocessRunner(config)

        if stage1_hash:
            click.echo(f"Reprocessing Stage 1 for {stage1_hash[:12]}...")
            res = runner.reprocess_commit(stage1_hash, stage="stage1", dry_run=dry_run, max_retries=max_retries)
            return 0 if res["status"] == "success" else 1
        elif stage2_hash:
            click.echo(f"Reprocessing Stage 2 for {stage2_hash[:12]}...")
            res = runner.reprocess_commit(stage2_hash, stage="stage2", dry_run=dry_run, max_retries=max_retries)
            return 0 if res["status"] == "success" else 1
        elif commit_hash:
            click.echo(f"Reprocessing {commit_hash[:12]}...")
            res = runner.reprocess_commit(commit_hash, stage="both", dry_run=dry_run, max_retries=max_retries)
            return 0 if res["status"] == "success" else 1
        elif failed:
            summary = runner.reprocess_by_status(["error", "generation_error"], dry_run=dry_run, max_retries=max_retries)
            return 0 if summary["failed"] == 0 else 1
        elif pending:
            summary = runner.reprocess_by_status(["needs_doc"], dry_run=dry_run, max_retries=max_retries)
            return 0 if summary["failed"] == 0 else 1
        elif since:
            summary = runner.reprocess_since(since, dry_run=dry_run, max_retries=max_retries)
            return 0 if summary["failed"] == 0 else 1
        else:
            click.echo("Error: provide COMMIT_HASH, --failed, --pending, --stage1 HASH, --stage2 HASH, or --since", err=True)
            return 1

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def heal_command(cli_obj, fix: bool = False, dry_run: bool = False) -> int:
    """Detect and repair interrupted runs and stuck commits."""
    try:
        config = get_config(cli_obj)
        from docgap.orchestrator.reprocessor import ReprocessRunner
        runner = ReprocessRunner(config)

        click.echo("=== docgap Health Check ===")
        click.echo()
        result = runner.heal(fix=fix, dry_run=dry_run)

        if not fix and (result["stale_runs"] or result["incomplete_stage2"] or result["retryable_errors"]):
            total_issues = len(result["stale_runs"]) + len(result["incomplete_stage2"]) + len(result["retryable_errors"])
            click.echo()
            click.echo(f"Summary: {total_issues} issue(s) found. Run with --fix to repair.")

        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def validate_command(cli_obj) -> int:
    """Check system integrity: database, repos, LLM, config."""
    try:
        config = get_config(cli_obj)
        passed = 0
        warnings = 0
        errors = 0

        click.echo("=== docgap Validation ===")
        click.echo()

        # 1. Config
        click.echo("[OK]   Config loaded successfully")
        passed += 1

        # 2. Database
        db_path = Path(config.general.data_dir) / "docgap.sqlite"
        if db_path.exists():
            db = Database(str(db_path))
            counts = db.count_commits_by_status()
            total = sum(counts.values())
            click.echo(f"[OK]   Database: {db_path} ({total} commits)")
            passed += 1
        else:
            click.echo(f"[WARN] Database: {db_path} (not initialized)")
            warnings += 1

        # 3. Source repo
        src_path = Path(config.repositories.freebsd_src.path)
        if src_path.exists() and (src_path / "HEAD").exists():
            click.echo(f"[OK]   Source repo: {src_path} (bare)")
            passed += 1
        elif src_path.exists() and (src_path / ".git").exists():
            click.echo(f"[OK]   Source repo: {src_path}")
            passed += 1
        else:
            click.echo(f"[WARN] Source repo: {src_path} (not cloned)")
            warnings += 1

        # 4. Doc repo
        doc_path = Path(config.repositories.freebsd_doc.path)
        if doc_path.exists() and (doc_path / ".git").exists():
            click.echo(f"[OK]   Doc repo: {doc_path}")
            passed += 1
        else:
            click.echo(f"[WARN] Doc repo: {doc_path} (not cloned)")
            warnings += 1

        # 5. LLM connectivity
        client = OllamaClient(
            base_url=config.llm.base_url,
            model=config.llm.model,
        )
        if client.is_healthy():
            models = client.list_models()
            if config.llm.model in models or any(config.llm.model in m for m in models):
                click.echo(f"[OK]   LLM: {config.llm.base_url} (model: {config.llm.model})")
                passed += 1
            else:
                click.echo(f"[WARN] LLM: {config.llm.base_url} (model {config.llm.model} not found)")
                warnings += 1
        else:
            click.echo(f"[ERR]  LLM: {config.llm.base_url} (unreachable)")
            errors += 1

        # 6. Data directory
        data_dir = Path(config.general.data_dir)
        if data_dir.exists() and os.access(data_dir, os.W_OK):
            click.echo(f"[OK]   Data directory: {data_dir} (writable)")
            passed += 1
        elif data_dir.exists():
            click.echo(f"[ERR]  Data directory: {data_dir} (not writable)")
            errors += 1
        else:
            click.echo(f"[WARN] Data directory: {data_dir} (does not exist)")
            warnings += 1

        click.echo()
        click.echo(f"{passed} passed, {warnings} warning(s), {errors} error(s)")

        if errors > 0:
            return 2
        elif warnings > 0:
            return 1
        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def validate_commit_hash(commit_hash: str) -> bool:
    """Validate that a string looks like a hex commit hash."""
    return bool(re.fullmatch(r"[0-9a-fA-F]{4,64}", commit_hash))


def reset_command(cli_obj, commit_hash: str, confirm: bool = False) -> int:
    """Reset a commit to 'pending' status for full reprocessing."""
    try:
        if not validate_commit_hash(commit_hash):
            click.echo(f"Error: invalid commit hash: {commit_hash}", err=True)
            return 1
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))
        commit = db.get_commit_by_hash(commit_hash)

        if not commit:
            click.echo(f"Commit {commit_hash} not found.", err=True)
            return 1

        click.echo(f"Commit: {commit['hash'][:12]} | {commit.get('subject', 'N/A')}")
        click.echo(f"Current status: {commit['status']}")
        click.echo(f"Retry count: {commit.get('retry_count', 0)}")

        if not confirm:
            if not click.confirm("Reset this commit to pending?"):
                click.echo("Aborted.")
                return 0

        db.update_commit_by_hash(commit_hash, {
            "status": "pending",
            "classification": None,
            "confidence": None,
            "category": None,
            "doc_target": None,
            "reasoning": None,
            "retry_count": (commit.get("retry_count") or 0) + 1,
        })

        # Remove output directory if it exists
        output_dir = Path(config.general.data_dir) / "output" / commit_hash
        if output_dir.exists():
            import shutil
            shutil.rmtree(output_dir)
            click.echo(f"Removed output directory: {output_dir}")

        click.echo(f"Commit {commit_hash[:12]} reset to pending.")
        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


def purge_command(
    cli_obj,
    before: str,
    statuses: tuple = (),
    include_output: bool = False,
    dry_run: bool = False,
    confirm: bool = False,
) -> int:
    """Clean old data from the database and output directories."""
    try:
        config = get_config(cli_obj)
        db_path = Path(config.general.data_dir) / "docgap.sqlite"

        if not db_path.exists():
            click.echo("Database not initialized. Run 'docgap init' first.")
            return 1

        db = Database(str(db_path))

        # Default to terminal statuses if none specified
        status_list = list(statuses) if statuses else ["irrelevant", "false_positive", "reviewed", "submitted"]

        # Preview what will be purged
        with db.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in status_list)
            cursor.execute(
                f"SELECT COUNT(*) as cnt FROM commits WHERE date < ? AND status IN ({placeholders})",
                [before] + status_list,
            )
            count = cursor.fetchone()["cnt"]

        if count == 0:
            click.echo("No commits match the purge criteria.")
            return 0

        click.echo(f"Found {count} commit(s) to purge (before {before}, statuses: {', '.join(status_list)})")

        if dry_run:
            click.echo("[dry-run] No changes made.")
            return 0

        if not confirm:
            if not click.confirm(f"Delete {count} commit(s)?"):
                click.echo("Aborted.")
                return 0

        # Get hashes before deleting (for output cleanup)
        output_hashes = []
        if include_output:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT hash FROM commits WHERE date < ? AND status IN ({placeholders})",
                    [before] + status_list,
                )
                output_hashes = [row["hash"] for row in cursor.fetchall()]

        deleted = db.purge_commits_older_than(before, status_list)
        click.echo(f"Purged {deleted} commit(s) from database.")

        if include_output and output_hashes:
            import shutil
            removed = 0
            for h in output_hashes:
                if not validate_commit_hash(h):
                    continue
                output_dir = Path(config.general.data_dir) / "output" / h
                if output_dir.exists():
                    shutil.rmtree(output_dir)
                    removed += 1
            if removed:
                click.echo(f"Removed {removed} output director{'y' if removed == 1 else 'ies'}.")

        return 0

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1
