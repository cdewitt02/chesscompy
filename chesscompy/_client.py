"""
Low-level HTTP client for the Chess.com public API.

Keeps all network calls in one place so we can add rate-limit handling,
retries, or a custom User-Agent in one spot. The API requires no auth;
see https://www.chess.com/news/view/published-data-api

Chess.com API response codes:
    200 — Successful request
    301 — Redirected (followed automatically by requests)
    304 — Data not modified since last request
    404 — URL malformed or data not available
    410 — Data permanently unavailable
    429 — Rate limit exceeded

Features:
  - Automatic retries with exponential backoff on 429 (rate limit)
  - Custom exception wrapping: callers get ChessComAPIError subclasses
    instead of raw ``requests.HTTPError``
"""

from __future__ import annotations

import time

import requests

from chesscompy.exceptions import (
    ChessComAPIError,
    DataGoneError,
    PlayerNotFoundError,
    RateLimitError,
)

# Chess.com expects a descriptive User-Agent; see their API guidelines
DEFAULT_USER_AGENT = "chesscompy/0.1.0 (Python; Chess.com API extension)"

BASE_URL = "https://api.chess.com/pub"

# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0  # seconds; doubles each retry (1s, 2s, 4s)

# HTTP status codes that trigger a retry.
# Only 429 is retryable — the Chess.com API does not return 5xx errors.
_RETRYABLE_STATUS_CODES = frozenset({429})


def _raise_for_status(
    resp: requests.Response, *, url: str = "", context: str = ""
) -> None:
    """
    Inspect *resp* and raise an appropriate chesscompy exception on error.

    Maps Chess.com API status codes to our custom exception hierarchy so
    callers never need to handle raw ``requests.HTTPError`` directly.

    :param resp: The HTTP response to check.
    :param url: The request URL (used in DataGoneError messages).
    :param context: Optional string (e.g. a username) for richer error messages.
    :raises PlayerNotFoundError: On 404 when context is provided.
    :raises DataGoneError: On 410 (data permanently unavailable).
    :raises RateLimitError: On 429.
    :raises ChessComAPIError: On any other non-2xx status.
    """
    if resp.ok:
        return

    if resp.status_code == 404 and context:
        raise PlayerNotFoundError(context, response=resp)
    if resp.status_code == 410:
        raise DataGoneError(url or "unknown", response=resp)
    if resp.status_code == 429:
        raise RateLimitError(response=resp)

    # Fallback: wrap any other HTTP error in the base exception
    raise ChessComAPIError(
        f"Chess.com API error {resp.status_code}: {resp.reason}",
        response=resp,
    )


def get(
    url: str,
    *,
    session: requests.Session | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    context: str = "",
) -> requests.Response:
    """
    GET a Chess.com API URL with automatic retries and exception wrapping.

    Retries on 429 (rate limit) with exponential backoff.  All other error
    codes (301, 304, 404, 410) are non-retryable — they either succeed
    immediately, are handled by requests (301 redirect), or raise at once.

    :param url: Full URL (e.g. from BASE_URL + path).
    :param session: Optional requests.Session for connection reuse across many calls.
    :param max_retries: Max retry attempts for 429 rate limits (default 3).
    :param backoff_base: Base delay in seconds; doubles each retry (default 1.0).
    :param context: Optional context string (e.g. username) for better error messages.
    :return: Successful Response (status 2xx).
    :raises PlayerNotFoundError: If the API returns 404 and context is provided.
    :raises DataGoneError: If the API returns 410.
    :raises RateLimitError: If retries are exhausted on 429.
    :raises ChessComAPIError: On any other non-2xx status.
    """
    sess = session or requests
    last_resp: requests.Response | None = None

    for attempt in range(max_retries + 1):
        last_resp = sess.get(
            url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=30,
        )

        # Success — return immediately
        if last_resp.ok:
            return last_resp

        # Non-retryable status — raise immediately (e.g. 404, 410)
        if last_resp.status_code not in _RETRYABLE_STATUS_CODES:
            _raise_for_status(last_resp, url=url, context=context)

        # 429 rate limit — sleep with exponential backoff, then retry
        if attempt < max_retries:
            delay = backoff_base * (2 ** attempt)
            time.sleep(delay)

    # All retries exhausted — raise for the last response we got
    assert last_resp is not None  # at least one attempt was made
    _raise_for_status(last_resp, url=url, context=context)

    # _raise_for_status always raises on non-ok, but mypy doesn't know that
    raise ChessComAPIError("Unexpected: retries exhausted", response=last_resp)  # pragma: no cover


def games_url(username: str, year: int, month: int) -> str:
    """Build the URL for a player's games in a given year/month."""
    return f"{BASE_URL}/player/{username}/games/{year:04d}/{month:02d}"


def stats_url(username: str) -> str:
    """Build the URL for a player's stats (ratings, W/L records)."""
    return f"{BASE_URL}/player/{username}/stats"
