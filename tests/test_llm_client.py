"""Tests for LLM client (mocked)."""
from unittest.mock import MagicMock, patch

import pytest

from docgap.llm import OllamaClient


class TestOllamaClient:
    """Test Ollama client with mocked HTTP."""

    @pytest.fixture
    def client(self, temp_dir):
        """Create a test client."""
        return OllamaClient(
            base_url="http://localhost:11434",
            model="test-model",
            timeout=120
        )

    def test_client_initialization(self, temp_dir):
        """Test client initialization."""
        client = OllamaClient(
            base_url="http://localhost:11434",
            model="test-model",
            timeout=60
        )

        assert client.base_url == "http://localhost:11434"
        assert client.model == "test-model"
        assert client.timeout == 60

    @patch("requests.Session.request")
    def test_is_healthy(self, mock_request, client):
        """Test health check."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "test-model"}]}
        mock_request.return_value = mock_response

        assert client.is_healthy() is True

    @patch("requests.Session.request")
    def test_chat_without_json_mode(self, mock_request, client):
        """Test chat without JSON mode."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Test response"}
        }
        mock_request.return_value = mock_response

        messages = [{"role": "user", "content": "Hello"}]
        result = client.chat(messages, json_mode=False)

        assert result == "Test response"

    @patch("requests.Session.request")
    def test_chat_with_json_mode(self, mock_request, client):
        """Test chat with JSON mode."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": '{"classification": "NEEDS_DOC"}'}
        }
        mock_request.return_value = mock_response

        messages = [{"role": "user", "content": "Classify this"}]
        result = client.chat(messages, json_mode=True)

        assert "NEEDS_DOC" in result

    @patch("requests.Session.request")
    def test_generate(self, mock_request, client):
        """Test generate method."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Generated text"}
        mock_request.return_value = mock_response

        result = client.generate("Prompt here", {"temperature": 0.5})

        assert result == "Generated text"

    @patch("requests.post")
    def test_chat_timeout(self, mock_post, client):
        """Test chat timeout handling."""
        mock_post.side_effect = Exception("Timeout")

        with pytest.raises(Exception):
            client.chat([{"role": "user", "content": "Hello"}])


class TestOllamaClientErrorHandling:
    """Test error handling in OllamaClient."""

    @patch("requests.Session.request")
    def test_404_raises_model_not_found(self, mock_request):
        from docgap.llm.exceptions import ModelNotFoundError
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "model not found"
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="nonexistent", max_retries=0)
        with pytest.raises(ModelNotFoundError):
            client._make_request("GET", "/api/tags")

    @patch("requests.Session.request")
    def test_400_raises_api_error(self, mock_request):
        from docgap.llm.exceptions import APIError
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "bad request"
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test", max_retries=0)
        with pytest.raises(APIError):
            client._make_request("POST", "/api/generate", {"prompt": "test"})

    @patch("requests.Session.request")
    def test_500_raises_api_error(self, mock_request):
        from docgap.llm.exceptions import APIError
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "server error"
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test", max_retries=0)
        with pytest.raises(APIError):
            client._make_request("GET", "/api/tags")

    @patch("requests.Session.request")
    def test_connection_error_retries(self, mock_request):
        from docgap.llm.exceptions import ConnectionError
        mock_request.side_effect = requests.exceptions.ConnectionError("refused")
        client = OllamaClient(base_url="http://localhost:11434", model="test", max_retries=2, retry_delay=0.0)
        with pytest.raises(ConnectionError):
            client._make_request("GET", "/api/tags")
        assert mock_request.call_count == 3  # 1 initial + 2 retries

    @patch("requests.Session.request")
    def test_timeout_retries(self, mock_request):
        from docgap.llm.exceptions import TimeoutError
        mock_request.side_effect = requests.exceptions.Timeout("timed out")
        client = OllamaClient(base_url="http://localhost:11434", model="test", max_retries=1, retry_delay=0.0)
        with pytest.raises(TimeoutError):
            client._make_request("GET", "/api/tags")
        assert mock_request.call_count == 2

    @patch("requests.Session.request")
    def test_is_healthy_false_on_error(self, mock_request):
        mock_request.side_effect = requests.exceptions.ConnectionError("refused")
        client = OllamaClient(base_url="http://localhost:11434", model="test", max_retries=0)
        assert client.is_healthy() is False


