"""Retry logic with exponential backoff for LLM operations."""
import time
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from docgap.llm.exceptions import ConnectionError

# Type variable for decorated function
F = TypeVar('F', bound=Callable[..., Any])


def retry_with_backoff(max_retries: int = 3,
                       base_delay: float = 1.0,
                       max_delay: float = 30.0,
                       backoff_multiplier: float = 2.0) -> Callable[[F], F]:
    """Decorator to retry a function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_multiplier: Multiplier for delay each retry
        
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error: Optional[Exception] = None
            delay = base_delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except ConnectionError as e:
                    last_error = e
                    if attempt < max_retries:
                        print(f"attempt {attempt + 1}/{max_retries + 1} failed: {e}. Retrying in {delay}s...")
                        time.sleep(delay)
                        delay = min(delay * backoff_multiplier, max_delay)
                    else:
                        raise
                except Exception as e:
                    # For non-connection errors, fail immediately
                    raise
            
            # Should not reach here, but just in case
            if last_error:  # pragma: no cover
                raise last_error
            return None  # pragma: no cover
        
        return wrapper  # type: ignore
    return decorator


def exponential_backoff_delay(attempt: int,
                              base_delay: float = 1.0,
                              max_delay: float = 30.0,
                              backoff_multiplier: float = 2.0) -> float:
    """Calculate delay for a given attempt with exponential backoff.
    
    Args:
        attempt: Current attempt number (0-indexed)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_multiplier: Multiplier for delay each retry
        
    Returns:
        Delay in seconds
    """
    delay = base_delay * (backoff_multiplier ** attempt)
    return min(delay, max_delay)
