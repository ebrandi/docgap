"""Stage 1 detection - classify commits as needing documentation."""
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgap.config.schema import Config
from docgap.core.classification import Category, Classification, ClassificationResult
from docgap.core.prompts import format_classification_prompt, load_prompts
from docgap.git.fetcher import GitFetcher
from docgap.llm.client import OllamaClient

logger = logging.getLogger(__name__)

# Input size limits to prevent DoS via oversized inputs
MAX_DIFF_LENGTH = 100_000
MAX_SUBJECT_LENGTH = 1_000
MAX_FILES_PER_COMMIT = 500


class Stage1Detector:
    """Stage 1 detection - classifies commits using LLM."""
    
    def __init__(self,
                 llm_client: OllamaClient,
                 git_fetcher: GitFetcher,
                 config: Config):
        """Initialize the detector.
        
        Args:
            llm_client: OllamaClient instance for LLM calls
            git_fetcher: GitFetcher for getting diffs
            config: Configuration with detection settings
        """
        self.llm_client = llm_client
        self.git_fetcher = git_fetcher
        self.config = config
        
        # Load prompts
        self.prompts = load_prompts(config)
        
        # Get thresholds from config
        self.accept_threshold = config.detection.confidence_threshold_accept
        self.reject_threshold = config.detection.confidence_threshold_reject
        
        # Statistics
        self._stats: Dict[str, int | float] = {
            'total_classified': 0,
            'needs_doc': 0,
            'irrelevant': 0,
            'uncertain': 0,
            'errors': 0,
            'total_time_ms': 0,
        }
    
    def _get_diff(self, commit_hash: str) -> str:
        """Get the diff for a commit.
        
        Args:
            commit_hash: Commit hash to get diff for
            
        Returns:
            Diff text
        """
        return self.git_fetcher.get_diff(commit_hash)
    
    def _parse_llm_response(self, response: str) -> ClassificationResult:
        """Parse LLM JSON response into ClassificationResult.
        
        Args:
            response: Raw JSON string from LLM
            
        Returns:
            ClassificationResult
            
        Raises:
            MalformedResponseError: If response is not valid JSON
        """
        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")
        
        # Extract fields
        classification_str = data.get("classification", "").upper()
        if classification_str == "NEEDS_DOC":
            classification = Classification.NEEDS_DOC
        elif classification_str == "IRRELEVANT":
            classification = Classification.IRRELEVANT
        elif classification_str == "UNCERTAIN":
            classification = Classification.UNCERTAIN
        else:
            classification = Classification.UNCERTAIN
        
        # Confidence
        confidence = data.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        confidence = max(0.0, min(1.0, float(confidence)))
        
        # Category - handle various input formats
        category_str = data.get("category")
        category = None
        if category_str:
            # Normalize category string
            cat_lower = category_str.lower().strip()
            cat_normalized = cat_lower.replace("-", "_")
            
            for cat in Category:
                if cat.value.lower() == cat_normalized:
                    category = cat
                    break
            
            if category is None:
                category = Category.OTHER
        
        # Doc target -- sanitize to prevent path traversal
        doc_target = data.get("doc_target")
        if doc_target:
            doc_target = doc_target.strip()
            if '..' in doc_target or doc_target.startswith('/'):
                doc_target = None
            elif len(doc_target) > 500:
                doc_target = doc_target[:500]

        # Reasoning -- limit length
        reasoning = data.get("reasoning")
        if reasoning and len(reasoning) > 2000:
            reasoning = reasoning[:2000]
        
        return ClassificationResult(
            classification=classification,
            confidence=confidence,
            category=category,
            doc_target=doc_target,
            reasoning=reasoning,
        )
    
    def classify(self, commit_data: Dict[str, Any]) -> ClassificationResult:
        """Classify a single commit.
        
        Args:
            commit_data: Dictionary with commit metadata
            
        Returns:
            ClassificationResult with classification, confidence, category, doc_target, reasoning
        """
        start_time = time.time()
        
        try:
            commit_hash = commit_data.get("hash", "")

            # Get diff if not provided
            diff = commit_data.get("diff", "")
            if not diff:
                diff = self._get_diff(commit_hash)

            # Enforce input size limits to prevent resource exhaustion
            if len(diff) > MAX_DIFF_LENGTH:
                logger.warning("Diff for %s truncated from %d to %d chars", commit_hash, len(diff), MAX_DIFF_LENGTH)
                diff = diff[:MAX_DIFF_LENGTH]

            subject = commit_data.get("subject", "")
            if len(subject) > MAX_SUBJECT_LENGTH:
                commit_data = {**commit_data, "subject": subject[:MAX_SUBJECT_LENGTH]}

            files = commit_data.get("files", [])
            if len(files) > MAX_FILES_PER_COMMIT:
                logger.warning("File list for %s truncated from %d to %d", commit_hash, len(files), MAX_FILES_PER_COMMIT)
                commit_data = {**commit_data, "files": files[:MAX_FILES_PER_COMMIT]}

            # Format prompt
            prompt = format_classification_prompt(commit_data, diff, self.prompts["detection"])
            
            # Set debug context if available
            if self.llm_client.debug_logger:
                from docgap.llm.debug_logger import LLMCallContext
                seq = self.llm_client.debug_logger.get_next_sequence(commit_hash)
                self.llm_client._call_context = LLMCallContext(
                    commit_hash=commit_hash,
                    stage="stage1-detection",
                    sequence_num=seq,
                )

            # Call LLM
            logger.debug("Prompt for %s:\n%s", commit_hash[:12], prompt)
            response = self.llm_client.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Classify this commit and return JSON only."},
                ],
                json_mode=True,
            )
            logger.debug("LLM response for %s:\n%s", commit_hash[:12], response)

            # Parse response
            classification_result = self._parse_llm_response(response)
            
            # Apply confidence thresholds
            final_result = classification_result.apply_thresholds(
                self.accept_threshold,
                self.reject_threshold
            )
            
            # Update stats
            self._stats['total_classified'] += 1
            self._stats['needs_doc'] += 1 if final_result.classification == Classification.NEEDS_DOC else 0
            self._stats['irrelevant'] += 1 if final_result.classification == Classification.IRRELEVANT else 0
            self._stats['uncertain'] += 1 if final_result.classification == Classification.UNCERTAIN else 0
            
            elapsed_ms = float((time.time() - start_time) * 1000)
            self._stats['total_time_ms'] += elapsed_ms
            
            return final_result
            
        except Exception as e:
            self._stats['errors'] += 1
            
            # Return UNCERTAIN on error
            return ClassificationResult(
                classification=Classification.UNCERTAIN,
                confidence=0.0,
                category=None,
                doc_target=None,
                reasoning=f"Error during classification: {str(e)}"
            )
    
    def classify_batch(self, commits: List[Dict[str, Any]]) -> List[ClassificationResult]:
        """Classify a batch of commits.
        
        Args:
            commits: List of commit data dictionaries
            
        Returns:
            List of ClassificationResults
        """
        return [self.classify(commit) for commit in commits]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get detection statistics.
        
        Returns:
            Dictionary with statistics
        """
        stats = self._stats.copy()
        if stats['total_classified'] > 0:
            stats['avg_time_ms'] = float(stats['total_time_ms']) / stats['total_classified']
        else:
            stats['avg_time_ms'] = 0.0
        return stats
