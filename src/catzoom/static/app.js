let state = {listings: [], classifiers: [], page_size: 9, max_pool: 100, has_key: false};
let page = 0;
let busy = false;
let autoSignature = null;
let polling = false;
const $ = id => document.getElementById(id);
const node = (tag, cls, value) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (value !== undefined) element.textContent = String(value);
  return element;
};
const alertText = message => { $('notice').textContent = message; };

async function request(path, body) {
  const response = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Catzoom-Request': '1'},
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Request failed');
  return data;
}

function ordered() {
  const term = $('search').value.trim().toLocaleLowerCase();
  let rows = state.listings.filter(row => {
    const listing = row.listing;
    return `${listing.title} ${listing.location?.city || ''} ${listing.description || ''}`.toLocaleLowerCase().includes(term);
  });
  if ($('sort').value === 'score') rows = [...rows].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  return rows;
}

function current() {
  const rows = ordered();
  page = Math.min(page, Math.max(0, Math.ceil(rows.length / state.page_size) - 1));
  return rows.slice(page * state.page_size, (page + 1) * state.page_size);
}

function missingSignature() {
  return current().map(row => `${row.id}:${state.classifiers.filter(c => !row.results[c.id]).map(c => c.id).join(',')}`)
    .filter(item => item.endsWith(':') === false).join('|');
}

function dial(config, result, working) {
  const box = node('div', 'signal');
  if (!result) {
    box.append(node('div', 'pending', working ? '◌ Classifying' : '○ Pending'), node('small', '', config.name));
    return box;
  }
  const certainty = result.candidate === undefined ? Math.max(result.probability, 1 - result.probability) : result.probability;
  const pct = Math.round(certainty * 100);
  box.setAttribute('role', 'img');
  box.setAttribute('aria-label', `${config.name}: ${result.value}, ${pct}% certainty`);
  const arch = node('div', 'dial'), needle = node('div', 'needle');
  needle.style.setProperty('--angle', `${Math.round(certainty * 180)}deg`);
  arch.append(needle);
  box.append(arch, node('small', '', config.name), node('b', '', `${result.value} · ${pct}%`));
  return box;
}

function card(row) {
  const listing = row.listing, article = node('article', 'card'), cover = node('div', 'cover');
  article.dataset.listingId = row.id;
  let photo = listing.image || listing.images?.[0];
  try { if (new URL(photo).protocol !== 'https:') photo = null; } catch { photo = null; }
  if (photo) {
    const img = node('img');
    img.src = photo;
    img.alt = `Listing photo for ${listing.title}`;
    img.loading = 'lazy';
    img.referrerPolicy = 'no-referrer';
    cover.append(img);
  } else cover.append(node('span', '', 'No photo supplied'));
  const pending = state.classifiers.some(c => !row.results[c.id]);
  cover.append(node('span', 'score', row.score === null ? 'Unscored' : `${row.score}/100${pending ? ' · partial' : ''}`));
  const body = node('div', 'body');
  body.append(node('div', 'eyebrow', `${listing.transaction} · ${listing.location?.city || 'Unknown city'}`));
  const heading = node('h2'), link = node('a', '', listing.title || 'Untitled');
  try {
    const url = new URL(listing.url);
    link.href = url.protocol === 'https:' && url.hostname === 'www.storia.ro' ? url.href : '#';
  } catch { link.href = '#'; }
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  heading.append(link);
  body.append(heading,
    node('p', 'meta', `${listing.location?.district || ''} · ${listing.area_sqm ?? '—'} m² · ${listing.rooms ?? '—'} rooms · floor ${listing.floor ?? '—'}`),
    node('div', 'price', `${listing.price?.value ?? '—'} ${listing.price?.currency || ''}`));
  const dials = node('div', 'dials');
  for (const config of state.classifiers) dials.append(dial(config, row.results[config.id], state.classifying?.includes(row.id)));
  body.append(dials, node('p', 'description', (listing.description || '').slice(0, 420)));
  const detail = node('details');
  detail.append(node('summary', '', 'Full description & data'), node('p', '', listing.description || 'No description'),
    node('p', '', `Address: ${listing.street || listing.location?.street || 'Not provided'}`),
    node('p', '', `Amenities: ${(listing.features || []).join(', ') || 'Not provided'}`));
  body.append(detail);
  article.append(cover, body);
  return article;
}

