"""Small, bounded Storia __NEXT_DATA__ collector and deterministic normalizer."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

HOST = "www.storia.ro"
USER_AGENT = "CatZoomRadar/0.1 (+personal research; respectful crawler)"


class _NextData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.inside = True

    def handle_data(self, data):
        if self.inside:
            self.chunks.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []

    def handle_data(self, data):
        self.chunks.append(data)


def next_data(html):
    parser = _NextData()
    parser.feed(html)
    if not parser.chunks:
        raise ValueError("No __NEXT_DATA__ JSON; page may have changed or returned a challenge")
    return json.loads("".join(parser.chunks))


def clean_html(value):
    parser = _Text()
    parser.feed(str(value or ""))
    return re.sub(r"\s+", " ", " ".join(parser.chunks)).strip()


def number(value):
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def search_url(transaction, page):
    kind = "inchiriere" if transaction == "rent" else "vanzare"
    return f"https://{HOST}/ro/rezultate/{kind}/apartament/toata-romania?page={page}&by=LATEST&direction=DESC"


def _location(ad):
    places = ((ad.get("location") or {}).get("reverseGeocoding") or {}).get("locations") or []
    city = next((x.get("name") for x in places if x.get("locationLevel") in ("city", "town", "county_capital")), None)
    district = next((x.get("name") for x in places if x.get("locationLevel") == "district"), None)
    return {"city": city, "district": district}


def _tag_values(ad):
    attrs = ad.get("attributes") or {}
    tags = [x.get("value") for x in ad.get("tags") or [] if isinstance(x, dict)]
    for key in ("equipment_types", "extras_types", "media_types", "security_types"):
        value = attrs.get(key) or []
        tags.extend(value if isinstance(value, list) else [value])
    return sorted({str(x) for x in tags if x})


def normalize(summary, detail=None, transaction="rent"):
    detail = detail or {}
    attrs = detail.get("attributes") or {}
    target = detail.get("target") or {}
    price = detail.get("price") or detail.get("totalPrice") or summary.get("totalPrice") or {}
    if not isinstance(price, dict):
        price = {}
    area = number(detail.get("areaInSquareMeters") or summary.get("areaInSquareMeters") or target.get("Area"))
    value = number(price.get("value") or target.get("Price"))
    slug = summary.get("slug") or detail.get("slug") or str(summary["id"])
    # Slugs are path components only, never an arbitrary URL from site JSON.
    slug = re.sub(r"[^\w-]", "", str(slug), flags=re.UNICODE)
    description = clean_html(detail.get("description") or summary.get("shortDescription"))
    loc = _location(detail) if _location(detail)["city"] else _location(summary)
    owner = detail.get("ownerAccount") or detail.get("agency") or summary.get("agency") or summary.get("advertOwner") or {}
    return {
        "id": str(summary["id"]), "url": f"https://{HOST}/ro/oferta/{slug}",
        "transaction": transaction, "title": clean_html(detail.get("title") or summary.get("title")),
        "description": description,
        "price": {"value": value, "currency": price.get("currency") or "EUR", "per_sqm": round(value / area, 2) if value is not None and area and area > 0 else None,
                  "deposit": number((price.get("deposit") or {}).get("value")) if isinstance(price.get("deposit"), dict) else None},
        "area_sqm": area, "rooms": number(detail.get("roomsNumber") or summary.get("roomsNumber") or target.get("Rooms")),
        "floor": detail.get("floor_no") or attrs.get("floor_no") or detail.get("floorNumber") or summary.get("floorNumber"),
        "building_year": number(attrs.get("build_year")),
        "location": loc, "street": clean_html((detail.get("location") or {}).get("streetName")),
        "features": sorted(set(_tag_values(summary) + _tag_values(detail))),
        "seller": {"name": owner.get("name"), "agency": bool(detail.get("agency") or summary.get("agency"))},
        "listed_at": detail.get("createdAtFirst") or summary.get("createdAtFirst"),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "detail_found": bool(detail),
    }


def summaries(payload):
    try:
        items = payload["props"]["pageProps"]["data"]["searchAds"]["items"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Storia search JSON shape changed") from exc
    if not isinstance(items, list):
        raise ValueError("Storia search items are not a list")
    return [item for item in items if isinstance(item, dict) and item.get("id")]


def detail_ad(payload):
    try:
        ad = payload["props"]["pageProps"]["ad"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Storia detail JSON shape changed") from exc
    if not isinstance(ad, dict):
        raise ValueError("Storia detail ad is not an object")
    return ad


class Collector:
    def __init__(self, delay=3.0):
        self.delay = max(2.0, delay)
        self.last_request = 0.0
        robots_url = f"https://{HOST}/robots.txt"
        try:
            with urlopen(Request(robots_url, headers={"User-Agent": USER_AGENT}), timeout=15) as response:
                body = response.read(500_000).decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError("Cannot verify Storia robots.txt; stopping crawl") from exc
        self.robots = RobotFileParser()
        self.robots.parse(body.splitlines())

    def fetch(self, url):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != HOST or parsed.port is not None:
            raise ValueError("Only HTTPS Storia URLs are allowed")
        if not self.robots.can_fetch(USER_AGENT, url):
            raise RuntimeError(f"robots.txt disallows {parsed.path}; stopping crawl")
        pause = self.delay - (time.monotonic() - self.last_request)
        if pause > 0:
            time.sleep(pause)
        self.last_request = time.monotonic()
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=20) as response:
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise ValueError("Page exceeds 4 MB")
                return raw.decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"Fetch failed for {url}: {exc}") from exc

    def collect(self, transaction="rent", pages=1, limit=10):
        seen = set()
        for page in range(1, pages + 1):
            for item in summaries(next_data(self.fetch(search_url(transaction, page)))):
                if len(seen) >= limit:
                    return
                key = str(item["id"])
                if key in seen:
                    continue
                seen.add(key)
                base = normalize(item, transaction=transaction)
                try:
                    detail = detail_ad(next_data(self.fetch(base["url"])))
                    yield normalize(item, detail, transaction)
                except (ValueError, RuntimeError) as exc:
                    base["detail_error"] = str(exc)
                    yield base
