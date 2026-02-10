"""
Integration tests for the stats module against the live Chess.com API.

Tests use real data from user "cdew4" (same as test_games.py).
The API is public and requires no authentication.

Design notes:
  - The ``stats`` fixture is module-scoped so we make ONE API call and
    reuse the response across every test.
  - Tests verify structure and data types rather than specific values,
    since ratings change over time.
"""

import pytest

from chesscompy.exceptions import PlayerNotFoundError
from chesscompy.stats import get_player_stats


# ---------------------------------------------------------------------------
# Constants — single source of truth for test user
# ---------------------------------------------------------------------------

USERNAME = "cdew4"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stats():
    """
    Fetch stats for the test user from the live Chess.com API.

    Module-scoped so the API is only called once; every test in this file
    shares the same response data.
    """
    return get_player_stats(USERNAME)


# ---------------------------------------------------------------------------
# Structure and type tests
# ---------------------------------------------------------------------------


def test_returns_dict(stats):
    """get_player_stats should return a dictionary."""
    assert isinstance(stats, dict)


def test_contains_at_least_one_format(stats):
    """
    The stats dict should contain at least one time control format.

    Common formats: chess_rapid, chess_blitz, chess_bullet, chess_daily.
    An active player should have stats in at least one format.
    """
    known_formats = {
        "chess_rapid", "chess_blitz", "chess_bullet", "chess_daily",
        "tactics", "lessons", "puzzle_rush",
    }
    found_formats = set(stats.keys()) & known_formats
    assert len(found_formats) > 0, (
        f"Expected at least one known format in stats, got keys: {list(stats.keys())}"
    )


def test_rating_format_has_last_rating(stats):
    """
    Each game format (rapid/blitz/bullet/daily) should have a 'last' dict
    with at least a 'rating' field representing current rating.
    """
    game_formats = ["chess_rapid", "chess_blitz", "chess_bullet", "chess_daily"]

    # Find at least one game format the user has played
    found_format = None
    for fmt in game_formats:
        if fmt in stats:
            found_format = fmt
            break

    if found_format is None:
        pytest.skip(f"User {USERNAME} has no game format stats to test")

    format_stats = stats[found_format]
    assert "last" in format_stats, f"'{found_format}' missing 'last' field"
    assert "rating" in format_stats["last"], f"'{found_format}.last' missing 'rating'"
    assert isinstance(format_stats["last"]["rating"], int), "Rating should be an integer"


def test_rating_format_has_record(stats):
    """
    Each game format should have a 'record' dict with win/loss/draw counts.
    """
    game_formats = ["chess_rapid", "chess_blitz", "chess_bullet", "chess_daily"]

    found_format = None
    for fmt in game_formats:
        if fmt in stats:
            found_format = fmt
            break

    if found_format is None:
        pytest.skip(f"User {USERNAME} has no game format stats to test")

    format_stats = stats[found_format]
    assert "record" in format_stats, f"'{found_format}' missing 'record' field"

    record = format_stats["record"]
    assert "win" in record, "record missing 'win' field"
    assert "loss" in record, "record missing 'loss' field"
    assert "draw" in record, "record missing 'draw' field"

    # All should be non-negative integers
    assert isinstance(record["win"], int) and record["win"] >= 0
    assert isinstance(record["loss"], int) and record["loss"] >= 0
    assert isinstance(record["draw"], int) and record["draw"] >= 0


def test_rating_is_reasonable(stats):
    """
    Ratings should be within a reasonable range (typically 100-3500).

    This is a sanity check to ensure we're parsing the data correctly.
    """
    game_formats = ["chess_rapid", "chess_blitz", "chess_bullet", "chess_daily"]

    for fmt in game_formats:
        if fmt in stats and "last" in stats[fmt]:
            rating = stats[fmt]["last"].get("rating")
            if rating is not None:
                assert 100 <= rating <= 3500, (
                    f"Rating {rating} for {fmt} outside reasonable range"
                )


# ---------------------------------------------------------------------------
# Best rating tests (optional field)
# ---------------------------------------------------------------------------


def test_best_rating_when_present(stats):
    """
    If a format has a 'best' field, it should contain rating and date.
    """
    game_formats = ["chess_rapid", "chess_blitz", "chess_bullet", "chess_daily"]

    for fmt in game_formats:
        if fmt in stats and "best" in stats[fmt]:
            best = stats[fmt]["best"]
            assert "rating" in best, f"'{fmt}.best' missing 'rating'"
            assert "date" in best, f"'{fmt}.best' missing 'date'"
            # Best rating should be >= current rating (or close to it)
            assert isinstance(best["rating"], int)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_nonexistent_user_raises():
    """
    Querying for a nonexistent user should raise PlayerNotFoundError (404).
    """
    with pytest.raises(PlayerNotFoundError):
        get_player_stats("this-user-definitely-does-not-exist-xyz-999")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_username_case_insensitive():
    """
    Chess.com usernames are case-insensitive; different casings should work.

    We make separate API calls to verify the API accepts different cases.
    """
    # These should all return valid stats (same user)
    stats_lower = get_player_stats(USERNAME.lower())
    stats_upper = get_player_stats(USERNAME.upper())

    # Both should be valid dicts with some content
    assert isinstance(stats_lower, dict)
    assert isinstance(stats_upper, dict)
    assert len(stats_lower) > 0
    assert len(stats_upper) > 0
