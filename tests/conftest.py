"""Pytest fixtures for docgap tests."""
import json
import tempfile
from pathlib import Path

import pytest

from docgap.config import Config, load_config
from docgap.db import Database, init_database
from docgap.git import GitFetcher, LogParser


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_config(temp_dir):
    """Create a test configuration."""
    config_content = f"""
general:
  data_dir: {temp_dir}
  log_level: debug

repositories:
  freebsd_src:
    path: {temp_dir}/repos/freebsd-src
    remote: https://github.com/freebsd/freebsd-src.git
    branches:
      - main
  freebsd_doc:
    path: {temp_dir}/repos/freebsd-doc
    remote: https://github.com/freebsd/freebsd-doc.git

llm:
  provider: ollama
  base_url: http://localhost:11434
  model: qwen3-coder-next-512k
  temperature: 0.1
  max_context: 524288
  timeout: 120

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
    config_path = temp_dir / "config.yaml"
    config_path.write_text(config_content)
    
    return load_config(str(config_path))


@pytest.fixture
def test_database(temp_dir):
    """Create a test database."""
    db_path = temp_dir / "test.db"
    init_database(str(db_path))
    return Database(str(db_path))


@pytest.fixture
def sample_commit():
    """Sample commit data for testing."""
    return {
        "hash": "abc123def456789",
        "author": "Test User",
        "email": "test@example.com",
        "date": "2026-04-03T10:00:00Z",
        "subject": "Add new feature to ls command",
        "files": ["usr.bin/ls/ls.c", "usr.bin/ls/ls.1"],
    }


@pytest.fixture
def sample_diff():
    """Sample git diff for testing."""
    return """diff --git a/usr.bin/ls/ls.c b/usr.bin/ls/ls.c
--- a/usr.bin/ls/ls.c
+++ b/usr.bin/ls/ls.c
@@ -100,6 +100,7 @@
 +\tcase 'Z':\n+\t\tshow_security_context = 1;\n+\t\tbreak;
"""


@pytest.fixture
def sample_mdoc():
    """Sample mdoc content for testing."""
    return """.Dd April 3, 2026
.Dt TEST 1
.Os
.Sh NAME
.Nm test
.Nd test command
.Sh DESCRIPTION
This is a test.
"""


@pytest.fixture
def sample_asciidoc():
    """Sample AsciiDoc content for testing."""
    return """= Test Document

This is a test document.

== Section 1

Some content here.
"""


@pytest.fixture
def sample_git_log():
    """Sample git log output for testing."""
    return """abc123def456789|Test User|test@example.com|2026-04-03T10:00:00Z|Add feature
def456789abc123|Another User|another@example.com|2026-04-03T11:00:00Z|Fix bug
ghi789abc123def|Yet Another|yetanother@example.com|2026-04-03T12:00:00Z|MFC to stable
"""


@pytest.fixture
def sample_llm_classification_response():
    """Sample LLM classification response."""
    return json.dumps({
        "classification": "NEEDS_DOC",
        "confidence": 0.85,
        "category": "new_flag",
        "doc_target": "usr.bin/ls/ls.1",
        "reasoning": "Added new -Z flag for display"
    })


@pytest.fixture
def sample_llm_generation_response():
    """Sample LLM generation response."""
    return """--- a/usr.bin/ls/ls.1
+++ b/usr.bin/ls/ls.1
@@ -100,6 +100,8 @@
 +.It Fl Z
 +Display security context.
 .El
"""
