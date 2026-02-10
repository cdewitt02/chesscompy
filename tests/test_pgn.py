"""
Unit tests for the PGN parsing module.

All tests use static PGN strings — no network calls needed.
The sample PGN is based on actual Chess.com format with clock annotations.
"""

from __future__ import annotations

import pytest

from chesscompy.pgn import (
    extract_clocks,
    extract_clocks_by_color,
    extract_moves,
    find_time_pressure_moves,
)


# ---------------------------------------------------------------------------
# Sample PGN data — realistic Chess.com format
# ---------------------------------------------------------------------------

# Short game (11 moves) with clock annotations and increment
SAMPLE_PGN = """\
[Event "Live Chess"]
[Site "Chess.com"]
[Date "2026.01.01"]
[Round "-"]
[White "alice"]
[Black "bob"]
[Result "1-0"]
[ECO "B07"]
[TimeControl "180+2"]
[Termination "alice won by checkmate"]

1. e4 {[%clk 0:03:01.8]} 1... d6 {[%clk 0:03:01.9]} 2. d4 {[%clk 0:03:02.7]} 2... Nf6 {[%clk 0:03:03.1]} 3. Nc3 {[%clk 0:03:03]} 3... g6 {[%clk 0:03:04.3]} 4. Bc4 {[%clk 0:03:02.8]} 4... Bg7 {[%clk 0:03:05.3]} 5. Be3 {[%clk 0:03:03.1]} 5... Nbd7 {[%clk 0:03:04.7]} 6. Qd2 {[%clk 0:03:04.1]} 6... O-O {[%clk 0:03:02.7]} 7. Nf3 {[%clk 0:03:03.7]} 7... Re8 {[%clk 0:03:03.4]} 8. Bh6 {[%clk 0:03:04]} 8... Bh8 {[%clk 0:03:04.5]} 9. Rd1 {[%clk 0:02:53]} 9... e5 {[%clk 0:03:04.6]} 10. Ng5 {[%clk 0:02:46.6]} 10... exd4 {[%clk 0:02:55.1]} 11. Bxf7# {[%clk 0:02:46.3]} 1-0
"""

# Game with severe time pressure for Black (last moves under 10 seconds)
TIME_PRESSURE_PGN = """\
[Event "Live Chess"]
[Site "Chess.com"]
[White "alice"]
[Black "bob"]
[Result "1-0"]
[TimeControl "60"]

1. e4 {[%clk 0:00:59]} 1... e5 {[%clk 0:00:58]} 2. Nf3 {[%clk 0:00:55]} 2... Nc6 {[%clk 0:00:50]} 3. Bc4 {[%clk 0:00:52]} 3... Bc5 {[%clk 0:00:25]} 4. d3 {[%clk 0:00:48]} 4... Nf6 {[%clk 0:00:08]} 5. O-O {[%clk 0:00:45]} 5... O-O {[%clk 0:00:03.5]} 1-0
"""

# Empty PGN (headers only, no moves)
EMPTY_PGN = """\
[Event "Live Chess"]
[Site "Chess.com"]
[Result "*"]

*
"""

# PGN with no clock annotations at all
NO_CLOCK_PGN = """\
[Event "Live Chess"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 1-0
"""


# ---------------------------------------------------------------------------
# extract_clocks
# ---------------------------------------------------------------------------


class TestExtractClocks:
    """Tests for extracting clock times from PGN."""

    def test_correct_count(self):
        """Should extract one clock per half-move (21 moves = 21 clocks)."""
        clocks = extract_clocks(SAMPLE_PGN)
        # 11 white moves + 10 black moves = 21 total half-moves
        assert len(clocks) == 21

    def test_first_clock_value(self):
        """First clock (White move 1) should be 3:01.8 = 181.8 seconds."""
        clocks = extract_clocks(SAMPLE_PGN)
        assert clocks[0] == pytest.approx(181.8)

    def test_last_clock_value(self):
        """Last clock (White move 11, Bxf7#) should be 2:46.3 = 166.3 seconds."""
        clocks = extract_clocks(SAMPLE_PGN)
        assert clocks[-1] == pytest.approx(166.3)

    def test_empty_pgn(self):
        """PGN with no moves should return empty list."""
        assert extract_clocks(EMPTY_PGN) == []

    def test_no_clock_annotations(self):
        """PGN without clock annotations should return empty list."""
        assert extract_clocks(NO_CLOCK_PGN) == []

    def test_all_clocks_positive(self):
        """All extracted clock times should be positive."""
        clocks = extract_clocks(SAMPLE_PGN)
        assert all(c > 0 for c in clocks)

    def test_empty_string(self):
        """An empty string should return empty list."""
        assert extract_clocks("") == []


