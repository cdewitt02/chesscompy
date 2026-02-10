"""
Integration tests for the games module against the live Chess.com API.

All tests use real data from January 2026 for user "cdew".
The API is public and requires no authentication.

Design notes:
  - The ``games`` fixture is module-scoped so we make ONE API call and
    reuse the response across every test that only needs the raw game list.
  - Helper functions (_extract_eco_code, _extract_opening_name) pull test
    data dynamically from the response so test names stay data-agnostic.
  - Two tests exercise get_games_by_opening end-to-end (extra API calls).
  - _month_range tests are pure unit tests (no network calls).
  - get_games_batch tests hit the live API with a small range.
"""

import re
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest
import requests

from chesscompy.exceptions import ChessComAPIError, PlayerNotFoundError
from chesscompy.games import (
    _eco_matches,
    _is_loss,
    _month_range,
    _time_class_matches,
    filter_by_time_control,
    get_games,
    get_games_batch,
    get_games_by_opening,
    get_recent_losses,
)

# ---------------------------------------------------------------------------
# Constants — single source of truth for test user and period
# ---------------------------------------------------------------------------

USERNAME = "cdew4"
YEAR = 2026
MONTH = 1


# ---------------------------------------------------------------------------
# Helpers (not tests) — extract test data from real API responses
# ---------------------------------------------------------------------------


def _extract_eco_code(game: dict[str, Any]) -> str | None:
    """
    Pull the 3-character ECO code (e.g. "B07") from a game's PGN header.

    Returns None if the PGN doesn't contain an [ECO "..."] tag.
    """
    match = re.search(r'\[ECO "([A-E]\d{2})"\]', game.get("pgn", ""))
    return match.group(1) if match else None


def _extract_opening_name(game: dict[str, Any]) -> str | None:
    """
    Extract the opening family name from the game's eco URL.

    Chess.com eco URLs look like:
        https://www.chess.com/openings/Pirc-Defense-Austrian-Attack-...
    We grab the first two hyphenated words (e.g. "Pirc-Defense") which
    usually identifies the opening family broadly enough for filtering.

    Falls back to a single word if no hyphen is found.
    """
    eco_url = game.get("eco", "")
    # Try two-word opening name first (e.g. "Pirc-Defense", "Caro-Kann")
    match = re.search(r"/openings/([A-Za-z]+-[A-Za-z]+)", eco_url)
    if match:
        return match.group(1)
    # Fallback: single-word opening name (e.g. "Sicilian")
    match = re.search(r"/openings/([A-Za-z]+)", eco_url)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def games():
    """
    Fetch all games for the test user/month from the live Chess.com API.

    Module-scoped so the API is only called once; every test in this file
    shares the same response data.
    """
    return get_games(USERNAME, YEAR, MONTH)


# ---------------------------------------------------------------------------
# Fetch / structural tests
# ---------------------------------------------------------------------------


def test_fetch_returns_nonempty_list(games):
    """The API should return at least one game for the test period."""
    assert len(games) > 0, "Expected at least one game from the API"


def test_all_games_have_required_fields(games):
    """Every game dict should have the fields our library depends on.

    Note: 'eco' is NOT present on every game — bot games and some variants
    omit it.  We only assert it's well-formed when it *is* present.
    The 'url' and 'pgn' fields are universal.
    """
    games_with_eco = 0
    for i, g in enumerate(games):
        assert "pgn" in g, f"Game {i} missing 'pgn' field"
        assert "url" in g, f"Game {i} missing 'url' field"
        # eco is optional — but when present it should be a valid URL
        if "eco" in g:
            games_with_eco += 1
            assert g["eco"].startswith("https://"), (
                f"Game {i} has unexpected eco value: {g['eco']!r}"
            )
    # Sanity check: most games should still have eco
    assert games_with_eco > 0, "Expected at least some games to have an 'eco' field"


# ---------------------------------------------------------------------------
# _eco_matches — ECO code filtering
# ---------------------------------------------------------------------------


