/**
 * graph_worker.js — D3 v7 force simulation running off the main thread.
 *
 * Messages IN  (from main thread):
 *   { type: 'init',   nodes: [...], edges: [...], width: N, height: N }
 *   { type: 'pin',    nodeId: '...', x: N, y: N }
 *   { type: 'unpin',  nodeId: '...' }
 *   { type: 'resize', width: N, height: N }
 *   { type: 'stop' }
 *
 * Messages OUT (to main thread):
 *   { type: 'tick',   nodes: [{id, x, y, vx, vy, fx, fy}], edges: [...] }
 *   { type: 'end' }
 */

importScripts('https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js');

let simulation = null;
let _nodes = [];
let _edges = [];

function buildSimulation(nodes, edges, width, height) {
  // Deep-copy so D3 can mutate freely
  _nodes = nodes.map(n => Object.assign({}, n));
  _edges = edges.map(e => Object.assign({}, e));

  if (simulation) simulation.stop();

  simulation = d3.forceSimulation(_nodes)
    .force('link', d3.forceLink(_edges)
      .id(d => d.id)
      .distance(d => 80 + (1 - (d.confidence || 0.5)) * 40)
      .strength(0.4)
    )
    .force('charge', d3.forceManyBody().strength(-300).distanceMax(400))
    .force('center', d3.forceCenter(width / 2, height / 2).strength(0.08))
    .force('collide', d3.forceCollide().radius(28).strength(0.7))
    .alphaDecay(0.028)
    .velocityDecay(0.4)
    .on('tick', () => {
      // Send positions to main thread every tick
      self.postMessage({
        type: 'tick',
        nodes: _nodes.map(n => ({
          id: n.id, x: n.x, y: n.y,
          vx: n.vx, vy: n.vy, fx: n.fx, fy: n.fy
        })),
        edges: _edges.map(e => ({
          source: typeof e.source === 'object' ? e.source.id : e.source,
          target: typeof e.target === 'object' ? e.target.id : e.target,
          type:   e.type,
          confidence: e.confidence
        }))
      });
    })
    .on('end', () => {
      self.postMessage({ type: 'end' });
    });
}

self.onmessage = function(evt) {
  const msg = evt.data;
  switch (msg.type) {
    case 'init':
      buildSimulation(msg.nodes, msg.edges, msg.width, msg.height);
      break;

    case 'pin': {
      const n = _nodes.find(x => x.id === msg.nodeId);
      if (n) { n.fx = msg.x; n.fy = msg.y; }
      if (simulation) simulation.alpha(0.1).restart();
      break;
    }

    case 'unpin': {
      const n = _nodes.find(x => x.id === msg.nodeId);
      if (n) { n.fx = null; n.fy = null; }
      if (simulation) simulation.alpha(0.1).restart();
      break;
    }

    case 'resize':
      if (simulation) {
        simulation.force('center', d3.forceCenter(msg.width / 2, msg.height / 2).strength(0.08));
        simulation.alpha(0.1).restart();
      }
      break;

    case 'stop':
      if (simulation) simulation.stop();
      break;

    default:
      break;
  }
};
