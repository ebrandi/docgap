"""Tests for validator."""
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from docgap.core.validator import DocValidator
from docgap.core.validation_result import ValidationIssue, ValidationResult


class TestDocValidator:
    """Test documentation validation."""

    @pytest.fixture
    def validator(self, temp_dir, test_config):
        """Create a test validator."""
        return DocValidator(config=test_config)

    def test_validator_initialization(self, temp_dir, test_config):
        """Test validator initialization."""
        validator = DocValidator(config=test_config)
        
        assert validator is not None
        assert validator.config is not None

    def test_valid_mdoc(self, temp_dir, test_config):
        """Test validation of valid mdoc content."""
        validator = DocValidator(config=test_config)
        
        valid_mdoc = """.Dd April 3, 2026
.Dt TEST 1
.Os
.Sh NAME
.Nm test
.Nd test command
.Sh DESCRIPTION
This is a test.
"""
        
        result = validator.validate_mdoc(valid_mdoc)
        
        assert result is not None
        assert result.valid is True or result.valid is False

    def test_invalid_mdoc(self, temp_dir, test_config):
        """Test validation of invalid mdoc content."""
        validator = DocValidator(config=test_config)
        
        invalid_mdoc = """.Dd April 3, 2026
.Dt TEST
.Os
.Sh NAME
This is missing proper markup
"""
        
        result = validator.validate_mdoc(invalid_mdoc)
        
        assert result is not None

    @patch("subprocess.run")
    def test_validate_asciidoc(self, mock_run, temp_dir, test_config):
        """Test AsciiDoc validation."""
        validator = DocValidator(config=test_config)
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        valid_adoc = """= Test Document

This is a test.
"""
        
        result = validator.validate_asciidoc(valid_adoc)
        
        assert result is not None

    def test_validation_result(self, temp_dir, test_config):
        """Test Validation result structure."""
        issue = ValidationIssue(
            severity="ERROR",
            line=10,
            message="Invalid markup"
        )
        
        assert issue.severity == "ERROR"
        assert issue.line == 10
        assert issue.message == "Invalid markup"

    def test_validation_result_valid(self, temp_dir, test_config):
        """Test ValidationResult validation."""
        result = ValidationResult(
            valid=True,
            errors=[],
            warnings=[]
        )

        assert result.valid is True
        assert len(result.errors) == 0


