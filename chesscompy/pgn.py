"""
PGN parsing utilities for Chess.com game data.

Chess.com PGNs include inline clock annotations in the format:
    {[%clk H:MM:SS.d]}

This module extracts:
  - Per-move clock times (seconds remaining)
  - Move list in Standard Algebraic Notation (SAN)
  - Moves made under time pressure (below a configurable threshold)

All functions work on raw PGN strings — no external chess libraries needed.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches clock annotations like {[%clk 0:03:01.8]} or {[%clk 1:23:45]}
# Captures hours, minutes, seconds (with optional decimal)
_CLK_PATTERN = re.compile(
    r"\{\[%clk\s+(\d+):(\d{2}):(\d{2}(?:\.\d+)?)\]\}"
)

# Matches move numbers like "1." or "12..." (with optional ellipsis for black)
_MOVE_NUMBER_PATTERN = re.compile(r"\d+\.{1,3}\s*")

# Matches the result token at the end of the PGN movetext
_RESULT_PATTERN = re.compile(r"\s*(1-0|0-1|1/2-1/2|\*)\s*$")

# Matches PGN header tags like [Event "Live Chess"]
_HEADER_PATTERN = re.compile(r"^\[.+\]\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Clock extraction
# ---------------------------------------------------------------------------


def _clk_to_seconds(hours: str, minutes: str, seconds: str) -> float:
    """
    Convert clock components to total seconds.

    :param hours: Hours string (e.g. "0", "1").
    :param minutes: Minutes string (e.g. "03", "59").
    :param seconds: Seconds string, optionally with decimal (e.g. "01.8").
    :return: Total seconds as a float.
    """
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def extract_clocks(pgn: str) -> list[float]:
    """
    Extract all clock times from a PGN string, in move order.

    Clock values represent time *remaining* on the player's clock after
    making that move.  Chess.com PGNs interleave clocks: index 0 is
    White's clock after move 1, index 1 is Black's clock after move 1, etc.

    :param pgn: Raw PGN string from the Chess.com API.
    :return: List of clock times in seconds (float), in move order.
             Empty list if the PGN has no clock annotations.
    """
    return [
        _clk_to_seconds(m.group(1), m.group(2), m.group(3))
        for m in _CLK_PATTERN.finditer(pgn)
    ]


def extract_clocks_by_color(pgn: str) -> dict[str, list[float]]:
    """
    Extract clock times separated by color (White and Black).

    :param pgn: Raw PGN string from the Chess.com API.
    :return: Dict with "white" and "black" keys, each mapping to a list
             of clock times (seconds remaining) in move order.
    """
    all_clocks = extract_clocks(pgn)
    return {
        "white": all_clocks[0::2],  # Even indices: White's moves
        "black": all_clocks[1::2],  # Odd indices: Black's moves
    }


# ---------------------------------------------------------------------------
# Move extraction
# ---------------------------------------------------------------------------


def _strip_headers(pgn: str) -> str:
    """
    Remove PGN header tags, returning only the movetext portion.

    Headers are lines matching [Tag "value"] at the start of the PGN.
    """
    return _HEADER_PATTERN.sub("", pgn).strip()


def extract_moves(pgn: str) -> list[str]:
    """
    Extract the move list from a PGN string in Standard Algebraic Notation.

    Returns moves in order: [White move 1, Black move 1, White move 2, ...].
    Clock annotations, comments, move numbers, and the result token are stripped.

    :param pgn: Raw PGN string from the Chess.com API.
    :return: List of SAN move strings (e.g. ["e4", "d6", "d4", "Nf6", ...]).
             Empty list if no moves are found.
    """
    movetext = _strip_headers(pgn)

    # Remove clock annotations {[%clk ...]}
    movetext = _CLK_PATTERN.sub("", movetext)

    # Remove any other brace comments {anything}
    movetext = re.sub(r"\{[^}]*\}", "", movetext)

    # Remove result token at the end
    movetext = _RESULT_PATTERN.sub("", movetext)

    # Remove move numbers (e.g. "1.", "12...", "3. ")
    movetext = _MOVE_NUMBER_PATTERN.sub("", movetext)

    # Split on whitespace and filter out empty strings
    tokens = movetext.split()
    return [t for t in tokens if t]


# ---------------------------------------------------------------------------
# Time pressure detection
# ---------------------------------------------------------------------------


def find_time_pressure_moves(
    pgn: str,
    threshold_seconds: float = 30.0,
    color: str | None = None,
) -> list[dict[str, Any]]:
    """
    Find moves where a player had less than *threshold_seconds* on the clock.

    Each returned dict contains:
      - "move_number": int — the move number (1-indexed, chess convention)
      - "color": str — "white" or "black"
      - "move": str — the SAN move played (e.g. "Nf6")
      - "clock_seconds": float — seconds remaining after this move
      - "ply": int — 0-indexed half-move (ply) position in the move list

    This is useful for identifying time-pressure blunders — moves made
    when the player was running low on time.  The SaaS can correlate these
    with Stockfish eval drops to distinguish genuine tactical errors from
    time-induced mistakes.

    :param pgn: Raw PGN string from the Chess.com API.
    :param threshold_seconds: Clock time threshold in seconds (default 30.0).
                              Moves with clock <= this value are flagged.
    :param color: Optional filter — "white" or "black".  If None, returns
                  time-pressure moves for both colors.
    :return: List of dicts describing each time-pressure move.
    """
    clocks = extract_clocks(pgn)
    moves = extract_moves(pgn)

    # The number of clocks and moves should match (one clock per half-move)
    # but be defensive: use the shorter length
    n = min(len(clocks), len(moves))

    results: list[dict[str, Any]] = []
    for ply in range(n):
        move_color = "white" if ply % 2 == 0 else "black"

        # Skip if caller only wants a specific color
        if color is not None and move_color != color.lower():
            continue

        clock_secs = clocks[ply]
        if clock_secs <= threshold_seconds:
            results.append({
                "move_number": (ply // 2) + 1,
                "color": move_color,
                "move": moves[ply],
                "clock_seconds": clock_secs,
                "ply": ply,
            })

    return results
