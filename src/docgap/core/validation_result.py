"""Validation result dataclasses."""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ValidationIssue:
    """A single validation issue (error or warning)."""
    severity: str  # 'ERROR' or 'WARNING'
    line: Optional[int]
    message: str
    
    def is_error(self) -> bool:
        """Check if this is an error."""
        return self.severity.upper() == 'ERROR'
    
    def is_warning(self) -> bool:
        """Check if this is a warning."""
        return self.severity.upper() == 'WARNING'


@dataclass
class ValidationResult:
    """Result of documentation validation."""
    valid: bool
    errors: List[ValidationIssue]
    warnings: List[ValidationIssue]
    format: str = "mdoc"  # 'mdoc' or 'asciidoc'
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
    
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0
    
    def is_valid(self) -> bool:
        """Check if validation passed (no errors)."""
        return not self.has_errors()
    
    def get_summary(self) -> str:
        """Get a human-readable summary."""
        parts = [f"Validation {'PASSED' if self.valid else 'FAILED'} ({self.format})"]
        if self.errors:
            parts.append(f"Errors: {len(self.errors)}")
        if self.warnings:
            parts.append(f"Warnings: {len(self.warnings)}")
        return ", ".join(parts)
