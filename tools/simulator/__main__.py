import argparse
import asyncio
import json
import os
import sys

from simulator.report import problems, render
from simulator.run import Options, run


def parse(argv: list[str] | None = None) -> tuple[Options, str | None]:
    parser = argparse.ArgumentParser(
        prog="simulator",
        description="Send helpdesk webhooks and measure the pipeline (SPEC §11).",
    )
    parser.add_argument("--base-url", default="http://backend:8000")
    parser.add_argument("--mock-url", default="http://mock-helpdesk:8000")
    parser.add_argument("--reply-host", default="mock-helpdesk:8000")
    parser.add_argument("--events", type=int, default=500)
    parser.add_argument("--duration", type=float, default=600.0)
    parser.add_argument("--duplicate-rate", type=float, default=0.1)
    parser.add_argument("--concurrent-duplicates", type=int, default=3)
    parser.add_argument(
        "--approve",
        action="store_true",
        help="approve this run's drafts through the operator API, so they are sent",
    )
    parser.add_argument("--drain-timeout", type=float, default=900.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="also write the summary as JSON to this file, or to stdout with '-'",
    )
    args = parser.parse_args(argv)
    if args.events < 1 or args.duration < 0 or not 0 <= args.duplicate_rate <= 1:
        parser.error("events must be positive, duration and duplicate rate in range")
    options = Options(
        base_url=args.base_url,
        mock_url=args.mock_url,
        reply_host=args.reply_host,
        events=args.events,
        duration=args.duration,
        duplicate_rate=args.duplicate_rate,
        concurrent_duplicates=args.concurrent_duplicates,
        approve=args.approve,
        operator=(
            os.environ.get("OPERATOR_USER", "operator"),
            os.environ.get("OPERATOR_PASSWORD", "operator"),
        ),
        drain_timeout=args.drain_timeout,
        seed=args.seed,
    )
    return options, args.json_path


def write_json(summary: dict[str, object], path: str) -> None:
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if path == "-":
        print(text)
        return
    with open(path, "w", encoding="utf-8") as output:
        output.write(text)


def main() -> None:
    options, json_path = parse()
    summary = asyncio.run(run(options)).summary()
    print(render(summary))
    if json_path:
        write_json(summary, json_path)
    found = problems(summary)
    for problem in found:
        print(f"FAILED: {problem}", file=sys.stderr)
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
