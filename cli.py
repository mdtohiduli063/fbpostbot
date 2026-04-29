"""Unified CLI for the AI News Bot.

Examples
--------
    # Run the full bot (image + video + scheduler) — same as `python main.py`
    python cli.py run

    # Test the IMAGE pipeline (single post, real upload to FB)
    python cli.py test image
    python cli.py test image --dry-run            # render only, no FB upload
    python cli.py test image --count 3            # post top 3 articles
    python cli.py test image --category breaking  # filter by category

    # Test the VIDEO pipeline (single post, real upload to FB)
    python cli.py test video
    python cli.py test video --dry-run
    python cli.py test video --source wikimedia   # restrict to one source
    python cli.py test video --source youtube     # only the YouTube channels

    # Inspect what's configured
    python cli.py sources image                   # show RSS news sources
    python cli.py sources video                   # show video sources + API keys

    # Show current bot status (queues, posted counts, disk usage)
    python cli.py status
"""
from __future__ import annotations

import argparse
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _run_module(module_name: str, extra: list[str]) -> int:
    """Invoke another script as if it were called from the command line.

    Done in-process (not via subprocess) to avoid long-path issues on
    sandboxed Linux runtimes.
    """
    saved_argv = sys.argv
    try:
        sys.argv = [module_name + ".py", *extra]
        mod = __import__(module_name)
        try:
            mod.main()
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0
    finally:
        sys.argv = saved_argv


def cmd_run(extra: list[str]) -> int:
    return _run_module("main", extra)


def cmd_test(args: argparse.Namespace, extra: list[str]) -> int:
    if args.kind == "image":
        return _run_module("test_image", extra)
    if args.kind == "video":
        return _run_module("test_video", extra)
    print(f"Unknown test kind: {args.kind}")
    return 2


def cmd_sources(args: argparse.Namespace) -> int:
    if args.kind == "image":
        return _run_module("test_image", ["--list-sources"])
    if args.kind == "video":
        return _run_module("test_video", ["--list-sources"])
    print(f"Unknown sources kind: {args.kind}")
    return 2


def cmd_status() -> int:
    """Print a human-readable snapshot of the bot's current state."""
    import json
    from datetime import datetime

    data_dir = os.path.join(HERE, "data")
    logs_dir = os.path.join(HERE, "logs")
    images_dir = os.path.join(data_dir, "images")
    videos_dir = os.path.join(data_dir, "videos")

    def _du(path: str) -> str:
        if not os.path.isdir(path):
            return "—"
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return f"{total / (1024 * 1024):.2f} MB"

    def _count(path: str) -> int:
        if not os.path.isdir(path):
            return 0
        n = 0
        for _, _, files in os.walk(path):
            n += len(files)
        return n

    posted_path = os.path.join(data_dir, "posted.json")
    posted_videos_path = os.path.join(data_dir, "posted_videos.json")
    events_path = os.path.join(data_dir, "events.jsonl")

    def _jload(path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    posted = _jload(posted_path) or {}
    posted_videos = _jload(posted_videos_path) or {}

    posted_count = len(posted) if isinstance(posted, dict) else 0
    posted_video_count = len(posted_videos) if isinstance(posted_videos, dict) else 0

    print()
    print("=" * 60)
    print(" AI News Bot — Status")
    print(" Time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)
    print(f"  Articles posted (cache):  {posted_count}")
    print(f"  Videos posted (cache):    {posted_video_count}")
    print(f"  Images on disk:           {_count(images_dir)}  ({_du(images_dir)})")
    print(f"  Videos on disk:           {_count(videos_dir)}  ({_du(videos_dir)})")
    print(f"  Logs size:                {_du(logs_dir)}")
    print(f"  Events.jsonl size:        "
          f"{os.path.getsize(events_path)/1024:.1f} KB"
          if os.path.isfile(events_path) else "  Events.jsonl size:        —")
    print("=" * 60)

    # Today's report (if any)
    today = datetime.now().strftime("%Y-%m-%d")
    rep = _jload(os.path.join(data_dir, f"report_{today}.json"))
    if rep:
        print(f"  Today's report ({today}):")
        for k, v in rep.items():
            print(f"    {k}: {v}")
        print("=" * 60)
    print()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="cli.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="Run the full bot (same as python main.py)")

    p_test = sub.add_parser("test", help="Test image or video pipeline once")
    p_test.add_argument("kind", choices=["image", "video"])

    p_src = sub.add_parser("sources", help="List image (RSS) or video sources")
    p_src.add_argument("kind", choices=["image", "video"])

    sub.add_parser("status", help="Print a snapshot of bot disk + cache state")

    # First parse known args, then forward the rest verbatim to the underlying script
    args, extra = p.parse_known_args()

    if args.cmd == "run":
        sys.exit(cmd_run(extra))
    if args.cmd == "test":
        sys.exit(cmd_test(args, extra))
    if args.cmd == "sources":
        sys.exit(cmd_sources(args))
    if args.cmd == "status":
        sys.exit(cmd_status())

    p.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
