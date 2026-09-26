import argparse
import json
import os
import sys
from pathlib import Path

from .jev import evaluate
from .report import render
from .storia import Collector, detail_ad, next_data, normalize, summaries


def main(argv=None):
    parser = argparse.ArgumentParser(description="Storia listings + bounded Jev apartment clues")
    parser.add_argument("--transaction", choices=["rent", "sale"], default="rent")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--delay", type=float, default=3.0, help="minimum seconds between Storia requests (floor: 2)")
    parser.add_argument("--fixture", type=Path, help="offline __NEXT_DATA__ search JSON fixture")
    parser.add_argument("--detail-fixture", type=Path, help="offline __NEXT_DATA__ detail JSON fixture")
    parser.add_argument("--no-jev", action="store_true", help="normalize only; spend no API credits")
    parser.add_argument("--model", default="jev-latest")
    parser.add_argument("--output", type=Path, default=Path("out"))
    args = parser.parse_args(argv)
    if not 1 <= args.pages <= 3 or not 1 <= args.limit <= 30:
        parser.error("pages must be 1–3 and limit 1–30")
    if args.detail_fixture and not args.fixture:
        parser.error("--detail-fixture requires --fixture")
    key = os.environ.get("JEV_API_KEY")
    if not args.no_jev and not key:
        parser.error("JEV_API_KEY is missing; export it or use --no-jev")
    try:
        if args.fixture:
            detail = detail_ad(json.loads(args.detail_fixture.read_text())) if args.detail_fixture else None
            items = (normalize(s, detail if detail and str(s["id"]) == str(detail.get("id")) else None, args.transaction)
                     for s in summaries(json.loads(args.fixture.read_text())))
        else:
            items = Collector(args.delay).collect(args.transaction, args.pages, args.limit)
        args.output.mkdir(parents=True, exist_ok=True)
        records = []
        for listing in items:
            if len(records) >= args.limit:
                break
            record = {"listing": listing, "jev": None}
            if not args.no_jev:
                try:
                    record["jev"] = evaluate(listing, key, args.model)
                except (RuntimeError, ValueError) as exc:
                    record["jev_error"] = str(exc)
            records.append(record)
            print(f"[{len(records)}] {listing['title']} — {'classified' if record['jev'] else 'unclassified'}")
        (args.output / "listings.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        (args.output / "index.html").write_text(render(records))
        print(f"Wrote {len(records)} listings to {args.output.resolve()}")
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"catzoom: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
