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


# ---------------------------------------------------------------------------
# Loss detection — identify games where a player lost
# ---------------------------------------------------------------------------

# Chess.com result strings that indicate a loss for the player.
# These are the possible values when a player is on the *losing* side.
# Note: "win" means the player won, draws have their own result strings.
LOSS_RESULTS = frozenset({
    "checkmated",    # Lost by checkmate
    "resigned",      # Player resigned
    "timeout",       # Ran out of time (opponent had mating material)
    "abandoned",     # Left the game
    "kingofthehill", # Lost in King of the Hill variant
    "threecheck",    # Lost in Three-Check variant
    "bughousepartnerlose",  # Partner lost in Bughouse
})


def _is_loss(game: dict[str, Any], username: str) -> bool:
    """
    Determine if the given game is a loss for the specified username.

    How it works:
      1. Find which color (white/black) the user played by matching username
      2. Check if that color's result is in the set of losing results

    Chess.com usernames are case-insensitive, so we normalize to lowercase.

    :param game: Game dict from the Chess.com API.
    :param username: The username to check for a loss.
    :return: True if the user lost this game, False otherwise.
    """
    username_lower = username.lower()

    # Each game has 'white' and 'black' dicts with 'username' and 'result'
    white = game.get("white", {})
    black = game.get("black", {})

    # Determine which color the user played (if any)
    if white.get("username", "").lower() == username_lower:
        result = white.get("result", "")
    elif black.get("username", "").lower() == username_lower:
        result = black.get("result", "")
    else:
        # User not in this game
        return False

    return result in LOSS_RESULTS


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
    # context=username gives the error handler enough info for a
    # clear PlayerNotFoundError message on 404
    resp = get(url, context=username)
    data = resp.json()
    return data.get("games", [])


# ---------------------------------------------------------------------------
# Time control filtering — filter games by bullet/blitz/rapid/daily
# ---------------------------------------------------------------------------

# Valid time class values from the Chess.com API
VALID_TIME_CLASSES = frozenset({"bullet", "blitz", "rapid", "daily"})


def _time_class_matches(game: dict[str, Any], time_control: str | None) -> bool:
    """
    Return True if this game's time class matches the requested filter.

    :param game: Game dict from the Chess.com API.
    :param time_control: One of "bullet", "blitz", "rapid", "daily", or None.
                         None means no filter — always returns True.
    :return: True if the game matches (or no filter is set).
    """
    if time_control is None:
        return True
    return game.get("time_class", "").lower() == time_control.lower()


def filter_by_time_control(
    games: list[dict[str, Any]],
    time_control: str,
) -> list[dict[str, Any]]:
    """
    Filter a list of games to only those matching a specific time control.

    Useful when the caller already has a game list (e.g. from get_games_batch)
    and wants to narrow it down without re-fetching.

    :param games: List of game dicts from the Chess.com API.
    :param time_control: One of "bullet", "blitz", "rapid", "daily".
    :return: Filtered list of games matching the time control.
    :raises ValueError: If time_control is not a recognized value.
    """
    tc = time_control.strip().lower()
    if tc not in VALID_TIME_CLASSES:
        raise ValueError(
            f"Invalid time_control '{time_control}'. "
            f"Must be one of: {', '.join(sorted(VALID_TIME_CLASSES))}"
        )
    return [g for g in games if _time_class_matches(g, tc)]


# ---------------------------------------------------------------------------
# Opening filter — match by ECO code or opening name substring
# ---------------------------------------------------------------------------


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
    time_control: str | None = None,
    since: int | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch games across a multi-month date range using concurrent requests.

    Makes one API call per month in the range [start, end] (inclusive),
    running up to *max_workers* requests in parallel via a thread pool.
    Threads are ideal here because each task is I/O-bound (network wait).

    Optional client-side filters are applied *after* all months are fetched:
      - *time_control*: keep only games of a specific type (bullet/blitz/rapid/daily)
      - *since*: keep only games whose ``end_time`` is strictly after this epoch

    **Strict error handling**: if ANY single month's request fails, the
    exception propagates immediately — no partial results are returned.

    :param username:     Chess.com username.
    :param start:        Start date (day ignored; only year/month used).
    :param end:          End date   (day ignored; only year/month used).
    :param max_workers:  Max concurrent API requests (default 5).
    :param time_control: Optional filter — "bullet", "blitz", "rapid", or "daily".
    :param since:        Optional Unix epoch — exclude games with end_time <= since.
    :return: Combined list of game dicts, ordered chronologically by month.
    :raises ValueError:          If start is after end.
    :raises ChessComAPIError:    If any month's API request fails (strict).
    """
    months = _month_range(start, end)

    # Single month: skip thread-pool overhead entirely
    if len(months) == 1:
        y, m = months[0]
        all_games = get_games(username, y, m)
    else:
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
        all_games = []
        for ym in months:
            all_games.extend(results[ym])

    # Apply optional client-side filters
    out = all_games
    if time_control is not None:
        out = [g for g in out if _time_class_matches(g, time_control)]
    if since is not None:
        out = [g for g in out if g.get("end_time", 0) > since]

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


# ---------------------------------------------------------------------------
# Recent losses — fetch games where the user lost (most recent first)
# ---------------------------------------------------------------------------


def get_recent_losses(
    username: str,
    limit: int = 10,
    *,
    max_months: int = 12,
    time_control: str | None = None,
    since: int | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch the user's most recent lost games, up to `limit` games.

    Strategy:
      - Start from the current month and work backwards
      - Fetch one month at a time, filtering for losses
      - Stop as soon as we have `limit` losses (avoids over-fetching)
      - Give up after `max_months` to prevent unbounded API calls

    Optional filters narrow the results further:
      - *time_control*: only include losses from a specific format
        (e.g. "blitz", "rapid") — useful because the SaaS needs different
        Stockfish analysis depths per format.
      - *since*: only include losses whose ``end_time`` is strictly after
        this Unix epoch — enables incremental analysis (skip already-analyzed
        games).

    Results are returned in reverse chronological order — most recent first.
    Games within each month are reversed since the API returns oldest-first.

    :param username: Chess.com username.
    :param limit: Maximum number of losses to return (default 10).
    :param max_months: How many months back to search (default 12).
    :param time_control: Optional filter — "bullet", "blitz", "rapid", or "daily".
    :param since: Optional Unix epoch — exclude games with end_time <= since.
    :return: List of game dicts where the user lost, most recent first.
    :raises ChessComAPIError: If any API request fails.
    """
    losses: list[dict[str, Any]] = []
    today = date.today()
    year, month = today.year, today.month

    # Walk backwards through months until we have enough losses or hit max
    for _ in range(max_months):
        # Fetch all games for this month
        games = get_games(username, year, month)

        # Filter for losses and reverse to get most-recent-first within month
        # (API returns games in chronological order, oldest first)
        month_losses = [g for g in games if _is_loss(g, username)]

        # Apply optional time control filter
        if time_control is not None:
            month_losses = [
                g for g in month_losses if _time_class_matches(g, time_control)
            ]

        # Apply optional "since" filter — skip games already analyzed
        if since is not None:
            month_losses = [
                g for g in month_losses if g.get("end_time", 0) > since
            ]

        month_losses.reverse()

        # Add losses from this month, but don't exceed limit
        for loss in month_losses:
            if len(losses) >= limit:
                break
            losses.append(loss)

        # Stop early if we have enough
        if len(losses) >= limit:
            break

        # Move to previous month
        if month == 1:
            year -= 1
            month = 12
        else:
            month -= 1

    return losses
