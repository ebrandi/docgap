"""Tests for output manager."""
import tempfile
from pathlib import Path

import pytest

from docgap.core.output import OutputManager
from docgap.core.output_metadata import OutputMetadata
from docgap.core.classification import Classification, ClassificationResult, Category


class TestOutputManager:
    """Test output management functionality."""

    @pytest.fixture
    def manager(self, temp_dir, test_config):
        """Create a test output manager."""
        return OutputManager(config=test_config)

    def test_manager_initialization(self, temp_dir, test_config):
        """Test output manager initialization."""
        manager = OutputManager(config=test_config)
        
        assert manager is not None

    def test_create_output_directory(self, temp_dir, test_config):
        """Test that output directory is created."""
        manager = OutputManager(config=test_config)

        # base_dir is created in __init__
        assert manager.base_dir.exists()

    @pytest.fixture
    def sample_generation_result(self, temp_dir, test_config):
        """Create a sample generation result."""
        class GenResult:
            def __init__(self):
                self.patch = """--- a/usr.bin/ls/ls.1
+++ b/usr.bin/ls/ls.1
@@ -1 +1 @@
-test
+test updated
"""
                self.report = "This is a test report."
                self.format = "mdoc"
                self.success = True
                self.validation_passed = True
                self.duration_ms = 1500
                self.error = None
        
        return GenResult()

    def test_save_output(self, temp_dir, test_config, sample_generation_result):
        """Test saving output files."""
        manager = OutputManager(config=test_config)

        commit_hash = "abc123def456"

        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Added new flag"
        )

        output_paths = manager.save_output(
            commit_hash,
            sample_generation_result,
            classification
        )

        # Verify files were created
        assert len(output_paths) > 0
        for path in output_paths.values():
            assert path.exists()

    def test_load_output(self, temp_dir, test_config, sample_generation_result):
        """Test loading saved output."""
        manager = OutputManager(config=test_config)

        commit_hash = "def456abc123"

        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Added new flag"
        )

        manager.save_output(
            commit_hash,
            sample_generation_result,
            classification
        )

        metadata = manager.load_output(commit_hash)

        assert metadata is not None
        assert metadata["commit_hash"] == commit_hash

    def test_list_outputs(self, temp_dir, test_config, sample_generation_result):
        """Test listing all outputs."""
        manager = OutputManager(config=test_config)
        
        classifications = [
            ClassificationResult(
                classification=Classification.NEEDS_DOC,
                confidence=0.85,
                category=Category.NEW_FLAG,
                doc_target="usr.bin/ls/ls.1",
                reasoning="Added new flag"
            ),
            ClassificationResult(
                classification=Classification.NEEDS_DOC,
                confidence=0.90,
                category=Category.CHANGED_DEFAULT,
                doc_target="usr.bin/cat/cat.1",
                reasoning="Changed default behavior"
            )
        ]
        
        hashes = ["abc123", "def456"]
        
        for hash_val, classif in zip(hashes, classifications):
            manager.save_output(hash_val, sample_generation_result, classif)
        
        outputs = manager.list_outputs()

        assert len(outputs) >= 2
        for output in outputs:
            assert "commit_hash" in output


