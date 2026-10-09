/* MapLeads UI — talks to /api/v1. Settings inputs bind to the config object via data-k="section.key". */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const API = '/api/v1';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let S = null;            // settings
let providers = [];
const state = {view: 'dash', job: null, stream: null, leadPage: 1, sortK: 'created_at', sortD: 'desc', jobFilter: null, selected: new Set(), recipients: []};

async function api(path, opts = {}) {
  const init = {method: opts.method || 'GET', headers: {}};
  if (opts.body !== undefined) {
    if (opts.raw) init.body = opts.body;
    else { init.body = JSON.stringify(opts.body); init.headers['Content-Type'] = 'application/json'; }
  }
  const r = await fetch(API + path, init);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `HTTP ${r.status}`);
  return data;
}
function toast(m, bad) { const t = $('#toast'); t.textContent = m; t.style.background = bad ? 'var(--bad)' : ''; t.classList.add('on'); clearTimeout(t._); t._ = setTimeout(() => t.classList.remove('on'), bad ? 4500 : 2400); }
const fail = e => toast(e.message || String(e), true);
const getK = k => k.split('.').reduce((o, p) => o?.[p], S);
const setK = (k, v) => { const ps = k.split('.'); let o = S; ps.slice(0, -1).forEach(p => o = o[p] ??= {}); o[ps.at(-1)] = v; };

/* ---------- navigation ---------- */
const titles = {dash:'Dashboard',search:'Search Builder',run:'Live Run',leads:'Leads',outreach:'Outreach',filters:'Email Filters',crawl:'Crawler & Browser',providers:'Data Sources / APIs',presets:'Presets'};
const loaders = {dash: loadDash, run: loadJobs, leads: loadLeads, outreach: loadOutreach, filters: loadFilters, providers: loadProviders, presets: loadPresets, search: updateSummary};
function go(v) {
  state.view = v;
  $$('nav button').forEach(b => b.classList.toggle('on', b.dataset.v === v));
  $$('.view').forEach(s => s.classList.toggle('on', s.id === 'v-' + v));
  $('#title').textContent = titles[v];
  loaders[v]?.().catch(fail);
}
$$('nav button').forEach(b => b.onclick = () => go(b.dataset.v));
document.addEventListener('click', e => { const g = e.target.closest('[data-go]'); if (g) { e.preventDefault(); go(g.dataset.go); } });
$('#theme').onclick = () => { const r = document.documentElement; r.dataset.theme = r.dataset.theme === 'light' ? 'dark' : 'light'; try { localStorage.setItem('theme', r.dataset.theme); } catch {} };
try { const t = localStorage.getItem('theme'); if (t) document.documentElement.dataset.theme = t; } catch {}
$$('[data-tabs]').forEach(t => t.querySelectorAll('button').forEach(b => b.onclick = () => {
  t.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  t.parentElement.querySelectorAll('[data-pane]').forEach(p => p.hidden = p.dataset.pane !== b.dataset.t);
}));

/* ---------- settings binding ---------- */
function bindInputs() {
  $$('[data-k]').forEach(el => {
    const k = el.dataset.k, v = getK(k);
    if (el.type === 'checkbox') el.checked = !!v; else el.value = v ?? '';
    const handler = () => {
      setK(k, el.type === 'checkbox' ? el.checked : el.hasAttribute('data-num') ? Number(el.value) : el.value);
      $$(`[data-out="${k}"]`).forEach(o => o.textContent = getK(k));
      if (k.startsWith('search.') || k === 'crawl.enabled') updateSummary();
    };
    el.oninput = el.onchange = handler;
    $$(`[data-out="${k}"]`).forEach(o => o.textContent = v);
  });
  $$('[data-chips]').forEach(el => renderChips(el, () => getK(el.dataset.chips) || [], arr => { setK(el.dataset.chips, arr); updateSummary(); }));
}
function renderChips(el, get, set, cls = '') {
  const arr = get();
  el.innerHTML = arr.map((c, i) => `<span class="chip ${cls}">${esc(c)}<b data-i="${i}">×</b></span>`).join('') + '<input placeholder="+ add, Enter">';
  el.querySelectorAll('b').forEach(b => b.onclick = () => { const a = [...get()]; a.splice(+b.dataset.i, 1); set(a); renderChips(el, get, set, cls); });
  el.querySelector('input').onkeydown = e => {
    if (e.key === 'Enter' && e.target.value.trim()) {
      const add = e.target.value.split(',').map(x => x.trim()).filter(Boolean);
      set([...get(), ...add.filter(x => !get().includes(x))]); renderChips(el, get, set, cls); el.querySelector('input').focus();
    }
  };
}
async function saveSections(names) {
  const body = {}; names.forEach(n => body[n] = S[n]);
  S = await api('/config', {method: 'PUT', body});
  toast('Saved');
}
document.addEventListener('click', async e => {
  const s = e.target.closest('[data-save]'); const r = e.target.closest('[data-reset]');
  try {
    if (s) await saveSections(s.dataset.save.split(','));
    if (r && confirm(`Reset ${r.dataset.reset} settings to defaults?`)) { S = await api('/config/reset?section=' + r.dataset.reset, {method: 'POST'}); bindInputs(); if (r.dataset.reset === 'filters') loadFilters(); toast('Reset'); }
  } catch (err) { fail(err); }
});

