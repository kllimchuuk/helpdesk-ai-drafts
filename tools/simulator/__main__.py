import argparse
import asyncio
import json
import os

from simulator.report import render
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
    parser.add_argument("--json", dest="json_path", default=None)
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


def main() -> None:
    options, json_path = parse()
    summary = asyncio.run(run(options)).summary()
    print(render(summary))
    if json_path:
        with open(json_path, "w", encoding="utf-8") as output:
            json.dump(summary, output, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