def test_eco_code_filter_finds_matching_games(games):
    """
    Filtering by an ECO code found in the dataset should return at least
    one game, and every matched game should actually reference that code
    in its PGN header or eco URL.
    """
    # Dynamically extract an ECO code from the first game
    eco_code = _extract_eco_code(games[0])
    assert eco_code is not None, "Could not extract ECO code from first game's PGN"

    matched = [g for g in games if _eco_matches(g, eco_code)]
    assert len(matched) > 0, f"No games matched ECO code '{eco_code}'"

    # Every match should genuinely reference this ECO code
    for g in matched:
        eco_url = g.get("eco", "").lower()
        pgn = g.get("pgn", "")
        assert (
            eco_code.lower() in eco_url
            or f'[ECO "{eco_code.upper()}"]' in pgn
        ), (
            f"Game {g['url']} matched '{eco_code}' but doesn't reference it "
            f"in eco URL or PGN"
        )


def test_eco_code_filter_rejects_fabricated_code(games):
    """A fabricated ECO code (Z99) should not match any games."""
    matched = [g for g in games if _eco_matches(g, "Z99")]
    assert len(matched) == 0, "Fabricated ECO code should match nothing"


# ---------------------------------------------------------------------------
# _eco_matches — opening name substring filtering
# ---------------------------------------------------------------------------


def test_name_filter_finds_games_for_known_opening(games):
    """
    Filtering by an opening name extracted from the dataset should return
    at least one game.
    """
    opening_name = _extract_opening_name(games[0])
    assert opening_name is not None, "Could not extract opening name from first game"

    matched = [g for g in games if _eco_matches(g, opening_name)]
    assert len(matched) > 0, f"No games matched opening name '{opening_name}'"


def test_name_filter_produces_no_false_positives(games):
    """
    Every game matched by an opening name substring should actually
    contain that substring in its eco URL (case-insensitive).
    """
    opening_name = _extract_opening_name(games[0])
    assert opening_name is not None

    matched = [g for g in games if _eco_matches(g, opening_name)]
    key = opening_name.lower()
    for g in matched:
        eco_url = g.get("eco", "").lower()
        assert key in eco_url, (
            f"Game {g['url']} matched '{opening_name}' but eco URL "
            f"'{eco_url}' doesn't contain '{key}'"
        )


def test_name_filter_catches_all_eco_url_variants(games):
    """
    Filtering by opening name should find *every* game whose eco URL
    contains that name — regardless of which specific ECO code it has.

    This verifies that name-based filtering is a proper superset of any
    single ECO code filter for that opening family.
    """
    opening_name = _extract_opening_name(games[0])
    assert opening_name is not None

    # Ground truth: manually scan eco URLs for the substring
    by_url = [
        g for g in games if opening_name.lower() in g.get("eco", "").lower()
    ]
    # Library filter result
    by_filter = [g for g in games if _eco_matches(g, opening_name)]

    assert {g["url"] for g in by_filter} == {g["url"] for g in by_url}, (
        f"Name filter found {len(by_filter)} games but URL scan found "
        f"{len(by_url)} — filter may be missing some variants"
    )


# ---------------------------------------------------------------------------
# _eco_matches — edge cases
# ---------------------------------------------------------------------------


def test_empty_opening_matches_all_games(games):
    """An empty or whitespace-only opening spec should match every game."""
    assert all(_eco_matches(g, "") for g in games)
    assert all(_eco_matches(g, "   ") for g in games)


def test_nonexistent_opening_matches_nothing(games):
    """A completely fabricated opening name should match zero games."""
    matched = [g for g in games if _eco_matches(g, "Zyzzyva-Gambit")]
    assert len(matched) == 0


# ---------------------------------------------------------------------------
# get_games_by_opening — public API integration tests
#
# These call the real API through the full public interface, verifying that
# HTTP fetch + client-side filtering work together end-to-end.
# ---------------------------------------------------------------------------


def test_public_api_returns_filtered_subset(games):
    """
    get_games_by_opening should return a non-empty list that is a subset
    of the full month's games when given a specific opening.
    """
    opening_name = _extract_opening_name(games[0])
    assert opening_name is not None

    # This makes a real API call + filters server-side
    filtered = get_games_by_opening(USERNAME, opening_name, YEAR, MONTH)

    assert len(filtered) > 0, f"Expected games for opening '{opening_name}'"
    assert len(filtered) <= len(games), (
        "Filtered result should not exceed total games"
    )