/* ---------- dashboard ---------- */
async function loadDash() {
  const d = await api('/stats');
  $('#sListings').textContent = d.listings.toLocaleString();
  $('#sLeads').textContent = `${d.leads} leads stored`;
  $('#sWebsites').textContent = d.websites.toLocaleString();
  $('#sWithEmail').textContent = `${d.leads_with_email} with a valid email`;
  $('#sKept').textContent = d.emails_kept.toLocaleString();
  $('#sFiltered').textContent = `${(d.emails_found - d.emails_kept).toLocaleString()} filtered out`;
  $('#sSent').textContent = d.sent;
  $('#sReplied').textContent = `${d.replied} replied` + (d.sent ? ` · ${(d.replied / d.sent * 100).toFixed(1)}%` : '');
  $('#navLeads').textContent = d.leads;
  drawChart(d.per_day);
  const f = [['Listings scanned', d.listings], ['Websites', d.websites], ['Emails extracted', d.emails_found], ['Passed filters', d.emails_kept], ['Sent', d.sent], ['Replied', d.replied]];
  const mx = Math.max(1, ...f.map(x => x[1]));
  $('#funnel').innerHTML = f.map(([l, n]) => `<div style="margin-bottom:10px"><div class="row sm" style="justify-content:space-between"><span>${l}</span><b>${n.toLocaleString()}</b></div><div class="bar"><i style="width:${Math.max(2, n / mx * 100)}%"></i></div></div>`).join('');
  $('#jobs').innerHTML = d.jobs.length ? d.jobs.map(j => `<tr style="cursor:pointer" onclick="openJob(${j.id})"><td>${esc(j.name)}</td><td class="muted">${esc(srcName(j.source))}</td><td>${j.emails_kept}</td><td>${statusTag(j.status)}</td></tr>`).join('') : '<tr><td colspan="4" class="empty">No jobs yet — start one from Search Builder.</td></tr>';
  const dm = Math.max(1, ...d.districts.map(x => x.n));
  $('#districts').innerHTML = d.districts.length ? d.districts.map(x => `<div style="margin-bottom:9px"><div class="row sm" style="justify-content:space-between"><span>${esc(x.district)}</span><b>${x.n}</b></div><div class="bar"><i style="width:${x.n / dm * 100}%"></i></div></div>`).join('') : '<div class="empty">No emails yet.</div>';
}
function drawChart(rows) {
  const days = [...Array(14)].map((_, i) => { const d = new Date(Date.now() - (13 - i) * 864e5); return d.toISOString().slice(0, 10); });
  const map = Object.fromEntries(rows.map(r => [r.d, r.n]));
  const v = days.map(d => map[d] || 0), w = 600, h = 180, mx = Math.max(4, ...v);
  const pts = v.map((y, i) => [20 + i * (w - 40) / 13, h - 22 - (y / mx) * (h - 44)]);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p.join(',')).join('');
  $('#chart').innerHTML = `<defs><linearGradient id="gr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4f8cff" stop-opacity=".35"/><stop offset="1" stop-color="#4f8cff" stop-opacity="0"/></linearGradient></defs>
  ${[0, 1, 2, 3].map(i => `<line x1="20" x2="580" y1="${22 + i * 45.3}" y2="${22 + i * 45.3}" stroke="#8a91a322"/>`).join('')}
  <path d="${line}L580,158L20,158Z" fill="url(#gr)"/><path d="${line}" fill="none" stroke="#4f8cff" stroke-width="2.5"/>
  ${pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="#4f8cff"><title>${days[i]}: ${v[i]}</title></circle>`).join('')}
  <text x="20" y="176" font-size="10" fill="#8a91a3">${days[0].slice(5)}</text><text x="580" y="176" font-size="10" fill="#8a91a3" text-anchor="end">${days[13].slice(5)}</text>
  <text x="22" y="16" font-size="10" fill="#8a91a3">${mx}</text>`;
}
$('#importBtn').onclick = async () => { try { const r = await api('/leads/import', {method: 'POST'}); toast(`Imported ${r.websites} websites, ${r.emails} emails`); loadDash(); } catch (e) { fail(e); } };
const statusTag = s => `<span class="tag ${({done:'ok',running:'ok',sent:'ok',replied:'ok',paused:'w',queued:'w',interrupted:'w',stopped:'w',failed:'b',bounced:'b',rejected:'b'})[s] || ''}">${esc(s)}</span>`;
const srcName = id => providers.find(p => p.id === id)?.name || id;

/* ---------- search builder ---------- */
function queries() {
  const s = S.search, out = [];
  s.keywords.forEach(k => (s.locations.length ? s.locations : [null]).forEach(l => out.push(`${k} in ${l ? l + ' ' : ''}${s.city}`.trim())));
  return out;
}
function updateSummary() {
  if (!S) return;
  const q = queries(), n = q.length, per = S.search.max_results_per_query, src = $('#srcSel').value;
  $('#qcount').textContent = `${n} queries · up to ${(n * per).toLocaleString()} listings`;
  const mins = {selenium_maps: n * per * 0.12, places_api: n * 0.3, serpapi: n * 0.5, outscraper: n * 1}[src] || 0;
  const crawl = S.crawl.enabled ? n * per * 0.6 * 0.15 : 0;
  $('#eta').textContent = `~${Math.max(1, Math.round(mins + crawl))} min`;
  const cost = {selenium_maps: 0, places_api: n * Math.ceil(per / 20) * 0.035, serpapi: n * Math.ceil(per / 20) * 0.015, outscraper: n * per * 0.003}[src] || 0;
  $('#cost').textContent = cost ? `≈ $${cost.toFixed(2)}` : 'free (browser)';
  $('#qlist').innerHTML = q.map(esc).join('<br>');
}
$('#srcSel').onchange = updateSummary;
// Districts belong to one city; changing the city without reloading them builds queries like "Kreuzberg munich".
$('[data-k="search.city"]').addEventListener('change', () => {
  if (S.search.locations.length && confirm(`City changed to "${S.search.city}". The locations (${S.search.locations.slice(0, 3).join(', ')}…) are from the previous city.\n\nClear them? (Then use "Load districts from OpenStreetMap".)`)) {
    S.search.locations = []; bindInputs(); updateSummary();
  }
});
$$('.sug').forEach(s => { s.style.cursor = 'pointer'; s.onclick = () => { if (!S.search.keywords.includes(s.textContent)) S.search.keywords.push(s.textContent); bindInputs(); updateSummary(); }; });
$('#suggestDistricts').onclick = async e => {
  const b = e.currentTarget; b.disabled = true; b.innerHTML = '<span class="spin"></span> Loading…';
  try {
    const r = await api('/geo/districts?city=' + encodeURIComponent(S.search.city));
    if (confirm(`Found ${r.districts.length} districts in ${r.city}:\n\n${r.districts.slice(0, 40).join(', ')}${r.districts.length > 40 ? '…' : ''}\n\nReplace the current locations?`)) { S.search.locations = r.districts; bindInputs(); updateSummary(); }
  } catch (err) { fail(err); } finally { b.disabled = false; b.textContent = '⌖ Load districts from OpenStreetMap'; }
};
$('#startBtn').onclick = async () => {
  try {
    await api('/config', {method: 'PUT', body: {search: S.search, crawl: S.crawl}});
    const job = await api('/jobs', {method: 'POST', body: {source: $('#srcSel').value, name: $('#jobName').value || undefined, search: S.search}});
    toast('Job started'); $('#jobName').value = ''; openJob(job.id);
  } catch (e) { fail(e); }
};
$('#savePreset').onclick = async () => {
  const name = prompt('Preset name'); if (!name) return;
  try { await api('/presets', {method: 'POST', body: {name, description: queries().length + ' queries · ' + S.search.keywords.join(', '), source: $('#srcSel').value, search: S.search}}); toast('Preset saved'); } catch (e) { fail(e); }
};

/* ---------- live run ---------- */
async function loadJobs() {
  const list = await api('/jobs');
  const sel = $('#jobPick');
  sel.innerHTML = list.length ? list.map(j => `<option value="${j.id}">#${j.id} · ${esc(j.name)} · ${j.status}</option>`).join('') : '<option value="">No jobs yet</option>';
  const live = list.find(j => j.live);
  const id = state.job || live?.id || list[0]?.id;
  if (id) { sel.value = id; watchJob(+id); }
  else { $('#log').innerHTML = '<div class="t">Waiting for a job… start one from Search Builder or a Preset.</div>'; renderJob(null); }
}
$('#jobPick').onchange = e => watchJob(+e.target.value);
function openJob(id) { state.job = id; go('run'); }
function watchJob(id) {
  state.job = id;
  state.stream?.close();
  $('#log').innerHTML = '';
  const es = new EventSource(`${API}/jobs/${id}/stream`);
  state.stream = es;
  es.onmessage = ev => { const d = JSON.parse(ev.data); d.logs.forEach(addLog); renderJob(d.job); };
  es.onerror = () => { es.close(); };
}
function addLog(l) {
  const box = $('#log'), cls = {ok: 's', warn: 'w', error: 'e'}[l.level] || '';
  box.insertAdjacentHTML('beforeend', `<div><span class="t">${l.ts.slice(11, 19)}</span> <span class="${cls}">${esc(l.message)}</span></div>`);
  if ($('#autoscroll').checked) box.scrollTop = box.scrollHeight;
}
function renderJob(j) {
  const tag = $('#runTag');
  if (!j) { tag.textContent = 'idle'; return; }
  tag.outerHTML = statusTag(j.status).replace('class="tag', 'id="runTag" class="tag');
  $('#pbar').style.width = (j.total_queries ? j.query_index / j.total_queries * 100 : 0) + '%';
  $('#ptext').textContent = `${j.query_index} / ${j.total_queries} queries · ${srcName(j.source)}`;
  $('#perr').textContent = j.error || '';
  ['listings', 'websites', 'emails_kept', 'emails_filtered'].forEach((k, i) => $('#k' + (i + 1)).textContent = j[k]);
  $('#pauseBtn').disabled = !(j.live && j.status === 'running');
  $('#resumeBtn').disabled = !(j.status === 'paused' || (!j.live && ['stopped', 'interrupted', 'failed', 'queued'].includes(j.status)));
  $('#stopBtn').disabled = !j.live;
  $('#delJob').disabled = j.live;
  // coverage: one cell per query
  const map = $('#map');
  if (map.dataset.job != j.id || map.children.length !== j.total_queries) {
    map.dataset.job = j.id;
    const cols = Math.ceil(Math.sqrt(j.total_queries * 1.6)), rows = Math.ceil(j.total_queries / cols);
    map.innerHTML = j.queries.map((q, i) => `<div class="cell" title="${esc(q)}" style="left:${2 + (i % cols) * 96 / cols}%;top:${3 + Math.floor(i / cols) * 94 / rows}%;width:${96 / cols - 1.5}%;height:${94 / rows - 2}%;overflow:hidden">${esc(j.districts[i])}</div>`).join('');
  }
  [...map.children].forEach((c, i) => { c.classList.toggle('done', i < j.query_index); c.classList.toggle('run', i === j.query_index && j.status === 'running'); });
  updateHeader(j);
}
function updateHeader(j) {
  const running = j && j.live;
  $('#sdot').className = 'dot' + (running && j.status === 'running' ? '' : ' idle');
  $('#stext').textContent = running ? `${j.status === 'paused' ? 'Paused' : 'Scraping'} · ${j.queries[Math.min(j.query_index, j.total_queries - 1)] || ''}` : 'No job running';
  $('#navRun').textContent = running ? j.status : 'idle';
}
const jobAct = a => async () => { try { const j = await api(`/jobs/${state.job}/${a}`, {method: 'POST'}); renderJob(j); if (a === 'resume') watchJob(j.id); } catch (e) { fail(e); } };
$('#pauseBtn').onclick = jobAct('pause'); $('#resumeBtn').onclick = jobAct('resume'); $('#stopBtn').onclick = jobAct('stop');
$('#leadsOfJob').onclick = () => { state.jobFilter = state.job; state.leadPage = 1; go('leads'); };
$('#delJob').onclick = async () => { if (!state.job || !confirm('Delete this job and its log? Leads are kept.')) return; try { await api('/jobs/' + state.job, {method: 'DELETE'}); state.job = null; loadJobs(); } catch (e) { fail(e); } };
setInterval(async () => { // keep header status fresh on every view
  try { const live = (await api('/jobs')).find(j => j.live); updateHeader(live); $('#apiDot').style.color = 'var(--acc2)'; } catch { $('#apiDot').style.color = 'var(--bad)'; }
}, 5000);

