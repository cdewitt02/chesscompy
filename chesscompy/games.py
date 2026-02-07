"""
Games endpoint: fetch by month (Chess.com API) and by opening (client-side filter).

The official API only supports: GET /player/{username}/games/{YYYY}/{MM}.
To support "by opening" we fetch one or more months and filter by ECO/opening.
"""

from __future__ import annotations

from typing import Any

from chesscompy._client import get, games_url


def get_games(username: str, year: int, month: int) -> list[dict[str, Any]]:
    """
    Fetch all games for a player in a given month (direct Chess.com API).

    :param username: Chess.com username.
    :param year: Year (e.g. 2026).
    :param month: Month 1–12.
    :return: List of game dicts (same structure as API response).
    :raises requests.HTTPError: On 4xx/5xx from the API.
    """
    url = games_url(username, year, month)
    resp = get(url)
    resp.raise_for_status()
    data = resp.json()
    return data.get("games", [])


def _eco_matches(game: dict[str, Any], opening: str) -> bool:
    """
    Return True if this game's opening matches the given opening spec.

    opening can be:
    - ECO code (e.g. "B07", "B10") — matched against PGN [ECO] or eco URL.
    - Substring of the opening URL (e.g. "Pirc-Defense", "Caro-Kann").
    """
    opening = opening.strip()
    if not opening:
        return True

    eco_url = (game.get("eco") or "").lower()
    pgn = game.get("pgn") or ""
    key = opening.lower()

    # ECO codes are one letter + two digits (e.g. A00, B07); match as code if so
    if len(opening) == 3 and opening[0].isalpha() and opening[1:].isdigit():
        code = opening.upper()
        if f'[ECO "{code}"' in pgn or f'[ECO \"{code}\"]' in pgn:
            return True
        # URL often contains ECO in path
        if code.lower() in eco_url:
            return True

    # Otherwise treat as substring of opening name/URL
    return key in eco_url


def get_games_by_opening(
    username: str,
    opening: str,
    year: int,
    month: int | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch games for a player that match the given opening (client-side filter).

    Uses the same API as get_games; then filters by ECO code or opening name.
    opening can be an ECO code (e.g. "B07") or a substring of the opening URL
    (e.g. "Pirc-Defense", "Caro-Kann").

    :param username: Chess.com username.
    :param opening: ECO code (e.g. "B07") or opening name substring.
    :param year: Year to fetch.
    :param month: If given, only that month; if None, all 12 months (12 API calls).
    :return: List of game dicts matching the opening.
    """
    if month is not None:
        months = [(year, month)]
    else:
        months = [(year, m) for m in range(1, 13)]

    out: list[dict[str, Any]] = []
    for y, m in months:
        games = get_games(username, y, m)
        for g in games:
            if _eco_matches(g, opening):
                out.append(g)
    return out
