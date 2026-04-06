"""Tests for git commit filters."""
import pytest

from docgap.git.filters import CommitFilter, default_filter


class TestCommitFilterInit:
    def test_default_skip_paths_set(self):
        f = CommitFilter()
        assert "contrib/" in f.skip_paths
        assert "sys/contrib/" in f.skip_paths

    def test_default_skip_files_set(self):
        f = CommitFilter()
        assert "Makefile" in f.skip_files

    def test_custom_skip_patterns_compiled(self):
        f = CommitFilter(skip_patterns=["^Merge ", "^MFC "])
        assert len(f._pattern_regexes) == 2

    def test_invalid_regex_silently_ignored(self):
        f = CommitFilter(skip_patterns=["[invalid regex"])
        # Invalid pattern is skipped — no crash
        assert len(f._pattern_regexes) == 0

    def test_mixed_valid_invalid_patterns(self):
        f = CommitFilter(skip_patterns=["^Merge ", "[bad", "^MFC "])
        # Only valid patterns compiled
        assert len(f._pattern_regexes) == 2

    def test_bot_patterns_lowercased(self):
        f = CommitFilter(skip_bots=["Bot@Example.COM"])
        assert "bot@example.com" in f._bot_patterns


class TestCommitFilterShouldSkip:
    def test_subject_pattern_match(self):
        f = CommitFilter(skip_patterns=["^Merge "])
        should_skip, reason = f.should_skip(
            {"subject": "Merge branch feature", "files": ["f.c"], "author": "A", "email": ""}
        )
        assert should_skip
        assert reason == "subject_pattern"

    def test_subject_pattern_case_insensitive(self):
        f = CommitFilter(skip_patterns=["^merge "])
        should_skip, reason = f.should_skip(
            {"subject": "Merge branch feature", "files": ["f.c"], "author": "A", "email": ""}
        )
        assert should_skip

    def test_merge_commit_subject(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "Merge pull request #1", "files": ["f.c"], "author": "A", "email": ""}
        )
        assert should_skip
        assert reason == "merge_commit"

    def test_vendor_import_contrib(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "Update vendor", "files": ["contrib/libxyz/code.c"], "author": "A", "email": ""}
        )
        assert should_skip
        assert reason == "vendor_import"

    def test_vendor_import_sys_contrib(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "Update vendor", "files": ["sys/contrib/libxyz/code.c"], "author": "A", "email": ""}
        )
        assert should_skip
        assert reason == "vendor_import"

    def test_mfc_commit(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "MFC to stable/14", "files": ["f.c"], "author": "A", "email": ""}
        )
        assert should_skip
        assert reason == "mfc_commit"

    def test_mfs_commit(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "MFS r12345", "files": ["f.c"], "author": "A", "email": ""}
        )
        assert should_skip
        assert reason == "mfc_commit"

    def test_skip_files_only(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "Update Makefile", "files": ["Makefile", ".gitignore"], "author": "A", "email": ""}
        )
        assert should_skip
        assert reason == "skip_files_only"

    def test_skip_files_mixed_not_skipped(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "Add feature", "files": ["Makefile", "file.c"], "author": "A", "email": ""}
        )
        assert not should_skip

    def test_bot_detection_email_match(self):
        f = CommitFilter(skip_bots=["bot@example.com"])
        should_skip, reason = f.should_skip(
            {"subject": "Auto update", "files": ["f.c"], "author": "Bot", "email": "bot@example.com"}
        )
        assert should_skip
        assert reason == "bot_author"

    def test_bot_detection_partial_email_match(self):
        f = CommitFilter(skip_bots=["bot@"])
        should_skip, reason = f.should_skip(
            {"subject": "Auto update", "files": ["f.c"], "author": "Bot", "email": "mybot@example.com"}
        )
        assert should_skip
        assert reason == "bot_author"

    def test_bot_detection_case_insensitive(self):
        f = CommitFilter(skip_bots=["BOT@EXAMPLE.COM"])
        should_skip, reason = f.should_skip(
            {"subject": "Auto update", "files": ["f.c"], "author": "Bot", "email": "bot@example.com"}
        )
        assert should_skip

    def test_no_skip_normal_commit(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "Add new feature", "files": ["usr.bin/ls/ls.c"], "author": "Dev", "email": "dev@example.com"}
        )
        assert not should_skip
        assert reason == "none"

    def test_empty_files_list_not_skipped_on_skip_files(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "Add feature", "files": [], "author": "A", "email": ""}
        )
        assert not should_skip

    def test_none_files_not_skipped(self):
        f = CommitFilter()
        should_skip, reason = f.should_skip(
            {"subject": "Add feature", "files": None, "author": "A", "email": ""}
        )
        assert not should_skip

    def test_none_email_not_crashed(self):
        f = CommitFilter(skip_bots=["bot@example.com"])
        should_skip, reason = f.should_skip(
            {"subject": "Add feature", "files": ["f.c"], "author": "A", "email": None}
        )
        assert not should_skip


