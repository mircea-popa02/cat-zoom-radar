# 🐈 Cat & Zoom Radar

A tiny apartment scout for the unusually specific renter who has a cat **and** takes video calls. It reads Storia's embedded `__NEXT_DATA__` JSON, visits a bounded number of detail pages, normalizes prices and physical fields, and asks TypeSafe AI's Jev five typed questions: pet policy, private workspace, noise clues, outdoor space, and fine print. Open the offline HTML report to sort through the clues. Unknown or uncertain answers stay visible.

Inspired by [mircea-popa02/real-estate-scraper](https://github.com/mircea-popa02/real-estate-scraper), particularly its Storia search adapter and detail extraction. This is an independent small project: no MongoDB, browser, proxy, or dashboard service.

## Linux quick start

```bash
git clone https://github.com/mircea-popa02/cat-zoom-radar.git
cd cat-zoom-radar
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# You already exported JEV_API_KEY in this shell.
catzoom --transaction rent --pages 1 --limit 5
xdg-open out/index.html
```

`out/listings.jsonl` has the normalized facts and Jev results; `out/index.html` is a self-contained local report. Each listing costs one Jev request containing five questions. Start with `--limit 2` if you want to keep credit use tiny. Set `--model` to a pinned Jev version if you need repeatable thresholds. No API key is written to the output.

## Offline first

```bash
catzoom --fixture fixtures/search.json --detail-fixture fixtures/detail.json --no-jev
catzoom --fixture fixtures/search.json --detail-fixture fixtures/detail.json --limit 1
python3 -m unittest discover -s tests -v
```

The fixtures are **synthetic**, not scraped listings. The first command uses no network and no Jev credits; the second makes exactly one Jev request if your key is set. Offline normalization does not pretend to classify anything.

## How the judgments work

Numerical price, floor, location, size, and feature tags come directly from listing JSON. Jev only makes bounded choices based on text and tags. A probability below 0.72 on a choice or between 0.2 and 0.8 on the fine-print question is marked `review`. The report's 0–7 score is a simple sorting hint; a stated no-pets policy scores zero. Silence about pets or workspace earns no points. Descriptions are claims from advertisers, so verify pet permission, noise, and all costs yourself. The request sends title, description (up to 6,000 characters), tags, floor, room count, area, and transaction to Jev; it omits seller name and street.

## Crawl behavior

The collector uses one request at a time with at least two seconds between requests, checks `robots.txt` before crawling, accepts only `https://www.storia.ro` URLs, and caps runs at three search pages and thirty listings. It stops on a blocked search page, missing `__NEXT_DATA__`, or robot rules it cannot verify. A failed detail page produces a summary record with `detail_error` and remains unclassified or gets only summary-based Jev clues; no challenge bypass is attempted. Storia can change its JSON shape, policies, or access controls: use offline fixtures to adjust the parser, and follow the site's current terms.

Jev API errors leave the listing unclassified and add `jev_error` to JSONL. There is no silent fallback, retry storm, or fabricated confidence. The TypeSafe [HTTP reference](https://docs.typesafe.ai/api) describes `POST /v1/systemone`, its `choice` and `noul` question shapes, and the `answers` response map.

License: MIT.
