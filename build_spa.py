import os

def build():
    with open('static/style.css', 'r') as f:
        css = f.read()

    with open('static/app.js', 'r') as f:
        js = f.read()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lycan OSINT</title>
<style>
{css}
.hidden {{ display: none !important; }}
</style>
</head>
<body>
<div class="layout">
  <nav class="sidebar">
    <div class="logo">
      <span class="logo-icon">◈</span>
      <span class="logo-text">LYCAN</span>
    </div>
    <div class="nav-label">INTELLIGENCE</div>
    <a href="#/" class="nav-item" id="nav-search">⬡ Search</a>
    <a href="#/persons" class="nav-item" id="nav-persons">⬡ Persons</a>
    <div class="nav-label">SYSTEM</div>
    <a href="#/activity" class="nav-item" id="nav-activity">⬡ Activity</a>
    <a href="/docs" class="nav-item" target="_blank">⬡ API Docs</a>
    <div class="sidebar-bottom">
      <div class="status-row" id="sys-status"><span class="dot green pulse"></span><span>System Online</span></div>
      <div class="status-row" id="crawler-count"><span class="dot blue"></span><span id="crawler-num">—</span> crawlers</div>
    </div>
  </nav>

  <main class="main" id="app-root">
    <!-- Views will be injected here -->
  </main>
</div>

<script>
{js}
</script>

