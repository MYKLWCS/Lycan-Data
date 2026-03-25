/* Lycan OSINT — Knowledge Graph Canvas Renderer */
(function () {
  'use strict';

  var API = '/kg';
  var AUTH = localStorage.getItem('lycan_api_key') || '';
  var headers = { 'Content-Type': 'application/json' };
  if (AUTH) headers['Authorization'] = 'Bearer ' + AUTH;

  var nodes = [];
  var edges = [];
  var selectedNode = null;
  var zoom = 1;
  var panX = 0, panY = 0;
  var dragging = false, dragNode = null;
  var lastMouse = { x: 0, y: 0 };

  var COLORS = {
    Person: '#00c3ff', Company: '#ff6b6b', Address: '#ffc300',
    Phone: '#00ffaa', Email: '#9d00ff', Property: '#ff9500',
    Vehicle: '#36d1dc', Court_Case: '#ff2a55', Social_Profile: '#a855f7',
    Domain: '#06b6d4', Crypto_Wallet: '#f59e0b'
  };
  var SIZES = {
    Person: 18, Company: 22, Address: 12, Phone: 10, Email: 10,
    Property: 14, Vehicle: 12, Court_Case: 14, Social_Profile: 12,
    Domain: 12, Crypto_Wallet: 12
  };

  var canvas = document.getElementById('graph-canvas');
  var ctx = canvas.getContext('2d');

  function resize() {
    var container = document.getElementById('graph-container');
    var dpr = window.devicePixelRatio || 1;
    canvas.width = container.clientWidth * dpr;
    canvas.height = container.clientHeight * dpr;
    canvas.style.width = container.clientWidth + 'px';
    canvas.style.height = container.clientHeight + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }
  window.addEventListener('resize', resize);
  resize();

  function draw() {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.width / dpr;
    var h = canvas.height / dpr;
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(panX + w / 2, panY + h / 2);
    ctx.scale(zoom, zoom);

    ctx.strokeStyle = 'rgba(0, 195, 255, 0.15)';
    ctx.lineWidth = 1;
    for (var ei = 0; ei < edges.length; ei++) {
      var e = edges[ei];
      var a = findNode(e.source);
      var b = findNode(e.target);
      if (a && b) {
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }

    for (var ni = 0; ni < nodes.length; ni++) {
      var n = nodes[ni];
      var r = SIZES[n.label] || 14;
      var col = COLORS[n.label] || '#888';

      if (selectedNode && selectedNode.id === n.id) {
        ctx.save();
        ctx.shadowColor = col;
        ctx.shadowBlur = 20;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 4, 0, Math.PI * 2);
        ctx.fillStyle = col + '33';
        ctx.fill();
        ctx.restore();
      }

      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();

      ctx.fillStyle = '#e0e8f0';
      ctx.font = '10px Inter, sans-serif';
      ctx.textAlign = 'center';
      var displayName = getDisplayName(n);
      ctx.fillText(displayName, n.x, n.y + r + 12);
    }

    ctx.restore();
    document.getElementById('node-count').textContent = String(nodes.length);
    document.getElementById('edge-count').textContent = String(edges.length);
  }

  function findNode(id) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].id === id) return nodes[i];
    }
    return null;
  }

  function getDisplayName(n) {
    if (n.data) {
      return n.data.name || n.data.legal_name || n.data.number || n.data.address || n.id.slice(0, 8);
    }
    return n.id.slice(0, 8);
  }

  function mouseToGraph(evt) {
    var rect = canvas.getBoundingClientRect();
    var w = rect.width;
    var h = rect.height;
    var cx = evt.clientX - rect.left;
    var cy = evt.clientY - rect.top;
    return {
      mx: (cx - panX - w / 2) / zoom,
      my: (cy - panY - h / 2) / zoom
    };
  }

  function hitTest(mx, my) {
    for (var i = nodes.length - 1; i >= 0; i--) {
      var n = nodes[i];
      var r = (SIZES[n.label] || 14) + 4;
      var dx = mx - n.x;
      var dy = my - n.y;
      if (dx * dx + dy * dy <= r * r) return n;
    }
    return null;
  }

  function selectNode(n) {
    selectedNode = n;
    var panel = document.getElementById('node-panel');
    document.getElementById('panel-title').textContent = getDisplayName(n);
    document.getElementById('panel-label').textContent = n.label;

    var dl = document.getElementById('panel-props');
    while (dl.firstChild) dl.removeChild(dl.firstChild);
    if (n.data) {
      var keys = Object.keys(n.data);
      for (var ki = 0; ki < keys.length; ki++) {
        var k = keys[ki];
        if (k === 'entity_id' || k === 'updated_at') continue;
        var dt = document.createElement('dt');
        dt.textContent = k;
        var dd = document.createElement('dd');
        var val = n.data[k];
        dd.textContent = typeof val === 'object' ? JSON.stringify(val) : String(val);
        dl.appendChild(dt);
        dl.appendChild(dd);
      }
    }
    panel.classList.add('visible');
    draw();
  }

  function closePanel() {
    selectedNode = null;
    document.getElementById('node-panel').classList.remove('visible');
    draw();
  }

  // ── Canvas events ─────────────────────────────────────────────────────────
  canvas.addEventListener('mousedown', function (evt) {
    var coords = mouseToGraph(evt);
    var hit = hitTest(coords.mx, coords.my);
    if (hit) {
      dragNode = hit;
      selectNode(hit);
    } else {
      dragging = true;
      closePanel();
    }
    lastMouse = { x: evt.clientX, y: evt.clientY };
  });

  canvas.addEventListener('mousemove', function (evt) {
    var dx = evt.clientX - lastMouse.x;
    var dy = evt.clientY - lastMouse.y;
    if (dragNode) {
      dragNode.x += dx / zoom;
      dragNode.y += dy / zoom;
      draw();
    } else if (dragging) {
      panX += dx;
      panY += dy;
      draw();
    }
    lastMouse = { x: evt.clientX, y: evt.clientY };
  });

  canvas.addEventListener('mouseup', function () {
    dragging = false;
    dragNode = null;
  });

  canvas.addEventListener('wheel', function (evt) {
    evt.preventDefault();
    var factor = evt.deltaY > 0 ? 0.9 : 1.1;
    zoom = Math.max(0.1, Math.min(5, zoom * factor));
    draw();
  }, { passive: false });

  canvas.addEventListener('dblclick', function (evt) {
    var coords = mouseToGraph(evt);
    var hit = hitTest(coords.mx, coords.my);
    if (hit) expandNode(hit.id);
  });

  // ── Node / edge management ────────────────────────────────────────────────
  function addNode(id, label, data) {
    if (findNode(id)) return;
    nodes.push({
      id: id, label: label, data: data,
      x: (Math.random() - 0.5) * 400,
      y: (Math.random() - 0.5) * 300
    });
  }

  function addEdge(source, target) {
    for (var i = 0; i < edges.length; i++) {
      var e = edges[i];
      if ((e.source === source && e.target === target) ||
          (e.source === target && e.target === source)) return;
    }
    edges.push({ source: source, target: target });
  }

  function inferLabel(data) {
    if (data.legal_name || data.ein) return 'Company';
    if (data.full_name || data.dob) return 'Person';
    if (data.street || data.zip) return 'Address';
    if (data.number && data.carrier) return 'Phone';
    if (data.domain && data.breach_count !== undefined) return 'Email';
    if (data.vin) return 'Vehicle';
    if (data.case_number) return 'Court_Case';
    if (data.platform && data.username) return 'Social_Profile';
    if (data.domain_name) return 'Domain';
    if (data.chain && data.balance !== undefined) return 'Crypto_Wallet';
    return 'Person';
  }

  // ── Force layout ──────────────────────────────────────────────────────────
  function applyLayout() {
    var iterations = 50;
    var repulsion = 5000;
    var attraction = 0.01;
    var damping = 0.9;
    var len = nodes.length;
    var vx = new Float64Array(len);
    var vy = new Float64Array(len);

    for (var iter = 0; iter < iterations; iter++) {
      for (var i = 0; i < len; i++) {
        for (var j = i + 1; j < len; j++) {
          var dx = nodes[j].x - nodes[i].x;
          var dy = nodes[j].y - nodes[i].y;
          var dist = Math.sqrt(dx * dx + dy * dy) || 1;
          var force = repulsion / (dist * dist);
          var fx = (dx / dist) * force;
          var fy = (dy / dist) * force;
          vx[i] -= fx; vy[i] -= fy;
          vx[j] += fx; vy[j] += fy;
        }
      }
      for (var ei = 0; ei < edges.length; ei++) {
        var e = edges[ei];
        var ai = -1, bi = -1;
        for (var k = 0; k < len; k++) {
          if (nodes[k].id === e.source) ai = k;
          if (nodes[k].id === e.target) bi = k;
        }
        if (ai < 0 || bi < 0) continue;
        var dx2 = nodes[bi].x - nodes[ai].x;
        var dy2 = nodes[bi].y - nodes[ai].y;
        var dist2 = Math.sqrt(dx2 * dx2 + dy2 * dy2) || 1;
        var force2 = dist2 * attraction;
        var fx2 = (dx2 / dist2) * force2;
        var fy2 = (dy2 / dist2) * force2;
        vx[ai] += fx2; vy[ai] += fy2;
        vx[bi] -= fx2; vy[bi] -= fy2;
      }
      for (var m = 0; m < len; m++) {
        vx[m] *= damping;
        vy[m] *= damping;
        nodes[m].x += vx[m];
        nodes[m].y += vy[m];
      }
    }
  }

  // ── API calls ─────────────────────────────────────────────────────────────
  function searchEntity() {
    var label = document.getElementById('search-type').value;
    var term = document.getElementById('search-input').value.trim();
    if (!term) return;

    var btn = document.getElementById('btn-search');
    btn.disabled = true;

    fetch(API + '/search', {
      method: 'POST', headers: headers,
      body: JSON.stringify({ label: label, search_term: term, limit: 20 })
    })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (data.results && data.results.length > 0) {
        for (var i = 0; i < data.results.length; i++) {
          var entity = data.results[i];
          addNode(entity.entity_id || entity.id || String(i), label, entity);
        }
        applyLayout();
        draw();
      }
    })
    .catch(function (err) { console.error('Search failed:', err); })
    .finally(function () { btn.disabled = false; });
  }

  function expandNode(entityId) {
    fetch(API + '/expand/' + encodeURIComponent(entityId), { headers: headers })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (data.neighbours) {
        for (var i = 0; i < data.neighbours.length; i++) {
          var nb = data.neighbours[i];
          var nbData = nb.node || {};
          var nbId = nbData.entity_id || nbData.id || String(Math.random()).slice(2);
          var nbLabel = inferLabel(nbData);
          addNode(nbId, nbLabel, nbData);
          addEdge(entityId, nbId);
        }
        applyLayout();
        draw();
      }
    })
    .catch(function (err) { console.error('Expand failed:', err); });
  }

  function runSaturation() {
    var term = document.getElementById('search-input').value.trim();
    if (!term) { window.alert('Enter a seed entity first'); return; }

    var seedType = document.getElementById('search-type').value === 'Company' ? 'company' : 'person';
    var body = {
      seed: term,
      seed_type: seedType,
      max_depth: parseInt(document.getElementById('sat-depth').value, 10) || 3,
      max_entities: parseInt(document.getElementById('sat-max').value, 10) || 200,
      confidence_threshold: parseFloat(document.getElementById('sat-conf').value) || 0.6,
      novelty_threshold: parseFloat(document.getElementById('sat-novelty').value) || 0.05
    };

    var statsEl = document.getElementById('sat-stats');
    statsEl.style.display = 'block';
    statsEl.textContent = 'Running saturation crawl...';

    fetch(API + '/saturate', {
      method: 'POST', headers: headers, body: JSON.stringify(body)
    })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      var lines = [
        'Entities processed: ' + data.entities_processed,
        'Total results: ' + data.total_results,
        'Novel results: ' + data.novel_results,
        'Novelty rate: ' + (data.final_novelty_rate * 100).toFixed(1) + '%',
        'Saturation: ' + (data.saturation_reached ? 'REACHED' : 'NOT REACHED'),
        'Elapsed: ' + data.elapsed_seconds + 's'
      ];
      statsEl.textContent = lines.join('\n');
      searchEntity();
    })
    .catch(function (err) {
      statsEl.textContent = 'Error: ' + err.message;
    });
  }

  // ── Controls ──────────────────────────────────────────────────────────────
  document.getElementById('btn-zoom-in').addEventListener('click', function () {
    zoom = Math.min(5, zoom * 1.2); draw();
  });
  document.getElementById('btn-zoom-out').addEventListener('click', function () {
    zoom = Math.max(0.1, zoom / 1.2); draw();
  });
  document.getElementById('btn-reset').addEventListener('click', function () {
    zoom = 1; panX = 0; panY = 0; draw();
  });
  document.getElementById('btn-fit').addEventListener('click', function () {
    if (nodes.length === 0) return;
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (var i = 0; i < nodes.length; i++) {
      minX = Math.min(minX, nodes[i].x); maxX = Math.max(maxX, nodes[i].x);
      minY = Math.min(minY, nodes[i].y); maxY = Math.max(maxY, nodes[i].y);
    }
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.width / dpr;
    var h = canvas.height / dpr;
    zoom = Math.min(w / ((maxX - minX) + 100), h / ((maxY - minY) + 100), 2);
    panX = 0; panY = 0;
    draw();
  });

  document.getElementById('panel-close').addEventListener('click', closePanel);
  document.getElementById('btn-expand').addEventListener('click', function () {
    if (selectedNode) expandNode(selectedNode.id);
  });
  document.getElementById('btn-search').addEventListener('click', searchEntity);
  document.getElementById('btn-saturate').addEventListener('click', function () {
    var panel = document.getElementById('saturation-panel');
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  });
  document.getElementById('btn-run-sat').addEventListener('click', runSaturation);
  document.getElementById('search-input').addEventListener('keydown', function (evt) {
    if (evt.key === 'Enter') searchEntity();
  });

  draw();
})();
