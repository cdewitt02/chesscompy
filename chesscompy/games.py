"""
Games endpoint: fetch by month (Chess.com API) and by opening (client-side filter).

The official API only supports: GET /player/{username}/games/{YYYY}/{MM}.
To support "by opening" we fetch one or more months and filter by ECO/opening.
Batch operations allow fetching across multi-month date ranges concurrently.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
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


# ---------------------------------------------------------------------------
# Batch operations — multi-month date ranges with concurrent fetching
# ---------------------------------------------------------------------------


def _month_range(start: date, end: date) -> list[tuple[int, int]]:
    """
    Generate all (year, month) pairs from *start* to *end*, inclusive.

    Day-of-month is ignored — only the year and month parts are used.
    This means date(2025, 10, 31) and date(2025, 10, 1) are equivalent.

    :param start: Start date (day ignored; only year/month matter).
    :param end:   End date   (day ignored; only year/month matter).
    :return: List of (year, month) tuples in chronological order.
    :raises ValueError: If start month is after end month.
    """
    # Compare as (year, month) tuples so the day component is irrelevant
    start_ym = (start.year, start.month)
    end_ym = (end.year, end.month)

    if start_ym > end_ym:
        raise ValueError(
            f"start ({start.year}-{start.month:02d}) is after "
            f"end ({end.year}-{end.month:02d})"
        )

    # Walk month-by-month from start to end
    months: list[tuple[int, int]] = []
    year, month = start_ym
    while (year, month) <= end_ym:
        months.append((year, month))
        # Roll over from December to January of next year
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    return months


def get_games_batch(
    username: str,
    start: date,
    end: date,
    *,
    max_workers: int = 5,
) -> list[dict[str, Any]]:
    """
    Fetch games across a multi-month date range using concurrent requests.

    Makes one API call per month in the range [start, end] (inclusive),
    running up to *max_workers* requests in parallel via a thread pool.
    Threads are ideal here because each task is I/O-bound (network wait).

    **Strict error handling**: if ANY single month's request fails, the
    exception propagates immediately — no partial results are returned.
    This uses ``future.result()`` which re-raises worker-thread exceptions
    on the calling thread.

    :param username:    Chess.com username.
    :param start:       Start date (day ignored; only year/month used).
    :param end:         End date   (day ignored; only year/month used).
    :param max_workers: Max concurrent API requests. Chess.com may rate-limit
                        aggressive clients; 5 is a safe default.
    :return: Combined list of game dicts, ordered chronologically by month.
    :raises ValueError:          If start is after end.
    :raises requests.HTTPError:  If any month's API request fails (strict).
    """
    months = _month_range(start, end)

    # Single month: skip thread-pool overhead entirely
    if len(months) == 1:
        y, m = months[0]
        return get_games(username, y, m)

    # Fan out one request per month across the thread pool
    results: dict[tuple[int, int], list[dict[str, Any]]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all months at once — the pool caps concurrency at max_workers
        future_to_month = {
            executor.submit(get_games, username, y, m): (y, m)
            for y, m in months
        }

        # Collect results as they complete (order doesn't matter yet)
        for future in as_completed(future_to_month):
            month_key = future_to_month[future]
            # .result() re-raises any exception the worker hit.
            # In strict mode this means one bad month kills the whole batch.
            results[month_key] = future.result()

    # Reassemble in chronological order — as_completed returns in *finish*
    # order, not submission order, so we iterate over the original month list.
    out: list[dict[str, Any]] = []
    for ym in months:
        out.extend(results[ym])
    return out


def get_games_batch_by_opening(
    username: str,
    opening: str,
    start: date,
    end: date,
    *,
    max_workers: int = 5,
) -> list[dict[str, Any]]:
    """
    Fetch games across a date range and filter by opening — concurrently.

    Composes two existing pieces:
      1. get_games_batch  — concurrent multi-month fetch
      2. _eco_matches     — client-side opening filter

    The filtering happens locally *after* all months have been fetched,
    so the network calls are fully parallelized and the filter adds
    negligible overhead (it's just string matching on already-fetched data).

    :param username:    Chess.com username.
    :param opening:     ECO code (e.g. "B07") or opening name substring
                        (e.g. "Pirc-Defense", "Caro-Kann"). Empty string
                        matches all games (no filter applied).
    :param start:       Start date (day ignored; only year/month used).
    :param end:         End date   (day ignored; only year/month used).
    :param max_workers: Max concurrent API requests (default 5).
    :return: Filtered list of game dicts, in chronological month order.
    :raises ValueError:          If start is after end.
    :raises requests.HTTPError:  If any month's API request fails (strict).
    """
    all_games = get_games_batch(username, start, end, max_workers=max_workers)
    # Filter locally — _eco_matches handles empty/whitespace opening gracefully
    return [g for g in all_games if _eco_matches(g, opening)]