/* ---------- leads ---------- */
function leadQuery() {
  const p = new URLSearchParams({page: state.leadPage, size: 50, sort: state.sortK, order: state.sortD});
  if ($('#q').value) p.set('q', $('#q').value);
  if ($('#fCity').value) p.set('city', $('#fCity').value);
  if ($('#fDistrict').value) p.set('district', $('#fDistrict').value);
  if ($('#fStatus').value) p.set('status', $('#fStatus').value);
  if ($('#fType').value) p.set('type', $('#fType').value);
  if ($('#fEmail').checked) p.set('has_email', 'true');
  if (state.jobFilter) p.set('job_id', state.jobFilter);
  return p;
}
async function loadLeads() {
  const d = await api('/leads?' + leadQuery());
  const cur = $('#fDistrict').value;
  $('#fDistrict').innerHTML = '<option value="">All districts</option>' + d.districts.map(x => `<option>${esc(x)}</option>`).join('');
  $('#fDistrict').value = cur;
  const curCity = $('#fCity').value;
  $('#fCity').innerHTML = '<option value="">All cities</option>' + d.cities.map(x => `<option>${esc(x)}</option>`).join('');
  $('#fCity').value = curCity;
  $('#fJob').hidden = !state.jobFilter; $('#fJob').innerHTML = `job #${state.jobFilter} <b style="cursor:pointer" id="clrJob">×</b>`;
  if (state.jobFilter) $('#clrJob').onclick = () => { state.jobFilter = null; loadLeads(); };
  $('#leadRows').innerHTML = d.items.length ? d.items.map(l => `<tr>
    <td><input type="checkbox" class="sel" data-id="${l.id}" ${state.selected.has(l.id) ? 'checked' : ''}></td>
    <td><b>${esc(l.name)}</b><div class="sm muted">${l.domain ? `<a href="${esc(l.website || 'https://' + l.domain)}" target="_blank" rel="noopener">${esc(l.domain)}</a>` : 'no website'}</div></td>
    <td>${esc(l.city || '')}</td>
    <td>${esc(l.district || '')}</td>
    <td class="mono sm">${l.email ? esc(l.email) : '<span class="muted">— none</span>'}</td>
    <td>${l.email_type ? `<span class="tag">${l.email_type}</span>` : ''}</td>
    <td>${l.rating ? `${l.rating}★${l.reviews != null ? ` <span class="muted sm">(${l.reviews})</span>` : ''}` : '<span class="muted">–</span>'}</td>
    <td class="mono sm muted">${esc(l.found_on || '')}</td>
    <td>${statusTag(l.status)}</td>
    <td><button class="btn" style="padding:4px 9px" onclick="openLead(${l.id})">›</button></td></tr>`).join('')
    : '<tr><td colspan="10" class="empty">No leads match. Run a scrape, or import tracked_*.txt from the Dashboard.</td></tr>';
  $$('.sel').forEach(c => c.onchange = () => { c.checked ? state.selected.add(+c.dataset.id) : state.selected.delete(+c.dataset.id); selCount(); });
  const from = (d.page - 1) * d.size;
  $('#leadCount').textContent = `${d.total ? from + 1 : 0}–${from + d.items.length} of ${d.total}`;
  $('#prev').disabled = d.page <= 1; $('#next').disabled = from + d.items.length >= d.total;
  selCount();
}
function selCount() { $('#queueSel').textContent = `✉ Email selected (${state.selected.size})`; }
let qT; ['#q', '#fCity', '#fDistrict', '#fStatus', '#fType', '#fEmail'].forEach(s => $(s).oninput = () => { clearTimeout(qT); qT = setTimeout(() => { state.leadPage = 1; loadLeads().catch(fail); }, 250); });
$('#prev').onclick = () => { state.leadPage--; loadLeads().catch(fail); };
$('#next').onclick = () => { state.leadPage++; loadLeads().catch(fail); };
$$('th[data-s]').forEach(th => th.onclick = () => { state.sortD = state.sortK === th.dataset.s && state.sortD === 'asc' ? 'desc' : 'asc'; state.sortK = th.dataset.s; loadLeads().catch(fail); });
$('#all').onchange = e => { $$('.sel').forEach(c => { c.checked = e.target.checked; e.target.checked ? state.selected.add(+c.dataset.id) : state.selected.delete(+c.dataset.id); }); selCount(); };
$('#expCsv').onclick = () => { const p = leadQuery(); p.set('format', 'csv'); location.href = `${API}/leads/export?${p}`; };
$('#expJson').onclick = () => { const p = leadQuery(); p.set('format', 'json'); location.href = `${API}/leads/export?${p}`; };
$('#bulk').onchange = async e => {
  const v = e.target.value; e.target.value = '';
  if (!v || !state.selected.size) return toast('Select leads first');
  if (v === 'delete' && !confirm(`Delete ${state.selected.size} leads and their emails?`)) return;
  const [action, status] = v.split(':');
  try { await api('/leads/bulk', {method: 'POST', body: {ids: [...state.selected], action, status}}); toast('Done'); state.selected.clear(); loadLeads(); } catch (err) { fail(err); }
};
$('#queueSel').onclick = async () => {
  if (!state.selected.size) return toast('Select leads first');
  await setRecipients([...state.selected]);
  go('outreach');
};
async function openLead(id) {
  let l;
  try { l = await api('/leads/' + id); } catch (e) { return fail(e); }
  const d = $('#drawer');
  d.innerHTML = `<div class="row"><h2 style="margin:0;font-size:18px">${esc(l.name)}</h2><div style="flex:1"></div><button class="btn" id="dClose">✕</button></div>
  <p class="muted sm">${esc(l.address || '')}${l.phone ? ' · ' + esc(l.phone) : ''}</p>
  <div class="row">${statusTag(l.status)}${l.rating ? `<span class="tag">${l.rating}★${l.reviews != null ? ` · ${l.reviews} reviews` : ''}</span>` : ''}${l.district || l.city ? `<span class="tag">${esc([l.district, l.city].filter(Boolean).join(', '))}</span>` : ''}<span class="tag">${esc(srcName(l.source))}</span></div>
  <div class="kv" style="margin-top:12px"><span>Website</span><span>${l.website ? `<a href="${esc(l.website)}" target="_blank" rel="noopener">${esc(l.website)}</a>` : '–'}</span>
  <span>Category</span><span>${esc(l.category || '–')}</span><span>Query</span><span>${esc(l.query || '–')}</span>
  <span>Maps</span><span>${l.maps_url ? `<a href="${esc(l.maps_url)}" target="_blank" rel="noopener">open ↗</a>` : '–'}</span></div>
  <label class="f">Emails found</label>
  <div class="sm mono">${l.emails.length ? l.emails.map(e => e.kept ? `✔ ${esc(e.email)} <span class="muted">(${esc(e.found_on)} · ${esc(e.type)})</span>` : `✖ <s class="muted">${esc(e.email)}</s> <span class="muted">layer ${e.layer} · ${esc(e.reason)}</span>`).join('<br>') : '<span class="muted">none</span>'}</div>
  <label class="f">Pages crawled</label><div class="sm mono muted">${l.pages_crawled.map(esc).join(' · ') || '–'}</div>
  <label class="f">Status</label><select id="dStatus">${['new', 'queued', 'sent', 'replied', 'bounced', 'rejected'].map(s => `<option ${s === l.status ? 'selected' : ''}>${s}</option>`).join('')}</select>
  <label class="f">Tags</label><div class="chips" id="dTags"></div>
  <label class="f">Notes</label><textarea id="dNotes">${esc(l.notes || '')}</textarea>
  ${l.sent.length ? `<label class="f">Outreach history</label><div class="sm">${l.sent.map(s => `${s.ts.slice(0, 16)} · ${esc(s.email)} · ${esc(s.result)}${s.dry_run ? ' (dry run)' : ''}`).join('<br>')}</div>` : ''}
  <div class="row" style="margin-top:14px"><button class="btn p" id="dSave">💾 Save</button><button class="btn" id="dMail">✉ Email</button><button class="btn" id="dCrawl">↻ Re-crawl</button><button class="btn r" id="dEx">⊘ Exclude + block domain</button></div>`;
  d.classList.add('on');
  let tags = l.tags;
  renderChips($('#dTags'), () => tags, a => tags = a);
  $('#dClose').onclick = () => d.classList.remove('on');
  $('#dSave').onclick = async () => { try { await api('/leads/' + id, {method: 'PATCH', body: {status: $('#dStatus').value, notes: $('#dNotes').value, tags}}); toast('Saved'); loadLeads(); } catch (e) { fail(e); } };
  $('#dMail').onclick = async () => { d.classList.remove('on'); await setRecipients([id]); go('outreach'); };
  $('#dCrawl').onclick = async e => { e.target.innerHTML = '<span class="spin"></span> Crawling…'; try { const r = await api(`/leads/${id}/recrawl`, {method: 'POST'}); toast(`Re-crawled: ${r.kept} kept, ${r.filtered} filtered`); openLead(id); loadLeads(); } catch (err) { fail(err); e.target.textContent = '↻ Re-crawl'; } };
  $('#dEx').onclick = async () => { if (!confirm('Exclude this lead and add its domain to the block list?')) return; try { await api('/leads/' + id, {method: 'PATCH', body: {excluded: true, block_domain: true}}); toast('Excluded'); d.classList.remove('on'); loadLeads(); } catch (e) { fail(e); } };
}
window.openLead = openLead; window.openJob = openJob;