class TestCommitFilterFilterCommits:
    def test_filter_commits_statistics(self):
        f = CommitFilter(skip_patterns=["^Merge "])
        commits = [
            {"subject": "Merge branch", "files": ["f.c"], "author": "A", "email": ""},
            {"subject": "Add feat", "files": ["f.c"], "author": "B", "email": ""},
        ]
        filtered, stats = f.filter_commits(commits)
        assert stats["total"] == 2
        assert stats["skipped"] == 1
        assert stats["accepted"] == 1
        assert len(filtered) == 1

    def test_filter_commits_all_accepted(self):
        f = CommitFilter()
        commits = [
            {"subject": "Add feature", "files": ["usr.bin/ls/ls.c"], "author": "A", "email": ""},
            {"subject": "Fix bug", "files": ["usr.bin/cat/cat.c"], "author": "B", "email": ""},
        ]
        filtered, stats = f.filter_commits(commits)
        assert stats["accepted"] == 2
        assert stats["skipped"] == 0
        assert len(filtered) == 2

    def test_filter_commits_all_skipped(self):
        f = CommitFilter()
        commits = [
            {"subject": "Merge branch", "files": ["f.c"], "author": "A", "email": ""},
            {"subject": "MFC to stable", "files": ["f.c"], "author": "B", "email": ""},
        ]
        filtered, stats = f.filter_commits(commits)
        assert len(filtered) == 0
        assert stats["skipped"] == 2
        assert stats["accepted"] == 0

    def test_filter_commits_marks_skip_reason(self):
        f = CommitFilter()
        commits = [
            {"subject": "Merge branch", "files": ["f.c"], "author": "A", "email": ""},
        ]
        _, _ = f.filter_commits(commits)
        assert commits[0]["skip_reason"] == "merge_commit"
        assert commits[0]["filtered"] is True

    def test_filter_commits_marks_accepted_false_filtered(self):
        f = CommitFilter()
        commits = [
            {"subject": "Add feature", "files": ["usr.bin/ls/ls.c"], "author": "A", "email": ""},
        ]
        filtered, _ = f.filter_commits(commits)
        assert filtered[0]["filtered"] is False

    def test_filter_commits_empty_list(self):
        f = CommitFilter()
        filtered, stats = f.filter_commits([])
        assert filtered == []
        assert stats["total"] == 0
        assert stats["skipped"] == 0
        assert stats["accepted"] == 0

    def test_skip_files_only_commit_filtered(self):
        f = CommitFilter()
        commits = [
            {"subject": "chore", "files": ["Makefile"], "author": "A", "email": ""},
        ]
        filtered, stats = f.filter_commits(commits)
        assert len(filtered) == 0
        assert stats["skipped"] == 1


class TestDefaultFilter:
    def test_default_filter_returns_commit_filter(self):
        f = default_filter()
        assert isinstance(f, CommitFilter)

    def test_default_filter_has_patterns(self):
        f = default_filter()
        assert len(f.skip_patterns) > 0

    def test_default_filter_skips_merge(self):
        f = default_filter()
        should_skip, reason = f.should_skip(
            {"subject": "Merge branch main", "files": ["f.c"], "author": "A", "email": ""}
        )
        assert should_skip

    def test_default_filter_skips_mfc(self):
        f = default_filter()
        should_skip, reason = f.should_skip(
            {"subject": "MFC r12345", "files": ["f.c"], "author": "A", "email": ""}
        )
        assert should_skip

    def test_default_filter_skips_revert(self):
        f = default_filter()
        should_skip, reason = f.should_skip(
            {"subject": "Revert some commit", "files": ["f.c"], "author": "A", "email": ""}
        )
        assert should_skip
