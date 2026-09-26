import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from .jev import evaluate
from .report import render
from .storia import LOCATIONS, Collector, detail_ad, normalize, summaries


def _read_records(path):
    if not path.exists():
        return {}
    records = {}
    for line in path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            listing = record["listing"]
            records[(listing["transaction"], str(listing["id"]))] = record
    return records


def _save_records(path, records):
    # Replace only after the complete crawl has produced valid records.
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        for record in records.values():
            tmp.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "serve":
        from .server import serve_main
        return serve_main(argv[1:])
    parser = argparse.ArgumentParser(description="Storia listings + bounded Jev apartment clues")
    parser.add_argument("--transaction", choices=["rent", "sale"], default="rent")
    parser.add_argument("--location", "--city", choices=sorted(LOCATIONS), default="romania", help="Storia search area")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--delay", type=float, default=3.0, help="minimum seconds between Storia requests (floor: 2)")
    parser.add_argument("--fixture", type=Path, help="offline __NEXT_DATA__ search JSON fixture")
    parser.add_argument("--detail-fixture", type=Path, help="offline __NEXT_DATA__ detail JSON fixture")
    parser.add_argument("--no-jev", action="store_true", help="compatibility alias; normalization is the default")
    parser.add_argument("--classify-on-crawl", action="store_true", help="legacy mode: evaluate all new listings during crawling")
    parser.add_argument("--refresh", action="store_true", help="refetch and reclassify previously processed listings")
    parser.add_argument("--archive-raw", action="store_true", help="save full local Storia JSON under out/raw for parser research")
    parser.add_argument("--render-only", action="store_true", help="rebuild HTML from existing JSONL without scraping or Jev")
    parser.add_argument("--import-jsonl", type=Path, help="merge an existing saved JSONL and rebuild HTML without network")
    parser.add_argument("--model", default="jev-latest")
    parser.add_argument("--output", type=Path, default=Path("out"))
    args = parser.parse_args(argv)
    if not 1 <= args.pages <= 3 or not 1 <= args.limit <= 30:
        parser.error("pages must be 1–3 and limit 1–30")
    if args.detail_fixture and not args.fixture:
        parser.error("--detail-fixture requires --fixture")
    if args.no_jev and args.classify_on_crawl:
        parser.error("Choose either --no-jev or --classify-on-crawl")
    if args.import_jsonl and not args.import_jsonl.is_file():
        parser.error(f"Import file does not exist: {args.import_jsonl}")
    key = os.environ.get("JEV_API_KEY")
    if args.classify_on_crawl and not key:
        parser.error("JEV_API_KEY is missing; export it or omit --classify-on-crawl")
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        output_file = args.output / "listings.jsonl"
        records = _read_records(output_file)
        if args.import_jsonl:
            records.update(_read_records(args.import_jsonl))
        if args.render_only or args.import_jsonl:
            _save_records(output_file, records)
            (args.output / "index.html").write_text(render(list(records.values())))
            print(f"Rendered {len(records)} saved listings in {args.output.resolve()}")
            return 0
        skip_ids = {key[1] for key, record in records.items() if key[0] == args.transaction and record["listing"].get("detail_found") and
                    (not args.classify_on_crawl or record.get("jev"))} if not args.refresh else set()
        if args.fixture:
            detail = detail_ad(json.loads(args.detail_fixture.read_text())) if args.detail_fixture else None
            items = (normalize(s, detail if detail and str(s["id"]) == str(detail.get("id")) else None, args.transaction, args.location)
                     for s in summaries(json.loads(args.fixture.read_text())) if str(s["id"]) not in skip_ids)
        else:
            items = Collector(args.delay, args.output / "raw" if args.archive_raw else None).collect(args.transaction, args.pages, args.limit, args.location, skip_ids)
        new_count = 0
        for listing in items:
            if new_count >= args.limit:
                break
            record = {"listing": listing, "jev": None}
            if args.classify_on_crawl:
                try:
                    record["jev"] = evaluate(listing, key, args.model)
                except (RuntimeError, ValueError) as exc:
                    record["jev_error"] = str(exc)
            records[(listing["transaction"], listing["id"])] = record
            new_count += 1
            print(f"[{new_count}] {listing['title']} — {'classified' if record['jev'] else 'unclassified'}")
        _save_records(output_file, records)
        (args.output / "index.html").write_text(render(list(records.values())))
        print(f"Processed {new_count} new listings; {len(records)} total in {args.output.resolve()}")
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"catzoom: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