def test_public_api_empty_opening_returns_all(games):
    """
    get_games_by_opening with an empty opening string should return the
    same number of games as an unfiltered get_games call.
    """
    # This makes a real API call with no filter
    unfiltered = get_games_by_opening(USERNAME, "", YEAR, MONTH)
    assert len(unfiltered) == len(games)


# ---------------------------------------------------------------------------
# _month_range — pure unit tests (no network calls)
# ---------------------------------------------------------------------------


class TestMonthRange:
    """Tests for the _month_range helper that generates (year, month) pairs."""

    def test_single_month(self):
        """A range where start == end should return exactly one pair."""
        result = _month_range(date(2026, 1, 1), date(2026, 1, 31))
        assert result == [(2026, 1)]

    def test_same_month_different_days(self):
        """Day-of-month is ignored — same year/month always gives one pair."""
        result = _month_range(date(2026, 3, 15), date(2026, 3, 1))
        assert result == [(2026, 3)]

    def test_multi_month_same_year(self):
        """Several months within the same year."""
        result = _month_range(date(2026, 1, 1), date(2026, 4, 1))
        assert result == [(2026, 1), (2026, 2), (2026, 3), (2026, 4)]

    def test_cross_year_boundary(self):
        """Range spanning a year boundary (Dec -> Jan)."""
        result = _month_range(date(2025, 11, 1), date(2026, 2, 1))
        assert result == [
            (2025, 11), (2025, 12),
            (2026, 1), (2026, 2),
        ]

    def test_full_year(self):
        """All 12 months of a year."""
        result = _month_range(date(2025, 1, 1), date(2025, 12, 1))
        assert len(result) == 12
        assert result[0] == (2025, 1)
        assert result[-1] == (2025, 12)

    def test_multi_year_span(self):
        """Range spanning more than one year."""
        result = _month_range(date(2024, 11, 1), date(2026, 2, 1))
        # Nov 2024 -> Feb 2026 = 2 + 12 + 2 = 16 months
        assert len(result) == 16
        assert result[0] == (2024, 11)
        assert result[-1] == (2026, 2)

    def test_start_after_end_raises(self):
        """Reversed range should raise ValueError."""
        with pytest.raises(ValueError, match="after"):
            _month_range(date(2026, 3, 1), date(2026, 1, 1))

    def test_start_after_end_cross_year_raises(self):
        """Reversed range across years should also raise."""
        with pytest.raises(ValueError, match="after"):
            _month_range(date(2026, 1, 1), date(2025, 12, 1))


# ---------------------------------------------------------------------------
# get_games_batch — live API integration tests
# ---------------------------------------------------------------------------