/* ---------- outreach ---------- */
// Flow: 1 pick recipients → 2 write message (live preview per real recipient) → 3 review & send.
const O = {sel: new Set(), plan: null, step: 1, mode: 'dry', templates: [], tplDirty: false, pvIdx: 0, status: null,
           rPage: 1, rTotal: 0, camp: null, campTimer: null, armed: false};

function oTab(t) {
  $$('#oTabs button').forEach(b => b.classList.toggle('on', b.dataset.ot === t));
  $$('[data-op]').forEach(p => p.hidden = p.dataset.op !== t);
  if (t === 'history') loadCampaigns().catch(fail);
  if (t === 'settings') loadAccount().catch(fail);
}
$$('#oTabs button').forEach(b => b.onclick = () => oTab(b.dataset.ot));
document.addEventListener('click', e => { const g = e.target.closest('[data-ot-go]'); if (g) oTab(g.dataset.otGo); });

function oStep(n) {
  if (n > 1 && !O.plan?.count) { toast('Pick at least one recipient first'); n = 1; }
  O.step = n;
  $$('#stepper button').forEach(b => { b.classList.toggle('on', +b.dataset.step === n); b.classList.toggle('done', +b.dataset.step < n); });
  $$('[data-sp]').forEach(p => p.hidden = +p.dataset.sp !== n);
  if (n === 2) preview();
  if (n === 3) renderReview();
}
$$('#stepper button').forEach(b => b.onclick = () => oStep(+b.dataset.step));
document.addEventListener('click', e => { const n = e.target.closest('[data-next]'); if (n) oStep(+n.dataset.next); });

async function loadOutreach() {
  await Promise.all([loadStatus(), loadTemplates(), loadPicker(true)]);
  oStep(O.step);
}

/* status bar */
async function loadStatus() {
  const s = O.status = await api('/outreach/status');
  $('#osAccount').innerHTML = s.smtp_ready
    ? `<span class="os-l">Sending as</span><span class="os-v">${s.sender_name ? `${esc(s.sender_name)} <span class="muted">&lt;${esc(s.sender)}&gt;</span>` : `${esc(s.sender)} <button class="link sm" data-ot-go="settings">add your name</button>`}</span>`
    : `<span class="os-l">Email account</span><span class="os-v"><span class="err">Not set up</span> <button class="link" data-ot-go="settings">Set up →</button></span>`;
  $('#osToday').textContent = s.sent_today; $('#osCap').textContent = s.daily_cap;
  $('#osBar').style.width = Math.min(100, s.sent_today / Math.max(1, s.daily_cap) * 100) + '%';
  const c = s.settings;
  $('#osWindow').innerHTML = `${c.window_start}–${c.window_end}${c.weekdays_only ? ' · Mon–Fri' : ''} <span class="tag ${s.in_window ? 'ok' : 'w'}">${s.in_window ? 'open now' : 'closed now'}</span>`;
  const run = s.running[0];
  $('#osRunning').hidden = !run;
  if (run) $('#osRunning').innerHTML = `<span class="os-l">${run.dry_run ? 'Test run' : 'Sending'} #${run.id}</span><span class="os-v"><span class="spin"></span> ${run.sent + run.failed} / ${run.total} <button class="link" onclick="openCampaign(${run.id})">view</button></span>`;
  $('#oHistCount').textContent = '';
}

/* step 1: recipient picker */
function pickerQuery() {
  const p = new URLSearchParams({has_email: 'true', size: 100, page: O.rPage, sort: 'name', order: 'asc'});
  if ($('#rq').value) p.set('q', $('#rq').value);
  if ($('#rCity').value) p.set('city', $('#rCity').value);
  if ($('#rDistrict').value) p.set('district', $('#rDistrict').value);
  if ($('#rType').value) p.set('type', $('#rType').value);
  if ($('#rNew').checked) p.set('status', 'new');
  return p;
}
async function loadPicker(reset) {
  if (reset) O.rPage = 1;
  const d = await api('/leads?' + pickerQuery());
  O.rTotal = d.total;
  const fill = (el, list, label) => { const cur = el.value; el.innerHTML = `<option value="">${label}</option>` + list.map(x => `<option>${esc(x)}</option>`).join(''); el.value = cur; };
  fill($('#rCity'), d.cities, 'All cities'); fill($('#rDistrict'), d.districts, 'All districts');
  const rows = d.items.map(l => `<tr class="pick ${O.sel.has(l.id) ? 'picked' : ''}" data-id="${l.id}">
    <td><input type="checkbox" ${O.sel.has(l.id) ? 'checked' : ''} aria-label="Select ${esc(l.name)}"></td>
    <td><b>${esc(l.name)}</b><div class="sm muted">${esc(l.domain || '')}</div></td>
    <td class="sm">${esc([l.district, l.city].filter(Boolean).join(', '))}</td>
    <td class="mono sm">${esc(l.email)}</td><td><span class="tag">${esc(l.email_type)}</span></td></tr>`).join('');
  if (reset) $('#rRows').innerHTML = rows || '<tr><td colspan="5" class="empty">No leads with an email match these filters.</td></tr>';
  else $('#rRows').insertAdjacentHTML('beforeend', rows);
  const shown = $$('#rRows tr.pick').length;
  $('#rCount').textContent = `${d.total} matching lead${d.total === 1 ? '' : 's'} with an email`;
  $('#rMore').hidden = shown >= d.total;
  $('#rAll').textContent = `Select all ${d.total} matching`;
  syncPageBox();
}
$('#rRows').addEventListener('click', e => {
  const tr = e.target.closest('tr.pick'); if (!tr || e.target.closest('a')) return;
  const id = +tr.dataset.id, cb = tr.querySelector('input');
  if (e.target !== cb) cb.checked = !cb.checked;
  cb.checked ? O.sel.add(id) : O.sel.delete(id);
  tr.classList.toggle('picked', cb.checked);
  syncPageBox(); replan();
});
function syncPageBox() { const rows = $$('#rRows tr.pick'); $('#rPage').checked = rows.length > 0 && rows.every(r => O.sel.has(+r.dataset.id)); }
$('#rPage').onchange = e => { $$('#rRows tr.pick').forEach(tr => { const id = +tr.dataset.id; e.target.checked ? O.sel.add(id) : O.sel.delete(id); tr.classList.toggle('picked', e.target.checked); tr.querySelector('input').checked = e.target.checked; }); replan(); };
$('#rAll').onclick = async () => {
  const p = pickerQuery(); p.set('size', 500);
  let page = 1, got = 0;
  do { p.set('page', page); const d = await api('/leads?' + p); d.items.forEach(l => O.sel.add(l.id)); got += d.items.length; page++; if (got >= d.total || !d.items.length) break; } while (page < 20);
  loadPicker(true); replan();
};
$('#rNone').onclick = () => { O.sel.clear(); loadPicker(true); replan(); };
$('#rMore').onclick = () => { O.rPage++; loadPicker(false).catch(fail); };
let rT; ['#rq', '#rCity', '#rDistrict', '#rType', '#rNew'].forEach(s => $(s).oninput = () => { clearTimeout(rT); rT = setTimeout(() => loadPicker(true).catch(fail), 250); });

