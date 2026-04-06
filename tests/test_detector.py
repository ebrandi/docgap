"""Tests for Stage 1 detection (mocked LLM)."""
from unittest.mock import MagicMock

import pytest

from docgap.core.classification import Classification, ClassificationResult, Category
from docgap.core.detector import Stage1Detector


class TestStage1Detector:
    """Test Stage 1 detection functionality."""

    @pytest.fixture
    def detector(self, temp_dir, test_config):
        """Create a test detector."""
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        
        return Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )

    def test_detector_initialization(self, temp_dir, test_config):
        """Test detector initialization."""
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        
        assert detector is not None

    def test_classify_needs_doc(self, temp_dir, test_config):
        """Test classification as NEEDS_DOC."""
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        mock_client.chat.return_value = '{"classification": "NEEDS_DOC", "confidence": 0.85, "category": "new_flag", "doc_target": "usr.bin/ls/ls.1", "reasoning": "Added new flag"}'
        mock_fetcher.get_diff.return_value = "+int flag_z;"

        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )

        commit_data = {
            "hash": "abc123",
            "subject": "Add -Z flag",
            "files": ["usr.bin/ls/ls.c"]
        }

        result = detector.classify(commit_data)

        assert result.classification == Classification.NEEDS_DOC
        assert result.confidence == 0.85

    def test_classify_irrelevant(self, temp_dir, test_config):
        """Test classification as IRRELEVANT."""
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        mock_client.chat.return_value = '{"classification": "IRRELEVANT", "confidence": 0.90, "category": null, "doc_target": null, "reasoning": "Internal refactoring only"}'
        mock_fetcher.get_diff.return_value = ""

        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )

        commit_data = {
            "hash": "abc123",
            "subject": "Refactor code",
            "files": ["usr.bin/ls/ls.c"]
        }

        result = detector.classify(commit_data)

        assert result.classification == Classification.IRRELEVANT
        assert result.is_accepted(0.95) is False

    def test_apply_confidence_thresholds(self, temp_dir, test_config):
        """Test that confidence thresholds are applied correctly."""
        # Low confidence should be overridden to IRRELEVANT
        low_conf = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.40,
            category=None,
            doc_target=None,
            reasoning="Uncertain"
        )

        result = low_conf.apply_thresholds(
            test_config.detection.confidence_threshold_accept,
            test_config.detection.confidence_threshold_reject
        )

        assert result.classification == Classification.IRRELEVANT

    def test_classification_result_is_valid(self, temp_dir, test_config):
        """Test classification result validation."""
        result = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Added new flag"
        )
        
        assert result.is_valid() is True
        assert result.is_accepted(0.80) is True

    def test_classification_result_is_accepted(self, temp_dir, test_config):
        """Test the is_accepted method."""
        high_conf = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.85,
            category=Category.NEW_FLAG,
            doc_target="usr.bin/ls/ls.1",
            reasoning="Added new flag"
        )
        
        assert high_conf.is_accepted(0.80) is True
        assert high_conf.is_accepted(0.90) is False


