"""Offline, escaped HTML report; rankings are illustrative, not property facts."""
import html
import json


def score(record):
    signals = (record.get("jev") or {}).get("signals") or {}
    values = {k: v.get("value") for k, v in signals.items()}
    if not values:
        return None
    # Unknown is never treated as a positive. A pet prohibition is a hard stop.
    if values.get("pets") == "forbidden":
        return 0
    points = {"allowed": 3, "conditional": 1}.get(values.get("pets"), 0)
    points += {"dedicated": 2, "possible": 1}.get(values.get("workspace"), 0)
    points += {"quiet_claim": 1, "noise_warning": -1}.get(values.get("noise"), 0)
    points += {"private": 1}.get(values.get("balcony"), 0)
    return max(0, points)


def render(records):
    cards = []
    for item in sorted(records, key=lambda x: score(x) if score(x) is not None else -1, reverse=True):
        listing = item["listing"]
        signals = (item.get("jev") or {}).get("signals") or {}
        def esc(x):
            return html.escape(str(x if x is not None else "—"), quote=True)
        badges = "".join(f'<span class="badge">{esc(k)}: {esc(v["value"])} ({esc(round(v["probability"], 2))})</span>' for k, v in signals.items())
        price = listing["price"]
        points = score(item)
        cards.append(f'''<article><div class="top"><h2><a href="{esc(listing['url'])}" target="_blank" rel="noopener noreferrer">{esc(listing['title'])}</a></h2><strong>{esc(points) if points is not None else 'Unclassified'} / 7</strong></div>
<p class="meta">{esc(listing['location']['city'])} · {esc(listing['location']['district'])} · {esc(listing['area_sqm'])} m² · {esc(price['value'])} {esc(price['currency'])} · {esc(price['per_sqm'])} / m²</p>
<div class="badges">{badges or '<span class="badge">Jev not run</span>'}</div><p>{esc(listing['description'][:600])}</p>
<details><summary>Structured fields and uncertainty</summary><pre>{esc(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></article>''')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Cat & Zoom Radar</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f0e9;color:#26332f;font:16px/1.5 system-ui,sans-serif}header{background:#1d3932;color:#fff;padding:3rem max(5%,calc((100% - 900px)/2))}h1{font-size:clamp(2rem,6vw,4rem);margin:.1em 0}header p{max-width:45rem}main{max-width:900px;margin:2rem auto;padding:0 1rem}article{background:#fff;border:1px solid #ddd8cd;border-radius:16px;padding:1.4rem;margin:1rem 0;box-shadow:0 5px 20px #1d393211}.top{display:flex;justify-content:space-between;gap:1rem;align-items:baseline}.top h2{margin:0}.top strong{white-space:nowrap;color:#996329}a{color:#17635a}.meta{color:#53625b}.badges{display:flex;flex-wrap:wrap;gap:.4rem}.badge{font-size:.83rem;background:#e7f1e8;padding:.35rem .6rem;border-radius:50px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem;background:#f7f6f2;padding:1rem}summary{cursor:pointer}footer{padding:2rem 1rem;text-align:center;color:#53625b}</style>
<header><div>STORIA × JEV · PERSONAL SCOUT</div><h1>Cat & Zoom Radar</h1><p>Apartment clues for a renter with a cat and video calls. A claim is not a guarantee; unknown and low confidence need a human check.</p></header><main>''' + "\n".join(cards) + '''</main><footer>Scores are a sorting hint, not a safety, legal, or rental assessment. Open the original listing and confirm the details.</footer></html>'''
