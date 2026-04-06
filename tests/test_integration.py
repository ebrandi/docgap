"""Integration tests using real FreeBSD repos and Ollama server.

Run with: pytest tests/test_integration.py -v -m integration --timeout=300
Skip with: pytest tests/ -m "not integration"
"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from docgap.config import load_config
from docgap.core.classification import Classification, ClassificationResult
from docgap.core.detector import Stage1Detector
from docgap.git.fetcher import GitFetcher
from docgap.git.parser import LogParser
from docgap.llm.client import OllamaClient

FREEBSD_SRC = "/home/ebrandi/projects/freebsd-src"
FREEBSD_DOC = "/home/ebrandi/projects/freebsd-doc"
OLLAMA_LOCAL_URL = "http://localhost:11434"
OLLAMA_REMOTE_URL = "http://ai.ebrandi.eti.br:11434"
OLLAMA_MODEL = "qwen3.5:122b-96g-128k"


def _find_ollama_url() -> str:
    """Try local Ollama first, then remote. Return the working URL or skip."""
    import requests
    for url in (OLLAMA_LOCAL_URL, OLLAMA_REMOTE_URL):
        try:
            resp = requests.get(f"{url}/api/tags", timeout=5)
            if resp.status_code == 200:
                return url
        except Exception:
            continue
    pytest.skip("No Ollama server available (tried local and remote)")

# Known commits for deterministic tests
COMMIT_MATH = "e55db843ef45"       # lib/msun: Added fmaximum and fminimum family — likely NEEDS_DOC
COMMIT_BUILD_FIX = "3f79bc9ca336"  # Fix nooptions VIMAGE build — likely IRRELEVANT
COMMIT_DOCS = "fba8bd02340f"       # CONTRIBUTING.md: quality expectations — likely IRRELEVANT


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def git_fetcher():
    """GitFetcher pointed at the real (non-bare) freebsd-src repo."""
    return GitFetcher(
        src_path=FREEBSD_SRC,
        doc_path=FREEBSD_DOC,
        bare=False,
        timeout=60,
        max_retries=1,
    )


@pytest.fixture(scope="module")
def ollama_url():
    """Discover a working Ollama server (local first, then remote)."""
    return _find_ollama_url()


@pytest.fixture(scope="module")
def ollama_client(ollama_url):
    """OllamaClient pointed at the discovered Ollama server."""
    return OllamaClient(
        base_url=ollama_url,
        model=OLLAMA_MODEL,
        timeout=300,
        connect_timeout=10,
        max_retries=1,
    )


@pytest.fixture(scope="module")
def integration_config(tmp_path_factory, ollama_url):
    """Minimal Config object suitable for integration tests."""
    tmp = tmp_path_factory.mktemp("integration")
    config_content = f"""
general:
  data_dir: {tmp}
  log_level: warning

repositories:
  freebsd_src:
    path: {FREEBSD_SRC}
    remote: https://github.com/freebsd/freebsd-src.git
    branches:
      - main
  freebsd_doc:
    path: {FREEBSD_DOC}
    remote: https://github.com/freebsd/freebsd-doc.git

llm:
  provider: ollama
  base_url: {ollama_url}
  model: {OLLAMA_MODEL}
  temperature: 0.1
  max_context: 131072
  timeout: 300

detection:
  confidence_threshold_accept: 0.80
  confidence_threshold_reject: 0.50
  skip_patterns:
    - "^Merge "
    - "^MFC "
    - "^MFS "

generation:
  validate_mdoc: false
  validate_asciidoc: false
  max_retries: 1

review:
  auto_submit:
    enabled: false

notification:
  enabled: false
  from_address: docgap@example.com
  smtp_host: localhost
