# 🐈 Cat & Zoom Radar

A compact apartment scout for the oddly specific renter with a cat **and** video calls. It reads Storia's embedded `__NEXT_DATA__` search and detail JSON, normalizes listing facts, and asks TypeSafe AI's Jev bounded questions about pet policy, workspace, noise, outdoor space, agency fees, parking, utilities, and fine print. The offline report shows responsive photo cards, certainty dials, search, pet filtering, and nine cards per page.

Inspired by [mircea-popa02/real-estate-scraper](https://github.com/mircea-popa02/real-estate-scraper), especially its Storia search adapter and detail extraction. This is a smaller independent project with no MongoDB, browser automation, or service backend.

## Linux quick start

```bash
git clone https://github.com/mircea-popa02/cat-zoom-radar.git
cd cat-zoom-radar
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# JEV_API_KEY is already exported in your shell.
catzoom --transaction rent --city bucuresti-sector-6 --pages 2 --limit 10
xdg-open out/index.html
```

Location choices: `romania` (default), `bucuresti`, `bucuresti-sector-6`, and `cluj-napoca`. The two specific paths follow the supplied Storia examples. Use `--transaction sale --city cluj-napoca` for the Cluj sale search. New locations can be added to the `LOCATIONS` map in `storia.py` after verifying their Storia URL.

`out/listings.jsonl` is an accumulating, deduplicated collection keyed by transaction and Storia ID. A later run skips already detailed and classified listings **before fetching their detail page or spending Jev credits**. In `--no-jev` mode, detailed normalized listings are skipped; a later Jev run will enrich them. Failed detail or Jev results are retried on the next run. Use `--refresh` to refetch and reclassify, including listings from the previous version that lack images. `--limit` caps *new* listings per run, not the full saved collection. `out/` is ignored by Git.

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

The HTML report displays a photo when Storia JSON supplies an HTTPS image URL; old saved records without `image` or `images` show a placeholder until refreshed. Photos load from their original host when the report opens. The dial's percentage is the selected `choice` probability or, for yes/no questions, the probability of the chosen side. A high certainty in “unspecified” still means **there is no listing evidence**, not that an amenity exists.

## Data and decisions

Hard fields come from search and detail JSON: full detail description, price and deposit, area, rooms (including Storia's `ONE`/`TWO` enums), floor, search tags, grouped equipment/extras/media/security, building attributes, image URLs, seller, timestamps, and available location coordinates/street. The `attributes` bag preserves other detail attributes for inspection. If Storia omits the city but the search was city-specific, the city comes from that filter and `location.source` says `search_filter`. A missing street remains unknown; a description mention is not automatically promoted to a verified address. `--archive-raw` keeps complete JSON only in local `out/raw/` and may include seller contact details.

Jev receives the full normalized description up to 12,000 characters, amenities, building fields, price, and dimensions. It does not receive seller identity, precise address, coordinates, or photos. Its eight questions go in one API request per new listing. Choice probabilities below 0.72 and yes/no values between 0.2 and 0.8 display `review`. API errors leave the listing unclassified for a later retry. The 0–7 ranking is a sorting hint, with an explicit no-pets classification as a hard stop; missing evidence earns no positive points. Check all claims and costs with the advertiser. The TypeSafe [HTTP reference](https://docs.typesafe.ai/api) documents the typed `choice` and `noul` response shape.

## Crawl limits

One Storia request runs at a time with at least two seconds between requests. The collector checks `robots.txt`, restricts itself to `https://www.storia.ro`, and caps runs at three search pages and thirty new listings. It stops when search JSON or robots rules cannot be verified; a failed detail page is kept as a summary record and retried later. There is no CAPTCHA bypass, proxy rotation, or hidden API call.

Storia returned a CloudFront 403 to the development environment during this revision. Extraction changes were checked against the prior scraper's known JSON shapes, a 30-listing user-provided output sample, and synthetic raw JSON fixtures; live Storia extraction could not be confirmed here. The supplied sample showed all 30 old records missing image and normalized room fields, all 30 lacking street, and 24 lacking city. These gaps prompted the changes, but a source that omits address data cannot be made exhaustive by guessing.

License: MIT.
