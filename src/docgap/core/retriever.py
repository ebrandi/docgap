"""Documentation retriever for FreeBSD."""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docgap.config.schema import Config
from docgap.git.fetcher import GitFetcher

from docgap.core.mappings import PathMapper
from docgap.core.search import KeywordSearch


class DocReference:
    """Reference to a documentation file."""
    
    def __init__(self,
                 path: str,
                 content: str,
                 format: str = "mdoc",
                 relevance_score: float = 1.0):
        """Initialize documentation reference.
        
        Args:
            path: Path to documentation file
            content: Full content of documentation
            format: 'mdoc' or 'asciidoc'
            relevance_score: Relevance score 0.0-1.0
        """
        self.path = path
        self.content = content
        self.format = format
        self.relevance_score = relevance_score
    
    def is_mdoc(self) -> bool:
        """Check if this is an mdoc (manpage) format."""
        return self.format == "mdoc"
    
    def is_asciidoc(self) -> bool:
        """Check if this is an AsciiDoc format."""
        return self.format == "asciidoc"


class DocRetriever:
    """Retrieve FreeBSD documentation for commits."""
    
    def __init__(self,
                 doc_fetcher: GitFetcher,
                 config: Optional[Config] = None):
        """Initialize the retriever.
        
        Args:
            doc_fetcher: GitFetcher for doc repo
            config: Configuration (optional)
        """
        self.doc_fetcher = doc_fetcher
        self.config = config
        
        self.path_mapper = PathMapper()
        self.search = KeywordSearch()
        self._cache: Dict[str, DocReference] = {}
        self._indexed: bool = False
        self._max_index_files: int = 500
    
    def map_path_to_doc(self, path: str) -> Optional[str]:
        """Map a source file path to a documentation file.
        
        Args:
            path: Source file path
            
        Returns:
            Documentation file path or None
        """
        return self.path_mapper.map_path(path)
    
    def map_paths_to_docs(self, paths: List[str]) -> List[str]:
        """Map multiple source paths to documentation files.
        
        Args:
            paths: List of source file paths
            
        Returns:
            List of documentation paths (deduplicated)
        """
        return self.path_mapper.map_paths_to_docs(paths)
    
    def _format_from_path(self, path: str) -> str:
        """Determine format from path extension.
        
        Args:
            path: Documentation file path
            
        Returns:
            'mdoc' or 'asciidoc'
        """
        if path.endswith((".1", ".3", ".4", ".5", ".8", ".9", ".mdoc")):
            return "mdoc"
        elif path.endswith((".adoc", ".asciidoc", ".asc")):
            return "asciidoc"
        elif "handbook" in path.lower():
            return "asciidoc"
        else:
            return "mdoc"
    
    def _get_file_content(self, path: str) -> Optional[str]:
        """Get content of a documentation file.
        
        Args:
            path: Path to documentation file
            
        Returns:
            File content or None if not found
        """
        try:
            return self.doc_fetcher.get_file_content_at_commit(path, "HEAD")
        except Exception:
            return None
    
    def _retrieve_single_doc(self, doc_path: str) -> Optional[DocReference]:
        """Retrieve a single documentation file.
        
        Args:
            doc_path: Path to documentation file
            
        Returns:
            DocReference or None if not found
        """
        # Check cache first
        if doc_path in self._cache:
            return self._cache[doc_path]
        
        content = self._get_file_content(doc_path)
        if content is None:
            return None
        
        format_type = self._format_from_path(doc_path)
        
        ref = DocReference(
            path=doc_path,
            content=content,
            format=format_type,
            relevance_score=1.0
        )
        
        # Cache for later use
        self._cache[doc_path] = ref
        
        return ref
    
    def _search_docs(self, keywords: List[str], top_n: int = 3) -> List[DocReference]:
        """Search documentation for relevant content.

        Args:
            keywords: Search keywords
            top_n: Maximum number of results

        Returns:
            List of matching DocReferences
        """
        # First, index documentation from the doc repo
        self._index_default_docs()

        # Search for each keyword and collect results
        results: Dict[str, Tuple[float, DocReference]] = {}

        for keyword in keywords:
            searches = self.search.search(keyword, top_n=top_n)
            for doc_id, score in searches:
                if doc_id in results:
                    # Update score if this search is more relevant
                    old_score, ref = results[doc_id]
                    results[doc_id] = (max(old_score, score), ref)
                else:
                    ref = self._cache.get(doc_id)
                    if ref:
                        results[doc_id] = (score, ref)

        # Sort by score and return top_n
        sorted_results = sorted(results.values(), key=lambda x: x[0], reverse=True)
        return [ref for score, ref in sorted_results[:top_n]]

    def _index_default_docs(self) -> None:
        """Index documentation files from the doc repository for keyword search.

        Walks the doc fetcher's doc_path looking for manpages and AsciiDoc files,
        then indexes their filenames and first lines for keyword matching.
        Only indexes once per DocRetriever instance.
        """
        if self._indexed:
            return
        self._indexed = True

        if not self.doc_fetcher.doc_path:
            return

        from pathlib import Path
        doc_root = Path(str(self.doc_fetcher.doc_path))
        if not doc_root.exists():
            return

        # Index manpages and AsciiDoc files
        extensions = ('.1', '.2', '.3', '.4', '.5', '.8', '.9', '.adoc', '.asciidoc')
        indexed_count = 0
        max_files = self._max_index_files

        for ext in extensions:
            for filepath in doc_root.rglob(f'*{ext}'):
                if indexed_count >= max_files:
                    break
                try:
                    rel_path = str(filepath.relative_to(doc_root))
                    # Read first 500 chars for indexing (enough for title/synopsis)
                    content = filepath.read_text(errors='replace')[:500]
                    title = filepath.stem
                    self.search.index_content(rel_path, content, title)

                    # Also cache as DocReference for retrieval
                    fmt = self._format_from_path(rel_path)
                    full_content = filepath.read_text(errors='replace')
                    self._cache[rel_path] = DocReference(
                        path=rel_path,
                        content=full_content,
                        format=fmt,
                        relevance_score=0.5,
                    )
                    indexed_count += 1
                except (OSError, UnicodeDecodeError):
                    continue
    
    def retrieve_docs(self, commit_data: Dict[str, Any]) -> List[DocReference]:
        """Retrieve documentation for a commit.
        
        Args:
            commit_data: Commit metadata including files, subject, etc.
            
        Returns:
            List of DocReferences for affected documentation
        """
        paths = commit_data.get("files", [])
        keywords = commit_data.get("keywords", [])
        
        doc_paths = self.map_paths_to_docs(paths)
        docs: List[DocReference] = []
        
        # Try to retrieve each mapped doc
        for doc_path in doc_paths:
            ref = self._retrieve_single_doc(doc_path)
            if ref:
                docs.append(ref)
        
        # If no docs found via path mapping, try keyword search
        if not docs and keywords:
            docs.extend(self._search_docs(keywords))
        
        # Sort by relevance score (highest first)
        docs.sort(key=lambda d: d.relevance_score, reverse=True)
        
        return docs
    
    def get_doc_content(self, doc_path: str) -> Optional[str]:
        """Get content of a specific documentation file.
        
        Args:
            doc_path: Path to documentation file
            
        Returns:
            File content or None if not found
        """
        ref = self._retrieve_single_doc(doc_path)
        return ref.content if ref else None
    
    def get_format(self, doc_path: str) -> str:
        """Get format of a documentation file.
        
        Args:
            doc_path: Path to documentation file
            
        Returns:
            'mdoc' or 'asciidoc'
        """
        ref = self._retrieve_single_doc(doc_path)
        return ref.format if ref else "mdoc"
    
    def clear_cache(self) -> None:
        """Clear the documentation cache."""
        self._cache.clear()
