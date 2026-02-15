"""CLI entry point for git-wrapped."""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from git_wrapped import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git-wrapped",
        description="Spotify Wrapped, but for your Git history.",
        epilog="Example: git-wrapped --year 2025 --path ~/projects/myrepo",
    )
    parser.add_argument(
        "--path", "-p",
        default=".",
        help="Path to the git repository (default: current directory)",
    )
    parser.add_argument(
        "--year", "-y",
        type=int,
        default=None,
        help="Year to analyze (default: all time)",
    )
    parser.add_argument(
        "--author", "-a",
        default=None,
        help="Filter by author name or email (supports partial match)",
    )
    parser.add_argument(
        "--no-animate",
        action="store_true",
        help="Disable loading animation and section pauses",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw stats as JSON instead of the visual display",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"git-wrapped {__version__}",
    )
    return parser


def _serialize_stats(stats) -> dict:
    """Convert WrappedStats to a JSON-serializable dict."""
    data = {}
    for key, value in stats.__dict__.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
        elif isinstance(value, dict):
            data[key] = {str(k): v for k, v in value.items()}
        elif isinstance(value, list):
            serialized = []
            for item in value:
                if isinstance(item, tuple):
                    serialized.append(list(item))
                else:
                    serialized.append(item)
            data[key] = serialized
        elif isinstance(value, tuple):
            data[key] = list(value)
        else:
            data[key] = value
    return data


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Resolve repo path
    repo_path = str(Path(args.path).resolve())

    try:
        from git_wrapped.analyzer import analyze
        stats = analyze(
            repo_path=repo_path,
            year=args.year,
            author=args.author,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json_output:
        print(json.dumps(_serialize_stats(stats), indent=2))
        return

    from git_wrapped.display import display_wrapped
    display_wrapped(stats, animate=not args.no_animate)
