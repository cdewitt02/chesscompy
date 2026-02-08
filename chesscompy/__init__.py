"""
chesscompy — extend the Chess.com public API (e.g. games by opening).

Example:
    from chesscompy import get_games, get_games_by_opening, get_games_batch
    from chesscompy import get_games_batch_by_opening
    from datetime import date

    games = get_games("cdew4", 2026, 1)
    pirc_games = get_games_by_opening("cdew4", "B07", 2026, 1)
    caro_games = get_games_by_opening("cdew4", "Caro-Kann", 2026)

    # Batch: fetch Oct 2025 through Jan 2026 concurrently
    batch = get_games_batch("cdew4", date(2025, 10, 1), date(2026, 1, 31))

    # Batch + opening filter: all Pirc games from Oct 2025 through Jan 2026
    pirc_batch = get_games_batch_by_opening(
        "cdew4", "Pirc-Defense", date(2025, 10, 1), date(2026, 1, 31)
    )
"""

from chesscompy.games import (
    get_games,
    get_games_batch,
    get_games_batch_by_opening,
    get_games_by_opening,
)

__all__ = [
    "get_games",
    "get_games_batch",
    "get_games_batch_by_opening",
    "get_games_by_opening",
]
__version__ = "0.1.0"
