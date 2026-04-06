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