let planT;
function replan() { clearTimeout(planT); planT = setTimeout(() => doPlan().catch(fail), 200); }
async function doPlan() {
  const p = O.plan = O.sel.size ? await api('/outreach/plan', {method: 'POST', body: {lead_ids: [...O.sel]}}) : {count: 0, skipped: 0, recipients: [], skipped_list: []};
  $('#selN').textContent = p.count;
  $('#st1').textContent = p.count ? `${p.count} recipient${p.count === 1 ? '' : 's'}` : 'none selected';
  $('#selHint').hidden = p.count > 0;
  $('#selList').innerHTML = p.recipients.slice(0, 60).map(r => `<div class="sel-row"><span><b>${esc(r.name)}</b><small class="mono">${esc(r.email)}</small></span><button class="link" data-unsel="${r.lead_id}" aria-label="Remove">×</button></div>`).join('')
    + (p.recipients.length > 60 ? `<div class="sm muted">…and ${p.recipients.length - 60} more</div>` : '');
  const reasons = {};
  p.skipped_list.forEach(s => (reasons[s.reason] ||= []).push(s.name));
  $('#skipList').innerHTML = p.skipped ? `<details class="skipbox"><summary>${p.skipped} won't be emailed</summary>${Object.entries(reasons).map(([r, n]) => `<div class="sm"><b>${esc(r)}</b>: ${n.slice(0, 8).map(esc).join(', ')}${n.length > 8 ? '…' : ''}</div>`).join('')}</details>` : '';
  $('#toStep2').disabled = !p.count;
  O.pvIdx = Math.min(O.pvIdx, Math.max(0, p.count - 1));
}
$('#selList').addEventListener('click', e => { const b = e.target.closest('[data-unsel]'); if (!b) return; O.sel.delete(+b.dataset.unsel); loadPicker(true); replan(); });
async function setRecipients(ids) { ids.forEach(i => O.sel.add(i)); O.step = 1; await doPlan(); }

/* step 2: template editor + preview */
async function loadTemplates(selectId) {
  O.templates = await api('/templates');
  const cur = selectId || $('#tplSel').value;
  $('#tplSel').innerHTML = O.templates.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
  if (cur && O.templates.some(t => t.id == cur)) $('#tplSel').value = cur;
  showTemplate();
}
const curTpl = () => O.templates.find(t => t.id == $('#tplSel').value);
function showTemplate() {
  const t = curTpl(); if (!t) return;
  $('#subj').value = t.subject; $('#body').value = t.body;
  setDirty(false); renderAttachments(); preview();
}
$('#tplSel').onchange = async () => {
  if (O.tplDirty && !confirm('Discard unsaved changes to the current template?')) { $('#tplSel').value = O.lastTpl; return; }
  showTemplate();
};
function setDirty(v) { O.tplDirty = v; O.lastTpl = $('#tplSel').value; $('#tplDirty').hidden = !v; $('#tplSave').classList.toggle('p', v); $('#st2').textContent = (curTpl()?.name || '—') + (v ? ' (edited)' : ''); }
['#subj', '#body'].forEach(s => $(s).addEventListener('input', () => { setDirty(true); preview(); }));
const attSelected = () => $$('#attChips [data-att]').filter(c => c.classList.contains('on')).map(c => c.dataset.att);
async function saveTemplate(quiet) {
  const t = curTpl();
  await api('/templates/' + t.id, {method: 'PUT', body: {name: t.name, subject: $('#subj').value, body: $('#body').value, attachments: attSelected()}});
  Object.assign(t, {subject: $('#subj').value, body: $('#body').value, attachments: attSelected()});
  setDirty(false); if (!quiet) toast('Template saved');
}
$('#tplSave').onclick = () => saveTemplate().catch(fail);
$('#tplMenuBtn').onclick = e => { e.stopPropagation(); $('#tplMenu').hidden = !$('#tplMenu').hidden; };
document.addEventListener('click', e => { if (!e.target.closest('.menu')) $('#tplMenu').hidden = true; });
$('#tplSaveAs').onclick = async () => {
  const name = prompt('Name for the new template', curTpl().name + ' (copy)'); if (!name) return;
  try { const t = await api('/templates', {method: 'POST', body: {name, subject: $('#subj').value, body: $('#body').value, attachments: attSelected()}}); await loadTemplates(t.id); toast('Saved as “' + name + '”'); } catch (e) { fail(e); }
};
$('#tplRename').onclick = async () => {
  const t = curTpl(), name = prompt('Rename template', t.name); if (!name) return;
  try { await api('/templates/' + t.id, {method: 'PUT', body: {...t, name, subject: $('#subj').value, body: $('#body').value, attachments: attSelected()}}); await loadTemplates(t.id); } catch (e) { fail(e); }
};
$('#tplDel').onclick = async () => {
  if (O.templates.length < 2) return toast('Keep at least one template');
  if (!confirm(`Delete template “${curTpl().name}”?`)) return;
  try { await api('/templates/' + $('#tplSel').value, {method: 'DELETE'}); await loadTemplates(); } catch (e) { fail(e); }
};

// Variable buttons insert at the cursor of whichever field was last focused.
let lastField = null;
$$('[data-insertable]').forEach(f => f.addEventListener('focus', () => lastField = f));
function insertVar(v) {
  const f = lastField || $('#body'), s = f.selectionStart ?? f.value.length, e = f.selectionEnd ?? s;
  f.value = f.value.slice(0, s) + v + f.value.slice(e); f.focus(); f.setSelectionRange(s + v.length, s + v.length);
  setDirty(true); preview();
}
$$('[data-var]').forEach(b => b.onclick = () => insertVar(b.dataset.var));
$('#varMore').onchange = e => { if (e.target.value) insertVar(e.target.value); e.target.value = ''; };

