from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from config.portals import get_portal_config
from config.settings import get_settings
from database.db import init_db
from orchestrator import run_crawl


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gulf-crawler",
        description="Job Scraper — multi-portal Gulf job crawler",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="Run a crawl")
    crawl.add_argument("--portal", default="naukrigulf")
    crawl.add_argument(
        "--locations",
        required=True,
        help="Comma-separated location keys, e.g. dubai,abu-dhabi,riyadh",
    )
    crawl.add_argument(
        "--industry",
        default="it",
        help="Industry key (default: it). Use 'none' for all industries.",
    )
    crawl.add_argument("--max-pages", type=int, default=None)

    sub.add_parser("serve", help="Start FastAPI server for the frontend")
    sub.add_parser("init-db", help="Create database tables")

    meta = sub.add_parser("list-meta", help="List locations and industries")
    meta.add_argument("--portal", default="naukrigulf")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    _configure_logging(settings.log_level)

    if args.command == "init-db":
        init_db()
        print("Database tables created.")
        return 0

    if args.command == "list-meta":
        cfg = get_portal_config(args.portal)
        print("Locations:")
        for loc in cfg.locations.values():
            print(f"  {loc.key:12} {loc.label} ({loc.country})")
        print("Industries:")
        for key, ind in cfg.industries.items():
            print(f"  {key:16} {ind.label} (ClusterInd={ind.cluster_ind})")
        return 0

    if args.command == "serve":
        uvicorn.run(
            "api.app:app",
            host=settings.api_host,
            port=settings.api_port,
            reload=False,
        )
        return 0

    if args.command == "crawl":
        locations = [x.strip() for x in args.locations.split(",") if x.strip()]
        industry = None if args.industry.lower() in {"none", "all", ""} else args.industry
        result = run_crawl(
            portal=args.portal,
            locations=locations,
            industry=industry,
            max_pages=args.max_pages,
        )
        print(
            f"success={result.success} found={result.jobs_found} "
            f"new={result.jobs_new} pages={result.pages_crawled} "
            f"reason={result.stop_reason}"
        )
        if result.error:
            print(f"error={result.error}", file=sys.stderr)
            return 1
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())