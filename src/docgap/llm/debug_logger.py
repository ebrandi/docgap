"""LLM debug logger - saves prompts and responses to disk for debugging."""
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgap import __version__
from docgap.config.schema import Config

logger = logging.getLogger(__name__)


@dataclass
class LLMCallContext:
    commit_hash: str
    stage: str
    sequence_num: int


class LLMDebugLogger:
    """Saves LLM prompts and responses to disk for debugging and cross-model comparison."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._debug = config.debug
        if self._debug.log_dir:
            self._base_dir = Path(self._debug.log_dir)
        else:
            self._base_dir = Path(config.general.data_dir) / "debug"
        self._counters: Dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return self._debug.llm_logging

    def get_next_sequence(self, commit_hash: str) -> int:
        """Return next monotonic sequence number for the given commit."""
        self._counters[commit_hash] = self._counters.get(commit_hash, 0) + 1
        return self._counters[commit_hash]

    def _commit_dir(self, commit_hash: str) -> Path:
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit_hash):
            raise ValueError(f"Invalid commit hash: {commit_hash}")
        target = self._base_dir / commit_hash
        if target.is_symlink():
            raise ValueError(f"Symlink detected at debug path: {target}")
        return target

    def _pad(self, n: int) -> str:
        return str(n).zfill(2)

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(str(path.parent), 0o700)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def log_request(
        self,
        context: LLMCallContext,
        messages: List[Dict[str, Any]],
        json_mode: bool,
        options: Dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        prefix = f"{self._pad(context.sequence_num)}-{context.stage}"
        path = self._commit_dir(context.commit_hash) / f"{prefix}-prompt.txt"
        lines = [
            f"json_mode: {json_mode}",
            f"options: {json.dumps(options)}",
            "",
        ]
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"[{role}]")
            lines.append(content)
            lines.append("")
        self._atomic_write(path, "\n".join(lines))
        logger.debug("LLM request logged to %s", path)

    def log_response(
        self,
        context: LLMCallContext,
        raw_response: str,
        parsed_result: Optional[Any] = None,
    ) -> None:
        if not self.enabled:
            return
        prefix = f"{self._pad(context.sequence_num)}-{context.stage}"
        base = self._commit_dir(context.commit_hash)
        self._atomic_write(base / f"{prefix}-response.txt", raw_response)
        if parsed_result is not None:
            self._atomic_write(
                base / f"{prefix}-result.json",
                json.dumps(parsed_result, indent=2, default=str),
            )
        logger.debug("LLM response logged to %s", base / f"{prefix}-response.txt")

    def write_metadata(
        self,
        commit_hash: str,
        model: str,
        config: Config,
        started_at: str,
        finished_at: str,
        stage_durations: Optional[Dict[str, float]] = None,
    ) -> None:
        if not self.enabled:
            return
        data: Dict[str, Any] = {
            "commit_hash": commit_hash,
            "model": model,
            "pipeline_version": __version__,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        if stage_durations is not None:
            data["stage_durations"] = stage_durations
        if self._debug.include_config_snapshot:
            data["config_snapshot"] = {
                "detection": {
                    "confidence_threshold_accept": config.detection.confidence_threshold_accept,
                    "confidence_threshold_reject": config.detection.confidence_threshold_reject,
                    "skip_patterns": config.detection.skip_patterns,
                    "skip_paths": config.detection.skip_paths,
                    "skip_files": config.detection.skip_files,
                },
                "generation": {
                    "enabled": config.generation.enabled,
                    "validate_mdoc": config.generation.validate_mdoc,
                    "validate_asciidoc": config.generation.validate_asciidoc,
                    "max_retries": config.generation.max_retries,
                },
            }
        path = self._commit_dir(commit_hash) / "metadata.json"
        self._atomic_write(path, json.dumps(data, indent=2))

    def rotate_if_needed(self) -> int:
        """Delete oldest debug dirs when over limit; rename existing same-hash dir before fresh run."""
        if not self.enabled:
            return 0
        self._base_dir.mkdir(parents=True, exist_ok=True)
        rotated = 0

        # Rename any existing dir that matches a commit hash we're about to reuse.
        # Callers should call this before creating a new commit dir.
        # Here we handle the case where base_dir already contains a dir for any
        # active counter key (i.e. a re-run of the same commit).
        for commit_hash in list(self._counters):
            existing = self._commit_dir(commit_hash)
            if existing.exists():
                n = 1
                while True:
                    versioned = self._base_dir / f"{commit_hash}.v{n}"
                    if not versioned.exists():
                        existing.rename(versioned)
                        rotated += 1
                        break
                    n += 1

        # Enforce max_debug_entries limit by deleting oldest dirs.
        max_entries = self._debug.max_debug_entries
        dirs = sorted(
            [d for d in self._base_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
        )
        while len(dirs) > max_entries:
            oldest = dirs.pop(0)
            try:
                import shutil
                shutil.rmtree(oldest)
                rotated += 1
                logger.debug("Rotated debug dir %s", oldest)
            except OSError as e:
                logger.warning("Failed to remove debug dir %s: %s", oldest, e)

        return rotated
