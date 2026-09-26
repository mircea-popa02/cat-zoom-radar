"""Self-contained, escaped report with responsive cards and client-side pagination."""
import html
import json
from urllib.parse import urlparse


def score(record):
    signals = (record.get("jev") or {}).get("signals") or {}
    values = {k: v.get("value") for k, v in signals.items()}
    if not values:
        return None
    if values.get("pets") == "forbidden":
        return 0
    points = {"allowed": 3, "conditional": 1}.get(values.get("pets"), 0)
    points += {"dedicated": 2, "possible": 1}.get(values.get("workspace"), 0)
    points += {"quiet_claim": 1, "noise_warning": -1}.get(values.get("noise"), 0)
    points += {"private": 1}.get(values.get("balcony"), 0)
    return max(0, points)


def _esc(value):
    return html.escape(str(value if value is not None and value != "" else "—"), quote=True)


def _certainty(signal):
    value = signal.get("probability")
    if not isinstance(value, (int, float)) or not 0 <= value <= 1:
        return None
    return max(value, 1 - value) if "candidate" not in signal else value


def _dial(name, signal):
    certainty = _certainty(signal)
    if certainty is None:
        return ""
    pct = round(certainty * 100)
    angle = round(certainty * 180)
    label = f"{name}: {signal.get('value', 'review')}, certainty {pct}%"
    return (f'<div class="signal" role="img" aria-label="{_esc(label)}">'
            f'<div class="dial"><div class="needle" style="--angle:{angle}deg"></div><div class="hub"></div></div>'
            f'<div class="signal-name">{_esc(name.replace("_", " "))}</div>'
            f'<div class="signal-value">{_esc(signal.get("value"))} · {pct}%</div></div>')


def _image_url(listing):
    url = listing.get("image") or next(iter(listing.get("images") or []), None)
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None


def _listing_url(listing):
    url = listing.get("url") or ""
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.hostname == "www.storia.ro" else "#"


