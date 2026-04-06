"""Classification dataclasses and enums for Stage 1 detection."""
import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Classification(str, Enum):
    """Possible classification results from Stage 1 detection."""
    NEEDS_DOC = "NEEDS_DOC"
    IRRELEVANT = "IRRELEVANT"
    UNCERTAIN = "UNCERTAIN"


class Category(str, Enum):
    """Categories for classification."""
    NEW_FLAG = "new_flag"
    NEW_COMMAND = "new_command"
    CHANGED_DEFAULT = "changed_default"
    NEW_SYSCALL = "new_syscall"
    NEW_SYSCTL = "new_sysctl"
    CHANGED_OUTPUT = "changed_output"
    NEW_IOCTL = "new_ioctl"
    API_CHANGE = "api_change"
    OTHER = "other"


@dataclass
class ClassificationResult:
    """Result of Stage 1 classification."""
    classification: Classification
    confidence: float
    category: Optional[Category] = None
    doc_target: Optional[str] = None
    reasoning: Optional[str] = None

    def apply_thresholds(self, 
                         accept_threshold: float = 0.80,
                         reject_threshold: float = 0.50) -> "ClassificationResult":
        """Apply confidence thresholds to classification.
        
        Args:
            accept_threshold: Accept classification if confidence >= this
            reject_threshold: Override to UNCERTAIN if confidence < this
            
        Returns:
            Self with potentially adjusted classification
        """
        if self.confidence >= accept_threshold:
            return self
        elif self.confidence >= reject_threshold:
            return ClassificationResult(
                classification=Classification.UNCERTAIN,
                confidence=self.confidence,
                category=self.category,
                doc_target=self.doc_target,
                reasoning=f"Confidence ({self.confidence:.2f}) below accept threshold ({accept_threshold}), marked as UNCERTAIN. {self.reasoning or ''}"
            )
        else:
            return ClassificationResult(
                classification=Classification.IRRELEVANT,
                confidence=0.0,
                category=None,
                doc_target=None,
                reasoning=f"Confidence ({self.confidence:.2f}) below reject threshold ({reject_threshold}), marked as IRRELEVANT. {self.reasoning or ''}"
            )

    def is_valid(self) -> bool:
        """Check if the classification is valid."""
        if math.isnan(self.confidence) or math.isinf(self.confidence):
            return False
        if self.confidence < 0.0 or self.confidence > 1.0:
            return False
        if not isinstance(self.classification, Classification):
            return False
        return True

    def is_accepted(self, accept_threshold: float = 0.80) -> bool:
        """Check if classification passes the acceptance threshold."""
        return self.confidence >= accept_threshold