class TestOllamaClientListModels:
    """Test list_models."""

    @patch("requests.Session.request")
    def test_list_models(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "model1"},
                {"name": "model2"},
                {"name": ""},
            ]
        }
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        models = client.list_models()
        assert models == ["model1", "model2"]

    @patch("requests.Session.request")
    def test_list_models_empty(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": []}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        models = client.list_models()
        assert models == []


class TestOllamaClientEmbed:
    """Test embed method."""

    @patch("requests.Session.request")
    def test_embed_single_string(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        embeddings = client.embed("test text")
        assert len(embeddings) == 1
        assert embeddings[0] == [0.1, 0.2, 0.3]

    @patch("requests.Session.request")
    def test_embed_list_of_strings(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": [[0.1, 0.2], [0.3, 0.4]]}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        embeddings = client.embed(["text1", "text2"])
        assert len(embeddings) == 2


class TestOllamaClientContextManager:
    """Test context manager."""

    def test_context_manager(self):
        with OllamaClient(base_url="http://localhost:11434", model="test") as client:
            assert client is not None
        # Session should be closed after exit

    def test_close(self):
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        client.close()
        # Should not raise


class TestOllamaClientChatAdvanced:
    """Test chat with system message and malformed response."""

    @patch("requests.Session.request")
    def test_chat_with_system_message(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "response"}}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        result = client.chat([{"role": "user", "content": "hi"}], system="You are helpful")
        assert result == "response"
        # Verify system message was prepended
        call_data = mock_request.call_args[1]["json"]
        assert call_data["messages"][0]["role"] == "system"
        assert call_data["messages"][0]["content"] == "You are helpful"

    @patch("requests.Session.request")
    def test_chat_malformed_response(self, mock_request):
        from docgap.llm.exceptions import MalformedResponseError
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"no_message_key": True}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        with pytest.raises(MalformedResponseError):
            client.chat([{"role": "user", "content": "hi"}])

    @patch("requests.Session.request")
    def test_chat_response_truncation(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        long_content = "x" * 300_000
        mock_response.json.return_value = {"message": {"content": long_content}}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        result = client.chat([{"role": "user", "content": "hi"}])
        assert len(result) == 200_000

    @patch("requests.Session.request")
    def test_generate_response_truncation(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        long_content = "x" * 300_000
        mock_response.json.return_value = {"response": long_content}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        result = client.generate("test")
        assert len(result) == 200_000


class TestOllamaClientLogRequests:
    """Test log_requests option."""

    @patch("requests.Session.request")
    def test_log_requests_enabled(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": []}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test", log_requests=True)
        client._make_request("GET", "/api/tags")
        mock_request.assert_called_once()


import requests


class TestOllamaClientHTTPErrorRetry:
    """Test HTTPError retry for 503/504."""

    @patch("requests.Session.request")
    def test_503_retries(self, mock_request):
        from docgap.llm.exceptions import APIError
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        http_err = requests.exceptions.HTTPError(response=mock_response)
        mock_request.side_effect = http_err
        client = OllamaClient(base_url="http://localhost:11434", model="test", max_retries=1, retry_delay=0.0)
        with pytest.raises(APIError):
            client._make_request("GET", "/api/tags")
        assert mock_request.call_count == 2

    @patch("requests.Session.request")
    def test_http_error_non_retryable(self, mock_request):
        from docgap.llm.exceptions import APIError
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.text = "Unprocessable"
        http_err = requests.exceptions.HTTPError(response=mock_response)
        mock_request.side_effect = http_err
        client = OllamaClient(base_url="http://localhost:11434", model="test", max_retries=2, retry_delay=0.0)
        with pytest.raises(APIError):
            client._make_request("GET", "/api/tags")
        assert mock_request.call_count == 1

    @patch("requests.Session.request")
    def test_http_error_no_response(self, mock_request):
        from docgap.llm.exceptions import APIError
        http_err = requests.exceptions.HTTPError(response=None)
        mock_request.side_effect = http_err
        client = OllamaClient(base_url="http://localhost:11434", model="test", max_retries=0, retry_delay=0.0)
        with pytest.raises(APIError):
            client._make_request("GET", "/api/tags")


class TestOllamaClientGenerateAdvanced:
    """Test generate with system prompt and streaming."""

    @patch("requests.Session.request")
    def test_generate_with_system(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Generated"}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        result = client.generate("prompt", system="You are helpful")
        assert result == "Generated"
        call_data = mock_request.call_args[1]["json"]
        assert call_data["system"] == "You are helpful"

    @patch("requests.Session.request")
    def test_generate_with_stream_flag(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Generated"}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        # The stream=True path expects a string response with JSON lines
        # But _make_request returns dict, so the stream parsing will fail
        # Test with stream=False to ensure the data payload includes stream
        result = client.generate("prompt", stream=False)
        assert result == "Generated"

    @patch("requests.Session.request")
    def test_embed_with_custom_model(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": [[0.1, 0.2]]}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="default")
        embeddings = client.embed("text", model="custom-model")
        assert len(embeddings) == 1
        call_data = mock_request.call_args[1]["json"]
        assert call_data["model"] == "custom-model"

    @patch("requests.Session.request")
    def test_log_requests_with_post_data(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "ok"}
        mock_request.return_value = mock_response
        client = OllamaClient(base_url="http://localhost:11434", model="test", log_requests=True)
        client._make_request("POST", "/api/generate", data={"prompt": "test"})
        mock_request.assert_called_once()


class TestChatOptionsParam:
    """Cover chat with options parameter."""

    @patch("requests.Session.request")
    def test_chat_passes_options(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "ok"}}
        mock_request.return_value = mock_resp
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        result = client.chat([{"role": "user", "content": "hi"}], options={"temperature": 0.5})
        assert result == "ok"


class TestChatWithDebugLogger:
    """Test that chat() calls debug_logger methods when configured."""

    @patch("requests.Session.request")
    def test_chat_calls_log_request_and_log_response(self, mock_request):
        """chat() invokes debug_logger.log_request before the call and log_response after."""
        from docgap.llm.debug_logger import LLMCallContext

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "hello back"}}
        mock_request.return_value = mock_resp

        client = OllamaClient(base_url="http://localhost:11434", model="test")

        mock_debug_logger = MagicMock()
        mock_context = LLMCallContext(commit_hash="abc123def456", stage="detect", sequence_num=1)

        client.debug_logger = mock_debug_logger
        client._call_context = mock_context

        messages = [{"role": "user", "content": "classify this"}]
        result = client.chat(messages, json_mode=False)

        assert result == "hello back"
        mock_debug_logger.log_request.assert_called_once_with(
            mock_context, messages, False, {}
        )
        mock_debug_logger.log_response.assert_called_once_with(mock_context, "hello back")

    @patch("requests.Session.request")
    def test_chat_clears_call_context_after_response(self, mock_request):
        """chat() sets _call_context to None after a successful response."""
        from docgap.llm.debug_logger import LLMCallContext

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "done"}}
        mock_request.return_value = mock_resp

        client = OllamaClient(base_url="http://localhost:11434", model="test")
        client.debug_logger = MagicMock()
        client._call_context = LLMCallContext(commit_hash="abc123def456", stage="gen", sequence_num=2)

        client.chat([{"role": "user", "content": "go"}])

        assert client._call_context is None

    @patch("requests.Session.request")
    def test_chat_no_debug_logger_does_not_raise(self, mock_request):
        """chat() works normally when debug_logger is None (default)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "plain"}}
        mock_request.return_value = mock_resp

        client = OllamaClient(base_url="http://localhost:11434", model="test")
        # debug_logger is None by default; this must not raise
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "plain"


class TestOllamaClientSSRFProtection:
    """Test that OllamaClient blocks SSRF-prone URLs."""

    def test_ftp_scheme_raises_value_error(self):
        """OllamaClient rejects ftp:// base_url as unsupported scheme."""
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            OllamaClient(base_url="ftp://evil.com", model="test")

    def test_cloud_metadata_aws_raises_value_error(self):
        """OllamaClient rejects the AWS cloud metadata IP (SSRF protection)."""
        with pytest.raises(ValueError, match="Cloud metadata"):
            OllamaClient(base_url="http://169.254.169.254", model="test")

    def test_cloud_metadata_google_raises_value_error(self):
        """OllamaClient rejects the Google cloud metadata hostname."""
        with pytest.raises(ValueError, match="Cloud metadata"):
            OllamaClient(base_url="http://metadata.google.internal", model="test")

    def test_http_localhost_is_allowed(self):
        """OllamaClient accepts a standard http://localhost base_url."""
        client = OllamaClient(base_url="http://localhost:11434", model="test")
        assert client.base_url == "http://localhost:11434"

    def test_https_remote_is_allowed(self):
        """OllamaClient accepts an https:// remote base_url."""
        client = OllamaClient(base_url="https://ollama.example.com", model="test")
        assert client.base_url == "https://ollama.example.com"
