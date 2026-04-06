"""Tests for patch parsing and formatting."""
import pytest

from docgap.core.patch import PatchParser, Patch, Hunk


@pytest.fixture
def parser():
    return PatchParser()


SIMPLE_DIFF = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 line1
-line2
+line2_modified
+line3_new
 line4"""


def test_parse_simple_diff_file_paths(parser):
    patch = parser.parse(SIMPLE_DIFF)
    assert patch.old_file == "foo.py"
    assert patch.new_file == "foo.py"


def test_parse_simple_diff_hunk_count(parser):
    patch = parser.parse(SIMPLE_DIFF)
    assert len(patch.hunks) == 1


def test_parse_simple_diff_hunk_metadata(parser):
    patch = parser.parse(SIMPLE_DIFF)
    hunk = patch.hunks[0]
    assert hunk.old_start == 1
    assert hunk.old_lines == 3
    assert hunk.new_start == 1
    assert hunk.new_lines == 4


def test_parse_simple_diff_hunk_lines(parser):
    patch = parser.parse(SIMPLE_DIFF)
    hunk = patch.hunks[0]
    assert " line1" in hunk.lines
    assert "-line2" in hunk.lines
    assert "+line2_modified" in hunk.lines
    assert "+line3_new" in hunk.lines


MULTI_HUNK_DIFF = """\
--- a/bar.py
+++ b/bar.py
@@ -1,2 +1,2 @@
-old_line1
+new_line1
 context1
@@ -10,2 +10,2 @@
 context2
-old_line10
+new_line10"""


def test_parse_multiple_hunks_count(parser):
    patch = parser.parse(MULTI_HUNK_DIFF)
    assert len(patch.hunks) == 2


def test_parse_multiple_hunks_metadata(parser):
    patch = parser.parse(MULTI_HUNK_DIFF)
    assert patch.hunks[0].old_start == 1
    assert patch.hunks[1].old_start == 10


def test_parse_empty_diff_returns_no_hunks(parser):
    patch = parser.parse("")
    assert patch.hunks == []
    assert patch.old_file is None
    assert patch.new_file is None


def test_parse_diff_without_ab_prefix(parser):
    diff = "--- foo.py\n+++ foo.py\n@@ -1,1 +1,1 @@\n-old\n+new"
    patch = parser.parse(diff)
    assert patch.old_file == "foo.py"
    assert patch.new_file == "foo.py"
    assert len(patch.hunks) == 1


def test_format_patch_produces_file_headers(parser):
    patch = Patch(
        old_file="example.py",
        new_file="example.py",
        hunks=[]
    )
    output = parser.format_patch(patch)
    assert "--- a/example.py" in output
    assert "+++ b/example.py" in output


def test_format_patch_produces_hunk_header(parser):
    hunk = Hunk(old_start=5, old_lines=3, new_start=5, new_lines=4, lines=[" ctx", "-old", "+new"])
    patch = Patch(old_file="f.py", new_file="f.py", hunks=[hunk])
    output = parser.format_patch(patch)
    assert "@@ -5,3 +5,4 @@" in output


def test_format_patch_includes_hunk_lines(parser):
    hunk = Hunk(old_start=1, old_lines=2, new_start=1, new_lines=2, lines=["-removed", "+added", " context"])
    patch = Patch(old_file="g.py", new_file="g.py", hunks=[hunk])
    output = parser.format_patch(patch)
    assert "-removed" in output
    assert "+added" in output
    assert " context" in output


def test_round_trip_parse_format(parser):
    patch = parser.parse(SIMPLE_DIFF)
    formatted = parser.format_patch(patch)
    # Re-parse the formatted output and verify structure is preserved
    reparsed = parser.parse(formatted)
    assert reparsed.old_file == patch.old_file
    assert reparsed.new_file == patch.new_file
    assert len(reparsed.hunks) == len(patch.hunks)
    assert reparsed.hunks[0].old_start == patch.hunks[0].old_start
    assert reparsed.hunks[0].new_start == patch.hunks[0].new_start


def test_parse_hunk_with_no_comma_in_range(parser):
    # @@ -1 +1 @@ (single-line form, no comma)
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new"
    patch = parser.parse(diff)
    assert len(patch.hunks) == 1
    assert patch.hunks[0].old_lines == 1
    assert patch.hunks[0].new_lines == 1
