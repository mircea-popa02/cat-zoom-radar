"""Small, bounded Storia __NEXT_DATA__ collector and deterministic normalizer."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

HOST = "www.storia.ro"
USER_AGENT = "CatZoomRadar/0.2 (+personal research; respectful crawler)"
LOCATIONS = {
    "romania": "toata-romania",
    "bucuresti": "bucuresti",
    "bucuresti-sector-6": "bucuresti/sectorul-6",
    "cluj-napoca": "cluj/cluj--napoca",
}


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
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def rooms(value):
    mapping = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10}
    return number(value) if number(value) is not None else mapping.get(str(value).upper())


def search_url(transaction, page, location="romania"):
    if location not in LOCATIONS:
        raise ValueError(f"Unsupported location: {location}")
    kind = "inchiriere" if transaction == "rent" else "vanzare"
    query = urlencode({"page": page, "by": "LATEST", "direction": "DESC", "ownerTypeSingleSelect": "ALL"})
    return f"https://{HOST}/ro/rezultate/{kind}/apartament/{LOCATIONS[location]}?{query}"


def _location(ad):
    loc = ad.get("location") or {}
    places = (loc.get("reverseGeocoding") or {}).get("locations") or []
    city = next((x.get("name") for x in places if isinstance(x, dict) and x.get("locationLevel") in ("city", "town", "county_capital")), None)
    district = next((x.get("name") for x in places if isinstance(x, dict) and x.get("locationLevel") == "district"), None)
    coordinates = loc.get("coordinates") or {}
    lat, lng = number(coordinates.get("latitude")), number(coordinates.get("longitude"))
    street = clean_html(loc.get("streetName") or loc.get("address"))
    building_number = clean_html(loc.get("buildingNumber"))
    if street and building_number and building_number not in street:
        street = f"{street} {building_number}"
    return {"city": city, "district": district, "street": street,
            "coordinates": {"latitude": lat, "longitude": lng} if lat is not None and lng is not None else None}


def _tag_values(value):
    if not isinstance(value, list):
        value = [value] if value else []
    values = [x.get("value") or x.get("name") or x.get("key") if isinstance(x, dict) else x for x in value]
    return sorted({str(x) for x in values if x is not None and x != ""})


def _attributes(ad):
    attrs = ad.get("attributes") or {}
    if isinstance(attrs, list):
        attrs = {str(x.get("key") or x.get("code")): x.get("value") for x in attrs if isinstance(x, dict) and (x.get("key") or x.get("code"))}
    return attrs if isinstance(attrs, dict) else {}


def _images(ad):
    images = []
    for item in ad.get("images") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("large") or item.get("medium") or item.get("small")
        if isinstance(url, str) and url.startswith("//"):
            url = "https:" + url
        if isinstance(url, str) and urlparse(url).scheme == "https" and urlparse(url).hostname:
            images.append(url)
    return list(dict.fromkeys(images))


def normalize(summary, detail=None, transaction="rent", search_location="romania"):
    detail = detail or {}
    attrs = _attributes(detail)
    target = detail.get("target") or {}
    price = next((x for x in (detail.get("price"), detail.get("totalPrice"), summary.get("totalPrice")) if isinstance(x, dict) and x.get("value") is not None), {})
    area = next((x for x in (number(detail.get("areaInSquareMeters")), number(summary.get("areaInSquareMeters")), number(target.get("Area"))) if x is not None), None)
    value = number(price.get("value"))
    slug = summary.get("slug") or detail.get("slug") or str(summary["id"])
    # Slugs are path components only, never an arbitrary URL from site JSON.
    slug = re.sub(r"[^\w-]", "", str(slug), flags=re.UNICODE)
    description = clean_html(detail.get("description")) or clean_html(summary.get("shortDescription"))
    loc, fallback = _location(detail), _location(summary)
    for key in ("city", "district", "street", "coordinates"):
        loc[key] = loc[key] or fallback[key]
    loc["source"] = "listing_json" if loc["city"] else "unknown"
    if not loc["city"] and search_location != "romania":
        loc["city"] = "Cluj-Napoca" if search_location == "cluj-napoca" else "București"
        if search_location == "bucuresti-sector-6" and not loc["district"]:
            loc["district"] = "Sector 6"
        loc["source"] = "search_filter"
    owner = detail.get("ownerAccount") or detail.get("agency") or summary.get("agency") or summary.get("advertOwner") or {}
    if not isinstance(owner, dict):
        owner = {}
    amenities = {key: _tag_values(attrs.get(key)) for key in ("equipment_types", "extras_types", "media_types", "security_types")}
    amenities["search_tags"] = _tag_values(summary.get("tags"))
    images = _images(detail) or _images(summary)
    deposit = price.get("deposit")
    deposit = number(deposit.get("value")) if isinstance(deposit, dict) else number(deposit)
    return {
        "id": str(summary["id"]), "url": f"https://{HOST}/ro/oferta/{slug}",
        "transaction": transaction, "title": clean_html(detail.get("title") or summary.get("title")),
        "description": description, "description_source": "detail" if detail.get("description") else "summary",
        "price": {"value": value, "currency": price.get("currency") or "EUR", "per_sqm": round(value / area, 2) if value is not None and area and area > 0 else None,
                  "deposit": deposit, "price_per_sqm_advertised": number(attrs.get("price_per_m"))},
        "area_sqm": area, "rooms": rooms(detail.get("roomsNumber") or summary.get("roomsNumber") or target.get("Rooms")),
        "floor": detail.get("floor_no") or attrs.get("floor_no") or detail.get("floorNumber") or summary.get("floorNumber"),
        "building_year": number(attrs.get("build_year")),
        "building": {key: attrs.get(key) for key in ("build_year", "building_floors_num", "building_type", "building_material", "construction_status", "heating")},
        "location": loc, "street": loc["street"],
        "search_area": search_location,
        "amenities": amenities, "features": sorted(set(sum(amenities.values(), []))), "attributes": attrs,
        "images": images, "image": images[0] if images else None,
        "seller": {"name": owner.get("name"), "agency": bool(detail.get("agency") or summary.get("agency")), "address": owner.get("address")},
        "listed_at": detail.get("createdAtFirst") or summary.get("createdAtFirst"),
        "pushed_up_at": detail.get("pushedUpAt") or summary.get("pushedUpAt"),
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
    def __init__(self, delay=3.0, raw_dir=None):
        self.delay = max(2.0, delay)
        self.last_request = 0.0
        self.raw_dir = Path(raw_dir) if raw_dir else None
        if self.raw_dir:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
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

    def collect(self, transaction="rent", pages=1, limit=10, location="romania", skip_ids=()):
        seen = set(skip_ids)
        yielded = 0
        for page in range(1, pages + 1):
            search_payload = next_data(self.fetch(search_url(transaction, page, location)))
            self._archive(f"search-{transaction}-{location}-{page}", search_payload)
            for item in summaries(search_payload):
                if yielded >= limit:
                    return
                key = str(item["id"])
                if key in seen:
                    continue
                seen.add(key)
                base = normalize(item, transaction=transaction, search_location=location)
                try:
                    detail_payload = next_data(self.fetch(base["url"]))
                    detail = detail_ad(detail_payload)
                    if detail.get("id") is not None and str(detail["id"]) != key:
                        raise ValueError("Detail ID differs from search result")
                    self._archive(f"detail-{transaction}-{key}", detail_payload)
                    result = normalize(item, detail, transaction, location)
                except (ValueError, RuntimeError) as exc:
                    base["detail_error"] = str(exc)
                    result = base
                yielded += 1
                yield result

    def _archive(self, name, payload):
        if self.raw_dir:
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
            (self.raw_dir / f"{safe_name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
