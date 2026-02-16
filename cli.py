"""
Quick CLI for manually testing chesscompy against the live Chess.com API.

Usage examples:
    # Single month
    python cli.py cdew4 2026-01

    # Multi-month range (Oct 2025 through Jan 2026)
    python cli.py cdew4 2025-10 2026-01

    # Filter by opening — ECO code or name substring
    python cli.py cdew4 2025-10 2026-01 --opening B07
    python cli.py cdew4 2025-10 2026-01 -o Pirc-Defense

    # Filter by time control (bullet, blitz, rapid, daily)
    python cli.py cdew4 2025-10 2026-01 --time-control blitz

    # Only show losses
    python cli.py cdew4 2025-10 2026-01 --losses-only

    # Incremental fetch: only games after a given Unix timestamp
    python cli.py cdew4 2025-10 2026-01 --since 1704067200

    # Combine filters
    python cli.py cdew4 2025-10 2026-01 --time-control rapid --losses-only -v

    # Show full game details (verbose)
    python cli.py cdew4 2026-01 -v
"""

import argparse
import sys
import time
from collections import Counter
from datetime import date

from chesscompy.games import (
    _is_loss,
    get_games_batch,
    get_games_batch_by_opening,
)


def parse_month(value: str) -> date:
    """
    Parse a 'YYYY-MM' string into a date (day=1).

    argparse calls this for type validation, so a clear error message
    matters — the user sees it directly if they mistype the format.
    """
    try:
        year, month = value.split("-")
        return date(int(year), int(month), 1)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a valid YYYY-MM date (e.g. 2026-01)"
        )


def summarize(games: list[dict], verbose: bool = False) -> None:
    """Print a human-readable summary of the fetched games."""
    if not games:
        print("No games found matching the given filters.")
        return

    print(f"\nTotal games: {len(games)}")

    # Count games per time control category (bullet, blitz, rapid, etc.)
    time_controls = Counter(g.get("time_class", "unknown") for g in games)
    print("\nBy time control:")
    for tc, count in time_controls.most_common():
        print(f"  {tc:<12} {count}")

    # Count games by month (using end_time epoch -> YYYY-MM)
    month_counts: Counter[str] = Counter()
    for g in games:
        end_time = g.get("end_time")
        if end_time:
            # Convert epoch seconds to a YYYY-MM label
            d = date.fromtimestamp(end_time)
            month_counts[f"{d.year}-{d.month:02d}"] += 1
        else:
            month_counts["unknown"] += 1

    print("\nBy month:")
    for month_label, count in sorted(month_counts.items()):
        print(f"  {month_label}  {count} games")

    # Show a few sample games if verbose
    if verbose:
        print(f"\n--- First 5 games (of {len(games)}) ---\n")
        for g in games[:5]:
            url = g.get("url", "n/a")
            white = g.get("white", {}).get("username", "?")
            black = g.get("black", {}).get("username", "?")
            tc = g.get("time_class", "?")
            eco = g.get("eco", "n/a")
            w_result = g.get("white", {}).get("result", "?")
            b_result = g.get("black", {}).get("result", "?")
            print(f"  {white} ({w_result}) vs {black} ({b_result})  [{tc}]")
            print(f"    opening: {eco}")
            print(f"    url:     {url}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test chesscompy against the live Chess.com API.",
    )
    parser.add_argument(
        "username",
        help="Chess.com username (e.g. cdew4)",
    )
    parser.add_argument(
        "start",
        type=parse_month,
        help="Start month as YYYY-MM (e.g. 2025-10)",
    )
    parser.add_argument(
        "end",
        type=parse_month,
        nargs="?",          # optional — defaults to same as start
        default=None,
        help="End month as YYYY-MM (default: same as start)",
    )
    parser.add_argument(
        "--opening", "-o",
        type=str,
        default="",
        help='Filter by opening: ECO code (e.g. "B07") or name (e.g. "Pirc-Defense")',
    )
    parser.add_argument(
        "--time-control", "-t",
        type=str,
        default=None,
        choices=["bullet", "blitz", "rapid", "daily"],
        help="Filter by time control (bullet, blitz, rapid, daily)",
    )
    parser.add_argument(
        "--losses-only", "-l",
        action="store_true",
        help="Only show games where the user lost",
    )
    parser.add_argument(
        "--since", "-s",
        type=int,
        default=None,
        help="Only show games after this Unix timestamp (for incremental fetching)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show individual game details",
    )

    args = parser.parse_args()

    # If no end date given, treat it as a single-month fetch
    end = args.end if args.end is not None else args.start

    # Build a description string for the console output
    filters = []
    if args.opening:
        filters.append(f"opening='{args.opening}'")
    if args.time_control:
        filters.append(f"time_control={args.time_control}")
    if args.losses_only:
        filters.append("losses only")
    if args.since:
        filters.append(f"since={args.since}")
    filter_desc = f" [{', '.join(filters)}]" if filters else ""

    print(
        f"Fetching games for '{args.username}' "
        f"from {args.start.year}-{args.start.month:02d} "
        f"to {end.year}-{end.month:02d} "
        f"(sequential{filter_desc})..."
    )

    t0 = time.perf_counter()
    try:
        # Use the opening-filtered variant when an opening is specified;
        # otherwise use the base batch fetcher with optional filters.
        if args.opening:
            games = get_games_batch_by_opening(
                args.username, args.opening, args.start, end,
            )
        else:
            games = get_games_batch(
                args.username, args.start, end,
                time_control=args.time_control,
                since=args.since,
            )

        # --losses-only: filter to only losses for the given user
        if args.losses_only:
            games = [g for g in games if _is_loss(g, args.username)]

        # If opening path was used, apply time_control/since filters manually
        # (get_games_batch_by_opening doesn't have those params built in)
        if args.opening:
            if args.time_control:
                games = [
                    g for g in games
                    if g.get("time_class", "").lower() == args.time_control
                ]
            if args.since:
                games = [
                    g for g in games
                    if g.get("end_time", 0) > args.since
                ]

    except Exception as exc:
        # Surface the error clearly
        print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.perf_counter() - t0

    print(f"Completed in {elapsed:.2f}s")
    summarize(games, verbose=args.verbose)


if __name__ == "__main__":
    main()