async function renderAttachments() {
  const t = curTpl(); if (!t) return;
  const files = await api('/attachments');
  const icon = n => /\.(csv|xlsx?|json)$/i.test(n) ? '▦' : /\.(png|jpe?g)$/i.test(n) ? '🖼' : '📄';
  $('#attChips').innerHTML = files.length ? files.map(f => `<button class="att ${t.attachments.includes(f.name) ? 'on' : ''}" data-att="${esc(f.name)}" title="Click to attach / detach">
      <span>${icon(f.name)}</span><span class="att-n">${esc(f.name)}</span><small>${f.size > 1048576 ? (f.size / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(f.size / 1024)) + ' KB'}</small>
      <span class="att-x" data-delatt="${esc(f.name)}" title="Delete file">×</span></button>`).join('')
    : '<span class="sm muted">No files yet. Upload your CV, or attach leads as a CSV.</span>';
}
$('#attChips').addEventListener('click', async e => {
  const del = e.target.closest('[data-delatt]');
  if (del) { e.stopPropagation(); if (!confirm(`Delete ${del.dataset.delatt} from the attachments folder?`)) return; await api('/attachments/' + encodeURIComponent(del.dataset.delatt), {method: 'DELETE'}); curTpl().attachments = curTpl().attachments.filter(a => a !== del.dataset.delatt); setDirty(true); return renderAttachments(); }
  const b = e.target.closest('[data-att]'); if (!b) return;
  b.classList.toggle('on'); setDirty(true); preview();
});
$('#attFile').onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  try { await api('/attachments?name=' + encodeURIComponent(f.name), {method: 'POST', body: f, raw: true}); if (!curTpl().attachments.includes(f.name)) curTpl().attachments.push(f.name); setDirty(true); await renderAttachments(); preview(); toast('Uploaded and attached ' + f.name); } catch (err) { fail(err); }
  e.target.value = '';
};

// Leads → CSV attachment
const LC_COLS = {name: 'Company', email: 'Email', website: 'Website', city: 'City', district: 'District', address: 'Address', phone: 'Phone', category: 'Category', rating: 'Rating', email_type: 'Email type', maps_url: 'Maps link', status: 'Status'};
const LC_DEFAULT = ['name', 'email', 'website', 'city', 'district', 'phone'];
function openLeadCsv() {
  $('#leadCsvBox').hidden = false;
  $('#lcCols').innerHTML = Object.entries(LC_COLS).map(([k, v]) => `<label class="chip"><input type="checkbox" value="${k}" ${LC_DEFAULT.includes(k) ? 'checked' : ''}> ${v}</label>`).join('');
  $('#lcName').value = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
  const hasSel = O.sel.size > 0;
  $$('input[name=lcSrc]').forEach(r => { r.checked = (r.value === 'sel') === hasSel; if (r.value === 'sel') r.disabled = !hasSel; });
  $('#lcCount').textContent = hasSel ? `· ${O.sel.size} selected` : '';
}
$('#attLeads').onclick = openLeadCsv;
$('#lcCancel').onclick = () => $('#leadCsvBox').hidden = true;
$('#lcMake').onclick = async () => {
  const src = $$('input[name=lcSrc]').find(r => r.checked).value;
  const columns = $$('#lcCols input:checked').map(c => c.value);
  if (!columns.length) return toast('Pick at least one column');
  try {
    const r = await api('/attachments/from-leads', {method: 'POST', body: {name: $('#lcName').value, columns, ids: src === 'sel' ? [...O.sel] : null, filters: src === 'all' ? {has_email: true} : {}}});
    if (!curTpl().attachments.includes(r.name)) curTpl().attachments.push(r.name);
    setDirty(true); $('#leadCsvBox').hidden = true; await renderAttachments(); preview();
    toast(`Attached ${r.name} (${r.rows} leads)`);
  } catch (e) { fail(e); }
};

