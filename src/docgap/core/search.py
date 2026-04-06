"""Search functionality for documentation lookup."""
import re
from typing import List, Optional


class KeywordSearch:
    """Keyword-based search for documentation content."""
    
    def __init__(self):
        """Initialize the search index."""
        self._cache: dict = {}
    
    def tokenize(self, text: str) -> list[str]:
        """Tokenize text into words.
        
        Args:
            text: Input text
            
        Returns:
            List of lowercase words
        """
        if not text:
            return []
        
        # Clean and tokenize
        text = text.lower()
        # Remove non-alphanumeric chars except spaces
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        return text.split()
    
    def index_content(self, content_id: str, content: str, title: str = "") -> None:
        """Index content for search.
        
        Args:
            content_id: Unique identifier for the content
            content: Documentation content to index
            title: Optional title to boost in search
        """
        # Tokenize content
        words = self.tokenize(content)
        titles = self.tokenize(title)
        
        # Build inverted index
        word_positions: dict[str, list[int]] = {}
        for i, word in enumerate(words):
            if word not in word_positions:
                word_positions[word] = []
            word_positions[word].append(i)
        
        # Store in cache
        self._cache[content_id] = {
            "words": set(words),
            "word_positions": word_positions,
            "title": titles,
            "content": content,
        }
    
    def search(self, query: str, top_n: int = 5) -> list[tuple[str, float]]:
        """Search for content matching query.
        
        Args:
            query: Search query
            top_n: Maximum number of results
            
        Returns:
            List of (content_id, relevance_score) tuples
        """
        query_words = set(self.tokenize(query))
        
        if not query_words:
            return []
        
        scores: list[tuple[str, float]] = []
        
        for content_id, index in self._cache.items():
            # Calculate relevance score
            score = 0.0
            
            # Word match score
            matching_words = query_words & index["words"]
            if matching_words:
                score += len(matching_words) / len(query_words)
            
            # Title boost (title words appear earlier in content)
            for title_word in index["title"]:
                if title_word in index["word_positions"]:
                    positions = index["word_positions"][title_word]
                    # Early positions get higher scores
                    earliest = min(positions) if positions else 0
                    title_bonus = max(0, 1 - (earliest / 100))
                    score += title_bonus * 0.3
            
            if score > 0:
                scores.append((content_id, score))
        
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return scores[:top_n]
    
    def get_content(self, content_id: str) -> Optional[str]:
        """Get indexed content by ID.
        
        Args:
            content_id: Content identifier
            
        Returns:
            Content string or None if not found
        """
        return self._cache.get(content_id, {}).get("content")
    
    def clear_cache(self) -> None:
        """Clear the search cache."""
        self._cache.clear()