# ---------------------------------------------------------------------------
# extract_clocks_by_color
# ---------------------------------------------------------------------------


class TestExtractClocksByColor:
    """Tests for splitting clock times by color."""

    def test_white_count(self):
        """White made 11 moves, so should have 11 clock entries."""
        by_color = extract_clocks_by_color(SAMPLE_PGN)
        assert len(by_color["white"]) == 11

    def test_black_count(self):
        """Black made 10 moves, so should have 10 clock entries."""
        by_color = extract_clocks_by_color(SAMPLE_PGN)
        assert len(by_color["black"]) == 10

    def test_white_first_clock(self):
        """White's first clock should match the first overall clock."""
        by_color = extract_clocks_by_color(SAMPLE_PGN)
        assert by_color["white"][0] == pytest.approx(181.8)

    def test_black_first_clock(self):
        """Black's first clock should match the second overall clock."""
        by_color = extract_clocks_by_color(SAMPLE_PGN)
        assert by_color["black"][0] == pytest.approx(181.9)

    def test_empty_pgn(self):
        """Empty PGN should give empty lists for both colors."""
        by_color = extract_clocks_by_color(EMPTY_PGN)
        assert by_color["white"] == []
        assert by_color["black"] == []


# ---------------------------------------------------------------------------
# extract_moves
# ---------------------------------------------------------------------------


class TestExtractMoves:
    """Tests for extracting SAN moves from PGN."""

    def test_correct_count(self):
        """Should extract 21 half-moves (11 white + 10 black)."""
        moves = extract_moves(SAMPLE_PGN)
        assert len(moves) == 21

    def test_first_move(self):
        """First move should be White's e4."""
        moves = extract_moves(SAMPLE_PGN)
        assert moves[0] == "e4"

    def test_second_move(self):
        """Second move should be Black's d6."""
        moves = extract_moves(SAMPLE_PGN)
        assert moves[1] == "d6"

    def test_last_move(self):
        """Last move should be the checkmate Bxf7#."""
        moves = extract_moves(SAMPLE_PGN)
        assert moves[-1] == "Bxf7#"

    def test_castling_preserved(self):
        """Castling notation (O-O) should be preserved in the move list."""
        moves = extract_moves(SAMPLE_PGN)
        assert "O-O" in moves

    def test_no_move_numbers_in_output(self):
        """Move numbers (1., 2., etc.) should not appear in the extracted moves."""
        moves = extract_moves(SAMPLE_PGN)
        for move in moves:
            assert not move[0].isdigit(), f"Move '{move}' looks like a move number"

    def test_no_clock_annotations_in_output(self):
        """Clock annotations should be stripped from the output."""
        moves = extract_moves(SAMPLE_PGN)
        for move in moves:
            assert "%clk" not in move, f"Move '{move}' contains clock annotation"

    def test_no_result_in_output(self):
        """The result token (1-0, 0-1, etc.) should not be in the move list."""
        moves = extract_moves(SAMPLE_PGN)
        results = {"1-0", "0-1", "1/2-1/2", "*"}
        for move in moves:
            assert move not in results, f"Result token '{move}' in move list"

    def test_empty_pgn(self):
        """PGN with no moves should return empty list."""
        assert extract_moves(EMPTY_PGN) == []

    def test_no_clock_pgn(self):
        """PGN without clock annotations should still extract moves."""
        moves = extract_moves(NO_CLOCK_PGN)
        assert moves == ["e4", "e5", "Nf3", "Nc6", "Bb5"]

    def test_empty_string(self):
        """An empty string should return empty list."""
        assert extract_moves("") == []


