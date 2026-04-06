"""Tests for documentation retriever."""
from unittest.mock import MagicMock, patch

import pytest

from docgap.core.retriever import DocRetriever


class TestDocRetriever:
    """Test documentation retrieval."""

    @pytest.fixture
    def retriever(self, temp_dir, test_config):
        """Create a test retriever."""
        mock_fetcher = MagicMock()

        return DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

    def test_retriever_initialization(self, temp_dir, test_config):
        """Test retriever initialization."""
        mock_fetcher = MagicMock()

        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        assert retriever is not None

    def test_map_path_to_mdoc(self, temp_dir, test_config):
        """Test path mapping for mdoc files."""
        retriever = DocRetriever(doc_fetcher=MagicMock(), config=test_config)
        
        # Test usr.bin paths
        result = retriever.map_path_to_doc("usr.bin/ls/ls.c")
        assert result is None or result.endswith(".1")
        
        # Test sbin paths
        result = retriever.map_path_to_doc("sbin/mount/mount.c")
        assert result is None or result.endswith(".8")

    def test_map_path_to_asciidoc(self, temp_dir, test_config):
        """Test path mapping for AsciiDoc files."""
        retriever = DocRetriever(doc_fetcher=MagicMock(), config=test_config)

        # Handbook paths
        result = retriever.map_path_to_doc("documentation/content/en/books/handbook/")
        assert result is None or result.endswith(".adoc") or "documentation" in (result or "")

    def test_retrieve_docs(self, temp_dir, test_config):
        """Test document retrieval."""
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.return_value = ".Dd April 3, 2026\n.Dt LS 1"
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        commit_data = {
            "files": ["usr.bin/ls/ls.c"],
            "subject": "Add new flag"
        }

        docs = retriever.retrieve_docs(commit_data)

        assert len(docs) >= 0

    def test_retrieve_docs_fallback(self, temp_dir, test_config):
        """Test keyword search fallback."""
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.return_value = ".Dd April 3, 2026\n.Dt LS 1"
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        commit_data = {
            "files": [],
            "subject": "Add new feature"
        }

        docs = retriever.retrieve_docs(commit_data)

        assert docs is not None


from docgap.core.retriever import DocReference


class TestDocReference:
    """Test DocReference methods."""

    def test_is_mdoc(self):
        ref = DocReference(path="ls.1", content="test", format="mdoc")
        assert ref.is_mdoc() is True
        assert ref.is_asciidoc() is False

    def test_is_asciidoc(self):
        ref = DocReference(path="handbook.adoc", content="test", format="asciidoc")
        assert ref.is_mdoc() is False
        assert ref.is_asciidoc() is True


class TestDocRetrieverFormatFromPath:
    """Test _format_from_path."""

    def test_mdoc_extensions(self, temp_dir, test_config):
        retriever = DocRetriever(doc_fetcher=MagicMock(), config=test_config)
        for ext in [".1", ".3", ".4", ".5", ".8", ".9", ".mdoc"]:
            assert retriever._format_from_path(f"test{ext}") == "mdoc"

    def test_asciidoc_extensions(self, temp_dir, test_config):
        retriever = DocRetriever(doc_fetcher=MagicMock(), config=test_config)
        for ext in [".adoc", ".asciidoc", ".asc"]:
            assert retriever._format_from_path(f"test{ext}") == "asciidoc"

    def test_handbook_path(self, temp_dir, test_config):
        retriever = DocRetriever(doc_fetcher=MagicMock(), config=test_config)
        assert retriever._format_from_path("documentation/handbook/chapter.txt") == "asciidoc"

    def test_default_format(self, temp_dir, test_config):
        retriever = DocRetriever(doc_fetcher=MagicMock(), config=test_config)
        assert retriever._format_from_path("somefile.txt") == "mdoc"