function render() {
  const rows = ordered(), slice = current();
  const expanded = new Set([...$('grid').querySelectorAll('.card')]
    .filter(card => card.querySelector('details')?.open).map(card => card.dataset.listingId));
  $('grid').replaceChildren(...slice.map(card));
  for (const card of $('grid').querySelectorAll('.card')) {
    if (expanded.has(card.dataset.listingId)) card.querySelector('details').open = true;
  }
  $('count').textContent = `${rows.length} of ${state.listings.length} listings shown`;
  $('pool').textContent = `Work pool: newest ${state.max_pool} maximum`;
  const pages = Math.ceil(rows.length / state.page_size);
  $('page').textContent = `Page ${rows.length ? page + 1 : 0} of ${pages}`;
  $('prev').disabled = page === 0;
  $('next').disabled = (page + 1) * state.page_size >= rows.length;
  $('classify').disabled = busy || !state.has_key || !slice.length || !state.classifiers.length;
  const crawl = state.crawl || {};
  $('startCrawl').disabled = !!crawl.running;
  $('stopCrawl').hidden = !crawl.running;
  $('crawlStatus').textContent = crawl.running
    ? `${crawl.processed} new listings saved so far · ${crawl.area || ''}`
    : crawl.error ? `Crawl stopped: ${crawl.error}` : crawl.area ? `Crawl finished · ${crawl.processed} new listings saved` : '';
}

async function refresh() {
  if (polling) return;
  polling = true;
  try {
    const next = await fetch('/api/state', {cache: 'no-store'}).then(response => {
      if (!response.ok) throw Error('Could not load listings');
      return response.json();
    });
    if (JSON.stringify(next) !== JSON.stringify(state)) {
      state = next;
      render();
    }
    maybeAutoClassify();
  } catch (error) { alertText(error.message); }
  finally { polling = false; }
}

function maybeAutoClassify() {
  if (!$('auto').checked || busy || !state.has_key) return;
  const signature = missingSignature();
  if (signature && signature !== autoSignature) {
    autoSignature = signature; // A failed call is retried by the user, not every two seconds.
    classifyPage();
  }
}

async function classifyPage() {
  if (busy) return;
  if (!state.has_key) { alertText('Start the server with JEV_API_KEY exported to classify listings.'); return; }
  const ids = current().map(row => row.id);
  if (!ids.length || !state.classifiers.length) return;
  const knownIds = new Set(state.listings.map(row => row.id));
  busy = true;
  autoSignature = missingSignature();
  render();
  alertText(`Classifying up to ${ids.length} visible listings…`);
  try {
    const result = await request('/api/classify', {ids});
    state = result.state;
    alertText(`${result.classified} listings received new Jev decisions. Cached results were reused.`);
  } catch (error) { alertText(error.message); }
  finally {
    busy = false;
    render();
    autoSignature = missingSignature();
    if (current().some(row => !knownIds.has(row.id))) {
      autoSignature = null;
      maybeAutoClassify();
    }
  }
}

function editor() {
  const rows = $('rules');
  rows.replaceChildren();
  for (const config of state.classifiers) {
    const row = node('div', 'rule'), info = node('div');
    info.append(node('strong', '', config.name), node('p', '', config.question));
    const label = node('label', '', 'Weight '), input = node('input');
    input.type = 'number'; input.min = '0'; input.max = '5'; input.step = '0.5'; input.value = config.weight;
    input.setAttribute('aria-label', `${config.name} weight`);
    input.addEventListener('change', async () => {
      const copy = structuredClone(state.classifiers);
      copy.find(item => item.id === config.id).weight = Number(input.value);
      await saveConfig(copy);
    });
    label.append(input);
    const remove = node('button', '', 'Remove');
    remove.type = 'button';
    remove.addEventListener('click', () => saveConfig(state.classifiers.filter(item => item.id !== config.id)));
    row.append(info, label, remove);
    rows.append(row);
  }
  if (!rows.childElementCount) rows.append(node('p', '', 'No active classifiers. Add one below.'));
}