<script>
const App = {{
  root: document.getElementById('app-root'),
  
  async init() {{
    window.addEventListener('hashchange', () => this.route());
    this.route();
    
    // Update system stats
    try {{
      const d = await window.Lycan.apiGet('/system/health');
      document.getElementById('crawler-num').textContent = d.crawlers_registered;
    }} catch(e) {{}}
  }},

  route() {{
    const hash = window.location.hash || '#/';
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    
    if (hash === '#/') {{
      document.getElementById('nav-search').classList.add('active');
      this.renderSearch();
    }} else if (hash === '#/persons') {{
      document.getElementById('nav-persons').classList.add('active');
      this.renderPersons();
    }} else if (hash === '#/activity') {{
      document.getElementById('nav-activity').classList.add('active');
      this.renderActivity();
    }} else if (hash.startsWith('#/person/')) {{
      document.getElementById('nav-persons').classList.add('active');
      const id = hash.split('/')[2];
      this.renderPerson(id);
    }} else {{
      this.renderSearch();
    }}
  }},

  // ---------------------------------------------------------
  // Search View
  // ---------------------------------------------------------
  async renderSearch() {{
    this.root.innerHTML = `
      <div class="hero">
        <div class="hero-title">Intelligence Search</div>
        <div id="search-error" class="card hidden" style="border-color:var(--red);background:var(--red-lo);color:var(--red);padding:10px;margin-bottom:20px;text-align:center"></div>
        <div class="hero-sub">Search any identifier — name, username, phone, email, domain, VIN, crypto wallet</div>
        <div class="search-box">
          <div class="search-type-row" id="search-types">
            <button class="type-btn active" data-type="auto">Auto</button>
            <button class="type-btn" data-type="full_name">Name</button>
            <button class="type-btn" data-type="username">Username</button>
            <button class="type-btn" data-type="phone">Phone</button>
            <button class="type-btn" data-type="email">Email</button>
            <button class="type-btn" data-type="domain">Domain</button>
            <button class="type-btn" data-type="vin">VIN</button>
            <button class="type-btn" data-type="crypto_wallet">Crypto</button>
          </div>
          <div class="search-row">
            <input id="query" class="search-input" type="text" placeholder="Enter identifier..." autocomplete="off" autofocus>
            <select id="context-sel" class="context-sel">
              <option value="general">General</option>
              <option value="risk">Risk Assessment</option>
              <option value="wealth">Wealth</option>
              <option value="identity">Identity</option>
            </select>
            <button id="search-btn" class="search-btn">Search</button>
          </div>
        </div>
        <div class="recent hidden" id="recent-block">
          <div class="recent-label">RECENT</div>
          <div id="recent-list" class="recent-list"></div>
        </div>
      </div>
      <div class="stats-row">
        <div class="stat-card"><div class="stat-num" id="stat-persons">—</div><div class="stat-label">Persons Indexed</div></div>
        <div class="stat-card"><div class="stat-num" id="stat-crawlers">59</div><div class="stat-label">Active Scrapers</div></div>
        <div class="stat-card"><div class="stat-num" id="stat-sources">40+</div><div class="stat-label">Data Sources</div></div>
        <div class="stat-card"><div class="stat-num" id="stat-tor">3</div><div class="stat-label">Tor Circuits</div></div>
      </div>
    `;

    try {{
      const d = await window.Lycan.apiGet('/persons');
      document.getElementById('stat-persons').textContent = d.total ?? '—';
    }} catch(e) {{}}

    const types = document.querySelectorAll('.type-btn');
    types.forEach(btn => btn.addEventListener('click', () => {{
      types.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    }}));

    const sBtn = document.getElementById('search-btn');
    const qInp = document.getElementById('query');
    sBtn.addEventListener('click', () => this.doSearch());
    qInp.addEventListener('keydown', e => {{ if(e.key==='Enter') this.doSearch(); }});

    this.renderRecent();
  }},

  async doSearch() {{
    const q = document.getElementById('query').value.trim();
    if(!q) return;
    const tBtn = document.querySelector('.type-btn.active');
    const type = tBtn?.dataset.type === 'auto' ? null : tBtn?.dataset.type;
    const ctx = document.getElementById('context-sel').value;
    
    const btn = document.getElementById('search-btn');
    btn.textContent = 'Searching…'; btn.disabled = true;
    const errEl = document.getElementById('search-error');
    errEl.classList.add('hidden');

    try {{
      const r = await fetch('/search', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{ value: q, seed_type: type, context: ctx, priority: 'high' }})
      }});
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      
      const recent = JSON.parse(localStorage.getItem('lycan_recent')||'[]');
      recent.unshift({{ value: q, person_id: d.person_id, ts: Date.now() }});
      localStorage.setItem('lycan_recent', JSON.stringify(recent.slice(0,10)));
      
      window.location.hash = '#/person/' + d.person_id;
    }} catch(e) {{
      btn.textContent = 'Search'; btn.disabled = false;
      errEl.textContent = 'Search failed: ' + e.message;
      errEl.classList.remove('hidden');
    }}
  }},

  renderRecent() {{
    const recent = JSON.parse(localStorage.getItem('lycan_recent')||'[]');
    if(recent.length) {{
      document.getElementById('recent-block').classList.remove('hidden');
      const list = document.getElementById('recent-list');
      list.innerHTML = '';
      recent.slice(0,6).forEach(r => {{
        const a = document.createElement('a');
        a.href = '#/person/'+r.person_id;
        a.className = 'recent-item';
        a.textContent = r.value;
        list.appendChild(a);
      }});
    }}
  }},

  // ---------------------------------------------------------
  // Persons List
  // ---------------------------------------------------------
  async renderPersons() {{
    this.root.innerHTML = `<div class="page-header"><div><h1 class="page-title">Indexed Persons</h1></div></div><div id="persons-body">Loading...</div>`;
    try {{
      const d = await window.Lycan.apiGet('/persons');
      let html = `<div class="card"><div class="card-body" style="padding:0"><table class="data-table">
        <thead><tr><th>Name / ID</th><th>Risk</th><th>Created</th><th>Actions</th></tr></thead><tbody>`;
      if (!d.persons.length) {{
        html += `<tr><td colspan="4"><div class="empty-state"><div class="empty-state-title">No persons indexed</div></div></td></tr>`;
      }} else {{
        for (const p of d.persons) {{
          html += `<tr>
            <td><div style="font-weight:600;color:#e8eef5">${{p.full_name || 'Unknown'}}</div><div class="dim mono" style="font-size:10px">${{p.id}}</div></td>
            <td><span class="tag" style="background:${{window.Lycan.riskColor(p.default_risk_score)}}">${{window.Lycan.riskTier(p.default_risk_score)}}</span></td>
            <td class="dim mono">${{window.Lycan.fmtDate(p.created_at)}}</td>
            <td><a href="#/person/${{p.id}}" class="btn" style="padding:4px 10px;font-size:11px">View</a></td>
          </tr>`;
        }}
      }}
      html += `</tbody></table></div></div>`;
      document.getElementById('persons-body').innerHTML = html;
    }} catch(e) {{
      document.getElementById('persons-body').innerHTML = `<div class="red-txt">${{e.message}}</div>`;
    }}
  }},

  // ---------------------------------------------------------
  // Activity Log
  // ---------------------------------------------------------
  async renderActivity() {{
    this.root.innerHTML = `<div class="page-header"><div><h1 class="page-title">Activity</h1></div><button class="btn" onclick="App.renderActivity()">Refresh</button></div><div id="activity-body">Loading...</div>`;
    try {{
      const d = await window.Lycan.apiGet('/crawls');
      let html = `<div class="activity-log"><div class="activity-row header"><span>Platform</span><span>Identifier</span><span>Target</span><span>Status</span><span>Started</span></div>`;
      for (const j of d.jobs) {{
        html += `<div class="activity-row">
          <span class="bold">${{j.job_type}}</span>
          <span class="dim mono" style="font-size:10px">${{j.seed_identifier || '—'}}</span>
          <span class="mono" style="font-size:10px">${{j.person_id ? `<a href="#/person/${{j.person_id}}">${{j.person_id.substring(0,8)}}...</a>` : '—'}}</span>
          <span><span class="status-pill ${{j.status.toLowerCase()}}">${{j.status}}</span></span>
          <span class="dim mono" style="font-size:10px">${{window.Lycan.fmtDate(j.created_at)}}</span>
        </div>`;
      }}
      html += `</div>`;
      document.getElementById('activity-body').innerHTML = html;
    }} catch(e) {{
      document.getElementById('activity-body').innerHTML = `<div class="red-txt">${{e.message}}</div>`;
    }}
  }},

  // ---------------------------------------------------------
  // Person Dossier
  // ---------------------------------------------------------
  async renderPerson(id) {{
    this.root.innerHTML = `<div style="margin-bottom:20px"><a href="#/persons" class="btn">← Back</a></div><div id="person-body">Loading dossier...</div>`;
    
    // Disconnect old socket if any
    if(this._lp) this._lp.disconnect();

    try {{
      const d = await window.Lycan.apiGet('/persons/' + id + '/report');
      const p = d.person;
      const avatar = p.profile_image_url ? `<img class="person-avatar" src="${{p.profile_image_url}}">` : `<div class="person-avatar">◎</div>`;
      
      let html = `
        <div class="card" style="margin-bottom:20px"><div class="card-body">
          <div class="person-header">
            ${{avatar}}
            <div class="person-meta">
              <div class="person-name">${{p.full_name || 'Unknown Person'}}</div>
              <div class="tag-row">
                <span class="tag muted mono" style="font-size:10px">${{p.id.substring(0,8)}}</span>
                <span class="tag" style="background:${{window.Lycan.riskColor(p.default_risk_score)}}">${{window.Lycan.riskTier(p.default_risk_score)}} RISK</span>
              </div>
            </div>
          </div>
        </div></div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start">
          <div>
            <!-- Risks -->
            <div class="card">
              <div class="card-header"><span class="card-title">⬡ Risk Assessment</span></div>
              <div class="card-body"><div class="risk-grid">
                <div class="risk-item"><div class="risk-dial" id="dial-default"></div><div class="risk-label">Default</div></div>
                <div class="risk-item"><div class="risk-dial" id="dial-behaviour"></div><div class="risk-label">Behaviour</div></div>
                <div class="risk-item"><div class="risk-dial" id="dial-darkweb"></div><div class="risk-label">Dark Web</div></div>
                <div class="risk-item"><div class="risk-dial" id="dial-relationship"></div><div class="risk-label">Relations</div></div>
              </div></div>
            </div>

            <!-- Identifiers -->
            <div class="card" style="margin-top:16px">
              <div class="card-header"><span class="card-title">⬡ Identifiers</span><span class="card-badge">${{d.identifiers.length}}</span></div>
              <div class="card-body" style="padding:0">
                <table class="data-table"><thead><tr><th>Type</th><th>Value</th><th>Conf</th></tr></thead><tbody>
                  ${{d.identifiers.map(i => `<tr><td><span class="tag muted" style="font-size:10px">${{i.type}}</span></td><td class="mono">${{i.value}}</td><td class="dim">${{Math.round(i.confidence*100)}}%</td></tr>`).join('')}}
                </tbody></table>
              </div>
            </div>
          </div>

          <div>
            <!-- Live Feed -->
            <div class="card">
              <div class="card-header"><span class="card-title">⬡ Live Intelligence Feed</span><span class="card-badge" id="progress-label">active</span></div>
              <div class="card-body" style="padding:10px">
                <div class="progress-bar-wrap"><div class="progress-bar" id="progress-bar" style="width:0"></div></div>
                <div class="live-feed" id="live-feed"></div>
              </div>
            </div>

            <!-- Social Profiles -->
            <div class="card" style="margin-top:16px">
              <div class="card-header"><span class="card-title">⬡ Social Platforms</span><span class="card-badge">${{d.social_profiles.length}}</span></div>
              <div class="card-body">
                <div class="platform-grid">
                  ${{d.social_profiles.map(s => `
                    <div class="platform-card found" data-platform="${{s.platform}}">
                      <div class="platform-name">${{s.platform}}</div>
                      <div class="platform-handle">${{s.handle || s.display_name || '—'}}</div>
                      <div class="platform-status" style="color:var(--green)">● found</div>
                    </div>`).join('')}}
                </div>
              </div>
            </div>
          </div>
        </div>
      `;

      document.getElementById('person-body').innerHTML = html;

      // Draw dials
      window.Lycan.drawRiskDial('dial-default', p.default_risk_score, window.Lycan.riskColor(p.default_risk_score));
      window.Lycan.drawRiskDial('dial-behaviour', p.behavioural_risk, window.Lycan.riskColor(p.behavioural_risk));
      window.Lycan.drawRiskDial('dial-darkweb', p.darkweb_exposure, p.darkweb_exposure > 0 ? '#9f7aea' : 'var(--green)');
      window.Lycan.drawRiskDial('dial-relationship', p.relationship_score, window.Lycan.riskColor(p.relationship_score));

      // Connect WebSocket
      this._lp = new window.Lycan.LiveProgress(id, {{
        feed: document.getElementById('live-feed'),
        bar: document.getElementById('progress-bar'),
        onUpdate: () => {{}},
        onDone: () => {{
          document.getElementById('progress-label').textContent = 'complete';
          document.getElementById('progress-label').style.color = 'var(--green)';
        }}
      }});
      this._lp.connect();

    }} catch(e) {{
      document.getElementById('person-body').innerHTML = `<div class="red-txt">${{e.message}}</div>`;
    }}
  }}
}};

App.init();
</script>
</body>
</html>
"""
    with open('static/index.html', 'w') as f:
        f.write(html)

if __name__ == '__main__':
    build()
