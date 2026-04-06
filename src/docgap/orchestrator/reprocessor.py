"""Reprocessor for re-running commits through Stage 1 and/or Stage 2."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from docgap.config import Config
from docgap.core.classification import Classification, ClassificationResult
from docgap.core.detector import Stage1Detector
from docgap.core.generator import Stage2Generator
from docgap.core.output import OutputManager
from docgap.core.retriever import DocRetriever
from docgap.db import Database, init_database
from docgap.git import GitFetcher
from docgap.llm import OllamaClient

logger = logging.getLogger(__name__)


class ReprocessRunner:
    """Reprocess commits already in the DB through Stage 1 and/or Stage 2."""

    def __init__(self, config: Config):
        self.config = config
        self.data_dir = Path(config.general.data_dir)
        self.db_path = self.data_dir / "docgap.sqlite"

        # Lazily initialized
        self._llm_client: Optional[OllamaClient] = None
        self._src_fetcher: Optional[GitFetcher] = None
        self._detector: Optional[Stage1Detector] = None
        self._generator: Optional[Stage2Generator] = None
        self._output_manager: Optional[OutputManager] = None

    # ------------------------------------------------------------------
    # Lazy initializers
    # ------------------------------------------------------------------

    def _get_db(self) -> Database:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            init_database(str(self.db_path))
        return Database(str(self.db_path))

    def _get_llm_client(self) -> OllamaClient:
        if self._llm_client is None:
            verbose = logging.getLogger().level <= logging.DEBUG
            self._llm_client = OllamaClient(
                base_url=self.config.llm.base_url,
                model=self.config.llm.model,
                timeout=self.config.llm.timeout,
                log_requests=verbose,
            )
            if self.config.debug.llm_logging:
                from docgap.llm.debug_logger import LLMDebugLogger
                self._debug_logger = LLMDebugLogger(self.config)
                self._llm_client.debug_logger = self._debug_logger
        return self._llm_client

    def _get_src_fetcher(self) -> GitFetcher:
        if self._src_fetcher is None:
            self._src_fetcher = GitFetcher(
                src_path=self.config.repositories.freebsd_src.path,
                src_remote=self.config.repositories.freebsd_src.remote,
                bare=True,
                timeout=self.config.llm.timeout,
            )
        return self._src_fetcher

    def _get_detector(self) -> Stage1Detector:
        if self._detector is None:
            self._detector = Stage1Detector(
                llm_client=self._get_llm_client(),
                git_fetcher=self._get_src_fetcher(),
                config=self.config,
            )
        return self._detector

    def _get_generator(self) -> Stage2Generator:
        if self._generator is None:
            doc_fetcher = GitFetcher(
                doc_path=self.config.repositories.freebsd_doc.path,
                doc_remote=self.config.repositories.freebsd_doc.remote,
                bare=False,
                timeout=self.config.llm.timeout,
            )
            doc_retriever = DocRetriever(doc_fetcher, self.config)
            self._generator = Stage2Generator(
                self._get_llm_client(), doc_retriever, self.config
            )
        return self._generator

    def _get_output_manager(self) -> OutputManager:
        if self._output_manager is None:
            self._output_manager = OutputManager(self.config)
        return self._output_manager

    # ------------------------------------------------------------------
    # Core reprocess logic
    # ------------------------------------------------------------------

    def reprocess_commit(
        self,
        commit_hash: str,
        stage: str = "both",
        dry_run: bool = False,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Reprocess a single commit through Stage 1 and/or Stage 2.

        Args:
            commit_hash: Full or partial commit hash.
            stage: One of 'stage1', 'stage2', or 'both'.
            dry_run: If True, skip writing to DB and output files.
            max_retries: Maximum allowed retry_count before skipping.

        Returns:
            Dict with keys: hash, status, stage1_result, stage2_result, error
        """
        result: Dict[str, Any] = {
            "hash": commit_hash,
            "status": "skipped",
            "stage1_result": None,
            "stage2_result": None,
            "error": None,
        }

        db = self._get_db()

        commit = db.get_commit_by_hash(commit_hash)
        if commit is None:
            result["status"] = "not_found"
            result["error"] = f"Commit {commit_hash} not found in database"
            click.echo(f"  ERROR: {result['error']}", err=True)
            return result

        retry_count = commit.get("retry_count") or 0
        if retry_count >= max_retries:
            result["status"] = "skipped"
            result["error"] = (
                f"retry_count={retry_count} >= max_retries={max_retries}; skipping"
            )
            click.echo(f"  SKIP {commit_hash[:12]}: {result['error']}")
            return result

        # Create audit run record
        run_id: Optional[int] = None
        if not dry_run:
            run_id = db.insert_run({"status": "reprocess"})

        try:
            new_retry_count = retry_count + 1

            # ----------------------------------------------------------
            # Stage 1
            # ----------------------------------------------------------
            if stage in ("stage1", "both"):
                click.echo(f"  Stage 1: classifying {commit_hash[:12]}...")

                # Build commit_data dict expected by detector.classify()
                files = commit.get("files") or []
                if isinstance(files, str):
                    files = json.loads(files)

                diff = ""
                try:
                    diff = self._get_src_fetcher().get_diff(commit_hash)
                except Exception as e:
                    logger.warning("Could not fetch diff for %s: %s", commit_hash, e)

                commit_data: Dict[str, Any] = {
                    "hash": commit.get("hash"),
                    "author": commit.get("author"),
                    "email": commit.get("email"),
                    "date": commit.get("date"),
                    "subject": commit.get("subject"),
                    "files": files,
                    "diff": diff,
                }

                classification: ClassificationResult = self._get_detector().classify(
                    commit_data
                )
                classification = classification.apply_thresholds(
                    self.config.detection.confidence_threshold_accept,
                    self.config.detection.confidence_threshold_reject,
                )

                result["stage1_result"] = {
                    "classification": classification.classification.name,
                    "confidence": classification.confidence,
                    "category": classification.category.name if classification.category else None,
                    "doc_target": classification.doc_target,
                    "reasoning": classification.reasoning,
                }

                if not dry_run:
                    db.update_commit_by_hash(
                        commit_hash,
                        {
                            "status": classification.classification.name.lower(),
                            "classification": classification.classification.name,
                            "confidence": classification.confidence,
                            "category": classification.category.name if classification.category else None,
                            "doc_target": classification.doc_target,
                            "reasoning": classification.reasoning,
                            "retry_count": new_retry_count,
                        },
                    )
                    # Refresh commit from DB for stage 2
                    commit = db.get_commit_by_hash(commit_hash) or commit
            else:
                # Use existing classification for stage2-only runs
                cls_str = (commit.get("classification") or "IRRELEVANT").upper()
                try:
                    cls_enum = Classification(cls_str)
                except ValueError:
                    cls_enum = Classification.IRRELEVANT
                classification = ClassificationResult(
                    classification=cls_enum,
                    confidence=commit.get("confidence") or 0.0,
                    doc_target=commit.get("doc_target"),
                    reasoning=commit.get("reasoning"),
                )

            # ----------------------------------------------------------
            # Stage 2
            # ----------------------------------------------------------
            if stage in ("stage2", "both"):
                current_status = (
                    result["stage1_result"]["classification"].lower()
                    if result["stage1_result"]
                    else (commit.get("status") or "")
                )

                if classification.classification != Classification.NEEDS_DOC:
                    click.echo(
                        f"  Stage 2: skipping {commit_hash[:12]} "
                        f"(not needs_doc: {classification.classification.name})"
                    )
                else:
                    click.echo(f"  Stage 2: generating docs for {commit_hash[:12]}...")

                    files = commit.get("files") or []
                    if isinstance(files, str):
                        files = json.loads(files)

                    diff = ""
                    try:
                        diff = self._get_src_fetcher().get_diff(commit_hash)
                    except Exception as e:
                        logger.warning(
                            "Could not fetch diff for %s: %s", commit_hash, e
                        )

                    commit_data = {
                        "hash": commit.get("hash"),
                        "author": commit.get("author"),
                        "email": commit.get("email"),
                        "date": commit.get("date"),
                        "subject": commit.get("subject"),
                        "files": files,
                        "diff": diff,
                    }

                    gen_result = self._get_generator().generate(commit_data, classification)

                    result["stage2_result"] = {
                        "success": gen_result.success,
                        "report": gen_result.report,
                    }

                    if gen_result.success:
                        if not dry_run:
                            self._get_output_manager().save_output(
                                commit_hash, gen_result, classification
                            )
                            db.update_commit_by_hash(
                                commit_hash,
                                {
                                    "status": "doc_generated",
                                    "retry_count": new_retry_count,
                                },
                            )
                    else:
                        result["error"] = f"Generation failed: {gen_result.report}"
                        if not dry_run:
                            db.update_commit_by_hash(
                                commit_hash,
                                {
                                    "status": "generation_error",
                                    "reasoning": gen_result.report,
                                    "retry_count": new_retry_count,
                                },
                            )

            # Finalize run record
            if not dry_run and run_id is not None:
                db.update_run(
                    run_id,
                    {
                        "status": "completed",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "commits_processed": 1,
                    },
                )

            result["status"] = "success" if result["error"] is None else "failed"
            click.echo(f"  Done: {commit_hash[:12]} -> {result['status']}")
            return result

        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
            click.echo(f"  ERROR processing {commit_hash[:12]}: {exc}", err=True)

            if not dry_run:
                if run_id is not None:
                    db.update_run(
                        run_id,
                        {
                            "status": "failed",
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "error_message": str(exc),
                        },
                    )
                db.update_commit_by_hash(
                    commit_hash,
                    {
                        "status": "error",
                        "reasoning": str(exc),
                        "retry_count": (commit.get("retry_count") or 0) + 1,
                    },
                )

            return result

    # ------------------------------------------------------------------
    # Bulk reprocess helpers
    # ------------------------------------------------------------------

    def reprocess_by_status(
        self,
        statuses: List[str],
        dry_run: bool = False,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Reprocess all commits matching given statuses.

        Returns:
            Dict with keys: total, succeeded, failed, skipped, details
        """
        db = self._get_db()
        commits = db.get_commits_by_statuses(statuses)

        summary: Dict[str, Any] = {
            "total": len(commits),
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
        }

        click.echo(
            f"Reprocessing {len(commits)} commits with status in {statuses}..."
        )

        for commit in commits:
            commit_hash = commit.get("hash", "")
            res = self.reprocess_commit(
                commit_hash, stage="both", dry_run=dry_run, max_retries=max_retries
            )
            summary["details"].append(res)

            if res["status"] == "success":
                summary["succeeded"] += 1
            elif res["status"] == "skipped":
                summary["skipped"] += 1
            else:
                summary["failed"] += 1

        click.echo(
            f"Reprocess complete: {summary['succeeded']} succeeded, "
            f"{summary['failed']} failed, {summary['skipped']} skipped"
        )
        return summary

    def reprocess_since(
        self,
        since_iso: str,
        dry_run: bool = False,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Reprocess all commits whose date is >= since_iso.

        Returns:
            Dict with keys: total, succeeded, failed, skipped, details
        """
        db = self._get_db()

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM commits WHERE date >= ? ORDER BY date ASC",
                (since_iso,),
            )
            rows = cursor.fetchall()

        commits = []
        for row in rows:
            commit = dict(row)
            if commit.get("files"):
                commit["files"] = json.loads(commit["files"])
            commits.append(commit)

        summary: Dict[str, Any] = {
            "total": len(commits),
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
        }

        click.echo(f"Reprocessing {len(commits)} commits since {since_iso}...")

        for commit in commits:
            commit_hash = commit.get("hash", "")
            res = self.reprocess_commit(
                commit_hash, stage="both", dry_run=dry_run, max_retries=max_retries
            )
            summary["details"].append(res)

            if res["status"] == "success":
                summary["succeeded"] += 1
            elif res["status"] == "skipped":
                summary["skipped"] += 1
            else:
                summary["failed"] += 1

        click.echo(
            f"Reprocess complete: {summary['succeeded']} succeeded, "
            f"{summary['failed']} failed, {summary['skipped']} skipped"
        )
        return summary

    # ------------------------------------------------------------------
    # Heal
    # ------------------------------------------------------------------

    def heal(self, fix: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        """Detect and repair pipeline issues.

        Args:
            fix: If True, attempt to repair found issues.
            dry_run: If True, report issues but do not write changes.

        Returns:
            Dict with keys: stale_runs, incomplete_stage2, retryable_errors, actions_taken
        """
        db = self._get_db()
        output_manager = self._get_output_manager()

        result: Dict[str, Any] = {
            "stale_runs": [],
            "incomplete_stage2": [],
            "retryable_errors": [],
            "actions_taken": [],
        }

        # 1. Find stale runs (stuck in 'running' > 24h)
        stale_runs = db.get_stale_runs(older_than_hours=24)
        result["stale_runs"] = [r.get("id") for r in stale_runs]

        if stale_runs:
            click.echo(f"Found {len(stale_runs)} stale run(s): {result['stale_runs']}")
            if fix and not dry_run:
                for run in stale_runs:
                    db.update_run(
                        run["id"],
                        {
                            "status": "failed",
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "error_message": "Marked failed by heal: stale run",
                        },
                    )
                    result["actions_taken"].append(
                        f"Marked run {run['id']} as failed (stale)"
                    )
                click.echo(f"  Marked {len(stale_runs)} stale run(s) as failed")

        # 2. Find commits with needs_doc status but no output directory
        needs_doc_commits = db.get_commits_by_statuses(["needs_doc"])
        incomplete: List[str] = []
        for commit in needs_doc_commits:
            commit_hash = commit.get("hash", "")
            if not commit_hash:
                continue
            output = output_manager.load_output(commit_hash)
            if output is None:
                incomplete.append(commit_hash)

        result["incomplete_stage2"] = incomplete
        if incomplete:
            click.echo(
                f"Found {len(incomplete)} commit(s) with needs_doc but no output"
            )
            if fix:
                click.echo(f"  Reprocessing {len(incomplete)} incomplete stage2 commit(s)...")
                for commit_hash in incomplete:
                    res = self.reprocess_commit(
                        commit_hash, stage="stage2", dry_run=dry_run
                    )
                    action = f"Reprocessed stage2 for {commit_hash[:12]}: {res['status']}"
                    result["actions_taken"].append(action)
                    click.echo(f"  {action}")

        # 3. Find retryable errors
        error_commits = db.get_commits_by_statuses(["error", "generation_error"])
        retryable: List[str] = []
        for commit in error_commits:
            retry_count = commit.get("retry_count") or 0
            if retry_count < self.config.generation.max_retries:
                retryable.append(commit.get("hash", ""))

        result["retryable_errors"] = [h for h in retryable if h]
        if retryable:
            click.echo(
                f"Found {len(retryable)} retryable error commit(s)"
            )
            if fix:
                click.echo(f"  Reprocessing {len(retryable)} error commit(s)...")
                for commit_hash in retryable:
                    if not commit_hash:
                        continue
                    res = self.reprocess_commit(
                        commit_hash,
                        stage="both",
                        dry_run=dry_run,
                        max_retries=self.config.generation.max_retries,
                    )
                    action = f"Reprocessed {commit_hash[:12]}: {res['status']}"
                    result["actions_taken"].append(action)
                    click.echo(f"  {action}")

        if not result["actions_taken"]:
            click.echo("Heal complete: no actions taken")
        else:
            click.echo(
                f"Heal complete: {len(result['actions_taken'])} action(s) taken"
            )

        return result
