"""Ollama HTTP API client."""
import ipaddress
import json
import logging
import socket
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

# Maximum response length to prevent memory exhaustion
MAX_RESPONSE_LENGTH = 200_000

from docgap.llm.exceptions import (
    APIError,
    ConnectionError,
    MalformedResponseError,
    ModelNotFoundError,
    TimeoutError,
)

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for Ollama HTTP API."""
    
    def __init__(self,
                 base_url: str = "http://localhost:11434",
                 model: str = "qwen3-coder-next-512k",
                 timeout: int = 120,
                 connect_timeout: int = 5,
                 max_retries: int = 3,
                 retry_delay: float = 1.0,
                 log_requests: bool = False):
        """Initialize the Ollama client.
        
        Args:
            base_url: Base URL for Ollama API
            model: Default model name
            timeout: Request timeout in seconds
            connect_timeout: Connection timeout in seconds
            max_retries: Maximum retry attempts for transient failures
            retry_delay: Initial delay between retries in seconds
            log_requests: Whether to log requests at DEBUG level
        """
        if any(c in base_url for c in '\r\n\x00'):
            raise ValueError("Invalid characters in base_url")
        self.base_url = base_url.rstrip('/')
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
        # Block known cloud metadata hostnames that may not resolve in all environments
        _blocked_hostnames = {"metadata.google.internal"}
        if parsed.hostname in _blocked_hostnames:
            raise ValueError(f"Link-local addresses are not allowed as LLM base_url: {parsed.hostname}")
        # Resolve hostname and check against blocked IP ranges (covers hex/decimal/octal encodings)
        if parsed.hostname:
            try:
                resolved = socket.getaddrinfo(parsed.hostname, None)
                for family, type_, proto, canonname, sockaddr in resolved:
                    ip = ipaddress.ip_address(sockaddr[0])
                    if ip.is_link_local:
                        raise ValueError(f"Link-local addresses are not allowed as LLM base_url: {parsed.hostname}")
                    # Check IPv6-mapped IPv4 addresses (e.g., ::ffff:169.254.169.254)
                    mapped = getattr(ip, 'ipv4_mapped', None)
                    if mapped and mapped.is_link_local:
                        raise ValueError(f"Link-local addresses are not allowed as LLM base_url: {parsed.hostname}")
            except socket.gaierror:
                pass  # Unresolvable hostname is not a security issue here
        self.model = model
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.log_requests = log_requests
        self.debug_logger = None
        self._call_context = None

        # Session for connection pooling
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
        })
    
    def _build_url(self, path: str) -> str:
        """Build a full URL for an API endpoint."""
        return f"{self.base_url}{path}"
    
    def _make_request(self,
                      method: str,
                      path: str,
                      data: Optional[Dict[str, Any]] = None,
                      timeout: Optional[int] = None) -> Dict[str, Any]:
        """Make an HTTP request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., '/api/tags')
            data: JSON payload for POST requests
            timeout: Request timeout in seconds (uses default if None)
            
        Returns:
            Response JSON as dictionary
            
        Raises:
            ConnectionError: If cannot connect to Ollama
            TimeoutError: If request times out
            APIError: If API returns error status
        """
        url = self._build_url(path)
        req_timeout = timeout if timeout is not None else self.connect_timeout
        
        last_error: Optional[Exception] = None
        
        for attempt in range(self.max_retries + 1):
            try:
                if self.log_requests:
                    logger.debug(f"HTTP {method} {url}")
                    if data:
                        logger.debug(f"Payload: {json.dumps(data)}")
                
                response = self._session.request(
                    method=method,
                    url=url,
                    json=data,
                    timeout=(self.connect_timeout, timeout or self.timeout),
                )
                
                if self.log_requests:
                    logger.debug(f"Status: {response.status_code}")
                
                if response.status_code >= 400:
                    error_text = response.text
                    if response.status_code == 404:
                        raise ModelNotFoundError(self.model)
                    if response.status_code == 400:
                        raise APIError(response.status_code, error_text)
                    raise APIError(response.status_code, error_text)
                
                return response.json()
                
            except requests.exceptions.ConnectionError as e:
                last_error = ConnectionError(self.base_url, str(e))
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    raise last_error
                    
            except requests.exceptions.Timeout as e:
                last_error = TimeoutError(self.timeout)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    raise last_error
                    
            except requests.exceptions.HTTPError as e:
                last_error = APIError(e.response.status_code if e.response else 0, str(e))
                if attempt < self.max_retries and e.response is not None:
                    if e.response.status_code in (503, 504):
                        time.sleep(self.retry_delay * (2 ** attempt))
                        continue
                raise last_error
        
        if last_error:  # pragma: no cover
            raise last_error
        raise ConnectionError(self.base_url, "Unknown error")  # pragma: no cover
    
    def is_healthy(self) -> bool:
        """Check if Ollama is running and accessible.
        
        Returns:
            True if Ollama is healthy, False otherwise
        """
        try:
            self._make_request("GET", "/api/tags", timeout=5)
            return True
        except Exception:
            return False
    
    def list_models(self) -> List[str]:
        """List available models in Ollama.
        
        Returns:
            List of model names
        """
        response = self._make_request("GET", "/api/tags")
        models = response.get("models", [])
        return [m.get("name", "") for m in models if m.get("name")]
    
    def generate(self,
                 prompt: str,
                 options: Optional[Dict[str, Any]] = None,
                 system: Optional[str] = None,
                 stream: bool = False) -> str:
        """Generate text from a prompt.
        
        Args:
            prompt: Input prompt text
            options: Generation options (temperature, max_tokens, etc.)
            system: System prompt to set context
            stream: Whether to stream response
            
        Returns:
            Generated text
        """
        data: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
        }
        
        if options:
            data["options"] = options
        if system:
            data["system"] = system
        if stream:  # pragma: no cover
            data["stream"] = True  # pragma: no cover
        
        response = self._make_request("POST", "/api/generate", data)
        
        if stream:  # pragma: no cover
            # Handle streaming response
            full_response = ""  # pragma: no cover
            for line in response.split('\n'):  # pragma: no cover
                if line:  # pragma: no cover
                    chunk = json.loads(line)  # pragma: no cover
                    if 'response' in chunk:  # pragma: no cover
                        full_response += chunk['response']  # pragma: no cover
            return full_response  # pragma: no cover
        
        result = response.get("response", "")
        if len(result) > MAX_RESPONSE_LENGTH:
            logger.warning("LLM response truncated from %d to %d chars", len(result), MAX_RESPONSE_LENGTH)
            result = result[:MAX_RESPONSE_LENGTH]
        return result
    
    def chat(self,
             messages: List[Dict[str, str]],
             json_mode: bool = False,
             options: Optional[Dict[str, Any]] = None,
             system: Optional[str] = None) -> str:
        """Send a chat completion request.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            json_mode: If True, request JSON format output
            options: Generation options
            system: System message to set context
            
        Returns:
            AI response message content
        """
        data: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        if json_mode:
            data["format"] = "json"
        
        if options:
            data["options"] = options
        if system:
            # Prepend system message
            data["messages"] = [{"role": "system", "content": system}] + messages
        
        # Debug logging: capture request
        if self.debug_logger and self._call_context:
            self.debug_logger.log_request(self._call_context, data.get("messages", []), json_mode, options or {})

        response = self._make_request("POST", "/api/chat", data)

        if "message" in response and "content" in response["message"]:
            result = response["message"]["content"]
            if len(result) > MAX_RESPONSE_LENGTH:
                logger.warning("LLM chat response truncated from %d to %d chars", len(result), MAX_RESPONSE_LENGTH)
                result = result[:MAX_RESPONSE_LENGTH]
            # Debug logging: capture response
            if self.debug_logger and self._call_context:
                self.debug_logger.log_response(self._call_context, result)
                self._call_context = None
            return result

        raise MalformedResponseError(json.dumps(response), "No message content in response")
    
    def embed(self,
              inputs: str | List[str],
              model: Optional[str] = None) -> List[List[float]]:
        """Generate embeddings for input text(s).
        
        Args:
            inputs: Single string or list of strings
            model: Model name (uses default if None)
            
        Returns:
            List of embedding vectors
        """
        if isinstance(inputs, str):
            inputs = [inputs]
        
        data: Dict[str, Any] = {
            "model": model or self.model,
            "input": inputs,
        }
        
        response = self._make_request("POST", "/api/embeddings", data)
        
        embeddings = response.get("embeddings", [])
        return embeddings
    
    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
