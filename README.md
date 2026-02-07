# chesscompy

A small Python library that extends the [Chess.com public API](https://www.chess.com/news/view/published-data-api). It starts by adding **games by opening**: fetch a player's games and filter by ECO code or opening name (e.g. Pirc Defense, Caro-Kann).

The official API only supports:

- `GET /player/{username}/games/{YYYY}/{MM}` — games in a given month.

There is no server-side filter by opening, so chesscompy fetches games (by month) and filters client-side using each game's `eco` field (Chess.com opening URL) and PGN `[ECO "B07"]` tag.

## Install

From the project root (or after cloning):

```bash
pip install -e .
```

Optional dev deps (tests, coverage):

```bash
pip install -e ".[dev]"
```

### Development with a venv

Create and use a virtual environment so project dependencies stay isolated:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate     # Windows
pip install -e ".[dev]"
```

After activating, `which pip` and `which python` should point inside `.venv`. If you get **externally-managed-environment** (common on Debian/Ubuntu), the shell may be using the system Python. Create the venv with a non-system interpreter, e.g. with pyenv:

```bash
pyenv install -s 3.10.13   # if needed
~/.pyenv/versions/3.10.13/bin/python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run tests with pytest (not `python tests/`):

```bash
pytest tests/ -v
```

The repo already ignores `.venv`, `venv/`, and `env/`, so the environment won’t be committed.

## Usage

```python
from chesscompy import get_games, get_games_by_opening

# All games for a player in a month (direct API)
games = get_games("cdew4", 2026, 1)

# Games in that month that match an opening (client-side filter)
pirc_games = get_games_by_opening("cdew4", "B07", 2026, 1)   # ECO code
caro_games = get_games_by_opening("cdew4", "Caro-Kann", 2026, 1)  # name substring

# All games in a year matching an opening (12 API calls, then filter)
caro_in_year = get_games_by_opening("cdew4", "Caro-Kann", 2026)
```

Each game is a dict with the same shape as the API: `url`, `pgn`, `white`, `black`, `eco`, `time_control`, `fen`, etc.

## Project layout

- `chesscompy/` — main package  
  - `_client.py` — HTTP GET and URL helpers for api.chess.com  
  - `games.py` — `get_games(username, year, month)`, `get_games_by_opening(...)`  
  - `__init__.py` — re-exports public API
- `pyproject.toml` — metadata, dependencies, tool config
- `responses/` — sample API responses (e.g. for tests)

## License

MIT (see LICENSE).
