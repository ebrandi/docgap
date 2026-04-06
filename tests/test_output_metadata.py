"""Tests for OutputMetadata dataclass."""
import pytest
from datetime import datetime

from docgap.core.output_metadata import OutputMetadata


class TestOutputMetadataPostInit:
    """Test __post_init__ default field population."""

    def test_generated_at_set_when_none(self):
        m = OutputMetadata(commit_hash="abc", classification="NEEDS_DOC", confidence=0.9)
        assert m.generated_at is not None
        # Should be a valid ISO datetime string
        datetime.fromisoformat(m.generated_at)

    def test_generated_at_preserved_when_set(self):
        ts = "2026-01-01T00:00:00"
        m = OutputMetadata(
            commit_hash="abc",
            classification="NEEDS_DOC",
            confidence=0.9,
            generated_at=ts,
        )
        assert m.generated_at == ts

    def test_validation_errors_defaults_to_empty_list(self):
        m = OutputMetadata(commit_hash="abc", classification="NEEDS_DOC", confidence=0.9)
        assert m.validation_errors == []

    def test_validation_warnings_defaults_to_empty_list(self):
        m = OutputMetadata(commit_hash="abc", classification="NEEDS_DOC", confidence=0.9)
        assert m.validation_warnings == []

    def test_files_defaults_to_empty_list(self):
        m = OutputMetadata(commit_hash="abc", classification="NEEDS_DOC", confidence=0.9)
        assert m.files == []

    def test_explicit_none_fields_become_empty_lists(self):
        m = OutputMetadata(
            commit_hash="abc",
            classification="NEEDS_DOC",
            confidence=0.9,
            validation_errors=None,
            validation_warnings=None,
            files=None,
        )
        assert m.validation_errors == []
        assert m.validation_warnings == []
        assert m.files == []

    def test_explicit_values_preserved(self):
        m = OutputMetadata(
            commit_hash="abc",
            classification="NEEDS_DOC",
            confidence=0.9,
            validation_errors=["err1"],
            validation_warnings=["warn1"],
            files=["report.txt"],
        )
        assert m.validation_errors == ["err1"]
        assert m.validation_warnings == ["warn1"]
        assert m.files == ["report.txt"]


class TestOutputMetadataToDict:
    """Test to_dict serialization."""

    def test_to_dict_contains_all_keys(self):
        m = OutputMetadata(
            commit_hash="abc123",
            classification="NEEDS_DOC",
            confidence=0.85,
            category="new_flag",
        )
        d = m.to_dict()
        assert "commit_hash" in d
        assert "classification" in d
        assert "confidence" in d
        assert "category" in d
        assert "generated_at" in d
        assert "validation_passed" in d
        assert "validation_errors" in d
        assert "validation_warnings" in d
        assert "files" in d

    def test_to_dict_values_correct(self):
        m = OutputMetadata(
            commit_hash="abc123",
            classification="NEEDS_DOC",
            confidence=0.85,
        )
        d = m.to_dict()
        assert d["commit_hash"] == "abc123"
        assert d["classification"] == "NEEDS_DOC"
        assert d["confidence"] == 0.85


class TestOutputMetadataFromDict:
    """Test from_dict deserialization."""

    def test_round_trip(self):
        original = OutputMetadata(
            commit_hash="def456",
            classification="IRRELEVANT",
            confidence=0.7,
            category="other",
            validation_errors=["e1"],
            validation_warnings=["w1"],
            files=["report.txt"],
        )
        d = original.to_dict()
        restored = OutputMetadata.from_dict(d)
        assert restored.commit_hash == original.commit_hash
        assert restored.classification == original.classification
        assert restored.confidence == original.confidence
        assert restored.validation_errors == original.validation_errors
        assert restored.validation_warnings == original.validation_warnings
        assert restored.files == original.files

    def test_from_dict_optional_fields_default(self):
        data = {
            "commit_hash": "abc",
            "classification": "NEEDS_DOC",
            "confidence": 0.9,
        }
        m = OutputMetadata.from_dict(data)
        assert m.category is None
        assert m.validation_passed is True
        assert m.validation_errors == []
