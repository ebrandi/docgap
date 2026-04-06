"""Security-focused tests for documentation validator."""
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docgap.core.validator import DocValidator, ValidationIssue, ValidationResult
from docgap.config.schema import Config


class TestValidatorSecurity:
    """Test validator security aspects."""

    def test_temp_file_handling(self):
        """Test that temporary files are properly cleaned up."""
        # Create validator with mocked tool availability
        with patch.object(DocValidator, '_check_tool', return_value=True):
            validator = DocValidator()
         
        # Mock the subprocess call to avoid needing mandoc/asciidoctor
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            # Test multiple validations to ensure temp files are cleaned up
            for i in range(10):
                validator.validate_mdoc(f".Dd 2026-04-03\n.Dt TEST {i}\n.Os\n.Sh NAME\n.Nm test\n.Nd Test\n")

            # Verify that subprocess was called for each validation (10 times total)
            assert mock_run.call_count == 10

    def test_command_injection_in_validation(self):
        """Test that validation is safe from command injection."""
        validator = DocValidator()
        
        # Test with potentially malicious content that might try to break out of validation
        malicious_contents = [
            # Attempt to inject commands via filename (though we control the extension)
            ".Dd 2026-04-03\n.Dt TEST\n.Os\n.Sh NAME\n.Nm test\n.Nd Test; rm -rf /;\n",
            
            # Attempt to break out of quotes or commands
            ".Dd 2026-04-03\n.Dt TEST\n.Os\n.Sh NAME\n.Nm test\n.Nd Test`id`\n",
            
            # Very long content that might cause buffer issues
            ".Dd 2026-04-03\n.Dt TEST\n.Os\n.Sh NAME\n.Nm test\n.Nd " + "A" * 100000 + "\n",
            
            # Content with null bytes
            ".Dd 2026-04-03\n.Dt TEST\n.Os\n.Sh NAME\n.Nm test\n.Nd Test\x00\x01\x02\n",
            
            # Content with newlines and special chars
            ".Dd 2026-04-03\n.Dt TEST\n.Os\n.Sh NAME\n.Nm test\n.Nd Test\n.\" rm -rf / #\n",
        ]
        
        for content in malicious_contents:
            # Should not raise exceptions related to command injection
            try:
                result = validator.validate_mdoc(content)
                # Should return a ValidationResult
                assert isinstance(result, ValidationResult)
                assert hasattr(result, 'valid')
                assert hasattr(result, 'errors')
                assert hasattr(result, 'warnings')
            except Exception as e:
                # Should not be command injection or path traversal
                assert "command not found" not in str(e).lower()
                assert "permission denied" not in str(e).lower()
                assert "no such file or directory" not in str(e).lower()
                # Should be validation-related errors at worst
                assert "validation" in str(e).lower() or "mandoc" in str(e).lower()

    def test_path_traversal_in_temp_files(self):
        """Test that temp file handling is safe from path traversal."""
        validator = DocValidator()
        # Ensure tools are marked as available so validation runs
        validator.mandoc_available = True
         
        # Mock tempfile.NamedTemporaryFile to capture the filename
        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_file = Mock()
            mock_file.name = "/tmp/safe_temp_file.mdoc"
            mock_file.__enter__ = Mock(return_value=mock_file)
            mock_file.__exit__ = Mock(return_value=None)
            mock_temp.return_value = mock_file
         
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
                 
                # Test validation
                validator.validate_mdoc(".Dd 2026-04-03\n.Dt TEST\n.Os\n.Sh NAME\n.Nm test\n.Nd Test\n")
                 
                # Verify temp file was created with safe parameters
                mock_temp.assert_called_once()
                args, kwargs = mock_temp.call_args
                # Should not allow arbitrary path specification
                assert 'suffix' in kwargs
                assert kwargs['suffix'] == '.mdoc'
                # Should not allow dir to be set to arbitrary paths
                if 'dir' in kwargs:
                    # Should be a safe temporary directory
                    assert kwargs['dir'] is None or '/tmp' in kwargs['dir']

    def test_validation_tool_output_parsing_safety(self):
        """Test that parsing of validation tool output is safe."""
        validator = DocValidator()
        
        # Mock mandoc/asciidoctor availability
        validator.mandoc_available = True
        validator.asciidoctor_available = True
        
        # Test malicious output that might try to confuse the parser
        malicious_outputs = [
            # Attempt to inject new lines or fields
            "test.mdoc:1:1: error: test\n../../etc/passwd:2:2: warning: test2\n",
            
            # Very long lines
            "test.mdoc:1:1: error: " + "A" * 100000 + "\n",
            
            # Lines with special characters
            "test.mdoc:1:1: error: test\x00\x01\x02\n",
            
            # Attempt at format string injection (though we're not using format strings)
            "test.mdoc:1:1: error: %s %n\n",
            
            # Empty or malformed lines
            "\n\n\n",
            ":",
            "::::",
            "test.mdoc::::",
        ]
        
        for output in malicious_outputs:
            try:
                # Test mandoc output parsing
                result = validator._parse_mandoc_output(output, "")
                assert isinstance(result, ValidationResult)
                assert hasattr(result, 'errors')
                assert hasattr(result, 'warnings')
                assert hasattr(result, 'valid')
                
                # Test asciidoctor output parsing
                result2 = validator._parse_asciidoc_output("", output)
                assert isinstance(result2, ValidationResult)
                assert hasattr(result2, 'errors')
                assert hasattr(result2, 'warnings')
                assert hasattr(result2, 'valid')
            except Exception as e:
                # Should not be security-related exceptions
                assert "security" not in str(e).lower()
                assert "eval" not in str(e).lower()
                assert "exec" not in str(e).lower()
                assert "import" not in str(e).lower()

    def test_validation_with_missing_tools(self):
        """Test validation behavior when tools are missing."""
        # Test with mandoc unavailable
        validator = DocValidator()
        validator.mandoc_available = False
        validator.asciidoctor_available = True  # Keep asciidoctor for comparison
        
        # Should handle missing mandoc gracefully
        result = validator.validate_mdoc(".Dd 2026-04-03\n.Dt TEST\n.Os\n.Sh NAME\n.Nm test\n.Nd Test\n")
        assert isinstance(result, ValidationResult)
        # Should be valid (we assume valid when can't validate)
        assert result.valid == True
        # Should have warning about mandoc not being available
        assert len(result.warnings) > 0
        assert any("mandoc not available" in w.message for w in result.warnings)
        
        # Test with asciidoctor unavailable
        validator2 = DocValidator()
        validator2.mandoc_available = True
        validator2.asciidoctor_available = False
        
        result2 = validator2.validate_asciidoc("= Test\n\nThis is a test.")
        assert isinstance(result2, ValidationResult)
        assert result2.valid == True
        assert len(result2.warnings) > 0
        assert any("asciidoctor not available" in w.message for w in result2.warnings)
