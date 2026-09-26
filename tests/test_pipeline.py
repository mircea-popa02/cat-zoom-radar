import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catzoom.cli import main
from catzoom.jev import QUESTIONS, parse_answer, payload
from catzoom.report import render, score
from catzoom.storia import detail_ad, next_data, normalize, summaries

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

    def test_offline_cli(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"JEV_API_KEY": ""}):
                code = main(["--fixture", str(ROOT / "fixtures/search.json"), "--detail-fixture", str(ROOT / "fixtures/detail.json"), "--no-jev", "--output", tmp])
            self.assertEqual(code, 0)
            records = [json.loads(x) for x in (Path(tmp) / "listings.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0]["jev"])


if __name__ == "__main__":
    unittest.main()
