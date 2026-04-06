"""Tests for Stage 2 generation (mocked LLM)."""
from unittest.mock import MagicMock

import pytest

from docgap.core.classification import Classification, ClassificationResult, Category
from docgap.core.generator import Stage2Generator
from docgap.core.retriever import DocReference


class TestStage2Generator:
    """Test Stage 2 generation functionality."""

    @pytest.fixture
    def generator(self, temp_dir, test_config):
        """Create a test generator."""
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        
        return Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )

    def test_generator_initialization(self, temp_dir, test_config):
        """Test generator initialization."""
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        
        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )
        
        assert generator is not None

    def test_generate_mdoc(self, temp_dir, test_config):
        """Test mdoc generation."""
        mock_client = MagicMock()
        mock_retriever = MagicMock()

        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )

        # Mock the LLM response
        mock_client.chat.return_value = """--- a/usr.bin/ls/ls.1
+++ b/usr.bin/ls/ls.1
@@ -1,5 +1,6 @@
 .Dd April 3, 2026
 .Dt LS 1
+.It Fl Z
 .Sh DESCRIPTION
"""

        # Mock the retriever
        doc_ref = DocReference(
            path="usr.bin/ls/ls.1",
            content=".Dd April 3, 2026\n.Dt LS 1\n.Sh DESCRIPTION",
            format="mdoc",
            relevance_score=0.9
        )
        mock_retriever.retrieve_docs.return_value = [doc_ref]

        commit_data = {
            "hash": "abc123",
            "subject": "Add -Z flag",
            "files": ["usr.bin/ls/ls.c"]
        }

        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Added new flag"
        )

        result = generator.generate(commit_data, classification)

        assert result.success is True
        assert result.patch
        assert result.report

    def test_generate_asciidoc(self, temp_dir, test_config):
        """Test AsciiDoc generation."""
        mock_client = MagicMock()
        mock_retriever = MagicMock()

        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )

        # Mock the LLM response
        mock_client.chat.return_value = """--- a/handbook.adoc
+++ b/handbook.adoc
@@ -1,5 +1,6 @@
 = Handbook
 +New section
 == Section 1
"""

        # Mock the retriever
        doc_ref = DocReference(
            path="documentation/content/en/books/handbook/",
            content="= Handbook\n== Section 1",
            format="asciidoc",
            relevance_score=0.9
        )
        mock_retriever.retrieve_docs.return_value = [doc_ref]

        commit_data = {
            "hash": "abc123",
            "subject": "Update handbook",
            "files": ["documentation/..."]
        }

        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.API_CHANGE,
            doc_target="documentation/content/en/books/handbook/",
            reasoning="Updated API"
        )

        result = generator.generate(commit_data, classification)

        assert result.success is True
        assert result.patch

    def test_generate_failure(self, temp_dir, test_config):
        """Test generation failure handling."""
        mock_client = MagicMock()
        mock_retriever = MagicMock()

        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )

        mock_client.chat.side_effect = Exception("LLM error")

        commit_data = {
            "hash": "abc123",
            "subject": "Test",
            "files": []
        }

        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=None,
            doc_target=None,
            reasoning="Test"
        )

        result = generator.generate(commit_data, classification)

        assert result.success is False
        assert "failed" in result.report.lower()


class TestGenerationResult:
    """Test GenerationResult dataclass."""

    def test_default_validation_errors(self):
        from docgap.core.generator import GenerationResult
        result = GenerationResult(
            success=True, patch="patch", report="report",
            format="mdoc", duration_ms=100.0
        )
        assert result.validation_errors == []

    def test_invalid_format_normalized(self):
        from docgap.core.generator import GenerationResult
        result = GenerationResult(
            success=True, patch="patch", report="report",
            format="invalid", duration_ms=100.0
        )
        assert result.format == "mdoc"


class TestGeneratorGetStatistics:
    """Test get_statistics."""

    def test_get_statistics_initial(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )
        stats = generator.get_statistics()
        assert stats["total_generated"] == 0
        assert stats["avg_time_ms"] == 0.0

    def test_get_statistics_after_generate(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        mock_client.chat.return_value = "Report only, no diff"
        mock_retriever.retrieve_docs.return_value = []
        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )
        commit_data = {"hash": "abc123", "subject": "Test", "files": []}
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=None,
            doc_target=None,
            reasoning="Test"
        )
        generator.generate(commit_data, classification)
        stats = generator.get_statistics()
        assert stats["total_generated"] == 1
        assert stats["success"] == 1
        assert stats["avg_time_ms"] > 0


