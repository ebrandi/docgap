"""Pipeline runner for docgap - orchestrates the full detection and generation pipeline."""
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import click
import yaml

from docgap.config import load_config, Config
from docgap.db import Database, init_database
from docgap.core.classification import Classification, ClassificationResult
from docgap.core.detector import Stage1Detector
from docgap.core.generator import Stage2Generator
from docgap.core.output import OutputManager
from docgap.core.output_metadata import OutputMetadata
from docgap.core.retriever import DocRetriever
from docgap.git import GitFetcher, LogParser
from docgap.llm import OllamaClient


class PipelineRunner:
    """Manages and executes the full docgap pipeline."""

    def __init__(self, config: Config):
        """
        Initialize the pipeline runner.

        Args:
            config: Loaded configuration
        """
        self.config = config
        self.data_dir = Path(config.general.data_dir)
        self.db_path = self.data_dir / "docgap.sqlite"

    def ensure_database(self) -> Database:
        """Initialize database if needed and return connection."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (self.data_dir / "output").mkdir(exist_ok=True)
        (self.data_dir / "repos").mkdir(exist_ok=True)
        (self.data_dir / "logs").mkdir(exist_ok=True)
        
        # Initialize database
        if not self.db_path.exists():
            init_database(str(self.db_path))
        
        return Database(str(self.db_path))

    def run_pipeline(self, since_timestamp: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        Execute the full pipeline: fetch, parse, detect, generate.

        Args:
            since_timestamp: ISO 8601 timestamp to process commits since.
                           If None, processes since last successful run.
            dry_run: If True, skip persisting results and notifications.

        Returns:
            Dictionary with pipeline results
        """
        click.echo("Starting docgap pipeline...")

        db = self.ensure_database()
        result = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "commits_processed": 0,
            "commits_flagged": 0,
            "commits_with_doc": 0,
            "failed_commits": [],
            "errors": [],
            "filter_stats": {},
        }

        run_id = None

        try:
            # Initialize git fetcher
            src_fetcher = GitFetcher(
                src_path=self.config.repositories.freebsd_src.path,
                src_remote=self.config.repositories.freebsd_src.remote,
                bare=True,
                timeout=self.config.llm.timeout,
            )

            # Ensure repos exist and fetch latest commits
            click.echo("Setting up git repositories...")
            src_fetcher.ensure_repos()
            click.echo("Fetching latest commits...")
            src_fetcher.fetch_src()

            # Get last processed timestamp if not provided
            if since_timestamp is None:
                last_run = db.get_last_successful_run()
                if last_run and last_run.get("finished_at"):
                    since_timestamp = last_run["finished_at"]
                    click.echo(f"Resuming from: {since_timestamp}")
                else:
                    # First run - process recent commits
                    since_timestamp = (datetime.now(timezone.utc).astimezone() - timedelta(days=7)).isoformat()
                    click.echo(f"No previous run found, processing last 7 days")

            # Parse commits since last run
            parser = LogParser(src_fetcher, self.config)
            commits, filter_stats = parser.parse_and_filter(since_timestamp)
            result["filter_stats"] = filter_stats

            if not commits:
                click.echo("No new commits to process.")
                result["status"] = "no_commits"
                return result

            click.echo(f"Found {len(commits)} new commits")
            if filter_stats.get("filtered_out", 0) > 0:
                click.echo(f"Pre-filter: {filter_stats['filtered_out']} commits skipped")

            # Start database run record (skip in dry_run)
            if not dry_run:
                run_id = db.insert_run({"status": "running"})
            else:
                run_id = None

            # Initialize LLM client and stage components
            verbose = logging.getLogger().level <= logging.DEBUG
            llm_client = OllamaClient(
                base_url=self.config.llm.base_url,
                model=self.config.llm.model,
                timeout=self.config.llm.timeout,
                log_requests=verbose,
            )

            # Initialize debug logger if enabled
            debug_logger = None
            if self.config.debug.llm_logging:
                from docgap.llm.debug_logger import LLMDebugLogger
                debug_logger = LLMDebugLogger(self.config)
                llm_client.debug_logger = debug_logger

            detector = Stage1Detector(
                llm_client=llm_client,
                git_fetcher=src_fetcher,
                config=self.config,
            )

            # Initialize stage 2 components if generation is enabled
            if self.config.generation.enabled:
                doc_fetcher = GitFetcher(
                    doc_path=self.config.repositories.freebsd_doc.path,
                    doc_remote=self.config.repositories.freebsd_doc.remote,
                    bare=False,
                    timeout=self.config.llm.timeout,
                )
                doc_fetcher.ensure_repos()

                doc_retriever = DocRetriever(doc_fetcher, self.config)
                generator = Stage2Generator(llm_client, doc_retriever, self.config)
            else:
                doc_retriever = None
                generator = None

            # First pass: Stage 1 Detection
            click.echo("Stage 1: Detecting documentation needs...")
            flagged_commits = []

            for commit in commits:
                try:
                    # Skip commits already processed (e.g., from an interrupted run)
                    commit_hash = commit.get("hash")
                    if not dry_run and commit_hash and db.get_commit_by_hash(commit_hash):
                        click.echo(f"  Skipping already processed: {commit_hash[:12]}")
                        continue

                    result["commits_processed"] += 1

                    # Classify commit
                    classification = detector.classify(commit)

                    # Apply confidence thresholds
                    classification = classification.apply_thresholds(
                        self.config.detection.confidence_threshold_accept,
                        self.config.detection.confidence_threshold_reject,
                    )

                    # Save to database (skip in dry_run)
                    if not dry_run:
                        db.insert_commit({
                            "run_id": run_id,
                            "hash": commit.get("hash"),
                            "author": commit.get("author"),
                            "email": commit.get("email"),
                            "date": commit.get("date"),
                            "subject": commit.get("subject"),
                            "files": json.dumps(commit.get("files", [])),
                            "status": classification.classification.name.lower(),
                            "classification": classification.classification.name,
                            "confidence": classification.confidence,
                            "category": classification.category.name if classification.category else None,
                            "doc_target": classification.doc_target,
                            "reasoning": classification.reasoning,
                        })
                    else:  # pragma: no cover
                        click.echo(f"  [dry-run] Would insert commit {commit.get('hash', '')[:12]}: {classification.classification.name}")

                    # Track flagged commits
                    if classification.classification == Classification.NEEDS_DOC:
                        flagged_commits.append({
                            "commit": commit,
                            "classification": classification,
                        })
                        result["commits_flagged"] += 1

                    # Write debug metadata after Stage 1 (will be updated after Stage 2 if applicable)
                    if debug_logger and commit_hash:
                        debug_logger.write_metadata(
                            commit_hash=commit_hash,
                            model=self.config.llm.model,
                            config=self.config,
                            started_at=result["started_at"],
                            finished_at=datetime.now(timezone.utc).isoformat(),
                        )

                except Exception as e:
                    error_msg = f"Error classifying {commit.get('hash', 'unknown')}: {e}"
                    click.echo(f"ERROR: {error_msg}", err=True)
                    result["errors"].append(error_msg)
                    if not dry_run:
                        db.insert_commit({
                            "run_id": run_id,
                            "hash": commit.get("hash"),
                            "status": "error",
                            "classification": "ERROR",
                            "reasoning": str(e),
                        })

            # Second pass: Stage 2 Generation (if enabled)
            if generator and flagged_commits:
                click.echo(f"Stage 2: Generating documentation for {len(flagged_commits)} commits...")

                output_manager = OutputManager(self.config)

                for item in flagged_commits:
                    commit = item["commit"]
                    classification = item["classification"]

                    try:
                        # Generate documentation
                        gen_result = generator.generate(commit, classification)

                        if gen_result.success:
                            # Determine doc format from target path
                            doc_format = "mdoc"
                            if classification.doc_target and any(classification.doc_target.endswith(ext) for ext in ('.adoc', '.asciidoc')):
                                doc_format = "asciidoc"

                            # Validate output if enabled
                            if self.config.generation.validate_mdoc and doc_format == "mdoc":
                                from docgap.core.validator import DocValidator
                                validator = DocValidator(self.config)
                                val_result = validator.validate(gen_result.patch, "mdoc")

                                if not val_result.valid:
                                    click.echo(f"  WARNING: Validation failed for {commit['hash'][:12]}")
                            elif self.config.generation.validate_asciidoc and doc_format == "asciidoc":
                                from docgap.core.validator import DocValidator
                                validator = DocValidator(self.config)
                                val_result = validator.validate(gen_result.patch, "asciidoc")

                            # Save output
                            output_manager.save_output(
                                commit.get("hash"),
                                gen_result,
                                classification,
                            )
                            result["commits_with_doc"] += 1

                            # Update database (skip in dry_run)
                            if not dry_run:
                                db.update_commit_by_hash(commit.get("hash"), {
                                    "status": "doc_generated",
                                })
                        else:
                            error_msg = f"Generation failed for {commit.get('hash')}: {gen_result.report}"
                            click.echo(f"ERROR: {error_msg}", err=True)
                            result["errors"].append(error_msg)

                    except Exception as e:
                        error_msg = f"Error generating docs for {commit.get('hash', 'unknown')}: {e}"
                        click.echo(f"ERROR: {error_msg}", err=True)
                        result["errors"].append(error_msg)
                        if not dry_run:
                            db.update_commit_by_hash(commit.get("hash"), {
                                "status": "generation_error",
                                "reasoning": str(e),
                            })

            # Update run status (skip in dry_run)
            if not dry_run:
                db.update_run(run_id, {
                    "status": "completed",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "commits_processed": result["commits_processed"],
                    "commits_flagged": result["commits_flagged"],
                })

                # Send notifications (if enabled)
                if self.config.notification.enabled:
                    self._send_notifications(db, run_id, result)

            result["status"] = "completed"
            click.echo(f"Pipeline complete: {result['commits_processed']} processed, {result['commits_flagged']} flagged")
            return result

        except Exception as e:
            # Update run status to failed (skip in dry_run)
            if not dry_run and run_id is not None:
                db.update_run(run_id, {
                    "status": "failed",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "error_message": str(e),
                })
            result["status"] = "failed"
            result["error"] = str(e)
            click.echo(f"Pipeline failed: {e}", err=True)
            return result

    def _send_notifications(self, db: Database, run_id: int, result: Dict[str, Any]) -> None:
        """Send email notifications for this run."""
        from docgap.core.notifier import Notifier

        try:
            notifier = Notifier(self.config, db)

            # Get commits for notification
            flagged_commits = db.get_commits_by_status("needs_doc")
            uncertain_commits = db.get_commits_by_status("uncertain")

            # Build run results summary
            run_results = {
                "run_id": run_id,
                "total_commits": result["commits_processed"],
                "flagged_commits": result["commits_flagged"],
                "uncertain_commits": len(uncertain_commits),
                "commits_with_doc": result["commits_with_doc"],
                "commits": flagged_commits,
                "started_at": result.get("started_at", "N/A"),
                "finished_at": result.get("finished_at", "N/A"),
            }

            # Send digest to Doceng team
            notifier.send_digest(run_results)

            # Send per-commit emails to committers
            for commit in flagged_commits:
                notifier.send_per_commit(commit)

        except Exception as e:
            click.echo(f"Warning: Notification failed: {e}", err=True)

    def run_cron_mode(self) -> int:
        """
        Run in cron mode - with proper exit codes for cron jobs.

        Returns:
            Exit code (0=success, 1=partial, 2=failure)
        """
        result = self.run_pipeline()

        if result.get("status") == "completed":
            if result.get("errors"):
                return 1  # Partial success with errors
            return 0  # Success
        else:
            return 2  # Failure

    def run_manual(self, since_timestamp: Optional[str] = None, dry_run: bool = False) -> int:
        """
        Run in manual mode - with verbose output.

        Args:
            since_timestamp: Optional timestamp to process from
            dry_run: If True, skip persisting results and notifications

        Returns:
            Exit code (0=success, 1=partial, 2=failure)
        """
        result = self.run_pipeline(since_timestamp, dry_run=dry_run)

        if result.get("status") == "completed":
            return 0
        else:
            return 2


# Convenience function for CLI
def run_pipeline(
    config_path: Optional[str] = None,
    since_timestamp: Optional[str] = None,
) -> int:
    """
    Convenience function to run the pipeline.

    Args:
        config_path: Path to config file, defaults to config/config.yaml
        since_timestamp: ISO timestamp to process from

    Returns:
        Exit code
    """
    if config_path is None:
        config_path = "config/config.yaml"

    config = load_config(config_path)
    runner = PipelineRunner(config)
    return runner.run_manual(since_timestamp)
