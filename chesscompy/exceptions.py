"""
Custom exceptions for the chesscompy library.

Provides a hierarchy of errors so callers can handle Chess.com API failures
without importing ``requests`` directly.  Every exception carries the
original ``requests.Response`` (when available) for debugging.

Chess.com API status codes:
    200 — Successful request
    301 — Redirected to a new URL (handled automatically by requests)
    304 — Data not modified since last request (conditional fetch)
    404 — URL malformed or data not available
    410 — Data permanently unavailable
    429 — Rate limit exceeded

Hierarchy:
    ChessComAPIError          — base for all API errors
    ├── PlayerNotFoundError   — 404 on a player endpoint
    ├── DataGoneError         — 410 data permanently unavailable
    └── RateLimitError        — 429 Too Many Requests
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests


class ChessComAPIError(Exception):
    """
    Base exception for Chess.com API errors.

    Wraps the raw ``requests.Response`` so callers can inspect status codes
    or response bodies without depending on the ``requests`` library.
    """

    def __init__(self, message: str, response: requests.Response | None = None) -> None:
        super().__init__(message)
        self.response = response
        self.status_code: int | None = response.status_code if response is not None else None


class PlayerNotFoundError(ChessComAPIError):
    """
    Raised when the Chess.com API returns 404.

    This means the URL is malformed or the requested data is not available.
    When a ``context`` username is provided, the error message includes it.
    """

    def __init__(self, username: str, response: requests.Response | None = None) -> None:
        super().__init__(f"Player not found: '{username}'", response)
        self.username = username


class DataGoneError(ChessComAPIError):
    """
    Raised when the Chess.com API returns 410 Gone.

    This means the requested data is *permanently* unavailable — it
    once existed but has been removed.  Unlike 404, retrying will never
    succeed.
    """

    def __init__(self, url: str, response: requests.Response | None = None) -> None:
        super().__init__(f"Data permanently unavailable (410): {url}", response)
        self.url = url


class RateLimitError(ChessComAPIError):
    """
    Raised when the Chess.com API returns 429 Too Many Requests.

    This means the client has exceeded the API's rate limit.  Callers
    should back off before retrying.  The library retries automatically
    with exponential backoff, so this is only raised after all retries
    are exhausted.
    """

    def __init__(self, response: requests.Response | None = None) -> None:
        super().__init__("Chess.com API rate limit exceeded (429)", response)