def render(records):
    cards = []
    for item in sorted(records, key=lambda x: score(x) if score(x) is not None else -1, reverse=True):
        listing = item["listing"]
        signals = (item.get("jev") or {}).get("signals") or {}
        points = score(item)
        price = listing.get("price") or {}
        loc = listing.get("location") or {}
        image = _image_url(listing)
        cover = (f'<img src="{_esc(image)}" alt="Listing photo for {_esc(listing.get("title"))}" loading="lazy" referrerpolicy="no-referrer">'
                 if image else '<div class="no-image" aria-label="No listing image">No photo supplied</div>')
        dials = "".join(_dial(k, v) for k, v in signals.items()) or '<p class="muted">Jev not run</p>'
        city = loc.get("city") or "Unknown city"
        district = loc.get("district") or ""
        place = ", ".join(x for x in (city, district) if x)
        meta = f"{_esc(place)} · {_esc(listing.get('area_sqm'))} m² · {_esc(listing.get('rooms'))} rooms · {_esc(listing.get('floor'))}"
        cost = f"{_esc(price.get('value'))} {_esc(price.get('currency'))}"
        desc = listing.get("description") or ""
        full = json.dumps(item, ensure_ascii=False, indent=2)
        cards.append(f'''<article class="card" data-search="{_esc((listing.get('title') or '') + ' ' + (city or '') + ' ' + (district or '') + ' ' + desc)}" data-pets="{_esc((signals.get('pets') or {}).get('value') or 'unknown')}">
<div class="cover">{cover}<span class="rank">{_esc(points) if points is not None else '?'} / 7</span></div>
<div class="card-body"><div class="eyebrow">{_esc(listing.get('transaction'))} · {_esc(city)}</div><h2><a href="{_esc(_listing_url(listing))}" target="_blank" rel="noopener noreferrer">{_esc(listing.get('title'))}</a></h2>
<p class="meta">{meta}</p><div class="cost">{cost}<small>{_esc(price.get('per_sqm'))} / m²</small></div>
<div class="dials">{dials}</div><p class="description">{_esc(desc[:520])}{'…' if len(desc)>520 else ''}</p>
<details><summary>Full description & extracted details</summary><p>{_esc(desc)}</p><p><b>Address:</b> {_esc(listing.get('street') or loc.get('street'))}</p><p><b>Amenities:</b> {_esc(', '.join(listing.get('features') or []))}</p><pre>{_esc(full)}</pre></details></div></article>''')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Cat & Zoom Radar</title><style>
:root{font-family:system-ui,sans-serif;color:#20342d;background:#f5f2eb}*{box-sizing:border-box}body{margin:0}header{padding:3rem max(4%,calc((100% - 1220px)/2));background:#183d34;color:#f8f5ec}h1{font-size:clamp(2.4rem,6vw,5rem);line-height:1.05;margin:.25em 0}.subtitle{max-width:48rem;color:#d8e7dc}.shell{max-width:1220px;margin:auto;padding:1.4rem}.toolbar{display:flex;flex-wrap:wrap;gap:.7rem;align-items:center;justify-content:space-between;margin:0 0 1.3rem}.controls{display:flex;flex-wrap:wrap;gap:.6rem}input,select,button{font:inherit;border:1px solid #b9c6bc;border-radius:10px;padding:.55rem .75rem;background:#fff;color:#20342d}input{min-width:220px}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:1.2rem}.card{background:#fff;border:1px solid #dde1d8;border-radius:18px;overflow:hidden;box-shadow:0 7px 24px #16342a12}.cover{height:215px;position:relative;background:#e2e7df}.cover img{width:100%;height:100%;object-fit:cover}.no-image{height:100%;display:grid;place-items:center;color:#667d71}.rank{position:absolute;right:12px;top:12px;background:#183d34;color:white;border-radius:30px;padding:.35rem .65rem;font-weight:700}.card-body{padding:1.25rem}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:.72rem;font-weight:800;color:#56816a}.card h2{font-size:1.25rem;line-height:1.25;margin:.35rem 0}.card a{color:#174e40;text-decoration:none}.card a:hover{text-decoration:underline}.meta,.muted{color:#6c7b70}.cost{font-size:1.45rem;font-weight:800;margin:.6rem 0}.cost small{font-size:.75rem;font-weight:500;color:#69796e;margin-left:.7rem}.dials{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.55rem;margin:1rem 0}.signal{text-align:center;min-width:0}.dial{position:relative;width:65px;height:36px;overflow:hidden;margin:auto;background:conic-gradient(from 270deg at 50% 100%,#e35158 0deg,#f4bb51 90deg,#42a971 180deg,transparent 180deg);border-radius:65px 65px 0 0}.dial:after{content:"";position:absolute;bottom:0;left:10px;width:45px;height:26px;background:#fff;border-radius:45px 45px 0 0}.needle{position:absolute;bottom:0;left:32px;width:2px;height:27px;background:#233e33;z-index:2;transform-origin:bottom center;transform:rotate(calc(var(--angle) - 90deg))}.hub{position:absolute;bottom:0;left:29px;width:8px;height:8px;background:#233e33;border-radius:50%;z-index:3}.signal-name{font-size:.68rem;text-transform:capitalize;color:#68796e}.signal-value{font-size:.71rem;font-weight:700;overflow-wrap:anywhere}.description{font-size:.9rem;line-height:1.5;color:#3c5144}details{border-top:1px solid #e6eae3;padding-top:.7rem;margin-top:1rem}summary{cursor:pointer;font-weight:700}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f1;padding:.7rem;font-size:.72rem;max-height:260px;overflow:auto}.pager{display:flex;align-items:center;justify-content:center;gap:1rem;margin:2rem 0}footer{text-align:center;color:#6c7b70;padding:2rem}
</style></head><body><header><div>STORIA × JEV · PERSONAL SCOUT</div><h1>Cat & Zoom Radar</h1><p class="subtitle">Apartment clues for cats and video calls. The dials show model certainty in its classification. Check claims with the advertiser before deciding.</p></header><main class="shell"><div class="toolbar"><div class="controls"><input id="query" aria-label="Search listings" placeholder="Search title, city, description"><select id="petFilter" aria-label="Pet policy"><option value="all">Any pet policy</option><option value="allowed">Allowed</option><option value="conditional">Conditional</option><option value="forbidden">Forbidden</option><option value="unspecified">Unspecified</option></select></div><span id="count"></span></div><div class="grid" id="grid">''' + ''.join(cards) + '''</div><div class="pager"><button id="prev">← Previous</button><span id="page"></span><button id="next">Next →</button></div></main><footer>Scores and certainty are sorting aids. No listing claim is independently verified.</footer><script>
const cards=[...document.querySelectorAll('.card')], size=9; let page=0, visible=cards;
const query=document.getElementById('query'), pet=document.getElementById('petFilter');
function update(){const term=query.value.trim().toLocaleLowerCase(), p=pet.value;visible=cards.filter(c=>(!term||c.dataset.search.toLocaleLowerCase().includes(term))&&(p==='all'||c.dataset.pets===p));page=Math.min(page,Math.max(0,Math.ceil(visible.length/size)-1));cards.forEach(c=>c.hidden=true);visible.slice(page*size,(page+1)*size).forEach(c=>c.hidden=false);document.getElementById('count').textContent=`${visible.length} listing${visible.length===1?'':'s'}`;document.getElementById('page').textContent=`Page ${visible.length?page+1:0} of ${Math.ceil(visible.length/size)}`;document.getElementById('prev').disabled=page===0;document.getElementById('next').disabled=(page+1)*size>=visible.length;}
query.addEventListener('input',()=>{page=0;update()});pet.addEventListener('change',()=>{page=0;update()});document.getElementById('prev').addEventListener('click',()=>{page--;update();scrollTo(0,0)});document.getElementById('next').addEventListener('click',()=>{page++;update();scrollTo(0,0)});update();
</script></body></html>'''
