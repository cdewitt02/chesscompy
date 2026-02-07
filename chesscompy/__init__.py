"""
chesscompy — extend the Chess.com public API (e.g. games by opening).

Example:
    from chesscompy import get_games, get_games_by_opening

    games = get_games("cdew4", 2026, 1)
    pirc_games = get_games_by_opening("cdew4", "B07", 2026, 1)
    caro_games = get_games_by_opening("cdew4", "Caro-Kann", 2026)
"""

from chesscompy.games import get_games, get_games_by_opening

__all__ = ["get_games", "get_games_by_opening"]
__version__ = "0.1.0"
