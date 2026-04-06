"""Tests for LLM exception classes."""
import pytest

from docgap.llm.exceptions import (
    LLMError,
    ConnectionError,
    ModelNotFoundError,
    TimeoutError,
    MalformedResponseError,
    APIError,
    _sanitize_url,
)


class TestSanitizeUrl:
    """Test URL sanitization."""

    def test_sanitize_url_with_credentials(self):
        url = "https://user:pass@example.com/api"
        assert "user" not in _sanitize_url(url)
        assert "pass" not in _sanitize_url(url)
        assert "***" in _sanitize_url(url)

    def test_sanitize_url_without_credentials(self):
        url = "https://example.com/api"
        assert _sanitize_url(url) == url


class TestConnectionError:
    """Test ConnectionError."""

    def test_connection_error(self):
        err = ConnectionError("http://localhost:11434", "Connection refused")
        assert "localhost" in str(err)
        assert err.base_url == "http://localhost:11434"
        assert err.message == "Connection refused"

    def test_connection_error_sanitizes_url(self):
        err = ConnectionError("https://token@host.com/api", "failed")
        assert "token" not in str(err)

    def test_connection_error_truncates_message(self):
        long_msg = "x" * 1000
        err = ConnectionError("http://localhost", long_msg)
        # Message should be truncated to 500 chars
        assert isinstance(err, LLMError)


class TestModelNotFoundError:
    """Test ModelNotFoundError."""

    def test_model_not_found_basic(self):
        err = ModelNotFoundError("test-model")
        assert "test-model" in str(err)
        assert err.model_name == "test-model"
        assert err.available_models == []

    def test_model_not_found_with_available(self):
        err = ModelNotFoundError("test-model", ["model1", "model2"])
        assert "model1" in str(err)
        assert "model2" in str(err)
        assert err.available_models == ["model1", "model2"]


class TestTimeoutError:
    """Test TimeoutError."""

    def test_timeout_error_default(self):
        err = TimeoutError(120)
        assert "120" in str(err)
        assert "inference" in str(err)
        assert err.timeout == 120
        assert err.operation == "inference"

    def test_timeout_error_custom_operation(self):
        err = TimeoutError(60, operation="embedding")
        assert "embedding" in str(err)
        assert err.operation == "embedding"


class TestMalformedResponseError:
    """Test MalformedResponseError."""

    def test_malformed_response_error(self):
        err = MalformedResponseError("raw response data", "missing field")
        assert "missing field" in str(err)
        assert err.raw_response == "raw response data"
        assert err.message == "missing field"

    def test_malformed_response_truncates_raw(self):
        long_response = "x" * 500
        err = MalformedResponseError(long_response, "test")
        assert len(err.raw_response) == 200


class TestAPIError:
    """Test APIError."""

    def test_api_error(self):
        err = APIError(500, "Internal Server Error")
        assert "500" in str(err)
        assert err.status_code == 500
        assert err.response_text == "Internal Server Error"

    def test_api_error_truncates_response(self):
        long_text = "x" * 1000
        err = APIError(500, long_text)
        assert len(err.response_text) == 500


class TestLLMError:
    """Test base LLMError."""

    def test_llm_error_is_exception(self):
        err = LLMError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"

    def test_all_errors_inherit_from_llm_error(self):
        assert issubclass(ConnectionError, LLMError)
        assert issubclass(ModelNotFoundError, LLMError)
        assert issubclass(TimeoutError, LLMError)
        assert issubclass(MalformedResponseError, LLMError)
        assert issubclass(APIError, LLMError)