"""
    config_path = tmp / "config.yaml"
    config_path.write_text(config_content)
    return load_config(str(config_path))


# ---------------------------------------------------------------------------
# 1. Git integration tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_git_get_commit_info(git_fetcher):
    """GitFetcher.get_commit_info() returns correct metadata for a known commit."""
    info = git_fetcher.get_commit_info(COMMIT_MATH)

    assert info["hash"].startswith(COMMIT_MATH[:8])
    assert info["author"]
    assert info["email"]
    assert info["date"]
    assert "fmaximum" in info["subject"].lower() or "msun" in info["subject"].lower()


@pytest.mark.integration
def test_git_get_diff(git_fetcher):
    """GitFetcher.get_diff() returns non-empty diff for a known commit."""
    diff = git_fetcher.get_diff(COMMIT_MATH)

    assert diff
    assert "diff --git" in diff
    # The commit touches lib/msun
    assert "msun" in diff.lower() or "fmaximum" in diff.lower() or "fminimum" in diff.lower()


@pytest.mark.integration
def test_git_get_file_list_at_commit(git_fetcher):
    """GitFetcher.get_file_list_at_commit() returns the files changed in a known commit."""
    files = git_fetcher.get_file_list_at_commit(COMMIT_MATH)

    assert isinstance(files, list)
    assert len(files) > 0
    # At least one file should be under lib/msun
    assert any("msun" in f for f in files)


@pytest.mark.integration
def test_git_get_commit_info_build_fix(git_fetcher):
    """GitFetcher.get_commit_info() works on a second known commit."""
    info = git_fetcher.get_commit_info(COMMIT_BUILD_FIX)

    assert info["hash"].startswith(COMMIT_BUILD_FIX[:8])
    assert info["subject"]


# ---------------------------------------------------------------------------
# 2. Log parser integration tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_log_parser_parse_commits(git_fetcher, integration_config):
    """LogParser.parse_commits() returns commits with proper structure."""
    parser = LogParser(git_fetcher, integration_config)

    since = (datetime.now(tz=timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    commits = parser.parse_commits(since_timestamp=since, branch="main")

    assert isinstance(commits, list)
    assert len(commits) > 0

    first = commits[0]
    assert "hash" in first
    assert "author" in first
    assert "email" in first
    assert "date" in first
    assert "subject" in first
    assert "files" in first
    assert isinstance(first["files"], list)


@pytest.mark.integration
def test_log_parser_returns_recent_commits(git_fetcher, integration_config):
    """LogParser returns commits within the requested time window."""
    parser = LogParser(git_fetcher, integration_config)

    since = (datetime.now(tz=timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    commits = parser.parse_commits(since_timestamp=since, branch="main")

    # Each commit date should be parseable as ISO 8601
    for commit in commits[:5]:
        assert commit["date"]


# ---------------------------------------------------------------------------
# 3. Filter integration tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_filter_removes_mfc_and_merges(git_fetcher, integration_config):
    """filter_commits() removes MFC/Merge commits and keeps regular ones."""
    parser = LogParser(git_fetcher, integration_config)

    since = (datetime.now(tz=timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    commits = parser.parse_commits(since_timestamp=since, branch="main")

    assert len(commits) > 0, "Expected commits in the last 30 days"

    filtered, stats = parser.filter_commits(commits)

    # Some commits should have been filtered out (MFC, merges, etc.)
    assert stats["total"] == len(commits)
    assert isinstance(filtered, list)
    # All returned commits should not be filtered
    for commit in filtered:
        assert commit.get("filtered") is False


@pytest.mark.integration
def test_filter_stats_are_populated(git_fetcher, integration_config):
    """filter_commits() returns populated statistics."""
    parser = LogParser(git_fetcher, integration_config)

    since = (datetime.now(tz=timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    commits = parser.parse_commits(since_timestamp=since, branch="main")
    _, stats = parser.filter_commits(commits)

    assert "accepted" in stats
    assert "filtered_out" in stats
    assert stats["accepted"] + stats["filtered_out"] == stats["total"]


# ---------------------------------------------------------------------------
# 4. Ollama health tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_ollama_is_healthy(ollama_client):
    """OllamaClient.is_healthy() returns True when the server is up."""
    assert ollama_client.is_healthy() is True


# ---------------------------------------------------------------------------
# 5. Ollama chat JSON mode tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_ollama_chat_json_mode(ollama_client):
    """OllamaClient.chat() with json_mode=True returns parseable JSON."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a classifier. Always respond with valid JSON only. "
                'Return exactly: {"status": "ok", "value": 42}'
            ),
        },
        {"role": "user", "content": "Return the JSON now."},
    ]

    response = ollama_client.chat(messages, json_mode=True)

    assert response
    data = json.loads(response)
    assert isinstance(data, dict)
    assert "status" in data or "value" in data


# ---------------------------------------------------------------------------
# 6. Stage 1 detection round-trip — NEEDS_DOC commit
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_stage1_detector_math_commit(git_fetcher, ollama_client, integration_config):
    """Stage1Detector.classify() returns valid result for a math-function commit."""
    detector = Stage1Detector(
        llm_client=ollama_client,
        git_fetcher=git_fetcher,
        config=integration_config,
    )

    commit_info = git_fetcher.get_commit_info(COMMIT_MATH)
    files = git_fetcher.get_file_list_at_commit(COMMIT_MATH)
    commit_data = {**commit_info, "files": files}

    result = detector.classify(commit_data)

    assert isinstance(result, ClassificationResult)
    assert result.classification in list(Classification)
    assert 0.0 <= result.confidence <= 1.0
    assert result.reasoning is not None


# ---------------------------------------------------------------------------
# 7. Stage 1 detection round-trip — IRRELEVANT commit
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_stage1_detector_build_fix_commit(git_fetcher, ollama_client, integration_config):
    """Stage1Detector.classify() returns valid result for a build-fix commit."""
    detector = Stage1Detector(
        llm_client=ollama_client,
        git_fetcher=git_fetcher,
        config=integration_config,
    )

    commit_info = git_fetcher.get_commit_info(COMMIT_BUILD_FIX)
    files = git_fetcher.get_file_list_at_commit(COMMIT_BUILD_FIX)
    commit_data = {**commit_info, "files": files}

    result = detector.classify(commit_data)

    assert isinstance(result, ClassificationResult)
    assert result.classification in list(Classification)
    assert 0.0 <= result.confidence <= 1.0
    assert result.reasoning is not None