class TestGetGamesBatch:
    """
    Integration tests for batch fetching across multiple months.

    These hit the live Chess.com API. We use a small date range
    (just January 2026) for the basic test to keep it fast, and
    a two-month range for the multi-month test.
    """

    def test_single_month_matches_get_games(self, games):
        """
        Batch with a one-month range should return the same games
        as a direct get_games call for that month.
        """
        batch = get_games_batch(
            USERNAME,
            date(YEAR, MONTH, 1),
            date(YEAR, MONTH, 28),
        )
        # Same count — and same game URLs (order-independent)
        assert len(batch) == len(games)
        assert {g["url"] for g in batch} == {g["url"] for g in games}

    def test_multi_month_returns_superset(self):
        """
        Batch spanning two months should return at least as many
        games as a single-month fetch.
        """
        single = get_games(USERNAME, YEAR, MONTH)
        batch = get_games_batch(
            USERNAME,
            date(2025, 12, 1),
            date(YEAR, MONTH, 1),
        )
        # The batch covers Dec 2025 + Jan 2026, so it should be >= Jan alone
        assert len(batch) >= len(single)
        # All January games should appear in the batch
        single_urls = {g["url"] for g in single}
        batch_urls = {g["url"] for g in batch}
        assert single_urls.issubset(batch_urls)

    def test_chronological_order(self):
        """
        Games should be ordered by month — all Dec games before Jan games.
        We verify by checking end_time timestamps are non-decreasing across
        month boundaries (games within a month are already chronological).
        """
        batch = get_games_batch(
            USERNAME,
            date(2025, 12, 1),
            date(YEAR, MONTH, 1),
        )
        if len(batch) < 2:
            pytest.skip("Need at least 2 games to test ordering")

        # Find the boundary: last Dec game and first Jan game
        dec_games = [g for g in batch if g.get("end_time", 0) < 1735689600]
        jan_games = [g for g in batch if g.get("end_time", 0) >= 1735689600]

        if dec_games and jan_games:
            last_dec_time = dec_games[-1].get("end_time", 0)
            first_jan_time = jan_games[0].get("end_time", 0)
            assert last_dec_time <= first_jan_time, (
                "December games should come before January games"
            )

    def test_invalid_range_raises(self):
        """Reversed date range should raise ValueError, not make API calls."""
        with pytest.raises(ValueError, match="after"):
            get_games_batch(USERNAME, date(2026, 3, 1), date(2026, 1, 1))

    def test_strict_error_on_bad_username(self):
        """
        Strict mode: a request that triggers an HTTP error should propagate
        the exception — no partial results, no silent failures.

        We use a username that will 404 to trigger the error.
        """
        with pytest.raises(PlayerNotFoundError):
            get_games_batch(
                "this-user-definitely-does-not-exist-xyz-999",
                date(YEAR, MONTH, 1),
                date(YEAR, MONTH, 1),
            )

    def test_strict_error_propagates_from_concurrent_workers(self):
        """
        When one month in a multi-month batch fails, strict mode should
        propagate the exception even though other months may succeed.

        We mock one of the months to fail while the other would succeed.
        """
        def failing_get_games(username, year, month):
            """Simulate the second month failing with a ChessComAPIError."""
            if month == 2:
                raise ChessComAPIError("Simulated failure for month 2")
            return get_games(username, year, month)

        with patch("chesscompy.games.get_games", side_effect=failing_get_games):
            with pytest.raises(ChessComAPIError):
                get_games_batch(
                    USERNAME,
                    date(YEAR, MONTH, 1),
                    date(YEAR, 2, 1),
                )


# ---------------------------------------------------------------------------
# _is_loss — unit tests for loss detection helper
# ---------------------------------------------------------------------------


