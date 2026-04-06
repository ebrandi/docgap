"""Output metadata structure for documentation generation results."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class OutputMetadata:
    """Metadata for a documentation output."""
    commit_hash: str
    classification: str
    confidence: float
    category: Optional[str] = None
    generated_at: Optional[str] = None
    validation_passed: bool = True
    validation_errors: List[str] = None  # type: ignore
    validation_warnings: List[str] = None  # type: ignore
    files: List[str] = None  # type: ignore
    
    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.now(timezone.utc).isoformat()
        if self.validation_errors is None:
            self.validation_errors = []
        if self.validation_warnings is None:
            self.validation_warnings = []
        if self.files is None:
            self.files = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "commit_hash": self.commit_hash,
            "classification": self.classification,
            "confidence": self.confidence,
            "category": self.category,
            "generated_at": self.generated_at,
            "validation_passed": self.validation_passed,
            "validation_errors": self.validation_errors,
            "validation_warnings": self.validation_warnings,
            "files": self.files,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutputMetadata":
        """Create from dictionary."""
        return cls(
            commit_hash=data["commit_hash"],
            classification=data["classification"],
            confidence=data["confidence"],
            category=data.get("category"),
            generated_at=data.get("generated_at"),
            validation_passed=data.get("validation_passed", True),
            validation_errors=data.get("validation_errors", []),
            validation_warnings=data.get("validation_warnings", []),
            files=data.get("files", []),
        )
