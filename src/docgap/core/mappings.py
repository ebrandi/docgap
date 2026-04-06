"""Path-to-documentation mapping rules for FreeBSD."""
from pathlib import Path
from typing import Optional


class PathMapper:
    """Map source file paths to documentation files."""
    
    # Mapping patterns for FreeBSD documentation
    # Format: (path_prefix, doc_dir, doc_extension)
    mappings = [
        # bin/<tool>/ -> bin/<tool>/<tool>.1
        ("bin/", "bin/", ".1"),
        # sbin/<tool>/ -> sbin/<tool>/<tool>.8
        ("sbin/", "sbin/", ".8"),
        # usr.bin/<tool>/ -> usr.bin/<tool>/<tool>.1
        ("usr.bin/", "usr.bin/", ".1"),
        # usr.sbin/<tool>/ -> usr.sbin/<tool>/<tool>.8
        ("usr.sbin/", "usr.sbin/", ".8"),
        # lib/lib<name>/ -> lib/lib<name>/<name>.3
        ("lib/lib", "lib/lib", ".3"),
        # share/man/man<sec>/ -> share/man/man<sec>/
        ("share/man/", "share/man/", ""),
    ]
    
    # Special cases for sys/ directory
    sys_kern_sections = [
        ("sys/kern/", "share/man/man9/", ".9"),  # kernel functions
        ("sys/sys/", "share/man/man9/", ".9"),   # system headers
        ("sys/net/", "share/man/man4/", ".4"),   # network interfaces
        ("sys/dev/", "share/man/man4/", ".4"),   # device drivers
    ]
    
    # Handbook sections
    handbook_sections = {
        "books/handbook/": "books/handbook/",
        "documentation/content/en/books/handbook/": "documentation/content/en/books/handbook/",
    }
    
    def map_path(self, path: str) -> Optional[str]:
        """Map a source file path to a documentation file.
        
        Args:
            path: Relative path to source file
            
        Returns:
            Path to documentation file, or None if not mappable
        """
        if not path:
            return None
        
        # Skip files in contrib/ (vendor code)
        if path.startswith("contrib/") or path.startswith("sys/contrib/"):
            return None
        
        # Check sys/ special cases first
        for prefix, doc_dir, ext in self.sys_kern_sections:
            if path.startswith(prefix):
                # Extract the last component as the doc name
                filename = Path(path).stem
                return f"{doc_dir}{filename}{ext}"
        
        # Check standard mappings
        for prefix, doc_dir, ext in self.mappings:
            if path.startswith(prefix):
                # Extract the tool name
                rest = path[len(prefix):]
                # Handle nested paths like lib/libc/string/strcpy.c
                if "/" in rest:
                    # Get the directory containing the file
                    dir_part = Path(rest).parent
                    filename = Path(rest).stem
                    return f"{doc_dir}{dir_part}/{filename}{ext}"
                else:
                    # Simple case like usr.bin/ls/ls.c
                    filename = Path(path).stem
                    return f"{doc_dir}{filename}{ext}"
        
        # Check for manpage references directly
        if "share/man/" in path:
            return path
        
        # Check if it's a .1, .3, .8, .9 file directly
        ext = Path(path).suffix
        if ext in (".1", ".3", ".8", ".9"):
            return path
        
        # Check handbook sections
        for prefix, doc_dir in self.handbook_sections.items():
            if path.startswith(prefix):
                return path
        
        return None
    
    def map_paths_to_docs(self, paths: list[str]) -> list[str]:
        """Map multiple source paths to documentation files.
        
        Args:
            paths: List of source file paths
            
        Returns:
            List of documentation file paths (deduplicated)
        """
        docs = set()
        for path in paths:
            doc = self.map_path(path)
            if doc:
                docs.add(doc)
        return list(docs)