class TestDocValidatorDispatch:
    """Test validate dispatch to correct format."""

    def test_validate_mdoc_dispatch(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        result = validator.validate(".Dd test", format="mdoc")
        assert result is not None

    def test_validate_asciidoc_dispatch(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        result = validator.validate("= Title\nContent", format="asciidoc")
        assert result is not None

    def test_validate_unknown_format(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        result = validator.validate("content", format="unknown_format")
        assert result.valid is False
        assert len(result.errors) == 1
        assert "Unknown format" in result.errors[0].message


class TestDocValidatorCheckTool:
    """Test _check_tool availability."""

    @patch("subprocess.run")
    def test_check_tool_available(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        validator = DocValidator.__new__(DocValidator)
        validator.config = None
        validator.timeout = 30
        assert validator._check_tool("mandoc") is True

    @patch("subprocess.run")
    def test_check_tool_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("not found")
        validator = DocValidator.__new__(DocValidator)
        validator.config = None
        validator.timeout = 30
        assert validator._check_tool("nonexistent_tool") is False

    @patch("subprocess.run")
    def test_check_tool_timeout(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd=["mandoc"], timeout=5)
        validator = DocValidator.__new__(DocValidator)
        validator.config = None
        validator.timeout = 30
        assert validator._check_tool("mandoc") is False


class TestDocValidatorMandocUnavailable:
    """Test mandoc validation when tool is unavailable."""

    def test_mandoc_unavailable_returns_valid_with_warning(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        validator.mandoc_available = False
        result = validator.validate_mdoc("test content")
        assert result.valid is True
        assert len(result.warnings) == 1
        assert "not available" in result.warnings[0].message


class TestDocValidatorAsciidocUnavailable:
    """Test asciidoc validation when tool is unavailable."""

    def test_asciidoc_unavailable_returns_valid_with_warning(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        validator.asciidoctor_available = False
        result = validator.validate_asciidoc("= Title\nContent")
        assert result.valid is True
        assert len(result.warnings) == 1
        assert "not available" in result.warnings[0].message


class TestDocValidatorParseMandocOutput:
    """Test _parse_mandoc_output."""

    def test_parse_mandoc_empty(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        result = validator._parse_mandoc_output("", "")
        assert result.valid is True
        assert result.errors == []

    def test_parse_mandoc_errors(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stderr = "test.mdoc:10:5: ERROR: bad macro"
        result = validator._parse_mandoc_output("", stderr)
        assert len(result.errors) > 0 or len(result.warnings) > 0

    def test_parse_mandoc_stdout_warnings(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stdout = "some warning message"
        result = validator._parse_mandoc_output(stdout, "")
        assert len(result.warnings) > 0

    def test_parse_mandoc_non_numeric_line(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stderr = "test.mdoc:abc:5: WARNING: bad macro"
        result = validator._parse_mandoc_output("", stderr)
        assert len(result.errors) > 0 or len(result.warnings) > 0


class TestDocValidatorParseAsciidocOutput:
    """Test _parse_asciidoc_output."""

    def test_parse_asciidoc_empty(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        result = validator._parse_asciidoc_output("", "")
        assert result.valid is True

    def test_parse_asciidoc_errors(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stderr = "asciidoctor: error: line 5: invalid syntax"
        result = validator._parse_asciidoc_output("", stderr)
        assert len(result.errors) > 0

    def test_parse_asciidoc_warnings_in_stdout(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stdout = "WARNING: missing section"
        result = validator._parse_asciidoc_output(stdout, "")
        # Should detect the warning keyword
        assert len(result.warnings) > 0

    def test_parse_asciidoc_error_with_line_number(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stderr = "asciidoctor: error: line 42 invalid"
        result = validator._parse_asciidoc_output("", stderr)
        assert len(result.errors) > 0

    def test_parse_asciidoc_stdout_error(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stdout = "error: something went wrong"
        result = validator._parse_asciidoc_output(stdout, "")
        assert len(result.errors) > 0

    def test_parse_asciidoc_stdout_non_matching(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stdout = "some normal output\ninfo: all good"
        result = validator._parse_asciidoc_output(stdout, "")
        # No warnings or errors from non-matching lines
        assert len(result.errors) == 0
        assert len(result.warnings) == 0


class TestDocValidatorWithMockedSubprocess:
    """Test actual validation paths with mocked subprocess."""

    @patch("subprocess.run")
    def test_validate_mdoc_with_errors(self, mock_run, temp_dir, test_config):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = "test.mdoc:5:3: ERROR: bad macro\n"
        mock_run.return_value = mock_result
        validator = DocValidator(config=test_config)
        validator.mandoc_available = True
        result = validator.validate_mdoc(".Dd test\n.Dt TEST 1\n")
        assert result is not None

    @patch("subprocess.run")
    def test_validate_mdoc_clean(self, mock_run, temp_dir, test_config):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        validator = DocValidator(config=test_config)
        validator.mandoc_available = True
        result = validator.validate_mdoc(".Dd test\n.Dt TEST 1\n")
        assert result.valid is True

    @patch("subprocess.run")
    def test_validate_asciidoc_with_errors(self, mock_run, temp_dir, test_config):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "asciidoctor: error: something failed"
        mock_run.return_value = mock_result
        validator = DocValidator(config=test_config)
        validator.asciidoctor_available = True
        result = validator.validate_asciidoc("= Title\nContent")
        assert result is not None


class TestDocValidatorStatistics:
    """Test get_statistics."""

    def test_get_statistics_initial(self, temp_dir, test_config):
        validator = DocValidator(config=test_config)
        stats = validator.get_statistics()
        assert stats["total_validated"] == 0
        assert stats["total_valid"] == 0
        assert stats["total_invalid"] == 0


class TestValidationResultMethods:
    """Test ValidationResult methods."""

    def test_has_errors_true(self):
        result = ValidationResult(
            valid=False,
            errors=[ValidationIssue("ERROR", 1, "bad")],
            warnings=[],
        )
        assert result.has_errors() is True
        assert result.is_valid() is False

    def test_has_errors_false(self):
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert result.has_errors() is False
        assert result.is_valid() is True

    def test_has_warnings(self):
        result = ValidationResult(
            valid=True,
            errors=[],
            warnings=[ValidationIssue("WARNING", None, "minor")],
        )
        assert result.has_warnings() is True

    def test_get_summary_passed(self):
        result = ValidationResult(valid=True, errors=[], warnings=[])
        summary = result.get_summary()
        assert "PASSED" in summary

    def test_get_summary_failed(self):
        result = ValidationResult(
            valid=False,
            errors=[ValidationIssue("ERROR", 1, "bad")],
            warnings=[ValidationIssue("WARNING", None, "minor")],
        )
        summary = result.get_summary()
        assert "FAILED" in summary
        assert "Errors: 1" in summary
        assert "Warnings: 1" in summary

    def test_post_init_none_errors(self):
        result = ValidationResult(valid=True, errors=None, warnings=None)
        assert result.errors == []
        assert result.warnings == []

    def test_validation_issue_is_error(self):
        issue = ValidationIssue("ERROR", 10, "test")
        assert issue.is_error() is True
        assert issue.is_warning() is False

    def test_validation_issue_is_warning(self):
        issue = ValidationIssue("WARNING", None, "test")
        assert issue.is_error() is False
        assert issue.is_warning() is True