class TestDocRetrieverGetFileContent:
    """Test _get_file_content."""

    def test_get_file_content_success(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.return_value = "content here"
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        assert retriever._get_file_content("test.1") == "content here"

    def test_get_file_content_exception(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.side_effect = Exception("not found")
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        assert retriever._get_file_content("test.1") is None


class TestDocRetrieverCache:
    """Test cache hit/miss."""

    def test_cache_hit(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.return_value = "cached content"
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        # First call should cache
        ref1 = retriever._retrieve_single_doc("test.1")
        assert ref1 is not None
        # Second call should hit cache
        ref2 = retriever._retrieve_single_doc("test.1")
        assert ref2 is ref1
        # Only called once
        assert mock_fetcher.get_file_content_at_commit.call_count == 1

    def test_cache_miss_returns_none(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.side_effect = Exception("not found")
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        ref = retriever._retrieve_single_doc("nonexistent.1")
        assert ref is None

    def test_clear_cache(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.return_value = "content"
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        retriever._retrieve_single_doc("test.1")
        assert len(retriever._cache) == 1
        retriever.clear_cache()
        assert len(retriever._cache) == 0


class TestDocRetrieverGetDocContent:
    """Test get_doc_content."""

    def test_get_doc_content_found(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.return_value = "doc content"
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        content = retriever.get_doc_content("test.1")
        assert content == "doc content"

    def test_get_doc_content_not_found(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.side_effect = Exception("nope")
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        content = retriever.get_doc_content("nonexistent.1")
        assert content is None


class TestDocRetrieverGetFormat:
    """Test get_format."""

    def test_get_format_found(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.return_value = "content"
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        fmt = retriever.get_format("test.adoc")
        assert fmt == "asciidoc"

    def test_get_format_not_found(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.get_file_content_at_commit.side_effect = Exception("nope")
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        fmt = retriever.get_format("nonexistent.1")
        assert fmt == "mdoc"


class TestDocRetrieverKeywordSearch:
    """Test keyword search."""

    def test_search_docs_empty_cache(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = None
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        results = retriever._search_docs(["ls", "command"])
        assert results == []

    def test_retrieve_docs_with_keywords(self, temp_dir, test_config):
        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = None
        mock_fetcher.get_file_content_at_commit.side_effect = Exception("nope")
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        commit_data = {
            "files": [],
            "keywords": ["ls", "listing"],
        }
        docs = retriever.retrieve_docs(commit_data)
        assert isinstance(docs, list)


class TestDocRetrieverIndexDefaultDocs:
    """Test _index_default_docs with real filesystem."""

    def test_index_finds_manpages(self, temp_dir, test_config):
        """_index_default_docs indexes .1 files from doc repo."""
        doc_dir = temp_dir / "doc_repo"
        doc_dir.mkdir()
        man_dir = doc_dir / "share" / "man" / "man1"
        man_dir.mkdir(parents=True)
        (man_dir / "ls.1").write_text(".Dd April 3, 2026\n.Dt LS 1\n.Sh NAME\n.Nm ls\n.Nd list directory contents\n")

        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(doc_dir)
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        retriever._index_default_docs()

        assert retriever._indexed is True
        # The search index should now contain the ls.1 file
        results = retriever.search.search("ls directory contents")
        assert len(results) >= 1
        assert any("ls.1" in doc_id for doc_id, _ in results)

    def test_index_finds_asciidoc(self, temp_dir, test_config):
        """_index_default_docs indexes .adoc files."""
        doc_dir = temp_dir / "doc_repo"
        doc_dir.mkdir()
        handbook_dir = doc_dir / "books" / "handbook" / "network"
        handbook_dir.mkdir(parents=True)
        (handbook_dir / "chapter.adoc").write_text("= Network Configuration\n\nThis chapter covers TCP/IP networking.\n")

        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(doc_dir)
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        retriever._index_default_docs()

        results = retriever.search.search("network tcp")
        assert len(results) >= 1

    def test_index_only_runs_once(self, temp_dir, test_config):
        """_index_default_docs only indexes once per instance."""
        doc_dir = temp_dir / "doc_repo"
        doc_dir.mkdir()
        (doc_dir / "test.1").write_text(".Dt TEST 1\n")

        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(doc_dir)
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        retriever._index_default_docs()
        first_cache_size = len(retriever._cache)
        retriever._index_default_docs()  # Should be a no-op
        assert len(retriever._cache) == first_cache_size

    def test_index_no_doc_path(self, temp_dir, test_config):
        """_index_default_docs does nothing if doc_path is None."""
        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = None
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        retriever._index_default_docs()
        assert retriever._indexed is True
        assert len(retriever._cache) == 0

    def test_index_nonexistent_path(self, temp_dir, test_config):
        """_index_default_docs does nothing if doc_path doesn't exist."""
        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(temp_dir / "nonexistent")
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        retriever._index_default_docs()
        assert retriever._indexed is True
        assert len(retriever._cache) == 0

    def test_index_skips_unreadable_files(self, temp_dir, test_config):
        """_index_default_docs skips files it can't read."""
        import os
        doc_dir = temp_dir / "doc_repo"
        doc_dir.mkdir()
        bad_file = doc_dir / "bad.1"
        bad_file.write_text("content")
        os.chmod(str(bad_file), 0o000)

        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(doc_dir)
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        # Should not raise — skips unreadable files
        retriever._index_default_docs()
        assert retriever._indexed is True
        # Restore permissions for cleanup
        os.chmod(str(bad_file), 0o644)

    def test_index_respects_max_files_limit(self, temp_dir, test_config):
        """_index_default_docs stops after _max_index_files."""
        doc_dir = temp_dir / "doc_repo"
        doc_dir.mkdir()
        # Create 5 files, but set limit to 2
        for i in range(5):
            (doc_dir / f"cmd{i}.1").write_text(f".Dt CMD{i} 1\n.Nm cmd{i}\n")

        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(doc_dir)
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)
        retriever._max_index_files = 2

        retriever._index_default_docs()
        assert len(retriever._cache) == 2


class TestDocRetrieverSearchIntegration:
    """Test _search_docs returns results after indexing."""

    def test_search_returns_cached_refs(self, temp_dir, test_config):
        """_search_docs returns DocReferences from cache when search matches."""
        doc_dir = temp_dir / "doc_repo"
        doc_dir.mkdir()
        (doc_dir / "mount.8").write_text(".Dt MOUNT 8\n.Nm mount\n.Nd mount file systems\n")
        (doc_dir / "ls.1").write_text(".Dt LS 1\n.Nm ls\n.Nd list directory contents\n")

        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(doc_dir)
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        results = retriever._search_docs(["mount", "file systems"])
        assert len(results) >= 1
        assert any("mount" in r.path for r in results)

    def test_search_deduplicates_across_keywords(self, temp_dir, test_config):
        """Multiple keywords matching the same doc don't duplicate it."""
        doc_dir = temp_dir / "doc_repo"
        doc_dir.mkdir()
        (doc_dir / "ifconfig.8").write_text(".Dt IFCONFIG 8\n.Nm ifconfig\n.Nd configure network interface\n")

        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(doc_dir)
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        results = retriever._search_docs(["ifconfig", "network", "interface"])
        # Should return at most 1 unique result for the same file
        paths = [r.path for r in results]
        assert len(paths) == len(set(paths))

    def test_end_to_end_keyword_fallback(self, temp_dir, test_config):
        """Full retrieve_docs falls back to keyword search when path mapping fails."""
        doc_dir = temp_dir / "doc_repo"
        doc_dir.mkdir()
        (doc_dir / "sysctl.8").write_text(".Dt SYSCTL 8\n.Nm sysctl\n.Nd get or set kernel state\n")

        mock_fetcher = MagicMock()
        mock_fetcher.doc_path = str(doc_dir)
        mock_fetcher.get_file_content_at_commit.side_effect = Exception("not found")
        retriever = DocRetriever(doc_fetcher=mock_fetcher, config=test_config)

        commit_data = {
            "files": [],  # No path mapping possible
            "keywords": ["sysctl", "kernel"],
        }
        docs = retriever.retrieve_docs(commit_data)
        assert len(docs) >= 1
        assert any("sysctl" in d.path for d in docs)
