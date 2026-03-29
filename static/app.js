/* Lycan OSINT — shared JS utilities */

'use strict';

// ── Safe DOM helpers ─────────────────────────────────────────────────
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls)  e.className   = cls;
  if (text) e.textContent = text;
  return e;
}

function span(cls, text) { return el('span', cls, text); }
function div(cls)        { return el('div',  cls); }

// ── WebSocket live progress ──────────────────────────────────────────
class LiveProgress {
  constructor(personId, opts = {}) {
    this.personId   = personId;
    this.feed       = opts.feed      || null;
    this.bar        = opts.bar       || null;
    this.onUpdate   = opts.onUpdate  || null;
    this.onDone     = opts.onDone    || null;
    this.total      = 0;
    this.done       = 0;
    this.ws         = null;
    this._reconnect = 0;
  }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url   = `${proto}://${location.host}/ws/progress/${this.personId}`;
    this.ws = new WebSocket(url);

    this.ws.onopen  = () => { this._reconnect = 0; this._log('system', 'Live connection established', 'ok'); };
    this.ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      this._handle(msg);
    };
    this.ws.onclose = () => {
      if (this._reconnect < 5) {
        this._reconnect++;
        setTimeout(() => this.connect(), 2000 * this._reconnect);
      }
    };
  }

  disconnect() { if (this.ws) { this.ws.close(); this.ws = null; } }

  _handle(msg) {
    const { event, platform, found, error, data } = msg;

    if (event === 'job_started') {
      this.total++;
      this._log(platform, 'scanning\u2026', 'scan');
      this._updateBar();
      this._setPlatformState(platform, 'scanning');
    }

    if (event === 'job_complete') {
      this.done++;
      const text = found ? 'found data' : (error || 'no results');
      this._log(platform, text, found ? 'ok' : 'fail');
      this._updateBar();
      this._setPlatformState(platform, found ? 'found' : 'not-found');
      if (this.onUpdate) this.onUpdate({ platform, found, data });
    }

    if (event === 'done') {
      this._log('system', `All scrapers finished (${this.done}/${this.total})`, 'ok');
      if (this.onDone) this.onDone();
    }
  }

  _log(platform, text, cls) {
    if (!this.feed) return;
    const now  = new Date().toLocaleTimeString('en-GB', { hour12: false });
    const line = div('feed-line');
    line.appendChild(span('feed-time',     now));
    line.appendChild(span('feed-platform', platform));
    const msg = span('feed-msg' + (cls ? ' ' + cls : ''), text);
    line.appendChild(msg);
    this.feed.appendChild(line);
    this.feed.scrollTop = this.feed.scrollHeight;
  }

  _updateBar() {
    if (!this.bar || !this.total) return;
    this.bar.style.width = Math.round((this.done / this.total) * 100) + '%';
  }

  _setPlatformState(platform, state) {
    const card = document.querySelector(`[data-platform="${platform}"]`);
    if (!card) return;
    card.classList.remove('scanning', 'found', 'not-found');
    card.classList.add(state);
    const statusEl = card.querySelector('.platform-status');
    if (statusEl) {
      const icons  = { scanning: '\u25cc', found: '\u25cf', 'not-found': '\u25cb' };
      const colors = { scanning: 'var(--accent)', found: 'var(--green)', 'not-found': 'var(--text-mute)' };
      statusEl.style.color = colors[state] || '';
      statusEl.textContent = (icons[state] || '') + ' ' + state.replace('-', ' ');
    }
  }
}

// ── OCEAN bars ───────────────────────────────────────────────────────
function drawOceanBars(data) {
  const dims   = ['openness','conscientiousness','extraversion','agreeableness','neuroticism'];
  const labels = ['Openness','Conscientiousness','Extraversion','Agreeableness','Neuroticism'];
  const container = document.getElementById('ocean-bars');
  if (!container) return;
  container.textContent = '';
  dims.forEach((d, i) => {
    const val = data[d] ?? 0;
    const pct = Math.round(val * 100);
    const row = div('ocean-row');

    const lbl = span('ocean-label', labels[i]);
    const wrap = div('ocean-bar-wrap');
    const inner = div('ocean-bar-inner');
    inner.style.width = pct + '%';
    wrap.appendChild(inner);
    const valEl = span('ocean-val', pct + '%');

    row.appendChild(lbl);
    row.appendChild(wrap);
    row.appendChild(valEl);
    container.appendChild(row);
  });
}

// ── Risk dial (SVG, no innerHTML on user data) ───────────────────────
function drawRiskDial(containerId, score, color) {
  const el2 = document.getElementById(containerId);
  if (!el2) return;
  const pct = Math.min(1, Math.max(0, score));
  const r = 26, cx = 32, cy = 36;
  const startA = -135 * Math.PI / 180;
  const sweepA = 270 * Math.PI / 180;
  const endA   = startA + pct * sweepA;

  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width',   '64');
  svg.setAttribute('height',  '64');
  svg.setAttribute('viewBox', '0 0 64 64');

  function makeArc(a1, a2, stroke) {
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
    const large = (a2 - a1) > Math.PI ? 1 : 0;
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', `M${x1} ${y1} A${r} ${r} 0 ${large} 1 ${x2} ${y2}`);
    path.setAttribute('stroke', stroke);
    path.setAttribute('stroke-width', '4');
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke-linecap', 'round');
    return path;
  }

  svg.appendChild(makeArc(startA, startA + sweepA, 'var(--border)'));
  if (pct > 0) svg.appendChild(makeArc(startA, endA, color));

  const txt = document.createElementNS(ns, 'text');
  txt.setAttribute('x', '32'); txt.setAttribute('y', '41');
  txt.setAttribute('text-anchor', 'middle');
  txt.setAttribute('font-size', '12'); txt.setAttribute('font-weight', '700');
  txt.setAttribute('fill', 'var(--text)');
  txt.setAttribute('font-family', 'var(--mono)');
  txt.textContent = Math.round(pct * 100);
  svg.appendChild(txt);

  el2.textContent = '';
  el2.appendChild(svg);
}

// ── Fetch helpers ────────────────────────────────────────────────────
const _apiKey = localStorage.getItem('lycan_api_key') || '';
function _authHeaders() {
  const h = {};
  if (_apiKey) h['Authorization'] = 'Bearer ' + _apiKey;
  return h;
}
async function apiGet(path) {
  const r = await fetch(path, { headers: _authHeaders() });
  if (r.status === 401) { promptApiKey(); throw new Error('Auth required'); }
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}
function promptApiKey() {
  const key = prompt('Enter API key:');
  if (key) { localStorage.setItem('lycan_api_key', key); location.reload(); }
}

// ── Format helpers ───────────────────────────────────────────────────
function fmtDate(iso) {
  if (!iso) return '\u2014';
  return new Date(iso).toLocaleDateString('en-GB', { year:'numeric', month:'short', day:'numeric' });
}

function fmtNum(n) {
  if (n == null || n === '') return '\u2014';
  return Number(n).toLocaleString();
}

function riskColor(score) {
  if (score >= 0.7) return 'var(--red)';
  if (score >= 0.4) return 'var(--yellow)';
  return 'var(--green)';
}

function riskTier(score) {
  if (score >= 0.7) return 'HIGH';
  if (score >= 0.4) return 'MEDIUM';
  return 'LOW';
}

window.Lycan = { LiveProgress, drawOceanBars, drawRiskDial, apiGet, fmtDate, fmtNum, riskColor, riskTier };
