import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catzoom.cli import main
from catzoom.jev import QUESTIONS, parse_answer, payload
from catzoom.report import render, score
from catzoom.storia import Collector, detail_ad, next_data, normalize, search_url, summaries

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def fixture_listing(self):
        search = json.loads((ROOT / "fixtures/search.json").read_text())
        detail = json.loads((ROOT / "fixtures/detail.json").read_text())
        return normalize(summaries(search)[0], detail_ad(detail))

    def test_extract_and_normalize_detail(self):
        listing = self.fixture_listing()
        self.assertEqual(listing["id"], "123")
        self.assertEqual(listing["location"]["district"], "Titan")
        self.assertEqual(listing["price"]["per_sqm"], 11.92)
        self.assertEqual(listing["price"]["deposit"], 620)
        self.assertIn("Comision agenție", listing["description"])
        self.assertEqual(listing["building_year"], 2018)
        self.assertEqual(listing["rooms"], 2)
        self.assertEqual(listing["image"], "https://cdn.example.test/room.jpg")
        self.assertIn("internet", listing["amenities"]["equipment_types"])

    def test_html_json_extraction(self):
        raw = (ROOT / "fixtures/search.json").read_text()
        self.assertEqual(len(summaries(next_data(f'<script id="__NEXT_DATA__">{raw}</script>'))), 1)

    def test_jev_request_excludes_identifying_fields_and_handles_uncertainty(self):
        listing = self.fixture_listing()
        listing["description"] = "<script>alert('x')</script>"
        state = payload(listing)["state"]
        self.assertNotIn("seller", state)
        self.assertNotIn("street", state)
        answers = {}
        for key, q in QUESTIONS.items():
            if q["type"] == "choice":
                options = list(q["criteria"])
                answers[key] = {"type": "choice", "choice": options[0], "probabilities": {options[0]: .6}}
            else:
                answers[key] = {"type": "noul", "noul": .5}
        result = parse_answer({"model": "jev-latest", "answers": answers})
        self.assertEqual(result["signals"]["pets"]["value"], "review")
        self.assertEqual(result["signals"]["fine_print"]["value"], "review")
        page = render([{"listing": listing, "jev": result}])
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_forbidden_cat_is_hard_stop(self):
        signals = {"pets": {"value": "forbidden"}, "workspace": {"value": "dedicated"}}
        self.assertEqual(score({"jev": {"signals": signals}}), 0)

    def test_city_urls_and_provenance(self):
        self.assertIn("/bucuresti/sectorul-6?", search_url("rent", 1, "bucuresti-sector-6"))
        self.assertIn("/cluj/cluj--napoca?", search_url("sale", 2, "cluj-napoca"))
        item = {"id": 7, "slug": "test", "location": {}}
        listing = normalize(item, search_location="cluj-napoca")
        self.assertEqual(listing["location"]["city"], "Cluj-Napoca")
        self.assertEqual(listing["location"]["source"], "search_filter")

    def test_collector_skips_existing_before_detail_fetch(self):
        search = (ROOT / "fixtures/search.json").read_text()
        collector = object.__new__(Collector)
        calls = []
        collector.raw_dir = None
        def fake_fetch(url):
            calls.append(url)
            return f'<script id="__NEXT_DATA__">{search}</script>'
        collector.fetch = fake_fetch
        self.assertEqual(list(collector.collect(skip_ids={"123"})), [])
        self.assertEqual(len(calls), 1)

    def test_offline_cli(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"JEV_API_KEY": ""}):
                code = main(["--fixture", str(ROOT / "fixtures/search.json"), "--detail-fixture", str(ROOT / "fixtures/detail.json"), "--no-jev", "--output", tmp])
            self.assertEqual(code, 0)
            records = [json.loads(x) for x in (Path(tmp) / "listings.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0]["jev"])
            with patch.dict("os.environ", {"JEV_API_KEY": ""}):
                self.assertEqual(main(["--fixture", str(ROOT / "fixtures/search.json"), "--detail-fixture", str(ROOT / "fixtures/detail.json"), "--no-jev", "--output", tmp]), 0)
            self.assertEqual(len((Path(tmp) / "listings.jsonl").read_text().splitlines()), 1)
            page = (Path(tmp) / "index.html").read_text()
            self.assertIn("class=\"grid\"", page)
            self.assertIn("cdn.example.test/room.jpg", page)
            self.assertIn("id=\"next\"", page)


if __name__ == "__main__":
    unittest.main()