let pvT;
function preview() {
  clearTimeout(pvT);
  pvT = setTimeout(async () => {
    const recips = O.plan?.recipients || [];
    const r0 = recips[O.pvIdx];
    $('#pvPos').textContent = recips.length ? `${O.pvIdx + 1} / ${recips.length}` : 'sample';
    $('#pvPrev').disabled = O.pvIdx <= 0; $('#pvNext').disabled = O.pvIdx >= recips.length - 1;
    try {
      const r = await api('/outreach/preview', {method: 'POST', body: {lead_id: r0?.lead_id || null, subject: $('#subj').value, body: $('#body').value}});
      const st = O.status || {};
      $('#pvFrom').textContent = st.sender ? (st.sender_name ? `${st.sender_name} <${st.sender}>` : st.sender) : '(email account not set up)';
      $('#pvTo').textContent = (r0 ? r0.name + ' · ' : 'Example GmbH · ') + (r.to || '');
      $('#pvSubj').textContent = r.subject || '(no subject)';
      $('#pvBody').textContent = r.body;
      const atts = attSelected();
      $('#pvAtt').innerHTML = atts.map(a => `<span class="tag">📎 ${esc(a)}</span>`).join('');
      const warns = [];
      if (!r.subject.trim()) warns.push('The subject is empty.');
      const left = (r.subject + r.body).match(/\{[a-z_]+\}/g);
      if (left) warns.push(`Unknown placeholder ${[...new Set(left)].join(', ')} — it will be sent as typed.`);
      if (/\{first_name/.test($('#body').value) && r0 && !/^Guten Tag \w|^Hallo \w|^Dear \w|^Hi \w/m.test(r.body)) warns.push('No first name found in this address, so the greeting has no name. That reads fine.');
      if (!atts.length) warns.push('No attachment. Add your CV if you want to send one.');
      $('#pvWarn').hidden = !warns.length; $('#pvWarn').innerHTML = warns.map(w => '• ' + esc(w)).join('<br>');
    } catch (e) { $('#pvBody').textContent = e.message; }
  }, 150);
}
$('#pvPrev').onclick = () => { O.pvIdx = Math.max(0, O.pvIdx - 1); preview(); };
$('#pvNext').onclick = () => { O.pvIdx = Math.min((O.plan?.count || 1) - 1, O.pvIdx + 1); preview(); };

/* step 3: review */
function fmtDur(sec) { if (sec < 90) return Math.round(sec) + ' s'; const m = sec / 60; if (m < 90) return Math.round(m) + ' min'; return (m / 60).toFixed(1).replace('.0', '') + ' h'; }
function renderReview() {
  const p = O.plan, c = S.outreach, n = p.count, st = O.status || {sent_today: 0, daily_cap: c.daily_cap};
  $('#rvN').textContent = n; $('#rvSkip').textContent = p.skipped ? `${p.skipped} skipped` : 'none skipped';
  $('#rvTpl').textContent = curTpl()?.name || '—';
  const atts = attSelected(); $('#rvAtt').textContent = atts.length ? '📎 ' + atts.join(', ') : 'no attachments';
  const live = O.mode === 'live';
  const avg = (Number(c.delay_min) + Number(c.delay_max)) / 2;
  if (!live) { $('#rvEta').textContent = 'instant'; $('#rvPace').textContent = 'test run, nothing waits'; $('#rvDone').textContent = 'right away'; $('#rvCap').textContent = 'doesn\'t count toward the daily cap'; }
  else {
    const cap = Number(c.daily_cap) || 60, todayLeft = Math.max(0, cap - st.sent_today);
    const days = n <= todayLeft ? 0 : Math.ceil((n - todayLeft) / cap);
    $('#rvEta').textContent = fmtDur(Math.max(0, n - 1) * avg) + ' sending';
    $('#rvPace').textContent = `one every ${c.delay_min}–${c.delay_max} s`;
    // Outside the send window nothing goes out until it opens again.
    $('#rvDone').textContent = !st.in_window && days === 0 ? `after ${c.window_start} next ${c.weekdays_only ? 'weekday' : 'day'}`
      : days === 0 ? 'today' : days === 1 ? 'tomorrow' : `in ${days + 1} days`;
    if (!st.in_window) $('#rvEta').textContent = 'waits for window';
    $('#rvCap').textContent = `${todayLeft} of ${cap} left today · ${c.window_start}–${c.window_end}${c.weekdays_only ? ' Mon–Fri' : ''}`;
  }
  $('#rvRules').innerHTML = `<span>Per company</span><span>${c.one_per_domain ? 'one email' : 'every address'}</span>
    <span>Already emailed</span><span>always skipped</span><span>Verify first</span><span>${c.verify_hunter ? 'yes, with Hunter' : 'no'}</span>`;
  $$('#modeSeg button').forEach(b => b.classList.toggle('on', b.dataset.mode === O.mode));
  const blocked = live && !st.smtp_ready;
  $('#liveBlock').hidden = !live;
  $('#liveBlock').innerHTML = blocked ? 'Your email account isn\'t set up yet. <button class="link" data-ot-go="settings">Set it up →</button>'
    : `Real emails go to ${n} compan${n === 1 ? 'y' : 'ies'} from <b>${esc(st.sender || '')}</b>. You can stop at any time; emails already sent can't be recalled.`;
  O.armed = false;
  const btn = $('#launch');
  btn.disabled = blocked || !n;
  btn.className = 'btn big-btn ' + (live ? 'p' : 'g');
  btn.textContent = live ? `Send ${n} email${n === 1 ? '' : 's'}` : `Start test run (${n})`;
  $('#st3').textContent = live ? 'send for real' : 'test run';
}
$$('#modeSeg button').forEach(b => b.onclick = () => { O.mode = b.dataset.mode; renderReview(); });
$('#launch').onclick = async () => {
  const live = O.mode === 'live', btn = $('#launch');
  // Real sends take a second click instead of a browser confirm dialog.
  if (live && !O.armed) { O.armed = true; btn.textContent = `Click again to send ${O.plan.count} emails`; btn.classList.add('armed'); setTimeout(() => { if (O.armed) renderReview(); }, 5000); return; }
  btn.disabled = true;
  try {
    if (O.tplDirty) { await saveTemplate(true); toast('Template saved'); }
    const r = await api('/outreach/campaigns', {method: 'POST', body: {template_id: +$('#tplSel').value, lead_ids: [...O.sel], dry_run: !live}});
    toast(`${live ? 'Sending' : 'Test run'} started: ${r.recipients} recipients`);
    if (live) { O.sel.clear(); O.plan = null; O.step = 1; doPlan(); loadPicker(true); }
    openCampaign(r.id);
  } catch (e) { fail(e); } finally { btn.disabled = false; renderReview(); }
};
$('#sendTest').onclick = async e => {
  const b = e.currentTarget; b.disabled = true; $('#testRes').innerHTML = '<span class="spin"></span> sending…';
  try {
    if (O.tplDirty) await saveTemplate(true);
    const r0 = O.plan?.recipients[O.pvIdx];
    const r = await api('/outreach/send-test', {method: 'POST', body: {template_id: +$('#tplSel').value, lead_id: r0?.lead_id || null}});
    $('#testRes').innerHTML = `<span class="tag ok">sent</span> Check ${esc(r.sent_to)}. It's personalised for ${esc(r0?.name || 'Example GmbH')}.`;
  } catch (err) { $('#testRes').innerHTML = `<span class="err">${esc(err.message)}</span>`; } finally { b.disabled = false; }
};

/* campaigns */
async function loadCampaigns() {
  const list = await api('/outreach/campaigns');
  $('#oHistCount').textContent = list.length || '';
  $('#campList').innerHTML = list.length ? list.map(c => {
    const done = c.sent + c.failed, pct = c.total ? done / c.total * 100 : 0;
    return `<button class="camp ${O.camp === c.id ? 'on' : ''}" onclick="openCampaign(${c.id})">
      <div class="row" style="justify-content:space-between"><b>#${c.id} · ${esc(c.template || 'deleted template')}</b>${statusTag(c.status.split(':')[0])}</div>
      <div class="bar" style="margin:8px 0 6px"><i style="width:${pct}%"></i></div>
      <div class="row sm muted" style="justify-content:space-between"><span>${c.dry_run ? 'Test run' : 'Real send'} · ${done}/${c.total}${c.failed ? ` · <span class="err">${c.failed} failed</span>` : ''}</span><span>${c.created_at.slice(0, 16).replace('T', ' ')}</span></div></button>`;
  }).join('') : '<div class="empty">No campaigns yet. Start one from “New campaign”.</div>';
}
async function openCampaign(id) {
  O.camp = id; oTab('history');
  clearTimeout(O.campTimer);
  const c = await api('/outreach/campaigns/' + id);
  const done = c.sent + c.failed;
  const labels = {'dry-run': 'logged (test)', sent: 'sent', bounced: 'bounced', failed: 'failed'};
  $('#campDetail').innerHTML = `<div class="row" style="justify-content:space-between"><h3 style="margin:0">#${c.id} · ${esc(c.template || '')}</h3>
      ${c.live ? `<button class="btn r" onclick="stopCamp(${c.id})">■ Stop</button>` : statusTag(c.status.split(':')[0])}</div>
    <p class="sm muted">${c.dry_run ? 'Test run, nothing was sent.' : 'Real send.'} Started ${c.created_at.replace('T', ' ').slice(0, 16)} UTC${c.finished_at ? ', finished ' + c.finished_at.replace('T', ' ').slice(11, 16) : ''}.</p>
    ${c.status.startsWith('failed') ? `<div class="warnbox sm">${esc(c.status)}</div>` : ''}
    <div class="bar" style="margin:10px 0"><i style="width:${c.total ? done / c.total * 100 : 0}%"></i></div>
    <div class="sm" style="margin-bottom:10px"><b>${done}</b> of ${c.total} processed${c.failed ? ` · <span class="err">${c.failed} failed</span>` : ''}${c.live && !c.dry_run ? ' · next email in a few minutes (pacing)' : ''}</div>
    <div style="max-height:420px;overflow:auto"><table><thead><tr><th>Time</th><th>Company</th><th>Email</th><th>Result</th></tr></thead><tbody>
    ${c.log.length ? c.log.map(x => `<tr><td class="mono sm">${x.ts.slice(11, 16)}</td><td>${esc(x.company || '')}</td><td class="mono sm">${esc(x.email)}</td><td>${statusTag(labels[x.result] || x.result)} <span class="sm err">${esc(x.error || '')}</span></td></tr>`).join('') : '<tr><td colspan="4" class="empty">Nothing processed yet.</td></tr>'}
    </tbody></table></div>`;
  loadCampaigns();
  if (c.live) O.campTimer = setTimeout(() => { if (state.view === 'outreach' && O.camp === id) openCampaign(id); }, 2500);
  else loadStatus().catch(() => {});
}
window.openCampaign = openCampaign;
window.stopCamp = async id => { await api(`/outreach/campaigns/${id}/stop`, {method: 'POST'}); toast('Stopping after the current email'); setTimeout(() => openCampaign(id), 800); };

/* settings */
async function loadAccount() {
  const s = await api('/secrets');
  $('#acctTag').innerHTML = s.SENDER_EMAIL && s.APP_PASSWORD ? '<span class="tag ok">connected</span>' : '<span class="tag w">not set up</span>';
  $('#secEmail').placeholder = O.status?.sender || 'you@gmail.com';
}
$('#saveSmtp').onclick = async () => {
  const body = {}; if ($('#secEmail').value) body.SENDER_EMAIL = $('#secEmail').value.trim(); if ($('#secPwd').value) body.APP_PASSWORD = $('#secPwd').value;
  try { if (Object.keys(body).length) await api('/secrets', {method: 'PUT', body}); await saveSections(['outreach']); $('#secEmail').value = $('#secPwd').value = ''; loadAccount(); loadStatus(); } catch (e) { fail(e); }
};
$('#testSmtp').onclick = async () => { $('#smtpRes').innerHTML = '<span class="spin"></span>'; try { await api('/outreach/test-smtp', {method: 'POST'}); $('#smtpRes').innerHTML = '<span class="tag ok">login works</span>'; } catch (e) { $('#smtpRes').innerHTML = `<span class="err">${esc(e.message)}</span>`; } };
$('#saveOutreach').onclick = async () => { try { await saveSections(['outreach']); loadStatus(); } catch (e) { fail(e); } };

/* Leads panel → attachment */
$('#saveAtt').onclick = async () => {
  const name = prompt('Save the leads in this view as an attachment named:', `leads-${new Date().toISOString().slice(0, 10)}.csv`); if (!name) return;
  const p = Object.fromEntries(leadQuery());
  const ids = state.selected.size ? [...state.selected] : null;
  try { const r = await api('/attachments/from-leads', {method: 'POST', body: {name, ids, filters: ids ? {} : {q: p.q, city: p.city, district: p.district, status: p.status, type: p.type, has_email: p.has_email === 'true'}}}); toast(`Saved ${r.name} (${r.rows} leads). Attach it in Outreach → Message.`); } catch (e) { fail(e); }
};

/* ---------- filters ---------- */
const LIST_LABELS = {patterns: 'Block patterns (wildcard)', domains: 'Block domains', domain_suffixes: 'Block domain suffixes', domain_extensions: 'Block domain extensions', localparts: 'Block local parts (exact)', localpart_prefixes: 'Block local-part prefixes', localpart_contains: 'Block local-part contains'};
async function loadFilters() {
  const f = await api('/filters/email');
  $('#layers').innerHTML = f.layers.map(l => `<div class="layer"><span class="n">${l.n}</span><span>${l.name}${l.rules != null ? ` <a href="#" class="sm" data-list="${l.list}">· ${S.filters.lists[l.list]?.length ?? l.rules} rules</a>` : ''}</span><span class="c">${l.blocked} blocked</span><label class="sw"><input type="checkbox" data-layer="${l.n}" ${S.filters.layers[l.n] !== false ? 'checked' : ''}><i></i></label></div>`).join('');
  $$('[data-layer]').forEach(c => c.onchange = () => S.filters.layers[c.dataset.layer] = c.checked);
  $$('[data-list]').forEach(a => a.onclick = e => { e.preventDefault(); $('#listSel').value = a.dataset.list; renderList(); $('#listChips').scrollIntoView({behavior: 'smooth'}); });
  if (!$('#listSel').options.length) $('#listSel').innerHTML = Object.entries(LIST_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
  renderList();
}
function renderList() { const k = $('#listSel').value; renderChips($('#listChips'), () => S.filters.lists[k] || [], a => S.filters.lists[k] = a, 'mono'); }
$('#listSel').onchange = renderList;
$('#saveLayers').onclick = () => saveSections(['filters']).catch(fail);
$('#reapply').onclick = async () => { try { await saveSections(['filters']); const r = await api('/filters/reapply', {method: 'POST'}); toast(`Re-applied: ${r.changed} emails changed`); loadFilters(); } catch (e) { fail(e); } };
async function testEmails(list) { await api('/config', {method: 'PUT', body: {filters: S.filters}}); return api('/filters/test', {method: 'POST', body: {emails: list}}); }
let tT;
$('#tester').oninput = e => {
  clearTimeout(tT);
  const v = e.target.value.trim(); if (!v) { $('#testRes').innerHTML = ''; return; }
  tT = setTimeout(async () => {
    const [r] = await testEmails([v]);
    $('#testRes').innerHTML = `<div class="test-r" style="background:${r.kept ? '#2bd4a422' : '#ff5d6c22'};color:${r.kept ? 'var(--acc2)' : 'var(--bad)'}">${r.kept ? '✔ Kept as ' + esc(r.email) : `✖ Blocked at layer ${r.layer} — ${esc(r.reason)}`}</div>`;
  }, 250);
};
$('#batchBtn').onclick = async () => {
  try {
    const r = await testEmails($('#batch').value.split('\n').map(x => x.trim()).filter(Boolean));
    $('#batchRes').innerHTML = `<b>${r.filter(x => x.kept).length}/${r.length} kept</b><br>` + r.map(x => `<span class="mono" style="color:${x.kept ? 'var(--acc2)' : 'var(--bad)'}">${x.kept ? '✔' : '✖'} ${esc(x.input)}</span> <span class="muted">${x.kept ? '' : 'L' + x.layer + ' ' + esc(x.reason)}</span>`).join('<br>');
  } catch (e) { fail(e); }
};

/* ---------- providers ---------- */
const PCOL = {selenium_maps: ['G', '#4f8cff'], places_api: ['P', '#34a853'], serpapi: ['S', '#ff7a45'], outscraper: ['O', '#9b6bff'], crawler: ['C', '#2bd4a4'], hunter: ['H', '#ff5d6c'], nominatim: ['N', '#6b7a90']};
async function loadProviders() {
  providers = await api('/providers');
  $('#provs').innerHTML = providers.map(p => `<div class="card"><div class="prov"><div class="pico" style="background:${PCOL[p.id][1]}">${PCOL[p.id][0]}</div><div style="flex:1"><b>${esc(p.name)}</b><div><span class="tag">${p.kind}</span> ${p.secret ? (p.key_set ? '<span class="tag ok">key set</span>' : '<span class="tag w">no key</span>') : ''}</div></div>
    ${p.can_discover ? '' : `<label class="sw"><input type="checkbox" data-pen="${p.id}" ${p.enabled ? 'checked' : ''}><i></i></label>`}</div>
    <p class="sm muted">${esc(p.about)}</p>
    ${p.secret ? `<label class="f">API key <span class="mono">${p.secret}</span></label><div class="row"><input type="password" id="key-${p.id}" placeholder="${p.key_set ? '•••••• (set — type to replace)' : 'paste key'}" style="flex:1" autocomplete="off"><button class="btn" data-psave="${p.id}">Save</button><button class="btn" data-ptest="${p.id}" ${p.key_set ? '' : 'disabled'}>Test</button></div>` : '<span class="tag ok">no key needed</span>'}
    ${p.can_discover ? '<div class="sm muted" style="margin-top:8px">Choose it as “Data source” in Search Builder.</div>' : ''}</div>`).join('');
  $$('[data-pen]').forEach(c => c.onchange = async () => { try { providers = await api('/providers/' + c.dataset.pen, {method: 'PUT', body: {enabled: c.checked}}); S.providers[c.dataset.pen] = {enabled: c.checked}; toast('Saved'); } catch (e) { fail(e); } });
  $$('[data-psave]').forEach(b => b.onclick = async () => { const v = $('#key-' + b.dataset.psave).value; if (!v) return; try { await api('/providers/' + b.dataset.psave, {method: 'PUT', body: {key: v}}); toast('Key saved to .env'); loadProviders(); } catch (e) { fail(e); } });
  $$('[data-ptest]').forEach(b => b.onclick = async () => { b.innerHTML = '<span class="spin"></span>'; try { await api(`/providers/${b.dataset.ptest}/test`, {method: 'POST'}); toast('Key works'); } catch (e) { fail(e); } b.textContent = 'Test'; });
  fillSources();
}
function fillSources() {
  const cur = $('#srcSel').value;
  $('#srcSel').innerHTML = providers.filter(p => p.can_discover).map(p => `<option value="${p.id}" ${p.secret && !p.key_set ? 'disabled' : ''}>${esc(p.name)}${p.secret && !p.key_set ? ' (no key)' : ''}</option>`).join('');
  if (cur) $('#srcSel').value = cur;
  updateSummary();
}

/* ---------- presets ---------- */
async function loadPresets() {
  const list = await api('/presets');
  $('#presets').innerHTML = list.length ? list.map(p => `<div class="card"><h3>★ ${esc(p.name)} ${p.is_default ? '<span class="tag ok">default</span>' : ''}<small><button class="btn r" style="padding:2px 8px" onclick="delPreset(${p.id})">×</button></small></h3><p class="sm muted">${esc(p.description || '')}</p><div class="row"><span class="tag">${esc(srcName(p.source))}</span><div style="flex:1"></div><button class="btn" onclick="usePreset(${p.id},false)">Load</button><button class="btn g" onclick="usePreset(${p.id},true)">▶ Run</button></div></div>`).join('') : '<div class="empty">No presets. Save one from Search Builder.</div>';
  window._presets = list;
}
window.delPreset = async id => { if (!confirm('Delete preset?')) return; await api('/presets/' + id, {method: 'DELETE'}); loadPresets(); };
window.usePreset = async (id, run) => {
  const p = window._presets.find(x => x.id === id);
  Object.assign(S.search, p.search); bindInputs();
  if ([...$('#srcSel').options].some(o => o.value === p.source && !o.disabled)) $('#srcSel').value = p.source;
  else if (run) return toast(`${srcName(p.source)} needs an API key first`, true);
  go('search');
  if (run) $('#startBtn').click(); else toast('Preset loaded');
};

/* ---------- boot ---------- */
(async function boot() {
  try {
    [S, providers] = await Promise.all([api('/config'), api('/providers')]);
    bindInputs(); fillSources(); loadDash();
  } catch (e) { fail(e); $('#apiDot').style.color = 'var(--bad)'; }
})();