class TestDetectorClassifyError:
    """Test error handling in classify."""

    def test_classify_returns_uncertain_on_error(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        mock_client.chat.side_effect = Exception("LLM down")
        mock_fetcher.get_diff.return_value = "diff"
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        commit_data = {"hash": "abc123", "subject": "Test", "files": ["f.c"]}
        result = detector.classify(commit_data)
        assert result.classification == Classification.UNCERTAIN
        assert result.confidence == 0.0
        assert "Error" in result.reasoning

    def test_classify_malformed_json(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        mock_client.chat.return_value = "not valid json"
        mock_fetcher.get_diff.return_value = "diff"
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        commit_data = {"hash": "abc123", "subject": "Test", "files": ["f.c"]}
        result = detector.classify(commit_data)
        # Should return UNCERTAIN on JSON parse error
        assert result.classification == Classification.UNCERTAIN


class TestDetectorClassifyBatch:
    """Test classify_batch."""

    def test_classify_batch(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        mock_client.chat.return_value = '{"classification": "IRRELEVANT", "confidence": 0.9}'
        mock_fetcher.get_diff.return_value = "diff"
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        commits = [
            {"hash": "a1", "subject": "Test1", "files": ["f.c"]},
            {"hash": "a2", "subject": "Test2", "files": ["g.c"]},
        ]
        results = detector.classify_batch(commits)
        assert len(results) == 2


class TestDetectorInputSizeLimits:
    """Test input size truncation."""

    def test_large_diff_truncated(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        mock_client.chat.return_value = '{"classification": "NEEDS_DOC", "confidence": 0.85, "category": "new_flag"}'
        mock_fetcher.get_diff.return_value = "x" * 200_000  # Over MAX_DIFF_LENGTH
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        commit_data = {"hash": "abc123", "subject": "Test", "files": ["f.c"]}
        result = detector.classify(commit_data)
        assert result is not None

    def test_large_files_list_truncated(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        mock_client.chat.return_value = '{"classification": "NEEDS_DOC", "confidence": 0.85}'
        mock_fetcher.get_diff.return_value = "diff"
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        commit_data = {
            "hash": "abc123",
            "subject": "Test",
            "files": [f"file{i}.c" for i in range(600)],  # Over MAX_FILES_PER_COMMIT
        }
        result = detector.classify(commit_data)
        assert result is not None


class TestDetectorGetStatistics:
    """Test get_statistics."""

    def test_get_statistics_initial(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        stats = detector.get_statistics()
        assert stats["total_classified"] == 0
        assert stats["avg_time_ms"] == 0.0

    def test_get_statistics_after_classify(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        mock_client.chat.return_value = '{"classification": "NEEDS_DOC", "confidence": 0.85}'
        mock_fetcher.get_diff.return_value = "diff"
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        detector.classify({"hash": "a1", "subject": "Test", "files": ["f.c"]})
        stats = detector.get_statistics()
        assert stats["total_classified"] == 1
        assert stats["avg_time_ms"] > 0


class TestDetectorParseLLMResponse:
    """Test _parse_llm_response edge cases."""

    def test_parse_unknown_classification(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        result = detector._parse_llm_response('{"classification": "UNKNOWN", "confidence": 0.5}')
        assert result.classification == Classification.UNCERTAIN

    def test_parse_invalid_confidence(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        result = detector._parse_llm_response('{"classification": "NEEDS_DOC", "confidence": "high"}')
        assert result.confidence == 0.0

    def test_parse_confidence_clamped(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        result = detector._parse_llm_response('{"classification": "NEEDS_DOC", "confidence": 1.5}')
        assert result.confidence == 1.0
        result2 = detector._parse_llm_response('{"classification": "NEEDS_DOC", "confidence": -0.5}')
        assert result2.confidence == 0.0

    def test_parse_unknown_category_defaults_to_other(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        result = detector._parse_llm_response('{"classification": "NEEDS_DOC", "confidence": 0.85, "category": "totally_new_thing"}')
        assert result.category == Category.OTHER

    def test_parse_category_with_hyphens(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        result = detector._parse_llm_response('{"classification": "NEEDS_DOC", "confidence": 0.85, "category": "new-flag"}')
        assert result.category == Category.NEW_FLAG

    def test_parse_uncertain_classification(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        result = detector._parse_llm_response('{"classification": "UNCERTAIN", "confidence": 0.6}')
        assert result.classification == Classification.UNCERTAIN

    def test_parse_with_doc_target_and_reasoning(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        detector = Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config
        )
        result = detector._parse_llm_response(
            '{"classification": "NEEDS_DOC", "confidence": 0.85, "doc_target": "ls.1", "reasoning": "New flag"}'
        )
        assert result.doc_target == "ls.1"
        assert result.reasoning == "New flag"

    def _make_detector(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        return Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config,
        )

    def test_nan_confidence_clamped_to_zero(self, temp_dir, test_config):
        """NaN confidence from LLM should be clamped to 0.0."""
        detector = self._make_detector(temp_dir, test_config)
        result = detector._parse_llm_response('{"classification": "NEEDS_DOC", "confidence": "not_a_number"}')
        assert result.confidence == 0.0


class TestClassificationResultIsValid:
    """Test is_valid edge cases."""

    def test_is_valid_negative_confidence(self):
        result = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=-0.1,
            category=None,
            doc_target=None,
            reasoning=None,
        )
        assert result.is_valid() is False

    def test_is_valid_confidence_over_one(self):
        result = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=1.1,
            category=None,
            doc_target=None,
            reasoning=None,
        )
        assert result.is_valid() is False

    def test_is_valid_not_classification_enum(self):
        result = ClassificationResult(
            classification="NOT_AN_ENUM",
            confidence=0.5,
            category=None,
            doc_target=None,
            reasoning=None,
        )
        assert result.is_valid() is False

    def test_nan_confidence_is_invalid(self):
        result = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=float('nan'),
        )
        assert result.is_valid() is False

    def test_inf_confidence_is_invalid(self):
        result = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=float('inf'),
        )
        assert result.is_valid() is False


class TestClassificationApplyThresholds:
    """Test apply_thresholds between reject and accept."""

    def test_between_thresholds_becomes_uncertain(self):
        result = ClassificationResult(
            classification=Classification.NEEDS_DOC,
            confidence=0.65,
            category=Category.NEW_FLAG,
            doc_target="ls.1",
            reasoning="Test",
        )
        applied = result.apply_thresholds(0.80, 0.50)
        assert applied.classification == Classification.UNCERTAIN
        assert "below accept threshold" in applied.reasoning


class TestDetectorDocTargetSanitization:
    """Test that _parse_llm_response sanitizes doc_target to prevent path traversal."""

    def _make_detector(self, temp_dir, test_config):
        mock_client = MagicMock()
        mock_fetcher = MagicMock()
        return Stage1Detector(
            llm_client=mock_client,
            git_fetcher=mock_fetcher,
            config=test_config,
        )

    def test_path_traversal_doc_target_returns_none(self, temp_dir, test_config):
        """_parse_llm_response sets doc_target to None when it contains '..'."""
        detector = self._make_detector(temp_dir, test_config)
        result = detector._parse_llm_response(
            '{"classification": "NEEDS_DOC", "confidence": 0.85, "doc_target": "../../etc/passwd"}'
        )
        assert result.doc_target is None

    def test_absolute_path_doc_target_returns_none(self, temp_dir, test_config):
        """_parse_llm_response sets doc_target to None when it is an absolute path."""
        detector = self._make_detector(temp_dir, test_config)
        result = detector._parse_llm_response(
            '{"classification": "NEEDS_DOC", "confidence": 0.85, "doc_target": "/etc/passwd"}'
        )
        assert result.doc_target is None

    def test_valid_relative_doc_target_preserved(self, temp_dir, test_config):
        """_parse_llm_response preserves a safe relative doc_target."""
        detector = self._make_detector(temp_dir, test_config)
        result = detector._parse_llm_response(
            '{"classification": "NEEDS_DOC", "confidence": 0.85, "doc_target": "usr.bin/ls/ls.1"}'
        )
        assert result.doc_target == "usr.bin/ls/ls.1"

    def test_overlong_doc_target_truncated(self, temp_dir, test_config):
        """_parse_llm_response truncates doc_target longer than 500 characters."""
        detector = self._make_detector(temp_dir, test_config)
        long_target = "a" * 600
        result = detector._parse_llm_response(
            f'{{"classification": "NEEDS_DOC", "confidence": 0.85, "doc_target": "{long_target}"}}'
        )
        assert result.doc_target is not None
        assert len(result.doc_target) <= 500
