"""Tests for keyword search functionality."""
import pytest

from docgap.core.search import KeywordSearch


@pytest.fixture
def search():
    return KeywordSearch()


def test_index_and_search_finds_document(search):
    search.index_content("doc1", "Python is a great programming language")
    results = search.search("Python programming")
    ids = [r[0] for r in results]
    assert "doc1" in ids


def test_search_no_matches_returns_empty(search):
    search.index_content("doc1", "Python is a great programming language")
    results = search.search("javascript typescript")
    assert results == []


def test_search_results_sorted_by_score(search):
    search.index_content("doc_low", "Python language")
    search.index_content("doc_high", "Python is a great programming language for programming")
    results = search.search("Python programming language")
    assert len(results) >= 2
    # Scores should be in descending order
    scores = [r[1] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_title_boost_ranks_title_match_higher(search):
    # Title boost applies when title words also appear in content (early positions score higher).
    # "boosted" has "python" in both title and content (early), so it gets the title bonus.
    search.index_content("boosted", "python overview and details about the language", title="python guide")
    search.index_content("no_boost", "information about the python language without a title")
    results = search.search("python")
    ids = [r[0] for r in results]
    assert "boosted" in ids
    # boosted should rank first or at least appear due to title bonus
    assert ids[0] == "boosted"


def test_top_n_limits_results(search):
    for i in range(10):
        search.index_content(f"doc{i}", f"Python programming language document {i}")
    results = search.search("Python programming", top_n=3)
    assert len(results) <= 3


def test_clear_cache_empties_index(search):
    search.index_content("doc1", "Python programming")
    search.clear_cache()
    results = search.search("Python")
    assert results == []


def test_search_multiple_documents_finds_correct_one(search):
    search.index_content("python_doc", "Python is a high-level programming language")
    search.index_content("java_doc", "Java is an object-oriented language")
    search.index_content("rust_doc", "Rust is a systems programming language")

    results = search.search("Python high-level")
    ids = [r[0] for r in results]
    assert ids[0] == "python_doc"


def test_get_content_returns_indexed_content(search):
    content = "The quick brown fox"
    search.index_content("fox_doc", content)
    assert search.get_content("fox_doc") == content


def test_get_content_missing_id_returns_none(search):
    assert search.get_content("nonexistent") is None


def test_search_empty_query_returns_empty(search):
    search.index_content("doc1", "some content")
    results = search.search("")
    assert results == []


def test_tokenize_lowercases_and_strips_punctuation(search):
    tokens = search.tokenize("Hello, World! Python3.")
    assert "hello" in tokens
    assert "world" in tokens
    assert "python3" in tokens
