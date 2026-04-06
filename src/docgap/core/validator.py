"""Documentation validator using mandoc and asciidoctor."""
import os
import tempfile
from pathlib import Path
from typing import Any, List, Optional

from docgap.config.schema import Config

from docgap.core.validation_result import ValidationIssue, ValidationResult


class DocValidator:
    """Validate documentation using mandoc and asciidoctor."""
    
    def __init__(self,
                 config: Optional[Config] = None,
                 timeout: int = 30):
        """Initialize the validator.
        
        Args:
            config: Configuration object
            timeout: Validation timeout in seconds
        """
        self.config = config
        self.timeout = timeout
        
        # Check if validation tools are available
        self.mandoc_available = self._check_tool("mandoc")
        self.asciidoctor_available = self._check_tool("asciidoctor")
        
        # Statistics
        self._stats = {
            'total_validated': 0,
            'mdoc_valid': 0,
            'mdoc_invalid': 0,
            'asciidoc_valid': 0,
            'asciidoc_invalid': 0,
        }
    
    def _check_tool(self, tool: str) -> bool:
        """Check if a validation tool is available.
        
        Args:
            tool: Tool name (mandoc or asciidoctor)
            
        Returns:
            True if tool is available
        """
        try:
            import subprocess
            result = subprocess.run(
                [tool, "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def validate(self, content: str, format: str = "mdoc") -> ValidationResult:
        """Validate documentation content.
        
        Args:
            content: Documentation content to validate
            format: 'mdoc' or 'asciidoc'
            
        Returns:
            ValidationResult with issues
        """
        self._stats['total_validated'] += 1
        
        if format == "mdoc":
            return self.validate_mdoc(content)
        elif format == "asciidoc":
            return self.validate_asciidoc(content)
        else:
            return ValidationResult(
                valid=False,
                errors=[ValidationIssue("ERROR", None, f"Unknown format: {format}")],
                warnings=[],
                format=format,
            )
    
    def validate_mdoc(self, content: str) -> ValidationResult:
        """Validate mdoc content using mandoc -Tlint.
        
        Args:
            content: mdoc content to validate
            
        Returns:
            ValidationResult with issues
        """
        # Check if mandoc is available
        if not self.mandoc_available:
            return ValidationResult(
                valid=True,  # Can't validate, so assume valid
                errors=[],
                warnings=[ValidationIssue("WARNING", None, "mandoc not available - skipping validation")],
                format="mdoc",
            )
        
        try:
            tmpdir = tempfile.mkdtemp(prefix="docgap-validate-")
            os.chmod(tmpdir, 0o700)
            tmp_path = os.path.join(tmpdir, "validate.mdoc")
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(content)

            try:
                import subprocess
                result = subprocess.run(
                    ["mandoc", "-Tlint", tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )

                issues = self._parse_mandoc_output(result.stdout, result.stderr)

                # Update stats
                if issues.errors:
                    self._stats['mdoc_invalid'] += 1
                else:
                    self._stats['mdoc_valid'] += 1

                return ValidationResult(
                    valid=not issues.errors,
                    errors=issues.errors,
                    warnings=issues.warnings,
                    format="mdoc",
                )

            finally:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)

        except Exception as e:  # pragma: no cover
            return ValidationResult(
                valid=False,
                errors=[ValidationIssue("ERROR", None, f"Validation error: {str(e)}")],
                warnings=[],
                format="mdoc",
            )

    def validate_asciidoc(self, content: str) -> ValidationResult:
        """Validate AsciiDoc content using asciidoctor --safe.
        
        Args:
            content: AsciiDoc content to validate
            
        Returns:
            ValidationResult with issues
        """
        # Check if asciidoctor is available
        if not self.asciidoctor_available:
            return ValidationResult(
                valid=True,  # Can't validate, so assume valid
                errors=[],
                warnings=[ValidationIssue("WARNING", None, "asciidoctor not available - skipping validation")],
                format="asciidoc",
            )
        
        try:
            tmpdir = tempfile.mkdtemp(prefix="docgap-validate-")
            os.chmod(tmpdir, 0o700)
            tmp_path = os.path.join(tmpdir, "validate.adoc")
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(content)

            try:
                import subprocess
                result = subprocess.run(
                    ["asciidoctor", "--safe", "-o", "/dev/null", tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )

                issues = self._parse_asciidoc_output(result.stdout, result.stderr)

                # Update stats
                if issues.errors:
                    self._stats['asciidoc_invalid'] += 1
                else:
                    self._stats['asciidoc_valid'] += 1

                return ValidationResult(
                    valid=not issues.errors,
                    errors=issues.errors,
                    warnings=issues.warnings,
                    format="asciidoc",
                )

            finally:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)

        except Exception as e:  # pragma: no cover
            return ValidationResult(
                valid=False,
                errors=[ValidationIssue("ERROR", None, f"Validation error: {str(e)}")],
                warnings=[],
                format="asciidoc",
            )
    
    def _parse_mandoc_output(self, stdout: str, stderr: str) -> ValidationResult:
        """Parse mandoc -Tlint output.
        
        Format: file:line:column: level: message
        
        Args:
            stdout: Standard output
            stderr: Standard error
            
        Returns:
            ValidationResult with parsed issues
        """
        issues = []
        
        # Parse stderr for errors
        for line in stderr.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Parse format: file:line:column: level: message
            parts = line.split(':', 3)
            if len(parts) >= 4:
                level = parts[3].strip().split()[0].upper()
                message = parts[3].strip()[len(level):].strip()
                
                try:
                    line_num = int(parts[1])
                except ValueError:
                    line_num = None
                
                severity = "ERROR" if "error" in level.lower() else "WARNING"
                issues.append(ValidationIssue(severity, line_num, message))
        
        # Also check stdout
        for line in stdout.split('\n'):
            line = line.strip()
            if not line or line.startswith("mandoc:"):
                continue
            
            issues.append(ValidationIssue("WARNING", None, line))
        
        errors = [i for i in issues if i.is_error()]
        warnings = [i for i in issues if i.is_warning()]
        
        return ValidationResult(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            format="mdoc",
        )
    
    def _parse_asciidoc_output(self, stdout: str, stderr: str) -> ValidationResult:
        """Parse asciidoctor output.
        
        Args:
            stdout: Standard output
            stderr: Standard error
            
        Returns:
            ValidationResult with parsed issues
        """
        issues = []
        
        # asciidoctor typically outputs to stderr for errors
        for line in stderr.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Parse error format
            if "asciidoctor:" in line or "error:" in line.lower():
                # Try to extract line number
                line_num = None
                message = line
                
                # Try to find "line X" pattern
                import re
                match = re.search(r'line (\d+)', line)
                if match:
                    line_num = int(match.group(1))
                    message = line.replace(match.group(0), "").strip()
                
                severity = "ERROR" if "error" in line.lower() else "WARNING"
                issues.append(ValidationIssue(severity, line_num, message))
        
        # Also check stdout
        for line in stdout.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Check for warning/error messages
            if "warning" in line.lower():
                severity = "WARNING"
            elif "error" in line.lower():
                severity = "ERROR"
            else:
                continue
            
            issues.append(ValidationIssue(severity, None, line))
        
        errors = [i for i in issues if i.is_error()]
        warnings = [i for i in issues if i.is_warning()]
        
        return ValidationResult(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            format="asciidoc",
        )
    
    def get_statistics(self) -> dict:
        """Get validation statistics."""
        stats = self._stats.copy()
        stats['total_valid'] = stats['mdoc_valid'] + stats['asciidoc_valid']
        stats['total_invalid'] = stats['mdoc_invalid'] + stats['asciidoc_invalid']
        return stats
