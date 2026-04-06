"""Output manager for saving documentation generation results."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from docgap.config.schema import Config

from docgap.core.output_metadata import OutputMetadata


class OutputManager:
    """Manage documentation output files."""
    
    def __init__(self, config: Config):
        """Initialize the output manager.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.base_dir = Path(config.general.data_dir) / "output"
        
        # Create base directory if it doesn't exist
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Statistics
        self._stats = {
            'total_saved': 0,
            'total_loaded': 0,
            'total_rotated': 0,
        }
    
    def _get_output_dir(self, commit_hash: str) -> Path:
        """Get output directory for a commit.
        
        Args:
            commit_hash: Commit hash
            
        Returns:
            Path to output directory
        """
        return self.base_dir / commit_hash[:2] / commit_hash
    
    def _get_output_dir_flat(self, commit_hash: str) -> Path:
        """Get output directory for a commit (flat structure).
        
        Args:
            commit_hash: Commit hash
            
        Returns:
            Path to output directory
        """
        return self.base_dir / commit_hash
    
    def save_output(
        self,
        commit_hash: str,
        generation_result: Any,
        classification_result: Any,
        validation_result: Optional[Any] = None,
    ) -> Dict[str, Path]:
        """Save all output files for a commit.
        
        Args:
            commit_hash: Commit hash
            generation_result: GenerationResult from Stage 2
            classification_result: ClassificationResult from Stage 1
            validation_result: ValidationResult (optional)
            
        Returns:
            Dictionary mapping filename to path
        """
        # Create output directory
        output_dir = self._get_output_dir_flat(commit_hash)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        saved_files: Dict[str, Path] = {}
        
        # Save report.txt
        if generation_result.report:
            report_path = output_dir / "report.txt"
            self._write_atomic(report_path, generation_result.report)
            saved_files["report.txt"] = report_path
        
        # Save patch file (handbook.patch for asciidoc, manpage.patch for mdoc)
        if generation_result.patch:
            patch_filename = "handbook.patch" if getattr(generation_result, 'format', 'mdoc') == "asciidoc" else "manpage.patch"
            patch_path = output_dir / patch_filename
            self._write_atomic(patch_path, generation_result.patch)
            saved_files[patch_filename] = patch_path
        
        # Save metadata.json
        metadata = OutputMetadata(
            commit_hash=commit_hash,
            classification=classification_result.classification.name,
            confidence=classification_result.confidence,
            category=classification_result.category.name if classification_result.category else None,
            generated_at=datetime.now(timezone.utc).isoformat(),
            validation_passed=validation_result.is_valid() if validation_result else True,
            validation_errors=validation_result.errors if validation_result else [],
            validation_warnings=validation_result.warnings if validation_result else [],
            files=list(saved_files.keys()),
        )
        
        metadata_path = output_dir / "metadata.json"
        self._write_atomic(metadata_path, json.dumps(metadata.to_dict(), indent=2))
        saved_files["metadata.json"] = metadata_path
        
        # Update stats
        self._stats['total_saved'] += 1
        
        return saved_files
    
    def load_output(self, commit_hash: str) -> Optional[Dict[str, Any]]:
        """Load output for a commit.
        
        Args:
            commit_hash: Commit hash
            
        Returns:
            Dictionary with loaded files, or None if not found
        """
        output_dir = self._get_output_dir_flat(commit_hash)
        
        if not output_dir.exists():
            return None
        
        result: Dict[str, Any] = {
            "commit_hash": commit_hash,
            "output_dir": str(output_dir),
        }
        
        # Load metadata
        metadata_path = output_dir / "metadata.json"
        if metadata_path.exists():
            result["metadata"] = OutputMetadata.from_dict(
                json.loads(metadata_path.read_text())
            )
        
        # Load report
        report_path = output_dir / "report.txt"
        if report_path.exists():
            result["report"] = report_path.read_text()
        
        # Load patch (check both filenames)
        for patch_name in ("manpage.patch", "handbook.patch"):
            patch_path = output_dir / patch_name
            if patch_path.exists():
                result["patch"] = patch_path.read_text()
                result["patch_filename"] = patch_name
                break
        
        self._stats['total_loaded'] += 1
        
        return result
    
    def list_outputs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all saved outputs.
        
        Args:
            limit: Maximum number of results
            
        Returns:
            List of metadata dictionaries
        """
        outputs: List[Dict[str, Any]] = []
        
        if not self.base_dir.exists():
            return outputs
        
        # Find all output directories
        output_dirs = [
            d for d in self.base_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        
        # Sort by name (commit hash is timestamp-like)
        output_dirs.sort(reverse=True)
        
        for output_dir in output_dirs[:limit]:
            metadata_path = output_dir / "metadata.json"
            if metadata_path.exists():
                try:
                    metadata = OutputMetadata.from_dict(
                        json.loads(metadata_path.read_text())
                    )
                    outputs.append({
                        "commit_hash": metadata.commit_hash,
                        "output_dir": str(output_dir),
                        "classification": metadata.classification,
                        "confidence": metadata.confidence,
                        "generated_at": metadata.generated_at,
                    })
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return outputs
    
    def _write_atomic(self, path: Path, content: str) -> None:
        """Write content to file atomically.
        
        Args:
            path: Target file path
            content: Content to write
        """
        # Write to temp file first
        fd, temp_path = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=path.name + ".",
        )
        
        try:
            # Write content
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            
            # Atomic rename
            os.rename(temp_path, path)
            
        except Exception:
            # Cleanup on error
            try:  # pragma: no cover
                os.unlink(temp_path)  # pragma: no cover
            except OSError:  # pragma: no cover
                pass  # pragma: no cover
            raise  # pragma: no cover
    
    def rotate_outputs(self, max_outputs: int = 1000, max_size_mb: int = 100) -> int:
        """Rotate old outputs to maintain limits.
        
        Args:
            max_outputs: Maximum number of output directories
            max_size_mb: Maximum total size in MB
            
        Returns:
            Number of rotated outputs
        """
        rotated = 0
        
        if not self.base_dir.exists():  # pragma: no cover
            return rotated  # pragma: no cover
        
        # Get all output directories
        output_dirs = [
            d for d in self.base_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        
        # Sort by name (newest first due to commit hash format)
        output_dirs.sort(reverse=True)
        
        # Rotate if too many outputs
        while len(output_dirs) > max_outputs:
            oldest = output_dirs.pop()
            try:
                import shutil
                shutil.rmtree(oldest)
                rotated += 1
                self._stats['total_rotated'] += 1
            except OSError:  # pragma: no cover
                continue

        # Check total size if needed
        if rotated == 0 and self._get_total_size_mb() > max_size_mb:
            self._rotate_by_size(max_size_mb)
            rotated = 1  # At least one rotation occurred
        
        return rotated
    
    def _get_total_size_mb(self) -> float:
        """Get total size of output directory in MB."""
        if not self.base_dir.exists():  # pragma: no cover
            return 0.0  # pragma: no cover
        
        total = sum(
            f.stat().st_size
            for f in self.base_dir.rglob('*')
            if f.is_file()
        )
        return total / (1024 * 1024)
    
    def _rotate_by_size(self, max_size_mb: int) -> int:
        """Rotate outputs until under size limit.
        
        Args:
            max_size_mb: Maximum size in MB
            
        Returns:
            Number of rotated outputs
        """
        rotated = 0
        
        while self._get_total_size_mb() > max_size_mb:
            output_dirs = [
                d for d in self.base_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ]
            
            if not output_dirs:  # pragma: no cover
                break

            # Sort by name (newest first)
            output_dirs.sort(reverse=True)

            # Remove oldest
            oldest = output_dirs.pop()
            try:
                import shutil
                shutil.rmtree(oldest)
                rotated += 1
                self._stats['total_rotated'] += 1
            except OSError:  # pragma: no cover
                break
        
        return rotated
    
    def get_statistics(self) -> Dict[str, int]:
        """Get output statistics."""
        return self._stats.copy()