class TestGeneratorPatchExtraction:
    """Test patch extraction from LLM response."""

    def test_extract_patch_with_plus_in_diff_header(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        # Response where --- line contains + (diff format: --- a/path +++ b/path on same line)
        mock_client.chat.return_value = (
            "Report text here\n"
            "--- a/usr.bin/ls/ls.1 +++ b/usr.bin/ls/ls.1\n"
            "@@ -1,5 +1,6 @@\n"
            " .Dd April 3, 2026\n"
            "+.It Fl Z\n"
        )
        mock_retriever.retrieve_docs.return_value = []
        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )
        commit_data = {"hash": "abc123", "subject": "Test", "files": []}
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="ls.1",
            reasoning="Test"
        )
        result = generator.generate(commit_data, classification)
        assert result.success is True
        assert "---" in result.patch


class TestGeneratorNoPatchInResponse:
    """Test generate when LLM returns no diff format."""

    def test_no_patch_generates_placeholder(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        mock_client.chat.return_value = "This is just a text report without any diff format."
        mock_retriever.retrieve_docs.return_value = []
        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config
        )
        commit_data = {"hash": "abc123", "subject": "Test", "files": []}
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="ls.1",
            reasoning="Test"
        )
        result = generator.generate(commit_data, classification)
        assert result.success is True
        assert result.report != ""


class TestDetectFormat:
    """Test _detect_format static method."""

    def test_none_returns_mdoc(self):
        assert Stage2Generator._detect_format(None) == "mdoc"

    def test_empty_returns_mdoc(self):
        assert Stage2Generator._detect_format("") == "mdoc"

    def test_manpage_returns_mdoc(self):
        assert Stage2Generator._detect_format("usr.bin/ls/ls.1") == "mdoc"

    def test_adoc_extension_returns_asciidoc(self):
        assert Stage2Generator._detect_format("chapter.adoc") == "asciidoc"

    def test_asciidoc_extension_returns_asciidoc(self):
        assert Stage2Generator._detect_format("guide.asciidoc") == "asciidoc"

    def test_asc_extension_returns_asciidoc(self):
        assert Stage2Generator._detect_format("notes.asc") == "asciidoc"

    def test_handbook_path_returns_asciidoc(self):
        assert Stage2Generator._detect_format("books/handbook/network/chapter.adoc") == "asciidoc"

    def test_handbook_keyword_returns_asciidoc(self):
        assert Stage2Generator._detect_format("handbook/config") == "asciidoc"

    def test_books_path_returns_asciidoc(self):
        assert Stage2Generator._detect_format("books/fdp-primer/overview") == "asciidoc"

    def test_articles_path_returns_asciidoc(self):
        assert Stage2Generator._detect_format("articles/committers-guide/article") == "asciidoc"

    def test_regular_manpage_section_8(self):
        assert Stage2Generator._detect_format("sbin/mount/mount.8") == "mdoc"


class TestGeneratorFormatDetection:
    """Test that generate() returns correct format based on doc_target."""

    def test_asciidoc_target_sets_format(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        mock_client.chat.return_value = "Report about handbook update."
        mock_retriever.retrieve_docs.return_value = []
        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config,
        )
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.90,
            category=Category.NEW_FLAG,
            doc_target="books/handbook/network/chapter.adoc",
            reasoning="New network feature",
        )
        result = generator.generate({"hash": "abc", "subject": "Test", "files": []}, classification)
        assert result.format == "asciidoc"

    def test_mdoc_target_sets_format(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        mock_client.chat.return_value = "Report about manpage update."
        mock_retriever.retrieve_docs.return_value = []
        generator = Stage2Generator(
            llm_client=mock_client,
            doc_retriever=mock_retriever,
            config=test_config,
        )
        classification = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.90,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="New flag",
        )
        result = generator.generate({"hash": "abc", "subject": "Test", "files": []}, classification)
        assert result.format == "mdoc"
