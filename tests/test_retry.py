"""Tests for retry decorator with exponential backoff."""
from unittest.mock import patch, MagicMock

import pytest

from docgap.llm.retry import retry_with_backoff, exponential_backoff_delay
from docgap.llm.exceptions import ConnectionError


def make_connection_error():
    return ConnectionError(base_url="http://localhost:11434", message="refused")


def test_succeeds_on_first_try():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.0)
    def always_succeeds():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = always_succeeds()
    assert result == "ok"
    assert call_count == 1


def test_retries_on_connection_error_then_succeeds():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.0)
    def fails_once():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise make_connection_error()
        return "recovered"

    with patch("docgap.llm.retry.time.sleep"):
        result = fails_once()

    assert result == "recovered"
    assert call_count == 2


def test_exhausts_all_retries_raises_last_exception():
    @retry_with_backoff(max_retries=2, base_delay=0.0)
    def always_fails():
        raise make_connection_error()

    with patch("docgap.llm.retry.time.sleep"):
        with pytest.raises(ConnectionError):
            always_fails()


def test_exhausts_retries_calls_function_correct_number_of_times():
    call_count = 0

    @retry_with_backoff(max_retries=2, base_delay=0.0)
    def always_fails():
        nonlocal call_count
        call_count += 1
        raise make_connection_error()

    with patch("docgap.llm.retry.time.sleep"):
        with pytest.raises(ConnectionError):
            always_fails()

    # max_retries=2 means 1 initial attempt + 2 retries = 3 total
    assert call_count == 3


def test_non_connection_error_not_retried():
    call_count = 0

    @retry_with_backoff(max_retries=3, base_delay=0.0)
    def raises_value_error():
        nonlocal call_count
        call_count += 1
        raise ValueError("not a connection error")

    with pytest.raises(ValueError):
        raises_value_error()

    assert call_count == 1


def test_backoff_delay_increases_between_retries():
    sleep_calls = []

    @retry_with_backoff(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
    def always_fails():
        raise make_connection_error()

    with patch("docgap.llm.retry.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
        with pytest.raises(ConnectionError):
            always_fails()

    # Should sleep 3 times (after each of the first 3 failures, not after the last)
    assert len(sleep_calls) == 3
    # Each delay should be larger than the previous
    assert sleep_calls[1] > sleep_calls[0]
    assert sleep_calls[2] > sleep_calls[1]


def test_backoff_delay_capped_at_max_delay():
    sleep_calls = []

    @retry_with_backoff(max_retries=5, base_delay=10.0, max_delay=15.0, backoff_multiplier=3.0)
    def always_fails():
        raise make_connection_error()

    with patch("docgap.llm.retry.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
        with pytest.raises(ConnectionError):
            always_fails()

    assert all(d <= 15.0 for d in sleep_calls)


def test_exponential_backoff_delay_calculation():
    # attempt 0: 1.0 * 2^0 = 1.0
    assert exponential_backoff_delay(0, base_delay=1.0, backoff_multiplier=2.0) == 1.0
    # attempt 1: 1.0 * 2^1 = 2.0
    assert exponential_backoff_delay(1, base_delay=1.0, backoff_multiplier=2.0) == 2.0
    # attempt 2: 1.0 * 2^2 = 4.0
    assert exponential_backoff_delay(2, base_delay=1.0, backoff_multiplier=2.0) == 4.0


def test_exponential_backoff_delay_respects_max():
    result = exponential_backoff_delay(10, base_delay=1.0, max_delay=5.0, backoff_multiplier=2.0)
    assert result == 5.0


def test_retry_preserves_return_value_after_retry():
    call_count = 0

    @retry_with_backoff(max_retries=2, base_delay=0.0)
    def fails_twice_then_returns_42():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise make_connection_error()
        return 42

    with patch("docgap.llm.retry.time.sleep"):
        result = fails_twice_then_returns_42()

    assert result == 42


def test_non_connection_error_raised_immediately_no_sleep():
    """Non-ConnectionError exceptions skip retry and raise immediately."""
    sleep_calls = []

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def raises_type_error():
        raise TypeError("not a connection error")

    with patch("docgap.llm.retry.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
        with pytest.raises(TypeError):
            raises_type_error()

    assert len(sleep_calls) == 0


def test_retry_function_preserves_name():
    """retry_with_backoff preserves the decorated function's name."""
    @retry_with_backoff(max_retries=1)
    def my_named_function():
        return "ok"

    assert my_named_function.__name__ == "my_named_function"