# ---------------------------------------------------------------------------
# find_time_pressure_moves
# ---------------------------------------------------------------------------


class TestFindTimePressureMoves:
    """Tests for identifying time-pressure moves."""

    def test_finds_pressure_moves(self):
        """Should find moves where clock is below the threshold."""
        # In TIME_PRESSURE_PGN, Black's last two moves are at 8s and 3.5s
        results = find_time_pressure_moves(TIME_PRESSURE_PGN, threshold_seconds=10.0)
        assert len(results) > 0

    def test_all_results_below_threshold(self):
        """Every returned move should have clock_seconds <= threshold."""
        threshold = 10.0
        results = find_time_pressure_moves(TIME_PRESSURE_PGN, threshold_seconds=threshold)
        for r in results:
            assert r["clock_seconds"] <= threshold, (
                f"Move {r['move']} has clock {r['clock_seconds']}s > threshold {threshold}s"
            )

    def test_result_structure(self):
        """Each result dict should have the expected keys."""
        results = find_time_pressure_moves(TIME_PRESSURE_PGN, threshold_seconds=60.0)
        assert len(results) > 0
        for r in results:
            assert "move_number" in r
            assert "color" in r
            assert "move" in r
            assert "clock_seconds" in r
            assert "ply" in r
            assert r["color"] in ("white", "black")
            assert isinstance(r["move_number"], int)
            assert r["move_number"] >= 1

    def test_color_filter_white(self):
        """Filtering by color='white' should only return white moves."""
        results = find_time_pressure_moves(
            TIME_PRESSURE_PGN, threshold_seconds=60.0, color="white"
        )
        for r in results:
            assert r["color"] == "white"

    def test_color_filter_black(self):
        """Filtering by color='black' should only return black moves."""
        results = find_time_pressure_moves(
            TIME_PRESSURE_PGN, threshold_seconds=60.0, color="black"
        )
        for r in results:
            assert r["color"] == "black"

    def test_high_threshold_captures_all(self):
        """A very high threshold should flag every move."""
        moves = extract_moves(TIME_PRESSURE_PGN)
        results = find_time_pressure_moves(
            TIME_PRESSURE_PGN, threshold_seconds=99999.0
        )
        assert len(results) == len(moves)

    def test_zero_threshold_captures_none(self):
        """A threshold of 0 should not flag any moves (all clocks are > 0)."""
        results = find_time_pressure_moves(TIME_PRESSURE_PGN, threshold_seconds=0.0)
        assert len(results) == 0

    def test_no_clock_pgn_returns_empty(self):
        """PGN without clock annotations should return empty list."""
        results = find_time_pressure_moves(NO_CLOCK_PGN, threshold_seconds=30.0)
        assert results == []

    def test_empty_pgn_returns_empty(self):
        """Empty PGN should return empty list."""
        results = find_time_pressure_moves(EMPTY_PGN, threshold_seconds=30.0)
        assert results == []

    def test_specific_time_pressure_move(self):
        """
        In TIME_PRESSURE_PGN, Black's move 5 (O-O) has clock 3.5 seconds.
        It should appear in results with threshold=10.
        """
        results = find_time_pressure_moves(
            TIME_PRESSURE_PGN, threshold_seconds=10.0, color="black"
        )
        # Find the O-O move
        castling_moves = [r for r in results if r["move"] == "O-O"]
        assert len(castling_moves) == 1
        assert castling_moves[0]["clock_seconds"] == pytest.approx(3.5)
        assert castling_moves[0]["move_number"] == 5
        assert castling_moves[0]["color"] == "black"

    def test_move_number_calculation(self):
        """
        Move numbers should follow chess convention: ply 0,1 -> move 1;
        ply 2,3 -> move 2; etc.
        """
        results = find_time_pressure_moves(
            TIME_PRESSURE_PGN, threshold_seconds=99999.0
        )
        for r in results:
            expected_move_num = (r["ply"] // 2) + 1
            assert r["move_number"] == expected_move_num