class TestIsLoss:
    """
    Unit tests for the _is_loss helper function.

    Chess.com uses various result strings to indicate how a game ended.
    A "loss" is when the player was on the losing side — checkmated,
    resigned, timed out, etc. Draws and wins should return False.
    """

    # ----- Losing results (should return True) -----

    def test_checkmated_is_loss(self):
        """Player who got checkmated lost the game."""
        game = {
            "white": {"username": "alice", "result": "checkmated"},
            "black": {"username": "bob", "result": "win"},
        }
        assert _is_loss(game, "alice") is True
        assert _is_loss(game, "bob") is False

    def test_resigned_is_loss(self):
        """Player who resigned lost the game."""
        game = {
            "white": {"username": "alice", "result": "win"},
            "black": {"username": "bob", "result": "resigned"},
        }
        assert _is_loss(game, "bob") is True
        assert _is_loss(game, "alice") is False

    def test_timeout_is_loss(self):
        """Player who ran out of time lost the game."""
        game = {
            "white": {"username": "alice", "result": "timeout"},
            "black": {"username": "bob", "result": "win"},
        }
        assert _is_loss(game, "alice") is True

    def test_abandoned_is_loss(self):
        """Player who abandoned the game lost."""
        game = {
            "white": {"username": "alice", "result": "abandoned"},
            "black": {"username": "bob", "result": "win"},
        }
        assert _is_loss(game, "alice") is True

    # ----- Non-losing results (should return False) -----

    def test_win_is_not_loss(self):
        """Winner did not lose."""
        game = {
            "white": {"username": "alice", "result": "win"},
            "black": {"username": "bob", "result": "checkmated"},
        }
        assert _is_loss(game, "alice") is False

    def test_draw_stalemate_is_not_loss(self):
        """Stalemate is a draw, not a loss for either player."""
        game = {
            "white": {"username": "alice", "result": "stalemate"},
            "black": {"username": "bob", "result": "stalemate"},
        }
        assert _is_loss(game, "alice") is False
        assert _is_loss(game, "bob") is False

    def test_draw_agreed_is_not_loss(self):
        """Draw by agreement is not a loss."""
        game = {
            "white": {"username": "alice", "result": "agreed"},
            "black": {"username": "bob", "result": "agreed"},
        }
        assert _is_loss(game, "alice") is False
        assert _is_loss(game, "bob") is False

    def test_draw_repetition_is_not_loss(self):
        """Draw by repetition is not a loss."""
        game = {
            "white": {"username": "alice", "result": "repetition"},
            "black": {"username": "bob", "result": "repetition"},
        }
        assert _is_loss(game, "alice") is False
        assert _is_loss(game, "bob") is False

    def test_draw_insufficient_is_not_loss(self):
        """Draw by insufficient material is not a loss."""
        game = {
            "white": {"username": "alice", "result": "insufficient"},
            "black": {"username": "bob", "result": "insufficient"},
        }
        assert _is_loss(game, "alice") is False
        assert _is_loss(game, "bob") is False

    def test_draw_50move_is_not_loss(self):
        """Draw by 50-move rule is not a loss."""
        game = {
            "white": {"username": "alice", "result": "50move"},
            "black": {"username": "bob", "result": "50move"},
        }
        assert _is_loss(game, "alice") is False
        assert _is_loss(game, "bob") is False

    def test_draw_timevsinsufficient_is_not_loss(self):
        """Timeout vs insufficient material is a draw, not a loss."""
        game = {
            "white": {"username": "alice", "result": "timevsinsufficient"},
            "black": {"username": "bob", "result": "timevsinsufficient"},
        }
        assert _is_loss(game, "alice") is False
        assert _is_loss(game, "bob") is False

    # ----- Edge cases -----

    def test_username_case_insensitive(self):
        """Username matching should be case-insensitive (Chess.com usernames are)."""
        game = {
            "white": {"username": "Alice", "result": "checkmated"},
            "black": {"username": "Bob", "result": "win"},
        }
        # Query with different casing should still work
        assert _is_loss(game, "alice") is True
        assert _is_loss(game, "ALICE") is True
        assert _is_loss(game, "bob") is False

    def test_username_not_in_game_returns_false(self):
        """If the username isn't in the game at all, return False."""
        game = {
            "white": {"username": "alice", "result": "win"},
            "black": {"username": "bob", "result": "checkmated"},
        }
        assert _is_loss(game, "charlie") is False


# ---------------------------------------------------------------------------
# get_recent_losses — live API integration tests
# ---------------------------------------------------------------------------


class TestGetRecentLosses:
    """
    Integration tests for fetching recent losses from the live Chess.com API.

    These tests verify that:
      - Only games where the user lost are returned
      - The limit parameter is respected
      - Results are in reverse chronological order (most recent first)
    """

    def test_returns_only_losses(self):
        """
        Every game returned should be a loss for the specified username.

        We verify by checking the result field for the user's color.
        """
        losses = get_recent_losses(USERNAME, limit=5)

        # Skip if the user has no losses in recent history
        if not losses:
            pytest.skip(f"User {USERNAME} has no recent losses to test")

        for game in losses:
            assert _is_loss(game, USERNAME), (
                f"Game {game.get('url')} was returned but is not a loss for {USERNAME}"
            )

    def test_respects_limit(self):
        """
        Should return at most `limit` games.
        """
        limit = 3
        losses = get_recent_losses(USERNAME, limit=limit)
        assert len(losses) <= limit

    def test_default_limit_is_10(self):
        """
        Default limit should be 10 when not specified.
        """
        losses = get_recent_losses(USERNAME)
        assert len(losses) <= 10

    def test_returns_most_recent_first(self):
        """
        Games should be in reverse chronological order — most recent loss first.

        We verify by checking that end_time values are non-increasing.
        """
        losses = get_recent_losses(USERNAME, limit=5)

        if len(losses) < 2:
            pytest.skip("Need at least 2 losses to test ordering")

        end_times = [g.get("end_time", 0) for g in losses]
        for i in range(len(end_times) - 1):
            assert end_times[i] >= end_times[i + 1], (
                f"Games not in reverse chronological order: "
                f"game {i} ended at {end_times[i]}, game {i+1} at {end_times[i+1]}"
            )

    def test_nonexistent_user_raises(self):
        """
        Querying for a nonexistent user should raise PlayerNotFoundError.
        """
        with pytest.raises(PlayerNotFoundError):
            get_recent_losses("this-user-definitely-does-not-exist-xyz-999", limit=1)

    def test_time_control_filter(self):
        """
        When time_control is specified, only losses from that format are returned.
        """
        losses = get_recent_losses(USERNAME, limit=20, time_control="blitz")

        if not losses:
            pytest.skip(f"User {USERNAME} has no recent blitz losses")

        for game in losses:
            assert game.get("time_class") == "blitz", (
                f"Game {game.get('url')} has time_class "
                f"'{game.get('time_class')}', expected 'blitz'"
            )

    def test_since_filter_excludes_old_games(self):
        """
        When since is provided, only games with end_time > since are returned.

        We fetch losses without filter, grab a mid-list timestamp, then
        re-fetch with since=that timestamp and confirm the result is smaller.
        """
        all_losses = get_recent_losses(USERNAME, limit=10)

        if len(all_losses) < 3:
            pytest.skip("Need at least 3 losses to test 'since' filter")

        # Pick a timestamp from the middle of the list
        mid_idx = len(all_losses) // 2
        cutoff = all_losses[mid_idx].get("end_time", 0)

        filtered = get_recent_losses(USERNAME, limit=10, since=cutoff)

        # Every filtered game should have end_time > cutoff
        for game in filtered:
            assert game.get("end_time", 0) > cutoff

        # Filtered list should be a subset of the original
        assert len(filtered) <= len(all_losses)


