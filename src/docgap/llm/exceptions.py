"""Custom exceptions for LLM client operations."""

import re


def _sanitize_url(url: str) -> str:
    """Remove credentials from URLs to prevent information leakage."""
    return re.sub(r'://[^@]+@', '://***@', url)


class LLMError(Exception):
    """Base exception for LLM-related errors."""
    pass


class ConnectionError(LLMError):
    """Raised when connection to the LLM server fails."""
    def __init__(self, base_url: str, message: str):
        self.base_url = base_url
        self.message = message
        safe_url = _sanitize_url(base_url)
        safe_msg = _sanitize_url(str(message)[:500])
        super().__init__(f"Failed to connect to LLM at {safe_url}: {safe_msg}")


class ModelNotFoundError(LLMError):
    """Raised when the requested model is not found."""
    def __init__(self, model_name: str, available_models: list[str] | None = None):
        self.model_name = model_name
        self.available_models = available_models or []
        msg = f"Model '{model_name}' not found"
        if available_models:
            msg += f". Available models: {', '.join(available_models)}"
        super().__init__(msg)


class TimeoutError(LLMError):
    """Raised when LLM request times out."""
    def __init__(self, timeout: int, operation: str = "inference"):
        self.timeout = timeout
        self.operation = operation
        super().__init__(f"LLM {operation} timed out after {timeout}s")


class MalformedResponseError(LLMError):
    """Raised when the LLM response is malformed or invalid."""
    def __init__(self, raw_response: str, message: str = "Malformed response"):
        self.raw_response = raw_response[:200]
        self.message = message
        super().__init__(f"Malformed response: {message}")


class APIError(LLMError):
    """Raised when the LLM API returns an error."""
    def __init__(self, status_code: int, response_text: str):
        self.status_code = status_code
        self.response_text = response_text[:500]
        super().__init__(f"LLM API error (status {status_code})")
