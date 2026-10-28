const $ = (selector) => document.querySelector(selector);
const STATE = { up: 'Up', degraded: 'Degraded', down: 'Down', unknown: 'Waiting' };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children.filter((c) => c !== null && c !== undefined));
  return node;
}

const pct = (v) => (v === null ? '—' : `${v.toFixed(v === 100 ? 0 : 2)}%`);
const ago = (iso) => {
  if (!iso) return 'not checked yet';
  const s = Math.round((Date.now() - new Date(iso)) / 1000);
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
};
const duration = (s) => (s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);

async function api(path, options) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg.replace(/^Value error, /, '')).join(' ') : body.detail;
    throw new Error(detail || 'Something went wrong.');
  }
  return body;
}

function renderMonitors(monitors) {
  const down = monitors.filter((m) => m.state === 'down').length;
  const failing = monitors.filter((m) => m.state === 'degraded').length;
  const up = monitors.filter((m) => m.state === 'up').length;
  const parts = [down && `${down} down`, failing && `${failing} degraded`, `${up} up`].filter(Boolean);
  $('#summary').textContent = down || failing ? parts.join(' · ') : `All ${monitors.length} up`;
  $('#summary').className = `summary ${down ? 'down' : failing ? 'degraded' : 'up'}`;

  $('#monitors').replaceChildren(...monitors.map((m) => el('li', { class: 'monitor' },
    el('div', { class: 'monitor-head' },
      el('div', {},
        el('strong', {}, m.name),
        el('div', { class: 'muted small' }, m.url)),
      el('span', { class: `badge ${m.state}` }, STATE[m.state] ?? m.state)),
    el('div', { class: 'bars', role: 'img', 'aria-label': `Last 24 hours: ${m.timeline.filter((b) => b === 'down').length} periods with failures` },
      ...m.timeline.map((b) => el('span', { class: `bar ${b}` }))),
    el('div', { class: 'facts small' },
      el('span', {}, `24 h ${pct(m.uptime_24h)}`),
      el('span', {}, `7 d ${pct(m.uptime_7d)}`),
      el('span', {}, m.p95_ms_24h === null ? 'p95 —' : `p95 ${m.p95_ms_24h} ms`),
      el('span', { class: 'muted' }, ago(m.last_checked_at)),
      m.state !== 'up' && m.last_error ? el('span', { class: 'err' }, m.last_error) : null,
      el('button', { class: 'link', onclick: () => remove(m) }, 'Remove')),
  )));
}

function renderIncidents(items) {
  $('#incidents').replaceChildren(...(items.length ? items.map((i) => el('li', {},
    el('span', { class: `badge ${i.resolved_at ? 'up' : 'down'}` }, i.resolved_at ? 'Resolved' : 'Ongoing'),
    ` ${i.monitor} — ${i.cause} `,
    el('span', { class: 'muted' }, `· ${new Date(i.started_at).toLocaleString('en-GB')} · ${duration(i.duration_seconds)} · ${i.failed_checks} failed checks`),
  )) : [el('li', { class: 'muted' }, 'No incidents yet.')]));
}

async function refresh() {
  try {
    const [monitors, incidents] = await Promise.all([api('/api/monitors'), api('/api/incidents')]);
    renderMonitors(monitors);
    renderIncidents(incidents);
  } catch (e) {
    $('#summary').textContent = e.message;
  }
}

async function remove(m) {
  if (!confirm(`Stop monitoring ${m.name}?`)) return;
  await api(`/api/monitors/${m.id}`, { method: 'DELETE' }).catch((e) => alert(e.message));
  refresh();
}

$('#add').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const error = $('#add-error');
  error.hidden = true;
  try {
    await api('/api/monitors', { method: 'POST', body: JSON.stringify({ name: form.get('name'), url: form.get('url') }) });
    event.target.reset();
    refresh();
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  }
});

refresh();
setInterval(refresh, 15000);