async function saveConfig(configs) {
  try {
    state = await request('/api/classifiers', {classifiers: configs});
    $('editorNotice').textContent = 'Saved';
    editor(); render();
    return true;
  } catch (error) {
    $('editorNotice').textContent = error.message;
    return false;
  }
}

function changeKind() {
  $('preferredWrap').hidden = $('newKind').value !== 'noul';
  $('optionsWrap').hidden = $('newKind').value !== 'choice';
  $('levelsWrap').hidden = $('newKind').value !== 'score';
}

async function addRule() {
  const kind = $('newKind').value;
  const rule = {name: $('newName').value, question: $('newQuestion').value, kind, weight: Number($('newWeight').value)};
  if (kind === 'noul') rule.preferred = $('newPreferred').value;
  else if (kind === 'score') rule.levels = $('newLevels').value.trim().split('\n').map(value => value.trim());
  else {
    try {
      rule.options = $('newOptions').value.trim().split('\n').map(line => {
        const parts = line.split('|').map(value => value.trim());
        if (parts.length !== 3) throw Error('Use key | meaning | score on every line');
        return {key: parts[0], description: parts[1], value: Number(parts[2])};
      });
    } catch (error) { $('editorNotice').textContent = error.message; return; }
  }
  if (!await saveConfig([...state.classifiers, rule])) return;
  for (const id of ['newName', 'newQuestion', 'newOptions', 'newLevels']) $(id).value = '';
  $('newWeight').value = '2';
  $('newKind').value = 'noul';
  $('newPreferred').value = 'yes';
  changeKind();
  $('editorNotice').textContent = state.has_key ? 'Saved. Classifying this page…' : 'Saved. Set JEV_API_KEY to classify.';
  await classifyPage(); // Adding a question explicitly requests decisions for this page.
  if (state.has_key) $('editorNotice').textContent = $('notice').textContent;
}

async function startCrawl() {
  try {
    state = await request('/api/crawl', {
      transaction: $('crawlTransaction').value, location: $('crawlLocation').value,
      pages: Number($('crawlPages').value), limit: Number($('crawlLimit').value)
    });
    render();
    alertText('Crawl started. New listings will appear here as they are saved.');
  } catch (error) { alertText(error.message); }
}

async function stopCrawl() {
  try { state = await request('/api/crawl/stop', {}); render(); alertText('Stopping after the current request.'); }
  catch (error) { alertText(error.message); }
}

$('settings').addEventListener('click', () => { editor(); $('editor').showModal(); });
$('addRule').addEventListener('click', addRule);
$('newKind').addEventListener('change', changeKind);
$('restore').addEventListener('click', async () => {
  if (await saveConfig([...state.classifiers, ...state.presets.filter(p => !state.classifiers.some(c => c.id === p.id))])) await classifyPage();
});
$('classify').addEventListener('click', classifyPage);
$('startCrawl').addEventListener('click', startCrawl);
$('stopCrawl').addEventListener('click', stopCrawl);
$('auto').addEventListener('change', () => { autoSignature = null; maybeAutoClassify(); });
$('search').addEventListener('input', () => { page = 0; render(); maybeAutoClassify(); });
$('sort').addEventListener('change', () => { page = 0; render(); maybeAutoClassify(); });
$('prev').addEventListener('click', () => { page--; render(); autoSignature = null; maybeAutoClassify(); });
$('next').addEventListener('click', () => { page++; render(); autoSignature = null; maybeAutoClassify(); });
refresh();
setInterval(refresh, 2000);
