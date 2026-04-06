"""Tests for LLM debug logger."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pytest

from docgap.config.schema import (
    AutoSubmitConfig,
    Config,
    DebugConfig,
    DetectionConfig,
    GeneralConfig,
    GenerationConfig,
    LLMConfig,
    NotificationConfig,
    RepositoriesConfig,
    RepositoryConfig,
    ReviewConfig,
)
from docgap.llm.debug_logger import LLMCallContext, LLMDebugLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, **debug_kwargs) -> Config:
    """Build a minimal Config with optional DebugConfig overrides."""
    return Config(
        general=GeneralConfig(data_dir=str(tmp_path), log_level="debug"),
        repositories=RepositoriesConfig(
            freebsd_src=RepositoryConfig(path=str(tmp_path / "src"), remote="https://example.com/src.git"),
            freebsd_doc=RepositoryConfig(path=str(tmp_path / "doc"), remote="https://example.com/doc.git"),
        ),
        llm=LLMConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="test-model",
            temperature=0.1,
            max_context=4096,
            timeout=30,
        ),
        detection=DetectionConfig(
            confidence_threshold_accept=0.80,
            confidence_threshold_reject=0.50,
        ),
        generation=GenerationConfig(),
        review=ReviewConfig(auto_submit=AutoSubmitConfig(enabled=False, hold_period_hours=24)),
        notification=NotificationConfig(),
        debug=DebugConfig(**debug_kwargs),
    )


def _context(commit: str = "abc123def4567", stage: str = "detect", seq: int = 1) -> LLMCallContext:
    return LLMCallContext(commit_hash=commit, stage=stage, sequence_num=seq)


# ---------------------------------------------------------------------------
# LLMCallContext
# ---------------------------------------------------------------------------

class TestLLMCallContext:
    def test_dataclass_fields(self):
        ctx = LLMCallContext(commit_hash="deadbeef", stage="generate", sequence_num=3)
        assert ctx.commit_hash == "deadbeef"
        assert ctx.stage == "generate"
        assert ctx.sequence_num == 3


# ---------------------------------------------------------------------------
# LLMDebugLogger.enabled
# ---------------------------------------------------------------------------

class TestEnabled:
    def test_disabled_by_default(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path))
        assert logger.enabled is False

    def test_enabled_when_config_true(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        assert logger.enabled is True


# ---------------------------------------------------------------------------
# get_next_sequence
# ---------------------------------------------------------------------------

class TestGetNextSequence:
    def test_starts_at_one(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path))
        assert logger.get_next_sequence("abc") == 1

    def test_monotonically_increasing(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path))
        results = [logger.get_next_sequence("abc") for _ in range(5)]
        assert results == [1, 2, 3, 4, 5]

    def test_independent_per_commit(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path))
        logger.get_next_sequence("aaa")
        logger.get_next_sequence("aaa")
        assert logger.get_next_sequence("bbb") == 1
        assert logger.get_next_sequence("aaa") == 3


# ---------------------------------------------------------------------------
# log_request
# ---------------------------------------------------------------------------

class TestLogRequest:
    def test_creates_prompt_file(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        ctx = _context(commit="abc123def4567", stage="detect", seq=1)
        messages = [{"role": "user", "content": "hello"}]
        logger.log_request(ctx, messages, json_mode=False, options={"temperature": 0.1})

        prompt_file = tmp_path / "debug" / "abc123def4567" / "01-detect-prompt.txt"
        assert prompt_file.exists()

    def test_prompt_file_contains_metadata(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        ctx = _context(commit="abc123def4567", stage="detect", seq=1)
        messages = [{"role": "system", "content": "You are a bot"}]
        logger.log_request(ctx, messages, json_mode=True, options={"temperature": 0.2})

        content = (tmp_path / "debug" / "abc123def4567" / "01-detect-prompt.txt").read_text()
        assert "json_mode: True" in content
        assert '"temperature": 0.2' in content
        assert "[system]" in content
        assert "You are a bot" in content

    def test_sequence_pads_to_two_digits(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        ctx = _context(commit="abc123def4567", stage="gen", seq=5)
        logger.log_request(ctx, [], json_mode=False, options={})
        assert (tmp_path / "debug" / "abc123def4567" / "05-gen-prompt.txt").exists()

    def test_no_op_when_disabled(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=False))
        logger.log_request(_context(), [], json_mode=False, options={})
        assert not (tmp_path / "debug").exists()

    def test_custom_log_dir(self, tmp_path):
        log_dir = str(tmp_path / "custom_logs")
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True, log_dir=log_dir))
        ctx = _context(commit="abc123def4567", stage="detect", seq=1)
        logger.log_request(ctx, [], json_mode=False, options={})
        assert (tmp_path / "custom_logs" / "abc123def4567" / "01-detect-prompt.txt").exists()


# ---------------------------------------------------------------------------
# log_response
# ---------------------------------------------------------------------------

class TestLogResponse:
    def test_creates_response_file(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        ctx = _context(commit="abc123def4567", stage="detect", seq=1)
        logger.log_response(ctx, raw_response="raw text here")

        response_file = tmp_path / "debug" / "abc123def4567" / "01-detect-response.txt"
        assert response_file.exists()
        assert response_file.read_text() == "raw text here"

    def test_no_result_json_without_parsed(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        ctx = _context(commit="abc123def4567", stage="detect", seq=1)
        logger.log_response(ctx, raw_response="raw")

        result_file = tmp_path / "debug" / "abc123def4567" / "01-detect-result.json"
        assert not result_file.exists()

    def test_creates_result_json_with_parsed(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        ctx = _context(commit="abc123def4567", stage="detect", seq=2)
        parsed = {"classification": "NEEDS_DOC", "confidence": 0.9}
        logger.log_response(ctx, raw_response="raw", parsed_result=parsed)

        result_file = tmp_path / "debug" / "abc123def4567" / "02-detect-result.json"
        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["classification"] == "NEEDS_DOC"
        assert data["confidence"] == 0.9

    def test_no_op_when_disabled(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=False))
        logger.log_response(_context(), raw_response="raw", parsed_result={"x": 1})
        assert not (tmp_path / "debug").exists()


# ---------------------------------------------------------------------------
# write_metadata
# ---------------------------------------------------------------------------

class TestWriteMetadata:
    def test_creates_metadata_json(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True)
        logger = LLMDebugLogger(config)
        logger.write_metadata(
            commit_hash="abc123def4567",
            model="test-model",
            config=config,
            started_at="2026-04-06T10:00:00Z",
            finished_at="2026-04-06T10:01:00Z",
        )

        meta_file = tmp_path / "debug" / "abc123def4567" / "metadata.json"
        assert meta_file.exists()

    def test_metadata_core_fields(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True)
        logger = LLMDebugLogger(config)
        logger.write_metadata(
            commit_hash="abc123def4567",
            model="mymodel",
            config=config,
            started_at="2026-04-06T10:00:00Z",
            finished_at="2026-04-06T10:01:00Z",
        )

        data = json.loads((tmp_path / "debug" / "abc123def4567" / "metadata.json").read_text())
        assert data["commit_hash"] == "abc123def4567"
        assert data["model"] == "mymodel"
        assert data["started_at"] == "2026-04-06T10:00:00Z"
        assert data["finished_at"] == "2026-04-06T10:01:00Z"
        assert "pipeline_version" in data

    def test_stage_durations_included_when_provided(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True)
        logger = LLMDebugLogger(config)
        durations = {"detect": 1.2, "generate": 3.4}
        logger.write_metadata(
            commit_hash="abc123def4567",
            model="m",
            config=config,
            started_at="s",
            finished_at="f",
            stage_durations=durations,
        )

        data = json.loads((tmp_path / "debug" / "abc123def4567" / "metadata.json").read_text())
        assert data["stage_durations"] == durations

    def test_config_snapshot_included_by_default(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True, include_config_snapshot=True)
        logger = LLMDebugLogger(config)
        logger.write_metadata("abc123def4567", "m", config, "s", "f")

        data = json.loads((tmp_path / "debug" / "abc123def4567" / "metadata.json").read_text())
        assert "config_snapshot" in data
        assert "detection" in data["config_snapshot"]
        assert "generation" in data["config_snapshot"]

    def test_config_snapshot_excluded_when_disabled(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True, include_config_snapshot=False)
        logger = LLMDebugLogger(config)
        logger.write_metadata("abc123def4567", "m", config, "s", "f")

        data = json.loads((tmp_path / "debug" / "abc123def4567" / "metadata.json").read_text())
        assert "config_snapshot" not in data

    def test_no_op_when_disabled(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=False)
        logger = LLMDebugLogger(config)
        logger.write_metadata("abc123def4567", "m", config, "s", "f")
        assert not (tmp_path / "debug").exists()


# ---------------------------------------------------------------------------
# rotate_if_needed
# ---------------------------------------------------------------------------

class TestRotateIfNeeded:
    def test_no_op_when_disabled(self, tmp_path):
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=False))
        result = logger.rotate_if_needed()
        assert result == 0

    def test_renames_existing_commit_dir(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True)
        logger = LLMDebugLogger(config)
        commit = "abc123def4567"
        # Pre-seed a counter so rotate_if_needed knows about this commit.
        logger._counters[commit] = 1
        # Create existing dir to simulate a previous run.
        existing = tmp_path / "debug" / commit
        existing.mkdir(parents=True)
        (existing / "metadata.json").write_text("{}")

        rotated = logger.rotate_if_needed()

        assert rotated >= 1
        assert not existing.exists()
        versioned = tmp_path / "debug" / f"{commit}.v1"
        assert versioned.exists()

    def test_increments_version_suffix(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True)
        logger = LLMDebugLogger(config)
        commit = "abc123def4567"
        logger._counters[commit] = 1
        base = tmp_path / "debug"
        # Simulate v1 already exists from a previous rotation.
        (base / commit).mkdir(parents=True)
        (base / f"{commit}.v1").mkdir(parents=True)

        logger.rotate_if_needed()

        assert (base / f"{commit}.v2").exists()

    def test_enforces_max_debug_entries(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True, max_debug_entries=2)
        logger = LLMDebugLogger(config)
        base = tmp_path / "debug"
        base.mkdir(parents=True)
        # Create 4 directories that should be trimmed to 2.
        for name in ["d1", "d2", "d3", "d4"]:
            d = base / name
            d.mkdir()
            (d / "f").write_text("x")

        rotated = logger.rotate_if_needed()

        remaining = [d for d in base.iterdir() if d.is_dir()]
        assert len(remaining) == 2
        assert rotated == 2

    def test_returns_zero_when_under_limit(self, tmp_path):
        config = _make_config(tmp_path, llm_logging=True, max_debug_entries=10)
        logger = LLMDebugLogger(config)
        base = tmp_path / "debug"
        base.mkdir(parents=True)
        for name in ["d1", "d2"]:
            (base / name).mkdir()

        rotated = logger.rotate_if_needed()

        assert rotated == 0

    def test_rmtree_failure_is_silently_ignored(self, tmp_path):
        """rotate_if_needed continues without crashing when shutil.rmtree raises OSError."""
        import shutil
        from unittest.mock import patch

        config = _make_config(tmp_path, llm_logging=True, max_debug_entries=1)
        logger = LLMDebugLogger(config)
        base = tmp_path / "debug"
        base.mkdir(parents=True)
        # Two dirs so the oldest one will be scheduled for removal.
        for name in ["d1", "d2"]:
            d = base / name
            d.mkdir()
            (d / "f").write_text("x")

        with patch("shutil.rmtree", side_effect=OSError("permission denied")):
            rotated = logger.rotate_if_needed()

        # rotated should be 0 because rmtree failed each time.
        assert rotated == 0
        # Both dirs still exist because deletion was skipped.
        remaining = [d for d in base.iterdir() if d.is_dir()]
        assert len(remaining) == 2


class TestAtomicWrite:
    """Test _atomic_write internals."""

    def test_chmod_called_on_parent_directory(self, tmp_path):
        """_atomic_write calls os.chmod(parent, 0o700) when it succeeds."""
        import os
        from unittest.mock import patch, call

        config = _make_config(tmp_path, llm_logging=True)
        logger = LLMDebugLogger(config)
        dest = tmp_path / "subdir" / "file.txt"

        chmod_calls = []
        original_chmod = os.chmod

        def recording_chmod(path, mode):
            chmod_calls.append((path, mode))
            # Allow real chmod to run so the path actually gets set.
            try:
                original_chmod(path, mode)
            except OSError:
                pass

        with patch("os.chmod", side_effect=recording_chmod):
            logger._atomic_write(dest, "content")

        parent_str = str(dest.parent)
        assert any(path == parent_str and mode == 0o700 for path, mode in chmod_calls)

    def test_fdopen_failure_cleans_up_temp_file_and_reraises(self, tmp_path):
        """_atomic_write removes the temp file and re-raises if os.fdopen raises."""
        import os
        import tempfile
        from unittest.mock import patch

        config = _make_config(tmp_path, llm_logging=True)
        logger = LLMDebugLogger(config)
        dest = tmp_path / "output.txt"

        created_tmp_files = []
        original_mkstemp = tempfile.mkstemp

        def recording_mkstemp(**kw):
            fd, tmp = original_mkstemp(**kw)
            created_tmp_files.append(tmp)
            return fd, tmp

        with patch("tempfile.mkstemp", side_effect=recording_mkstemp):
            with patch("os.fdopen", side_effect=IOError("disk full")):
                with pytest.raises(IOError, match="disk full"):
                    logger._atomic_write(dest, "hello")

        # The temp file must have been cleaned up.
        for tmp in created_tmp_files:
            assert not Path(tmp).exists(), f"Temp file {tmp} was not cleaned up"


# ---------------------------------------------------------------------------
# _commit_dir hash validation (security hardening)
# ---------------------------------------------------------------------------

class TestCommitDirHashValidation:
    """Test that _commit_dir raises ValueError for invalid or malicious hashes."""

    def test_path_traversal_raises_value_error(self, tmp_path):
        """_commit_dir raises ValueError for a hash containing path traversal."""
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        with pytest.raises(ValueError, match="Invalid commit hash"):
            logger._commit_dir("../../../etc")

    def test_absolute_path_hash_raises_value_error(self, tmp_path):
        """_commit_dir raises ValueError for a hash that is an absolute path."""
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        with pytest.raises(ValueError, match="Invalid commit hash"):
            logger._commit_dir("/etc/passwd")

    def test_non_hex_characters_raise_value_error(self, tmp_path):
        """_commit_dir raises ValueError for a hash containing non-hex characters."""
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        with pytest.raises(ValueError, match="Invalid commit hash"):
            logger._commit_dir("zzzzzzzzzzzzzz")

    def test_empty_string_raises_value_error(self, tmp_path):
        """_commit_dir raises ValueError for an empty string hash."""
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        with pytest.raises(ValueError, match="Invalid commit hash"):
            logger._commit_dir("")

    def test_valid_short_hex_hash_returns_path(self, tmp_path):
        """_commit_dir returns a Path under base_dir for a valid hex commit hash."""
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        path = logger._commit_dir("abc123def456")
        assert path.name == "abc123def456"

    def test_valid_full_sha256_hash_returns_path(self, tmp_path):
        """_commit_dir accepts a full 64-character hex hash."""
        logger = LLMDebugLogger(_make_config(tmp_path, llm_logging=True))
        full_hash = "a" * 64
        path = logger._commit_dir(full_hash)
        assert path.name == full_hash
