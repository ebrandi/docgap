"""Core logic for the Documentation Gap Detector."""

from docgap.core.classification import Classification, ClassificationResult
from docgap.core.prompts import load_prompt, format_classification_prompt
from docgap.core.detector import Stage1Detector
from docgap.core.mappings import PathMapper
from docgap.core.search import KeywordSearch
from docgap.core.retriever import DocRetriever, DocReference
from docgap.core.generator import Stage2Generator, GenerationResult
from docgap.core.patch import PatchParser, Patch, Hunk
from docgap.core.validator import DocValidator
from docgap.core.validation_result import ValidationIssue, ValidationResult
from docgap.core.output import OutputManager
from docgap.core.output_metadata import OutputMetadata
from docgap.core.notifier import Notifier, NotificationResult

__all__ = [
    "Classification",
    "ClassificationResult",
    "load_prompt",
    "format_classification_prompt",
    "Stage1Detector",
    "Stage2Generator",
    "GenerationResult",
    "PathMapper",
    "KeywordSearch",
    "DocRetriever",
    "DocReference",
    "PatchParser",
    "Patch",
    "Hunk",
    "DocValidator",
    "ValidationIssue",
    "ValidationResult",
    "OutputManager",
    "OutputMetadata",
    "Notifier",
    "NotificationResult",
]
