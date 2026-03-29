/* Lycan OSINT — Interactive Relationship Graph Visualization
 *
 * Canvas-based renderer with:
 * - Family tree gravity (parents up, children down, spouses beside)
 * - Color-coded edges by relationship type
 * - Edge thickness by strength, line style by confidence
 * - Click-to-expand lazy loading
 * - Hover tooltips, right-click context menu
 * - Sidebar filter panel
 */
(function () {
  'use strict';

  var API_BASE = '/relationships';
  var AUTH = localStorage.getItem('lycan_api_key') || '';
  var headers = { 'Content-Type': 'application/json' };
  if (AUTH) headers['Authorization'] = 'Bearer ' + AUTH;

  // ── State ─────────────────────────────────────────────────────────────

  var nodes = [];
  var edges = [];
  var centerNodeId = null;
  var selectedNode = null;
  var hoveredNode = null;
  var hoveredEdge = null;
  var zoom = 1;
  var panX = 0, panY = 0;
  var dragging = false, dragNode = null;
  var lastMouse = { x: 0, y: 0 };
  var contextMenu = null;
  var filterState = {
    minConfidence: 0,
    minStrength: 0,
    showLabels: true,
    showPhotos: true,
    hiddenTypes: {},
  };

  // ── Relationship colors ───────────────────────────────────────────────

  var REL_COLORS = {
    spouse: '#DC2626', partner: '#DC2626',
    ex_spouse: '#FCA5A5', ex_partner: '#FCA5A5',
    girlfriend: '#EC4899', boyfriend: '#EC4899',
    parent: '#2563EB', child: '#2563EB',
    sibling: '#60A5FA',
    grandparent: '#1E3A8A', grandchild: '#1E3A8A',
    aunt_uncle: '#0D9488', cousin: '#0D9488',
    in_law: '#7C3AED',
    best_friend: '#16A34A',
    friend: '#4ADE80',
    acquaintance: '#BBF7D0',
    neighbor: '#EAB308', roommate: '#EAB308',
    classmate: '#F59E0B',
    colleague: '#EA580C',
    employer: '#C2410C', employee: '#C2410C',
    business_partner: '#92400E', co_founder: '#92400E',
    client: '#78716C', mentor: '#78716C',
    lawyer: '#991B1B', co_defendant: '#991B1B',
    plaintiff: '#991B1B', witness: '#991B1B',
    co_signer: '#CA8A04', beneficiary: '#CA8A04',
    trustee: '#CA8A04', power_of_attorney: '#CA8A04',
    family: '#2563EB', associate: '#6B7280'
  };

  var RISK_COLORS = {
    critical: '#EF4444', high: '#F97316',
    medium: '#EAB308', low: '#22C55E', unknown: '#6B7280'
  };

  // ── Canvas setup ──────────────────────────────────────────────────────

  var canvas = document.getElementById('graph-canvas');
  var ctx = canvas.getContext('2d');
  var tooltip = document.getElementById('tooltip');

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

  // ── Drawing ───────────────────────────────────────────────────────────

  function draw() {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.width / dpr;
    var h = canvas.height / dpr;
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(panX + w / 2, panY + h / 2);
    ctx.scale(zoom, zoom);

    // Draw edges
    for (var ei = 0; ei < edges.length; ei++) {
      var e = edges[ei];
      if (filterState.hiddenTypes[e.relationship_type]) continue;
      if (e.confidence < filterState.minConfidence / 100) continue;
      if (e.strength < filterState.minStrength) continue;

      var a = findNode(e.source);
      var b = findNode(e.target);
      if (!a || !b) continue;

      var color = e.color || REL_COLORS[e.relationship_type] || '#6B7280';
      var lineWidth = Math.max(1, (e.strength || 50) / 25);

      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = lineWidth;

      if (e.style === 'dotted') {
        ctx.setLineDash([2, 4]);
      } else if (e.style === 'dashed') {
        ctx.setLineDash([6, 4]);
      } else {
        ctx.setLineDash([]);
      }

      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);

      // Pulse animation for recent activity
      if (e._recent) {
        ctx.save();
        ctx.globalAlpha = 0.3 + 0.2 * Math.sin(Date.now() / 400);
        ctx.lineWidth = lineWidth + 3;
        ctx.strokeStyle = color;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.restore();
      }
    }

    // Draw nodes
    for (var ni = 0; ni < nodes.length; ni++) {
      var n = nodes[ni];
      var r = nodeRadius(n);
      var borderColor = n._borderColor || '#6B7280';

      // Glow for selected
      if (selectedNode && selectedNode.id === n.id) {
        ctx.save();
        ctx.shadowColor = borderColor;
        ctx.shadowBlur = 24;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 6, 0, Math.PI * 2);
        ctx.fillStyle = borderColor + '22';
        ctx.fill();
        ctx.restore();
      }

      // Node circle
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = n.id === centerNodeId ? '#0f172a' : '#1e293b';
      ctx.fill();
      ctx.lineWidth = n.id === centerNodeId ? 3 : 2;
      ctx.strokeStyle = borderColor;
      ctx.stroke();

      // Initials
      ctx.fillStyle = '#e0e8f0';
      ctx.font = (r > 16 ? '12' : '10') + 'px Inter, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      var initials = getInitials(n.name || '?');
      ctx.fillText(initials, n.x, n.y);

      // Risk tier badge
      var riskColor = RISK_COLORS[n.risk_tier] || RISK_COLORS.unknown;
      ctx.beginPath();
      ctx.arc(n.x + r - 2, n.y - r + 2, 4, 0, Math.PI * 2);
      ctx.fillStyle = riskColor;
      ctx.fill();

      // Label
      if (filterState.showLabels && n.name) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '10px Inter, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        var label = n.name.length > 20 ? n.name.substring(0, 18) + '..' : n.name;
        ctx.fillText(label, n.x, n.y + r + 4);

        if (n.relationship_to_center && n.id !== centerNodeId) {
          ctx.fillStyle = '#64748b';
          ctx.font = '9px Inter, system-ui, sans-serif';
          ctx.fillText(n.relationship_to_center.replace(/_/g, ' '), n.x, n.y + r + 16);
        }
      }
    }

    ctx.restore();

    document.getElementById('node-count').textContent = String(nodes.length);
    document.getElementById('edge-count').textContent = String(edges.length);
    buildLegend();
  }

  function nodeRadius(n) {
    var base = n.id === centerNodeId ? 28 : 18;
    var score = n.enrichment_score || 0;
    return base + Math.floor(score / 20);
  }

  function getInitials(name) {
    if (!name) return '?';
    var parts = name.split(' ').filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return parts[0][0].toUpperCase();
  }

  function findNode(id) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].id === id) return nodes[i];
    }
    return null;
  }

  // ── Force layout with family-tree gravity ─────────────────────────────

  function applyLayout() {
    var iterations = 80;
    var repulsion = 8000;
    var attraction = 0.008;
    var damping = 0.85;
    var familyGravity = 15;
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
        var ai = nodeIndex(e.source);
        var bi = nodeIndex(e.target);
        if (ai < 0 || bi < 0) continue;
        var dx2 = nodes[bi].x - nodes[ai].x;
        var dy2 = nodes[bi].y - nodes[ai].y;
        var dist2 = Math.sqrt(dx2 * dx2 + dy2 * dy2) || 1;
        var force2 = dist2 * attraction;
        var fx2 = (dx2 / dist2) * force2;
        var fy2 = (dy2 / dist2) * force2;
        vx[ai] += fx2; vy[ai] += fy2;
        vx[bi] -= fx2; vy[bi] -= fy2;

        var relType = e.relationship_type;
        if (relType === 'parent' || relType === 'grandparent') {
          vy[ai] -= familyGravity;
          vy[bi] += familyGravity;
        } else if (relType === 'child' || relType === 'grandchild') {
          vy[ai] += familyGravity;
          vy[bi] -= familyGravity;
        } else if (relType === 'spouse' || relType === 'partner' || relType === 'ex_spouse') {
          var midY = (nodes[ai].y + nodes[bi].y) / 2;
          vy[ai] += (midY - nodes[ai].y) * 0.1;
          vy[bi] += (midY - nodes[bi].y) * 0.1;
        } else if (relType === 'sibling') {
          var midY2 = (nodes[ai].y + nodes[bi].y) / 2;
          vy[ai] += (midY2 - nodes[ai].y) * 0.05;
          vy[bi] += (midY2 - nodes[bi].y) * 0.05;
        }
      }

      for (var m = 0; m < len; m++) {
        vx[m] *= damping;
        vy[m] *= damping;
        nodes[m].x += vx[m];
        nodes[m].y += vy[m];
      }
    }

    var center = findNode(centerNodeId);
    if (center) { center.x = 0; center.y = 0; }
  }

  function nodeIndex(id) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].id === id) return i;
    }
    return -1;
  }

  // ── Mouse interaction ─────────────────────────────────────────────────

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

  function hitTestNode(mx, my) {
    for (var i = nodes.length - 1; i >= 0; i--) {
      var n = nodes[i];
      var r = nodeRadius(n) + 4;
      var dx = mx - n.x;
      var dy = my - n.y;
      if (dx * dx + dy * dy <= r * r) return n;
    }
    return null;
  }

  function hitTestEdge(mx, my) {
    for (var i = 0; i < edges.length; i++) {
      var e = edges[i];
      var a = findNode(e.source);
      var b = findNode(e.target);
      if (!a || !b) continue;
      var dist = pointToSegmentDist(mx, my, a.x, a.y, b.x, b.y);
      if (dist < 8) return e;
    }
    return null;
  }

  function pointToSegmentDist(px, py, x1, y1, x2, y2) {
    var dx = x2 - x1;
    var dy = y2 - y1;
    var len2 = dx * dx + dy * dy;
    if (len2 === 0) return Math.sqrt((px - x1) * (px - x1) + (py - y1) * (py - y1));
    var t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / len2));
    var projX = x1 + t * dx;
    var projY = y1 + t * dy;
    return Math.sqrt((px - projX) * (px - projX) + (py - projY) * (py - projY));
  }

  canvas.addEventListener('mousedown', function (evt) {
    if (evt.button === 2) return;
    hideContextMenu();
    var coords = mouseToGraph(evt);
    var hit = hitTestNode(coords.mx, coords.my);
    if (hit) {
      dragNode = hit;
      selectNode(hit);
    } else {
      dragging = true;
      selectedNode = null;
      document.getElementById('node-panel').classList.remove('visible');
      draw();
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
    } else {
      var coords = mouseToGraph(evt);
      var hitN = hitTestNode(coords.mx, coords.my);
      var hitE = hitN ? null : hitTestEdge(coords.mx, coords.my);

      if (hitN !== hoveredNode || hitE !== hoveredEdge) {
        hoveredNode = hitN;
        hoveredEdge = hitE;
        showTooltip(evt, hitN, hitE);
      }
      if (hoveredNode || hoveredEdge) {
        tooltip.style.left = (evt.clientX + 12) + 'px';
        tooltip.style.top = (evt.clientY + 12) + 'px';
      }
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
    var hit = hitTestNode(coords.mx, coords.my);
    if (hit) {
      window.location.hash = '#/persons/' + hit.id;
    }
  });

  canvas.addEventListener('contextmenu', function (evt) {
    evt.preventDefault();
    var coords = mouseToGraph(evt);
    var hit = hitTestNode(coords.mx, coords.my);
    if (hit) {
      showContextMenu(evt, hit);
    } else {
      hideContextMenu();
    }
  });

  canvas.parentElement.addEventListener('click', function (evt) {
    if (evt.target.closest('.btn-expand-node') && selectedNode) {
      expandNode(selectedNode.id);
    }
  });

  // ── Tooltip ───────────────────────────────────────────────────────────

  function showTooltip(evt, node, edge) {
    if (!node && !edge) {
      tooltip.style.display = 'none';
      return;
    }
    tooltip.style.display = 'block';
    // Clear previous content safely
    while (tooltip.firstChild) tooltip.removeChild(tooltip.firstChild);

    if (node) {
      appendLine(tooltip, (node.name || 'Unknown'), true);
      if (node.age) appendLine(tooltip, 'Age: ' + node.age);
      if (node.location) appendLine(tooltip, 'Location: ' + node.location);
      appendLine(tooltip, 'Enrichment: ' + (node.enrichment_score || 0) + '%');
      if (node.relationship_to_center) {
        appendLine(tooltip, 'Relationship: ' + node.relationship_to_center.replace(/_/g, ' '));
        if (node.strength) appendLine(tooltip, 'Strength: ' + node.strength);
        if (node.confidence) appendLine(tooltip, 'Confidence: ' + Math.round(node.confidence * 100) + '%');
      }
    } else if (edge) {
      appendLine(tooltip, (edge.relationship_type || '').replace(/_/g, ' '), true);
      appendLine(tooltip, 'Strength: ' + (edge.strength || 0));
      appendLine(tooltip, 'Confidence: ' + Math.round((edge.confidence || 0) * 100) + '%');
      if (edge.discovered_via) appendLine(tooltip, 'Source: ' + edge.discovered_via);
      if (edge.last_confirmed) appendLine(tooltip, 'Confirmed: ' + edge.last_confirmed.split('T')[0]);
    }
  }

  function appendLine(parent, text, bold) {
    var el = document.createElement('div');
    el.textContent = text;
    if (bold) el.style.fontWeight = '600';
    parent.appendChild(el);
  }

  // ── Context menu ──────────────────────────────────────────────────────

  function showContextMenu(evt, node) {
    hideContextMenu();
    var menu = document.createElement('div');
    menu.className = 'context-menu';

    var items = [
      { label: 'View Profile', action: 'profile' },
      { label: 'Expand Network', action: 'expand' },
      { label: 'Run Deep Enrich', action: 'enrich' },
      { label: 'Add to Builder Job', action: 'builder' },
      { label: 'Flag for Review', action: 'flag' },
    ];

    for (var i = 0; i < items.length; i++) {
      var item = document.createElement('div');
      item.className = 'ctx-item';
      item.textContent = items[i].label;
      item.dataset.action = items[i].action;
      menu.appendChild(item);
    }

    menu.style.left = evt.clientX + 'px';
    menu.style.top = evt.clientY + 'px';
    document.body.appendChild(menu);
    contextMenu = menu;

    menu.addEventListener('click', function (e) {
      var action = e.target.dataset.action;
      if (action === 'profile') window.location.hash = '#/persons/' + node.id;
      else if (action === 'expand') expandNode(node.id);
      else if (action === 'enrich') triggerEnrich(node.id);
      hideContextMenu();
    });
  }

  function hideContextMenu() {
    if (contextMenu) {
      contextMenu.remove();
      contextMenu = null;
    }
  }

  document.addEventListener('click', function () { hideContextMenu(); });

  // ── Node selection panel ──────────────────────────────────────────────

  function selectNode(n) {
    selectedNode = n;
    var panel = document.getElementById('node-panel');
    document.getElementById('panel-title').textContent = n.name || 'Unknown';
    document.getElementById('panel-label').textContent =
      (n.relationship_to_center || 'center').replace(/_/g, ' ');

    var dl = document.getElementById('panel-props');
    while (dl.firstChild) dl.removeChild(dl.firstChild);

    var props = [
      ['Risk Tier', n.risk_tier],
      ['Enrichment', (n.enrichment_score || 0) + '%'],
      ['Distance', n.distance != null ? n.distance + ' hop(s)' : 'center'],
      ['Strength', n.strength],
      ['Confidence', n.confidence != null ? Math.round(n.confidence * 100) + '%' : '-'],
    ];
    for (var pi = 0; pi < props.length; pi++) {
      if (props[pi][1] == null) continue;
      var dt = document.createElement('dt');
      dt.textContent = props[pi][0];
      var dd = document.createElement('dd');
      dd.textContent = String(props[pi][1]);
      dl.appendChild(dt);
      dl.appendChild(dd);
    }
    panel.classList.add('visible');
    draw();
  }

  // ── API calls ─────────────────────────────────────────────────────────

  function loadPerson(personId) {
    centerNodeId = personId;
    nodes = [];
    edges = [];

    fetch(API_BASE + '/graph/person/' + encodeURIComponent(personId) + '/network?depth=2', { headers: headers })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.center) return;

        var c = data.center;
        nodes.push({
          id: c.id, name: c.name, photo_url: c.photo_url,
          enrichment_score: c.enrichment_score, age: c.age,
          location: c.location, risk_tier: c.risk_tier || 'unknown',
          relationship_to_center: null, strength: 100, confidence: 1.0,
          distance: 0, _borderColor: '#00d46a',
          x: 0, y: 0,
        });

        if (data.nodes) {
          for (var i = 0; i < data.nodes.length; i++) {
            var n = data.nodes[i];
            if (findNode(n.id)) continue;
            var relType = n.relationship_to_center || 'associate';
            nodes.push({
              id: n.id, name: n.name, photo_url: n.photo_url,
              enrichment_score: n.enrichment_score || 0,
              age: n.age, location: n.location,
              risk_tier: n.risk_tier || 'unknown',
              relationship_to_center: relType,
              strength: n.strength || 50, confidence: n.confidence || 0.5,
              distance: n.distance || 1,
              _borderColor: REL_COLORS[relType] || '#6B7280',
              x: (Math.random() - 0.5) * 600,
              y: (Math.random() - 0.5) * 400,
            });
          }
        }

        if (data.edges) {
          for (var j = 0; j < data.edges.length; j++) {
            var e = data.edges[j];
            edges.push({
              source: e.source, target: e.target,
              relationship_type: e.relationship_type || 'associate',
              strength: e.strength || 50, confidence: e.confidence || 0.5,
              discovered_via: e.discovered_via, last_confirmed: e.last_confirmed,
              color: e.color || REL_COLORS[e.relationship_type] || '#6B7280',
              style: e.style || 'solid', _recent: false,
            });
          }
        }

        applyLayout();
        draw();
      })
      .catch(function (err) { console.error('Failed to load person network:', err); });
  }

  function expandNode(nodeId) {
    fetch(API_BASE + '/graph/person/' + encodeURIComponent(nodeId) + '/network?depth=1', { headers: headers })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.nodes) return;
        var added = 0;
        for (var i = 0; i < data.nodes.length; i++) {
          var n = data.nodes[i];
          if (findNode(n.id)) continue;
          var relType = n.relationship_to_center || 'associate';
          var parentNode = findNode(nodeId);
          nodes.push({
            id: n.id, name: n.name, photo_url: n.photo_url,
            enrichment_score: n.enrichment_score || 0,
            age: n.age, location: n.location,
            risk_tier: n.risk_tier || 'unknown',
            relationship_to_center: relType,
            strength: n.strength || 50, confidence: n.confidence || 0.5,
            distance: (parentNode ? (parentNode.distance || 0) : 0) + 1,
            _borderColor: REL_COLORS[relType] || '#6B7280',
            x: (parentNode ? parentNode.x : 0) + (Math.random() - 0.5) * 200,
            y: (parentNode ? parentNode.y : 0) + (Math.random() - 0.5) * 200,
          });
          added++;
        }
        if (data.edges) {
          for (var j = 0; j < data.edges.length; j++) {
            var e = data.edges[j];
            if (!edges.some(function (ex) {
              return ex.source === e.source && ex.target === e.target
                && ex.relationship_type === e.relationship_type;
            })) {
              edges.push({
                source: e.source, target: e.target,
                relationship_type: e.relationship_type || 'associate',
                strength: e.strength || 50, confidence: e.confidence || 0.5,
                discovered_via: e.discovered_via, last_confirmed: e.last_confirmed,
                color: e.color || REL_COLORS[e.relationship_type] || '#6B7280',
                style: e.style || 'solid', _recent: false,
              });
            }
          }
        }
        if (added > 0) { applyLayout(); draw(); }
      })
      .catch(function (err) { console.error('Expand failed:', err); });
  }

  function triggerEnrich(personId) {
    fetch('/enrich/person/' + encodeURIComponent(personId), {
      method: 'POST', headers: headers
    }).catch(function () {});
  }

  // ── Legend ─────────────────────────────────────────────────────────────

  function buildLegend() {
    var container = document.getElementById('legend-items');
    if (!container) return;
    while (container.firstChild) container.removeChild(container.firstChild);

    var typeCounts = {};
    for (var i = 0; i < edges.length; i++) {
      var t = edges[i].relationship_type;
      typeCounts[t] = (typeCounts[t] || 0) + 1;
    }

    var types = Object.keys(typeCounts).sort();
    for (var j = 0; j < types.length; j++) {
      var type = types[j];
      var color = REL_COLORS[type] || '#6B7280';
      var div = document.createElement('div');
      div.className = 'legend-item';
      var dot = document.createElement('div');
      dot.className = 'legend-dot';
      dot.style.background = color;
      var span = document.createElement('span');
      span.textContent = type.replace(/_/g, ' ') + ' (' + typeCounts[type] + ')';
      div.appendChild(dot);
      div.appendChild(span);
      container.appendChild(div);
    }
  }

  // ── Filter controls ───────────────────────────────────────────────────

  var confSlider = document.getElementById('filter-confidence');
  var strSlider = document.getElementById('filter-strength');
  var labelToggle = document.getElementById('toggle-labels');
  var photoToggle = document.getElementById('toggle-photos');

  if (confSlider) {
    confSlider.addEventListener('input', function () {
      filterState.minConfidence = parseInt(this.value, 10);
      document.getElementById('conf-value').textContent = this.value + '%';
      draw();
    });
  }
  if (strSlider) {
    strSlider.addEventListener('input', function () {
      filterState.minStrength = parseInt(this.value, 10);
      document.getElementById('str-value').textContent = this.value;
      draw();
    });
  }
  if (labelToggle) {
    labelToggle.addEventListener('change', function () {
      filterState.showLabels = this.checked;
      draw();
    });
  }
  if (photoToggle) {
    photoToggle.addEventListener('change', function () {
      filterState.showPhotos = this.checked;
      draw();
    });
  }

  // ── Zoom controls ─────────────────────────────────────────────────────

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
    zoom = Math.min(w / ((maxX - minX) + 200), h / ((maxY - minY) + 200), 2);
    panX = 0; panY = 0;
    draw();
  });

  document.getElementById('panel-close').addEventListener('click', function () {
    selectedNode = null;
    document.getElementById('node-panel').classList.remove('visible');
    draw();
  });

  // ── Export ─────────────────────────────────────────────────────────────

  var exportBtn = document.getElementById('btn-export');
  if (exportBtn) {
    exportBtn.addEventListener('click', function () {
      var link = document.createElement('a');
      link.download = 'lycan-graph-' + (centerNodeId || 'export') + '.png';
      link.href = canvas.toDataURL('image/png');
      link.click();
    });
  }

  // ── Search / load ─────────────────────────────────────────────────────

  var searchBtn = document.getElementById('btn-search');
  var searchInput = document.getElementById('search-input');

  if (searchBtn) {
    searchBtn.addEventListener('click', function () {
      var term = searchInput.value.trim();
      if (!term) return;

      searchBtn.disabled = true;
      fetch('/persons?search=' + encodeURIComponent(term) + '&limit=1', { headers: headers })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var persons = data.persons || data.results || [];
          if (persons.length > 0) {
            var pid = persons[0].id || persons[0].person_id;
            loadPerson(pid);
          }
        })
        .catch(function (err) { console.error('Search failed:', err); })
        .finally(function () { searchBtn.disabled = false; });
    });
  }
  if (searchInput) {
    searchInput.addEventListener('keydown', function (evt) {
      if (evt.key === 'Enter') searchBtn.click();
    });
  }

  // ── Initialize ────────────────────────────────────────────────────────

  resize();

  var hashMatch = window.location.hash.match(/person[s]?\/([a-f0-9-]+)/i);
  if (hashMatch) {
    loadPerson(hashMatch[1]);
  }

  window.LycanGraph = { loadPerson: loadPerson, expandNode: expandNode };
})();
