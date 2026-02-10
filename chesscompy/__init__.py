"""
chesscompy — extend the Chess.com public API (e.g. games by opening).

Example:
    from chesscompy import get_games, get_games_by_opening, get_games_batch
    from chesscompy import get_recent_losses, get_player_stats
    from chesscompy import extract_clocks, extract_moves, find_time_pressure_moves
    from datetime import date

    # Fetch all games for a single month
    games = get_games("cdew4", 2026, 1)

    # Filter by opening
    pirc_games = get_games_by_opening("cdew4", "B07", 2026, 1)

    # Batch fetch across a date range (concurrent)
    batch = get_games_batch("cdew4", date(2025, 10, 1), date(2026, 1, 31))

    # Batch with filters: only blitz games since a timestamp
    blitz = get_games_batch(
        "cdew4", date(2025, 10, 1), date(2026, 1, 31),
        time_control="blitz", since=1704067200,
    )

    # Recent losses (for analysis pipeline)
    losses = get_recent_losses("cdew4", limit=5, time_control="rapid")

    # Player stats (ratings, W/L records)
    stats = get_player_stats("cdew4")

    # PGN analysis — clock extraction and time-pressure detection
    pgn = games[0]["pgn"]
    clocks = extract_clocks(pgn)
    moves = extract_moves(pgn)
    pressure = find_time_pressure_moves(pgn, threshold_seconds=15.0)
"""

from chesscompy.exceptions import (
    ChessComAPIError,
    DataGoneError,
    PlayerNotFoundError,
    RateLimitError,
)
from chesscompy.games import (
    filter_by_time_control,
    get_games,
    get_games_batch,
    get_games_batch_by_opening,
    get_games_by_opening,
    get_recent_losses,
)
from chesscompy.pgn import (
    extract_clocks,
    extract_clocks_by_color,
    extract_moves,
    find_time_pressure_moves,
)
from chesscompy.stats import get_player_stats

__all__ = [
    # Exceptions
    "ChessComAPIError",
    "DataGoneError",
    "PlayerNotFoundError",
    "RateLimitError",
    # Game fetching
    "get_games",
    "get_games_batch",
    "get_games_batch_by_opening",
    "get_games_by_opening",
    "get_recent_losses",
    "filter_by_time_control",
    # Stats
    "get_player_stats",
    # PGN parsing
    "extract_clocks",
    "extract_clocks_by_color",
    "extract_moves",
    "find_time_pressure_moves",
]
__version__ = "0.1.0"
