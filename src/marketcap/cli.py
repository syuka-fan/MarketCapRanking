import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from marketcap.calendar import regular_session_open
from marketcap.closes import YahooHistory, download_closes, read_symbols
from marketcap.demo import generate
from marketcap.export import export_site
from marketcap.inspection import inspect_universe
from marketcap.models import DataError, Settings
from marketcap.pipeline import run
from marketcap.providers.yahoo import YahooProvider
from marketcap.provisional import collect_provisional
from marketcap.storage import atomic_json


def main() -> int:
    parser = argparse.ArgumentParser(description="US regular-close market-cap rankings")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect-universe",
        help="Inspect every US candidate and preview cap ordering; no daily snapshot",
    )
    inspect.add_argument("--settings", type=Path, default=Path("config/settings.json"))
    inspect.add_argument("--data-dir", type=Path, default=Path("data"))
    inspect.add_argument(
        "--archive", type=Path, help="Reuse an inspection bundle without network calls"
    )
    closes = commands.add_parser("download-closes", help="Download incremental US daily closes")
    closes.add_argument("--data-dir", type=Path, default=Path("data"))
    closes.add_argument("--settings", type=Path, default=Path("config/settings.json"))
    closes.add_argument("--symbols", type=Path, default=Path("config/symbols.json"))
    closes.add_argument("--tickers", help="Comma-separated subset from the symbols file")
    closes.add_argument("--start", type=date.fromisoformat, help="Inclusive US trade date")
    closes.add_argument("--end", type=date.fromisoformat, help="Inclusive US trade date")
    closes.add_argument("--refresh", action="store_true", help="Re-download all stored history")
    collect = commands.add_parser(
        "collect", help="Collect the latest closed session; recover archives"
    )
    collect.add_argument("--data-dir", type=Path, default=Path("data"))
    collect.add_argument("--settings", type=Path, default=Path("config/settings.json"))
    collect.add_argument("--from", dest="start", type=date.fromisoformat)
    collect.add_argument("--to", dest="end", type=date.fromisoformat)
    collect.add_argument(
        "--refresh", action="store_true", help="Reprocess archived closing bundles"
    )
    collect.add_argument(
        "--allow-provisional",
        action="store_true",
        help="Publish separate intraday quotes when open",
    )
    export = commands.add_parser("export", help="Export stored snapshots for the static site")
    export.add_argument("--data-dir", type=Path, default=Path("data"))
    export.add_argument("--output", type=Path, default=Path("web/public/data"))
    demo = commands.add_parser("demo", help="Generate clearly labeled fictional preview data")
    demo.add_argument("--data-dir", type=Path, default=Path("demo-data"))
    check = commands.add_parser(
        "probe", help="Fetch one small live batch without publishing rankings"
    )
    check.add_argument("--settings", type=Path, default=Path("config/settings.json"))
    check.add_argument("--size", type=int, default=3, choices=range(1, 11), metavar="1..10")
    check.add_argument("--output", type=Path, default=Path("data/probe.json"))
    args = parser.parse_args()
    try:
        if args.command == "inspect-universe":
            provider = YahooProvider(Settings.read(args.settings), args.data_dir)
            bundle = json.loads(args.archive.read_text()) if args.archive else None
            result = inspect_universe(provider, bundle)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "download-closes":
            symbols = read_symbols(args.symbols, args.tickers)
            provider = YahooHistory(Settings.read(args.settings))
            result = download_closes(
                provider,
                symbols,
                args.data_dir,
                start=args.start,
                end=args.end,
                refresh=args.refresh,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 1 if result["state"] == "incomplete" else 0
        if args.command == "collect":
            settings = Settings.read(args.settings)
            provider = YahooProvider(settings, args.data_dir)
            if (
                args.allow_provisional
                and not (args.start or args.end or args.refresh)
                and regular_session_open(datetime.now(UTC))
            ):
                result = collect_provisional(provider)
            else:
                result = run(
                    provider,
                    settings,
                    args.data_dir,
                    start=args.start,
                    end=args.end,
                    refresh=args.refresh,
                )
            print(json.dumps(result, ensure_ascii=False))
            return 1 if result["state"] == "incomplete" else 0
        if args.command == "probe":
            settings = Settings.read(args.settings)
            provider = YahooProvider(settings, args.output.parent)
            page = provider.screen(0, args.size)
            report = {
                "source": "yahoo",
                "scope": "connectivity_probe_not_closing_rankings",
                "checked_at": datetime.now(UTC).isoformat(),
                "http_requests": provider.requests_made,
                "reported_total": page.get("total"),
                "quotes": [
                    {
                        k: q.get(k)
                        for k in (
                            "symbol",
                            "longName",
                            "regularMarketPrice",
                            "regularMarketTime",
                            "marketState",
                            "marketCap",
                            "currency",
                        )
                    }
                    for q in page["quotes"]
                ],
            }
            atomic_json(args.output, report)
            print(
                f"Yahoo probe: {len(report['quotes'])} quotes, "
                f"{report['http_requests']} HTTP requests. Report: {args.output}"
            )
        elif args.command == "export":
            export_site(args.data_dir, args.output)
        else:
            generate(args.data_dir)
        return 0
    except (DataError, OSError, ValueError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