class TestOutputManagerGetOutputDir:
    """Test _get_output_dir and _get_output_dir_flat."""

    def test_get_output_dir_nested(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        path = manager._get_output_dir("abc123def456")
        assert "ab" in str(path)
        assert "abc123def456" in str(path)

    def test_get_output_dir_flat(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        path = manager._get_output_dir_flat("abc123def456")
        assert str(path).endswith("abc123def456")


class TestOutputManagerLoadNotFound:
    """Test load_output when not found."""

    def test_load_output_not_found(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        result = manager.load_output("nonexistent_hash")
        assert result is None


class TestOutputManagerListEmpty:
    """Test list_outputs when empty or error."""

    def test_list_outputs_empty(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        outputs = manager.list_outputs()
        assert outputs == []

    def test_list_outputs_with_corrupted_metadata(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        # Create a dir with bad metadata
        bad_dir = manager.base_dir / "badcommit"
        bad_dir.mkdir(parents=True)
        (bad_dir / "metadata.json").write_text("{invalid json")
        outputs = manager.list_outputs()
        assert outputs == []


class TestOutputManagerWriteAtomic:
    """Test _write_atomic and error cleanup."""

    def test_write_atomic_success(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        target = manager.base_dir / "test_file.txt"
        manager._write_atomic(target, "hello world")
        assert target.read_text() == "hello world"

    def test_write_atomic_overwrites(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        target = manager.base_dir / "test_file2.txt"
        manager._write_atomic(target, "first")
        manager._write_atomic(target, "second")
        assert target.read_text() == "second"


class TestOutputManagerRotateOutputs:
    """Test rotate_outputs."""

    def test_rotate_no_outputs(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        rotated = manager.rotate_outputs()
        assert rotated == 0

    def test_rotate_excess_outputs(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Added new flag"
        )

        class _GenResult:
            patch = "--- a/f\n+++ b/f\n"
            report = "test report"

        gen = _GenResult()
        for i in range(5):
            manager.save_output(f"hash{i:04d}", gen, classification)
        rotated = manager.rotate_outputs(max_outputs=3)
        assert rotated >= 2


class TestOutputManagerGetTotalSize:
    """Test _get_total_size_mb."""

    def test_get_total_size_empty(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        size = manager._get_total_size_mb()
        assert size == 0.0

    def test_get_total_size_with_files(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Test"
        )

        class _GenResult:
            patch = "--- a/f\n+++ b/f\n"
            report = "test report"

        manager.save_output("sizehash", _GenResult(), classification)
        size = manager._get_total_size_mb()
        assert size > 0.0


class TestOutputManagerRotateBySize:
    """Test _rotate_by_size."""

    def test_rotate_by_size_under_limit(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        rotated = manager._rotate_by_size(100)
        assert rotated == 0


class TestOutputManagerStatistics:
    """Test get_statistics."""

    def test_get_statistics(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        stats = manager.get_statistics()
        assert stats["total_saved"] == 0
        assert stats["total_loaded"] == 0
        assert stats["total_rotated"] == 0


class TestOutputManagerWriteAtomicError:
    """Test _write_atomic error cleanup."""

    def test_write_atomic_error_cleanup(self, temp_dir, test_config):
        import os
        manager = OutputManager(config=test_config)
        target = manager.base_dir / "error_test.txt"
        # Make write fail by patching os.fdopen to raise
        from unittest.mock import patch
        with patch("os.fdopen", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                manager._write_atomic(target, "content")
        # Target should not exist
        assert not target.exists()


class TestOutputManagerRotateBySize:
    """Test _rotate_by_size with actual data."""

    def test_rotate_by_size_with_data(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="ls.1",
            reasoning="Test"
        )

        class _GenResult:
            patch = "x" * 10000
            report = "y" * 10000

        for i in range(5):
            manager.save_output(f"sizehash{i:04d}", _GenResult(), classification)

        # Rotate with very small limit to force rotation
        rotated = manager.rotate_outputs(max_outputs=1000, max_size_mb=0)
        assert rotated >= 1


class TestOutputManagerListOutputsError:
    """Test list_outputs with missing base_dir."""

    def test_list_outputs_no_base_dir(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        import shutil
        shutil.rmtree(manager.base_dir)
        outputs = manager.list_outputs()
        assert outputs == []


class TestOutputManagerSaveWithValidation:
    """Test save_output with validation result."""

    def test_save_with_validation_result(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="ls.1",
            reasoning="Test"
        )

        class _GenResult:
            patch = "--- a/f\n+++ b/f\n"
            report = "report"

        class _ValResult:
            def is_valid(self):
                return False
            errors = ["error1"]
            warnings = ["warn1"]

        saved = manager.save_output("valhash", _GenResult(), classification, _ValResult())
        assert "metadata.json" in saved
        # Load and check validation info
        loaded = manager.load_output("valhash")
        assert loaded is not None


class TestOutputManagerPatchNaming:
    """Test patch file naming based on format."""

    def test_mdoc_saves_as_manpage_patch(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Test"
        )

        class _GenResult:
            patch = "--- a/f\n+++ b/f\n"
            report = "test report"
            format = "mdoc"

        saved = manager.save_output("mdochash", _GenResult(), classification)
        assert "manpage.patch" in saved

    def test_asciidoc_saves_as_handbook_patch(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="books/handbook/chapter.adoc",
            reasoning="Test"
        )

        class _GenResult:
            patch = "--- a/f\n+++ b/f\n"
            report = "test report"
            format = "asciidoc"

        saved = manager.save_output("adochash", _GenResult(), classification)
        assert "handbook.patch" in saved

    def test_load_output_finds_handbook_patch(self, temp_dir, test_config):
        manager = OutputManager(config=test_config)
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="books/handbook/chapter.adoc",
            reasoning="Test"
        )

        class _GenResult:
            patch = "--- a/f\n+++ b/f\n"
            report = "test report"
            format = "asciidoc"

        manager.save_output("loadhbhash", _GenResult(), classification)
        loaded = manager.load_output("loadhbhash")
        assert loaded is not None
        assert loaded.get("patch_filename") == "handbook.patch"

    def test_no_format_attr_defaults_to_manpage(self, temp_dir, test_config):
        """When generation_result has no format attribute, defaults to manpage.patch."""
        manager = OutputManager(config=test_config)
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Test"
        )

        class _GenResult:
            patch = "--- a/f\n+++ b/f\n"
            report = "test report"

        saved = manager.save_output("nofmthash", _GenResult(), classification)
        assert "manpage.patch" in saved
