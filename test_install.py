"""
Post-install smoke test for chesscompy.

Run this after installing from TestPyPI (or real PyPI) in a clean venv
to verify the distribution is correct and functional:

    python test_install.py

This script uses ONLY the public API — no internal modules, no pytest.
It exits with code 0 on success, 1 on any failure.
"""

import sys
from datetime import date


def check(label: str, passed: bool, detail: str = "") -> bool:
    """Print a pass/fail line and return the result."""
    status = "PASS" if passed else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return passed


def main() -> int:
    all_passed = True
    print("chesscompy install verification\n")

    # -----------------------------------------------------------------------
    # 1. Basic import — confirms the package is installed and __init__.py loads
    # -----------------------------------------------------------------------
    print("1. Package import")
    try:
        import chesscompy
        all_passed &= check("import chesscompy", True)
    except ImportError as e:
        check("import chesscompy", False, str(e))
        print("\n  Cannot proceed — package is not installed.")
        return 1

    # -----------------------------------------------------------------------
    # 2. Version — confirms __version__ is set and matches expectations
    # -----------------------------------------------------------------------
    print("\n2. Version")
    has_version = hasattr(chesscompy, "__version__")
    all_passed &= check("__version__ exists", has_version)

    if has_version:
        ver = chesscompy.__version__
        all_passed &= check(
            "__version__ is a non-empty string",
            isinstance(ver, str) and len(ver) > 0,
            f"got {ver!r}",
        )

    # -----------------------------------------------------------------------
    # 3. Public API surface — confirms all four functions are importable
    #    and __all__ matches what we expect
    # -----------------------------------------------------------------------
    print("\n3. Public API exports")

    expected_exports = [
        "get_games",
        "get_games_batch",
        "get_games_batch_by_opening",
        "get_games_by_opening",
    ]

    for name in expected_exports:
        exists = hasattr(chesscompy, name)
        is_callable = callable(getattr(chesscompy, name, None))
        all_passed &= check(
            f"{name} importable and callable",
            exists and is_callable,
        )

    # Verify __all__ contains exactly the expected names
    has_all = hasattr(chesscompy, "__all__")
    all_passed &= check("__all__ is defined", has_all)
    if has_all:
        all_passed &= check(
            "__all__ matches expected exports",
            sorted(chesscompy.__all__) == sorted(expected_exports),
            f"got {chesscompy.__all__}",
        )

    # -----------------------------------------------------------------------
    # 4. Explicit imports — mimics how a real user would write their code
    # -----------------------------------------------------------------------
    print("\n4. User-style imports")
    try:
        from chesscompy import get_games, get_games_by_opening
        from chesscompy import get_games_batch, get_games_batch_by_opening

        all_passed &= check("from chesscompy import all four functions", True)
    except ImportError as e:
        all_passed &= check("from chesscompy import all four functions", False, str(e))

    # -----------------------------------------------------------------------
    # 5. Live API smoke test — fetch games for a known user/month
    #    This confirms the HTTP client, URL construction, and response
    #    parsing all work end-to-end from the installed package.
    # -----------------------------------------------------------------------
    print("\n5. Live API: get_games")
    try:
        games = get_games("cdew4", 2026, 1)
        all_passed &= check(
            "get_games returns a list",
            isinstance(games, list),
            f"type={type(games).__name__}",
        )
        all_passed &= check(
            "got at least one game",
            len(games) > 0,
            f"count={len(games)}",
        )

        # Spot-check structure of the first game
        if games:
            first = games[0]
            all_passed &= check(
                "game has 'url' field",
                "url" in first,
            )
            all_passed &= check(
                "game has 'pgn' field",
                "pgn" in first,
            )
    except Exception as e:
        all_passed &= check("get_games call succeeded", False, str(e))

    # -----------------------------------------------------------------------
    # 6. Opening filter smoke test — verify client-side filtering works
    # -----------------------------------------------------------------------
    print("\n6. Live API: get_games_by_opening")
    try:
        # Use empty string filter — should return ALL games (same as unfiltered)
        unfiltered = get_games_by_opening("cdew4", "", 2026, 1)
        all_passed &= check(
            "empty opening returns all games",
            len(unfiltered) == len(games),
            f"unfiltered={len(unfiltered)}, total={len(games)}",
        )

        # Use a fabricated opening — should return zero games
        fabricated = get_games_by_opening("cdew4", "Zyzzyva-Gambit", 2026, 1)
        all_passed &= check(
            "fabricated opening returns zero games",
            len(fabricated) == 0,
            f"count={len(fabricated)}",
        )
    except Exception as e:
        all_passed &= check("get_games_by_opening call succeeded", False, str(e))

    # -----------------------------------------------------------------------
    # 7. Batch fetch smoke test — small range to avoid hammering the API
    # -----------------------------------------------------------------------
    print("\n7. Live API: get_games_batch")
    try:
        # Single month batch — should match get_games result
        batch = get_games_batch("cdew4", date(2026, 1, 1), date(2026, 1, 31))
        all_passed &= check(
            "single-month batch matches get_games count",
            len(batch) == len(games),
            f"batch={len(batch)}, get_games={len(games)}",
        )
    except Exception as e:
        all_passed &= check("get_games_batch call succeeded", False, str(e))

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 50)
    if all_passed:
        print("All checks passed. Package is correctly installed.")
        return 0
    else:
        print("Some checks FAILED. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
