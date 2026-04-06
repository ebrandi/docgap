"""Core generation logic for Stage 2."""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import time

from docgap.core.prompts import load_prompt

logger = logging.getLogger(__name__)

# Input size limits to prevent resource exhaustion
MAX_DIFF_LENGTH = 100_000
MAX_DOC_CONTENT_LENGTH = 50_000
MAX_FILES_PER_COMMIT = 500


@dataclass
class GenerationResult:
    """Result of documentation generation."""
    success: bool
    patch: str
    report: str
    format: str
    duration_ms: float
    validation_passed: bool = True
    validation_errors: List[str] = None  # type: ignore
    retry_count: int = 0
    
    def __post_init__(self):
        if self.validation_errors is None:
            self.validation_errors = []
        if self.format not in ("mdoc", "asciidoc"):
            self.format = "mdoc"


class Stage2Generator:
    """Stage 2 generation - produce documentation patches."""
    
    def __init__(self,
                 llm_client,
                 doc_retriever,
                 config):
        """Initialize the generator.
        
        Args:
            llm_client: OllamaClient for LLM calls
            doc_retriever: DocRetriever for existing docs
            config: Configuration object
        """
        self.llm_client = llm_client
        self.doc_retriever = doc_retriever
        self.config = config
        
        # Statistics
        self._stats: Dict[str, int | float] = {
            'total_generated': 0,
            'success': 0,
            'failed': 0,
            'total_time_ms': 0,
        }
    
    def generate(self,
                 commit_data: Dict[str, Any],
                 classification_result) -> GenerationResult:
        """Generate documentation for a commit.
        
        Args:
            commit_data: Commit metadata
            classification_result: Stage 1 classification result
            
        Returns:
            GenerationResult with patch and report
        """
        start_time = time.time()
        
        try:
            # Get existing documentation if available
            doc_target = classification_result.doc_target
            docs = []
            if doc_target:
                # Retrieve docs for the affected documentation
                docs = self.doc_retriever.retrieve_docs({
                    'files': [doc_target],
                    'keywords': [commit_data.get('subject', '')]
                })
            
            # Construct prompt
            prompt = self._construct_prompt(commit_data, classification_result, docs)
            
            # Set debug context if available
            commit_hash = commit_data.get("hash", "unknown")
            if self.llm_client.debug_logger:
                from docgap.llm.debug_logger import LLMCallContext
                seq = self.llm_client.debug_logger.get_next_sequence(commit_hash)
                self.llm_client._call_context = LLMCallContext(
                    commit_hash=commit_hash,
                    stage="stage2-generation",
                    sequence_num=seq,
                )

            # Call LLM
            response = self.llm_client.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate documentation patch in unified diff format. Return only the patch and a human-readable report."},
                ],
                json_mode=False,  # We want free-form text with patch
            )
            
            # Parse response - extract patch and report
            patch = ""
            report = ""
            
            # Try to extract unified diff format
            lines = response.split('\n')
            in_patch = False
            patch_lines = []
            report_lines = []
            
            for line in lines:
                if line.startswith('---') and '+' in line:
                    in_patch = True
                    patch_lines.append(line)
                elif in_patch:
                    patch_lines.append(line)
                else:
                    report_lines.append(line)
            
            patch = '\n'.join(patch_lines)
            report = '\n'.join(report_lines)
            
            # If no patch found, generate a basic one
            if not patch:
                patch = f"""# Documentation update for: {commit_data.get('subject', 'Unknown')}

# Based on classification: {classification_result.classification}
# Reasoning: {classification_result.reasoning}

# TODO: Add documentation here
"""
                report = response
            
            # Detect output format from doc_target
            doc_format = self._detect_format(doc_target)

            # Update stats
            self._stats['total_generated'] += 1
            self._stats['success'] += 1

            elapsed_ms = float((time.time() - start_time) * 1000)
            self._stats['total_time_ms'] += elapsed_ms

            return GenerationResult(
                success=True,
                patch=patch,
                report=report,
                format=doc_format,
                duration_ms=elapsed_ms,
                validation_passed=True,
                validation_errors=[],
                retry_count=0,
            )
            
        except Exception as e:
            self._stats['failed'] += 1
            elapsed_ms = float((time.time() - start_time) * 1000)
            self._stats['total_time_ms'] += elapsed_ms
            
            return GenerationResult(
                success=False,
                patch="",
                report=f"Generation failed: {str(e)}",
                format="mdoc",
                duration_ms=elapsed_ms,
                validation_passed=False,
                validation_errors=[str(e)],
                retry_count=0,
            )
    
    @staticmethod
    def _detect_format(doc_target: Optional[str]) -> str:
        """Detect documentation format from doc_target path.

        Args:
            doc_target: Path to the affected documentation file

        Returns:
            'asciidoc' for handbook/AsciiDoc targets, 'mdoc' otherwise
        """
        if not doc_target:
            return "mdoc"
        target_lower = doc_target.lower()
        if any(target_lower.endswith(ext) for ext in ('.adoc', '.asciidoc', '.asc')):
            return "asciidoc"
        if 'handbook' in target_lower or 'books/' in target_lower or 'articles/' in target_lower:
            return "asciidoc"
        return "mdoc"

    # Default prompts used when template files are not found
    _DEFAULT_MDOC_PROMPT = """You are a FreeBSD documentation writer. Your task is to generate
documentation patches for source code changes.

Follow FreeBSD Documentation Project (FDP) conventions:
- Use mdoc(7) for manpages (troff macros)
- Follow standard manpage structure: NAME, SYNOPSIS, DESCRIPTION, OPTIONS, EXIT STATUS, EXAMPLES, SEE ALSO
- Use proper mdoc macros: .Dd, .Dt, .Os, .Sh, .Nm, .Nd, .Bl, .It, .El
- Keep descriptions concise but complete
"""

    _DEFAULT_ASCIIDOC_PROMPT = """You are a FreeBSD documentation writer. Your task is to generate
documentation patches for source code changes.

Follow FreeBSD Documentation Project (FDP) conventions:
- Use AsciiDoc syntax for handbook/book/article content
- Follow FreeBSD handbook structure and conventions
- Use proper AsciiDoc elements: sections (==), lists, cross-references, admonitions
- Keep descriptions concise but complete
"""

    def _construct_prompt(self,
                          commit_data: Dict[str, Any],
                          classification_result,
                          docs: List) -> str:
        """Construct generation prompt with context.

        Args:
            commit_data: Commit metadata
            classification_result: Stage 1 classification
            docs: Existing documentation references

        Returns:
            Full prompt string
        """
        # Detect format and load appropriate prompt template
        doc_format = self._detect_format(classification_result.doc_target)
        if doc_format == "asciidoc":
            prompt = load_prompt("generation-asciidoc", self._DEFAULT_ASCIIDOC_PROMPT)
        else:
            prompt = load_prompt("generation-mdoc", self._DEFAULT_MDOC_PROMPT)
        prompt += "\n"
        
        # Add existing documentation if available
        if docs:
            prompt += "\n## Existing Documentation\n\n"
            for doc in docs[:3]:  # Limit to 3 docs
                prompt += f"### {doc.path}\n\n"
                prompt += f"{doc.content[:3000]}...\n"  # Limit content
                prompt += "\n"
        
        # Add commit context
        prompt += "\n## Commit Context\n\n"
        prompt += f"- Hash: {commit_data.get('hash', 'N/A')}\n"
        subject = commit_data.get('subject', 'N/A')[:1000]
        prompt += f"- Subject: {subject}\n"
        files = commit_data.get('files', [])[:MAX_FILES_PER_COMMIT]
        prompt += f"- Files: {', '.join(files[:20])}\n"

        # Add diff (truncated for safety)
        prompt += "\n## Code Diff\n\n"
        diff = commit_data.get('diff', '')
        if diff:
            if len(diff) > MAX_DIFF_LENGTH:
                logger.warning("Diff truncated from %d to %d chars in generation", len(diff), MAX_DIFF_LENGTH)
                diff = diff[:MAX_DIFF_LENGTH]
            prompt += f"```diff\n{diff[:5000]}\n```\n"
        
        # Add classification info
        prompt += "\n## Classification\n\n"
        prompt += f"- Classification: {classification_result.classification}\n"
        prompt += f"- Category: {classification_result.category}\n"
        prompt += f"- Doc Target: {classification_result.doc_target}\n"
        prompt += f"- Reasoning: {classification_result.reasoning}\n"
        
        # Add generation instructions
        prompt += """
## Instructions

Generate a documentation patch in unified diff format that updates the
affected documentation to reflect the code changes.

Format:
1. Start with unified diff header: --- a/path/to/file.N and +++ b/path/to/file.N
2. Include hunk headers: @@ line,lines @@
3. Use + for additions, - for deletions
4. For mdoc: use proper troff macros
5. For AsciiDoc: use proper AsciiDoc syntax

Also provide a human-readable report explaining the changes made.

Return your complete response with both the patch and report.
"""
        
        return prompt
    
    def get_statistics(self) -> Dict[str, float]:
        """Get generation statistics.
        
        Returns:
            Dictionary with statistics (all values are numeric)
        """
        stats = self._stats.copy()
        if stats['total_generated'] > 0:
            stats['avg_time_ms'] = float(stats['total_time_ms']) / stats['total_generated']
        else:
            stats['avg_time_ms'] = 0.0
        return stats
