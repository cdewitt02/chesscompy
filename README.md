# chesscompy

A Python library that extends the [Chess.com public API](https://www.chess.com/news/view/published-data-api). Fetch games by opening, batch-fetch across date ranges with concurrency, parse PGN clock/move data, pull player stats, and detect time-pressure blunders — all from a simple Python interface.

## Features

- **Games by opening** — filter by ECO code (`"B07"`) or opening name substring (`"Caro-Kann"`)
- **Batch fetching** — concurrent multi-month game retrieval via thread pool
- **Time control filters** — narrow results to bullet, blitz, rapid, or daily
- **Recent losses** — walk backwards through months to find your latest losses
- **Player stats** — current ratings and W/L/D records across all formats
- **PGN parsing** — extract clock times, move lists, and time-pressure moves from Chess.com PGNs
- **Custom exceptions** — `PlayerNotFoundError`, `RateLimitError`, `DataGoneError` so you never need to inspect raw HTTP status codes
- **Automatic retries** — exponential backoff on 429 (rate limit) responses

## Install

```bash
pip install chesscompy
```

### Development

For an editable install with test tools:

```bash
git clone https://github.com/cdewitt02/chesscompy.git
cd chesscompy
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS (.venv\Scripts\activate on Windows)
pip install -e ".[dev]"
```

Run tests:

```bash
pytest tests/ -v
```

## Usage

### Fetch games

```python
from chesscompy import get_games, get_games_by_opening

# All games for a player in a single month
games = get_games("cdew4", 2026, 1)

# Filter that month by opening (ECO code or name substring)
pirc_games = get_games_by_opening("cdew4", "B07", 2026, 1)
caro_games = get_games_by_opening("cdew4", "Caro-Kann", 2026, 1)

# All games in a year matching an opening (12 API calls, then filter)
caro_in_year = get_games_by_opening("cdew4", "Caro-Kann", 2026)
```

Each game is a dict with the same shape as the Chess.com API: `url`, `pgn`, `white`, `black`, `eco`, `time_control`, `fen`, etc.

### Batch fetch (concurrent)

```python
from datetime import date
from chesscompy import get_games_batch, get_games_batch_by_opening

# Fetch Oct 2025 through Jan 2026 concurrently (one request per month)
all_games = get_games_batch("cdew4", date(2025, 10, 1), date(2026, 1, 31))

# With filters: only blitz games since a Unix timestamp
blitz = get_games_batch(
    "cdew4", date(2025, 10, 1), date(2026, 1, 31),
    time_control="blitz", since=1704067200,
)

# Batch + opening filter combined
pirc_batch = get_games_batch_by_opening(
    "cdew4", "B07", date(2025, 10, 1), date(2026, 1, 31),
)
```

### Filter by time control

```python
from chesscompy import filter_by_time_control

rapid_only = filter_by_time_control(all_games, "rapid")
```

### Recent losses

```python
from chesscompy import get_recent_losses

# Most recent 5 rapid losses (walks backwards month by month)
losses = get_recent_losses("cdew4", limit=5, time_control="rapid")
```

### Player stats

```python
from chesscompy import get_player_stats

stats = get_player_stats("cdew4")
print(stats["chess_blitz"]["last"]["rating"])   # current blitz rating
print(stats["chess_blitz"]["record"])            # {"win": ..., "loss": ..., "draw": ...}
```

### PGN parsing

```python
from chesscompy import extract_clocks, extract_clocks_by_color, extract_moves
from chesscompy import find_time_pressure_moves

pgn = games[0]["pgn"]

# Clock times (seconds remaining) in move order
clocks = extract_clocks(pgn)

# Separated by color
by_color = extract_clocks_by_color(pgn)
print(by_color["white"])  # White's clock after each move
print(by_color["black"])  # Black's clock after each move

# SAN move list: ["e4", "d6", "d4", "Nf6", ...]
moves = extract_moves(pgn)

# Moves made under time pressure (< 15 seconds on the clock)
pressure = find_time_pressure_moves(pgn, threshold_seconds=15.0)
for p in pressure:
    print(f"Move {p['move_number']} ({p['color']}): {p['move']}  "
          f"— {p['clock_seconds']:.1f}s left")
```

### Error handling

```python
from chesscompy import get_games
from chesscompy import PlayerNotFoundError, RateLimitError, DataGoneError

try:
    games = get_games("nonexistent_user_xyz", 2026, 1)
except PlayerNotFoundError as e:
    print(f"No such player: {e.username}")
except RateLimitError:
    print("Rate limited — back off and retry later")
except DataGoneError as e:
    print(f"Data permanently removed: {e.url}")
```

The HTTP client retries automatically on 429 with exponential backoff (up to 3 retries). `RateLimitError` is only raised after all retries are exhausted.

## CLI

A quick CLI (`cli.py`) is included for manual testing against the live API:

```bash
# Single month
python cli.py cdew4 2026-01

# Multi-month range
python cli.py cdew4 2025-10 2026-01

# Filter by opening
python cli.py cdew4 2025-10 2026-01 --opening B07

# Filter by time control
python cli.py cdew4 2025-10 2026-01 --time-control blitz

# Only losses
python cli.py cdew4 2025-10 2026-01 --losses-only

# Combine filters with verbose output
python cli.py cdew4 2025-10 2026-01 --time-control rapid --losses-only -v
```

## Project layout

- `chesscompy/` — main package
  - `__init__.py` — re-exports public API
  - `_client.py` — HTTP GET with retries, backoff, and custom exception wrapping
  - `exceptions.py` — `ChessComAPIError`, `PlayerNotFoundError`, `DataGoneError`, `RateLimitError`
  - `games.py` — `get_games`, `get_games_by_opening`, `get_games_batch`, `get_games_batch_by_opening`, `get_recent_losses`, `filter_by_time_control`
  - `pgn.py` — `extract_clocks`, `extract_clocks_by_color`, `extract_moves`, `find_time_pressure_moves`
  - `stats.py` — `get_player_stats`
- `cli.py` — command-line tool for manual testing
- `tests/` — unit tests for all modules
- `pyproject.toml` — metadata, dependencies, tool config
- `responses/` — sample API responses (for tests)

## License

MIT (see LICENSE).