# ---------------------------------------------------------------------------
# _time_class_matches — unit tests for time control filter
# ---------------------------------------------------------------------------


class TestTimeClassMatches:
    """Unit tests for the _time_class_matches helper."""

    def test_none_matches_everything(self):
        """None time_control means no filter — should always match."""
        assert _time_class_matches({"time_class": "blitz"}, None) is True
        assert _time_class_matches({"time_class": "rapid"}, None) is True
        assert _time_class_matches({}, None) is True

    def test_exact_match(self):
        """Matching time class should return True."""
        assert _time_class_matches({"time_class": "blitz"}, "blitz") is True
        assert _time_class_matches({"time_class": "rapid"}, "rapid") is True
        assert _time_class_matches({"time_class": "bullet"}, "bullet") is True
        assert _time_class_matches({"time_class": "daily"}, "daily") is True

    def test_case_insensitive(self):
        """Matching should be case-insensitive."""
        assert _time_class_matches({"time_class": "Blitz"}, "blitz") is True
        assert _time_class_matches({"time_class": "blitz"}, "BLITZ") is True

    def test_mismatch(self):
        """Non-matching time class should return False."""
        assert _time_class_matches({"time_class": "blitz"}, "rapid") is False
        assert _time_class_matches({"time_class": "bullet"}, "daily") is False

    def test_missing_time_class(self):
        """Game without time_class field should not match any specific filter."""
        assert _time_class_matches({}, "blitz") is False


# ---------------------------------------------------------------------------
# filter_by_time_control — public filter function
# ---------------------------------------------------------------------------


class TestFilterByTimeControl:
    """Unit tests for the standalone filter_by_time_control function."""

    def test_filters_correctly(self):
        """Should return only games matching the requested time control."""
        games = [
            {"url": "g1", "time_class": "blitz"},
            {"url": "g2", "time_class": "rapid"},
            {"url": "g3", "time_class": "blitz"},
            {"url": "g4", "time_class": "bullet"},
        ]
        result = filter_by_time_control(games, "blitz")
        assert len(result) == 2
        assert all(g["time_class"] == "blitz" for g in result)

    def test_empty_list(self):
        """Filtering an empty list should return an empty list."""
        assert filter_by_time_control([], "rapid") == []

    def test_no_matches(self):
        """When no games match, should return an empty list."""
        games = [{"url": "g1", "time_class": "blitz"}]
        assert filter_by_time_control(games, "daily") == []

    def test_invalid_time_control_raises(self):
        """An unrecognized time control value should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid time_control"):
            filter_by_time_control([], "ultrafast")
