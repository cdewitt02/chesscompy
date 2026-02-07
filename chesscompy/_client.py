"""
Low-level HTTP client for the Chess.com public API.

Keeps all network calls in one place so we can add rate-limit handling,
retries, or a custom User-Agent in one spot. The API requires no auth;
see https://www.chess.com/news/view/published-data-api
"""

from __future__ import annotations

import requests

# Chess.com expects a descriptive User-Agent; see their API guidelines
DEFAULT_USER_AGENT = "chesscompy/0.1.0 (Python; Chess.com API extension)"

BASE_URL = "https://api.chess.com/pub"


def get(url: str, *, session: requests.Session | None = None) -> requests.Response:
    """
    GET a Chess.com API URL. Uses a default User-Agent so the API can identify the client.

    :param url: Full URL (e.g. from BASE_URL + path).
    :param session: Optional requests.Session for connection reuse across many calls.
    :return: Response; caller should check response.raise_for_status() or response.ok.
    """
    sess = session or requests
    return sess.get(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT},
        timeout=30,
    )


def games_url(username: str, year: int, month: int) -> str:
    """Build the URL for a player's games in a given year/month."""
    return f"{BASE_URL}/player/{username}/games/{year:04d}/{month:02d}"
