"""
Player stats endpoint: current ratings and W/L records across formats.

The Chess.com API provides a stats endpoint that returns:
  - Current rating ("last") for each time control
  - Best rating achieved ("best") with date and game link
  - Win/loss/draw record for each format

Endpoint: GET /pub/player/{username}/stats

Example response structure:
{
    "chess_rapid": {
        "last": {"rating": 1500, "date": 1704067200, "rd": 50},
        "best": {"rating": 1600, "date": 1701388800, "game": "https://..."},
        "record": {"win": 100, "loss": 50, "draw": 10}
    },
    "chess_blitz": { ... },
    "chess_bullet": { ... },
    ...
}
"""

from __future__ import annotations

from typing import Any

from chesscompy._client import get, stats_url


def get_player_stats(username: str) -> dict[str, Any]:
    """
    Fetch a player's current ratings and W/L records across all formats.

    Returns the raw stats dict from the Chess.com API, which contains
    nested dicts for each time control format the player has used.

    Common formats in the response:
      - chess_rapid: 10+ minute games
      - chess_blitz: 3-10 minute games
      - chess_bullet: <3 minute games
      - chess_daily: correspondence chess
      - tactics: puzzle rating
      - puzzle_rush: puzzle rush stats

    Each game format typically contains:
      - last: Current rating info (rating, date, rd)
      - best: Peak rating info (rating, date, game URL)
      - record: Win/loss/draw counts

    :param username: Chess.com username (case-insensitive).
    :return: Dict mapping format names to their stats.
    :raises PlayerNotFoundError: If the user doesn't exist (404).
    :raises ChessComAPIError: On other API errors (rate limit, server error, etc.).

    Example usage:
        >>> stats = get_player_stats("magnus")
        >>> stats["chess_blitz"]["last"]["rating"]
        3267
        >>> stats["chess_blitz"]["record"]
        {"win": 1234, "loss": 56, "draw": 78}
    """
    url = stats_url(username)
    resp = get(url, context=username)
    return resp.json()
