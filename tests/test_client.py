"""
Unit tests for the _client module: retry logic and exception wrapping.

All tests mock the network layer so no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from chesscompy._client import get, games_url, stats_url
from chesscompy.exceptions import (
    ChessComAPIError,
    DataGoneError,
    PlayerNotFoundError,
    RateLimitError,
)


# ---------------------------------------------------------------------------
# URL builders — pure unit tests
# ---------------------------------------------------------------------------


class TestUrlBuilders:
    """Verify that URL builder helpers produce correct API paths."""

    def test_games_url(self):
        assert games_url("cdew4", 2026, 1) == (
            "https://api.chess.com/pub/player/cdew4/games/2026/01"
        )

    def test_games_url_pads_month(self):
        """Month should be zero-padded to two digits."""
        assert "/2025/03" in games_url("alice", 2025, 3)

    def test_stats_url(self):
        assert stats_url("cdew4") == (
            "https://api.chess.com/pub/player/cdew4/stats"
        )


# ---------------------------------------------------------------------------
# Exception wrapping — _raise_for_status via get()
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, reason: str = "Error") -> MagicMock:
    """Create a mock requests.Response with the given status code."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.reason = reason
    resp.ok = 200 <= status_code < 300
    return resp


class TestExceptionWrapping:
    """
    Verify that HTTP errors are wrapped into our custom exception hierarchy.

    Chess.com API codes: 200, 301, 304, 404, 410, 429.
    """

    @patch("chesscompy._client.requests")
    def test_404_raises_player_not_found(self, mock_requests):
        """A 404 with a context username should raise PlayerNotFoundError."""
        mock_requests.get.return_value = _mock_response(404, "Not Found")

        with pytest.raises(PlayerNotFoundError, match="alice") as exc_info:
            get("https://api.chess.com/pub/player/alice/stats", context="alice")

        assert exc_info.value.status_code == 404
        assert exc_info.value.username == "alice"

    @patch("chesscompy._client.requests")
    def test_404_without_context_raises_base_error(self, mock_requests):
        """A 404 without context should raise ChessComAPIError (not PlayerNotFound)."""
        mock_requests.get.return_value = _mock_response(404, "Not Found")

        with pytest.raises(ChessComAPIError):
            get("https://api.chess.com/pub/some/endpoint", context="")

    @patch("chesscompy._client.requests")
    def test_410_raises_data_gone(self, mock_requests):
        """A 410 should raise DataGoneError with the request URL."""
        mock_requests.get.return_value = _mock_response(410, "Gone")
        url = "https://api.chess.com/pub/player/olduser/games/2020/01"

        with pytest.raises(DataGoneError, match="410") as exc_info:
            get(url, context="olduser")

        assert exc_info.value.status_code == 410
        assert exc_info.value.url == url

    @patch("chesscompy._client.requests")
    def test_410_is_not_retried(self, mock_requests):
        """410 is permanent — it should raise immediately, not retry."""
        mock_requests.get.return_value = _mock_response(410, "Gone")

        with pytest.raises(DataGoneError):
            get("https://example.com/gone", max_retries=3)

        # Only one attempt — no retries
        assert mock_requests.get.call_count == 1

    @patch("chesscompy._client.requests")
    def test_304_raises_base_error(self, mock_requests):
        """A 304 Not Modified should raise ChessComAPIError (non-retryable)."""
        mock_requests.get.return_value = _mock_response(304, "Not Modified")

        with pytest.raises(ChessComAPIError, match="304"):
            get("https://example.com", max_retries=0)

    @patch("chesscompy._client.requests")
    def test_success_returns_response(self, mock_requests):
        """A 200 response should be returned directly, no exception."""
        mock_resp = _mock_response(200, "OK")
        mock_requests.get.return_value = mock_resp

        result = get("https://example.com")
        assert result is mock_resp


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """
    Verify exponential backoff retry behaviour.

    Only 429 (rate limit) is retryable per the Chess.com API spec.
    All other error codes (304, 404, 410) raise immediately.
    """

    @patch("chesscompy._client.time.sleep")
    @patch("chesscompy._client.requests")
    def test_retries_on_429_then_succeeds(self, mock_requests, mock_sleep):
        """Should retry on 429 and succeed when the next attempt is OK."""
        fail_resp = _mock_response(429, "Too Many Requests")
        ok_resp = _mock_response(200, "OK")

        # First call fails with 429, second succeeds
        mock_requests.get.side_effect = [fail_resp, ok_resp]

        result = get("https://example.com", max_retries=2, backoff_base=0.1)

        assert result is ok_resp
        # Should have slept once (backoff_base * 2^0 = 0.1s)
        mock_sleep.assert_called_once_with(0.1)

    @patch("chesscompy._client.time.sleep")
    @patch("chesscompy._client.requests")
    def test_exhausted_retries_raises_rate_limit(self, mock_requests, mock_sleep):
        """When all retries are exhausted on 429, should raise RateLimitError."""
        fail_resp = _mock_response(429, "Too Many Requests")

        # All attempts fail with 429
        mock_requests.get.return_value = fail_resp

        with pytest.raises(RateLimitError):
            get("https://example.com", max_retries=2, backoff_base=0.01)

        # Should have made 3 total attempts (initial + 2 retries)
        assert mock_requests.get.call_count == 3

    @patch("chesscompy._client.time.sleep")
    @patch("chesscompy._client.requests")
    def test_exponential_backoff_delays(self, mock_requests, mock_sleep):
        """Backoff delays should double each retry: base, base*2, base*4."""
        fail_resp = _mock_response(429, "Too Many Requests")

        # All attempts fail with 429
        mock_requests.get.return_value = fail_resp

        with pytest.raises(RateLimitError):
            get("https://example.com", max_retries=3, backoff_base=1.0)

        # Verify the sleep calls used exponential backoff:
        # attempt 0 -> sleep(1.0), attempt 1 -> sleep(2.0), attempt 2 -> sleep(4.0)
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [1.0, 2.0, 4.0]

    @patch("chesscompy._client.time.sleep")
    @patch("chesscompy._client.requests")
    def test_no_retry_on_404(self, mock_requests, mock_sleep):
        """404 should raise immediately — no retries."""
        fail_resp = _mock_response(404, "Not Found")
        mock_requests.get.return_value = fail_resp

        with pytest.raises(ChessComAPIError):
            get("https://example.com", max_retries=3, backoff_base=0.01)

        assert mock_requests.get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("chesscompy._client.time.sleep")
    @patch("chesscompy._client.requests")
    def test_no_retry_on_410(self, mock_requests, mock_sleep):
        """410 (Gone) is permanent — should raise immediately, no retries."""
        fail_resp = _mock_response(410, "Gone")
        mock_requests.get.return_value = fail_resp

        with pytest.raises(DataGoneError):
            get("https://example.com/gone", max_retries=3, backoff_base=0.01)

        assert mock_requests.get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("chesscompy._client.requests")
    def test_zero_retries_means_single_attempt(self, mock_requests):
        """max_retries=0 should make exactly one attempt on 429."""
        fail_resp = _mock_response(429, "Too Many Requests")
        mock_requests.get.return_value = fail_resp

        with pytest.raises(RateLimitError):
            get("https://example.com", max_retries=0)

        assert mock_requests.get.call_count == 1

    @patch("chesscompy._client.requests")
    def test_session_is_used_when_provided(self, mock_requests):
        """When a session is provided, it should be used instead of requests."""
        mock_session = MagicMock(spec=requests.Session)
        ok_resp = _mock_response(200, "OK")
        mock_session.get.return_value = ok_resp

        result = get("https://example.com", session=mock_session)

        assert result is ok_resp
        mock_session.get.assert_called_once()
        # The module-level requests.get should NOT have been called
        mock_requests.get.assert_not_called()
