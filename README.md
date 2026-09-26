# 🐈 Cat & Zoom Radar

A compact apartment scout for the oddly specific renter with a cat **and** video calls. It reads Storia's embedded `__NEXT_DATA__` search and detail JSON, normalizes listing facts, and asks TypeSafe AI's Jev bounded questions about pet policy, workspace, noise, outdoor space, agency fees, parking, utilities, and fine print. The offline report shows photo cards and certainty dials; the local workbench adds editable classifiers, weighted scoring, and lazy page-by-page Jev evaluation.

Inspired by [mircea-popa02/real-estate-scraper](https://github.com/mircea-popa02/real-estate-scraper), especially its Storia search adapter and detail extraction. This is a smaller independent project with no MongoDB, browser automation, or service backend.

## Linux quick start

```bash
git clone https://github.com/mircea-popa02/cat-zoom-radar.git
cd cat-zoom-radar
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Keep JEV_API_KEY exported in this same shell, then start the private UI.
catzoom serve --output out --port 8765
# Open http://127.0.0.1:8765, choose an area, and press Start crawl.

# Optional: collect from another shell while the UI remains open.
catzoom --transaction rent --city bucuresti-sector-6 --pages 2 --limit 10
```

Location choices: `romania` (default), `bucuresti`, `bucuresti-sector-6`, and `cluj-napoca`. The two specific paths follow the supplied Storia examples. Use `--transaction sale --city cluj-napoca` for the Cluj sale search. New locations can be added to the `LOCATIONS` map in `storia.py` after verifying their Storia URL.

`out/listings.jsonl` is an accumulating, deduplicated collection keyed by transaction and Storia ID. Each listing is saved atomically as soon as its detail fetch finishes, so the open UI shows it on the next two-second update even if the run later fails. A later run skips already detailed listings **before fetching their detail page**. The workbench classifies the visible page and caches each decision. `--classify-on-crawl` retains the old batch behavior and requires `JEV_API_KEY`; `--no-jev` is accepted for compatibility. Failed detail results are retried on the next run. Use `--refresh` to refetch listings from the previous version that lack images; the workbench evaluates changed listing content on request. `--limit` caps *new* listings per run, not the full saved collection. `out/` is ignored by Git.

```bash
# Fast, credit-free offline parser demo using synthetic fixtures.
catzoom --fixture fixtures/search.json --detail-fixture fixtures/detail.json --no-jev

# Rebuild the new UI from an earlier JSONL without scraping or Jev.
catzoom --render-only
catzoom --import-jsonl /path/to/old/listings.jsonl

# Inspect complete Storia JSON locally when adapting to a changed schema.
catzoom --city cluj-napoca --limit 2 --archive-raw
python3 -m unittest discover -s tests -v
```

The static HTML report displays a photo when Storia JSON supplies an HTTPS image URL; old saved records without `image` or `images` show a placeholder until refreshed. Photos load from their original host when the report opens. The dial's percentage is the selected `choice` probability or, for yes/no questions, the probability of the chosen side. A high certainty in “unspecified” still means **there is no listing evidence**, not that an amenity exists.

## Data and decisions

Hard fields come from search and detail JSON: full detail description, price and deposit, area, rooms (including Storia's `ONE`/`TWO` enums), floor, search tags, grouped equipment/extras/media/security, building attributes, image URLs, seller, timestamps, and available location coordinates/street. The `attributes` bag preserves other detail attributes for inspection. If Storia omits the city but the search was city-specific, the city comes from that filter and `location.source` says `search_filter`. A missing street remains unknown; a description mention is not automatically promoted to a verified address. `--archive-raw` keeps complete JSON only in local `out/raw/` and may include seller contact details.

Jev receives the normalized description up to 12,000 characters, amenities, building fields, price, and dimensions. It does not receive seller identity, precise address, coordinates, or photos. In the workbench, all missing active questions for one listing go in one API request; a page can make up to nine requests. Choice probabilities below 0.72 and yes/no values between 0.2 and 0.8 display `review`. API errors leave the listing unclassified for a later retry. The 0–7 ranking is a sorting hint, with an explicit no-pets classification as a hard stop; missing evidence earns no positive points. Check all claims and costs with the advertiser. The TypeSafe [HTTP reference](https://docs.typesafe.ai/api) documents the typed `choice` and `noul` response shape.


## Your own classifiers

Run `catzoom serve` to collect and classify from one local UI. Choose rent or sale, area, pages (1–3), and new listings (1–30), then press **Start crawl**. The counter and listing grid update while the crawler is running. **Stop** finishes the current Storia request and retains saved listings. A separate CLI crawl writing to the same output directory also appears automatically. The server binds **only** to `127.0.0.1`; the API key remains in the Python process, never in HTML or JavaScript. The workbench shows the newest 100 saved listings, nine per page. **Classify visible page as it appears** is enabled by default: new listings and opened pages get missing decisions when the key is available. Uncheck it to spend credits only with **Classify this page** or when adding a classifier. Missing answers are batched into one Jev call per listing, and cached by listing content plus question definition. Changing a weight or sorting does not call Jev again. Changes to the question or listing content require a new decision. A failed Jev call remains pending for a manual retry instead of being retried on every poll.

Open **Classifiers & weights** to adjust the four presets (cats, workspace, quiet clues, outdoor space), remove them, restore them, or add your own. Adding one saves the rule, clears the form, and immediately classifies the current page; later pages are classified when opened if automatic classification is enabled. A custom yes/no question has a preferred answer. A multiple-choice question has 2–5 named options, each with an evidence description and a score from -2 to 1. A rubric score has 2–5 ordered levels from least to most desirable; Jev’s weighted level contributes proportionally to its classifier weight when confidence is sufficient. The classifier weight ranges from 0 to 5. Questions are limited to 12–300 characters, names to 48, option and rubric descriptions to 160, and the workbench accepts at most 12 active classifiers. These bounds also apply on the server API.

The displayed 0–100 score divides earned weighted points by the possible positive points and clamps penalties at zero. An unknown, unclassified, or low-confidence (`review`) answer earns no points. It is a personal ranking, not a probability of liking the property. The result dials still show Jev answer certainty. Presets and saved decisions live in local `out/classifiers.json` and `out/classifications.json`; both are excluded from Git. The existing `out/listings.jsonl` is left intact. The server rejects cross-origin writes and does not expose the API key.

The `--render-only` command still makes a static, offline HTML snapshot. Use `catzoom serve` for live collection and interactive Jev decisions.

## Crawl limits

Each collector sends one Storia request at a time with at least two seconds between requests. The collector checks `robots.txt` and restricts itself to `https://www.storia.ro`; the UI caps runs at three search pages and thirty new listings. The CLI accepts its explicit `--pages` and `--limit` values. Collection stops when search JSON or robots rules cannot be verified; a failed detail page is kept as a summary record and retried later. There is no CAPTCHA bypass, proxy rotation, or hidden API call.

Storia returned a CloudFront 403 to the development environment during this revision. Extraction changes were checked against the prior scraper's known JSON shapes, a 30-listing user-provided output sample, and synthetic raw JSON fixtures; live Storia extraction could not be confirmed here. The supplied sample showed all 30 old records missing image and normalized room fields, all 30 lacking street, and 24 lacking city. These gaps prompted the changes, but a source that omits address data cannot be made exhaustive by guessing.

License: MIT.
