import { useRef, useEffect, useState, useCallback } from 'react';
import './Neo4jGraph.css';

// ── Color palette per node label ─────────────────────────────────────────────
const LABEL_COLORS = {
  Member:    { bg: '#000048', text: '#fff' },
  Persona:   { bg: '#26EFE9', text: '#000048' },
  Measure:   { bg: '#E9C71D', text: '#000048' },
  Provider:  { bg: '#2DB81F', text: '#fff' },
  CareGap:   { bg: '#B81F2D', text: '#fff' },
  Action:    { bg: '#9333EA', text: '#fff' },
  // Knowledge Explorer leaf nodes
  AgeRange:  { bg: '#0EA5E9', text: '#fff' },
  Gender:    { bg: '#EC4899', text: '#fff' },
  Lookback:  { bg: '#6366F1', text: '#fff' },
  CPT:       { bg: '#14B8A6', text: '#fff' },
  ICD:       { bg: '#F97316', text: '#fff' },
  Disease: { bg: '#A855F7', text: '#fff' },
  Default:   { bg: '#6B7280', text: '#fff' },
};

// Stage-based colors for CareGap nodes
const STAGE_COLORS = {
  gap_identified:     { bg: '#B81F2D', text: '#fff' },  // Red
  analysis_started:   { bg: '#F59E0B', text: '#000' },  // Amber
  analysis_complete:  { bg: '#FF8C00', text: '#fff' },  // Orange
  outreach_sent:      { bg: '#3B82F6', text: '#fff' },  // Blue
  appointment_booked: { bg: '#8B5CF6', text: '#fff' },  // Purple
  gap_closed:         { bg: '#10B981', text: '#fff' },  // Green
};

const ACTION_COLORS = {
  identified:     '#B81F2D',
  analysis_start: '#F59E0B',
  analysis_done:  '#FF8C00',
  outreach:       '#3B82F6',
  appointment:    '#8B5CF6',
  closed:         '#10B981',
};

const LABEL_RADIUS = {
  Member: 28,
  Measure: 32,
  Persona: 22,
  Provider: 26,
  CareGap: 24,
  Action: 16,
  // Knowledge Explorer leaves are smaller — they hang off a primary node
  AgeRange: 18, Gender: 18, Lookback: 18, CPT: 18, ICD: 18, Disease: 18,
};

const REL_COLORS = {
  BELONGS_TO_MEASURE: '#E9C71D',
  HAS_PCP: '#2DB81F',
  HAS_CARE_GAP: '#B81F2D',
  FOR_MEASURE: '#FF8C00',
  HAS_CLAIM: '#6B7280',
  HAS_ENROLLMENT: '#9333EA',
  HAS_PERSONA: '#26EFE9',
  HAS_ACTION: '#9333EA',
};

// ── Simple force simulation ──────────────────────────────────────────────────
function initPositions(nodes, width, height) {
  const cx = width / 2;
  const cy = height / 2;
  return nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    const r = Math.min(width, height) * 0.35;
    return {
      ...n,
      x: cx + r * Math.cos(angle) + (Math.random() - 0.5) * 40,
      y: cy + r * Math.sin(angle) + (Math.random() - 0.5) * 40,
      vx: 0,
      vy: 0,
    };
  });
}

function simulate(nodes, edges, width, height, iterations = 120) {
  const cx = width / 2;
  const cy = height / 2;
  const nodeMap = {};
  nodes.forEach(n => { nodeMap[n.id] = n; });

  for (let iter = 0; iter < iterations; iter++) {
    const alpha = 1 - iter / iterations;
    const repulsion = 3000 * alpha;
    const attraction = 0.01 * alpha;

    // Repulsion between all node pairs
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = repulsion / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }
    }

    // Attraction along edges
    for (const edge of edges) {
      const a = nodeMap[edge.source];
      const b = nodeMap[edge.target];
      if (!a || !b) continue;
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = (dist - 120) * attraction;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }

    // Center gravity
    for (const n of nodes) {
      n.vx += (cx - n.x) * 0.002;
      n.vy += (cy - n.y) * 0.002;
    }

    // Apply velocities with damping
    for (const n of nodes) {
      n.vx *= 0.85;
      n.vy *= 0.85;
      n.x += n.vx;
      n.y += n.vy;
      // Keep within bounds
      const pad = 40;
      n.x = Math.max(pad, Math.min(width - pad, n.x));
      n.y = Math.max(pad, Math.min(height - pad, n.y));
    }
  }
  return nodes;
}

// ── Component ────────────────────────────────────────────────────────────────
function Neo4jGraph({ nodes: rawNodes, edges: rawEdges, width = 900, height = 500, title, onNodeClick }) {
  const svgRef = useRef(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [dragNode, setDragNode] = useState(null);
  const [dragStart, setDragStart] = useState(null);
  const [positions, setPositions] = useState([]);
  const [tooltip, setTooltip] = useState(null);

  // Layout nodes
  useEffect(() => {
    if (!rawNodes || rawNodes.length === 0) return;
    const initial = initPositions(rawNodes, width, height);
    const laid = simulate(initial, rawEdges || [], width, height);
    setPositions([...laid]);
  }, [rawNodes, rawEdges, width, height]);

  const nodeMap = {};
  positions.forEach(n => { nodeMap[n.id] = n; });

  // Drag handlers
  const handleMouseDown = useCallback((e, nodeId) => {
    e.preventDefault();
    setDragNode(nodeId);
    setDragStart({ x: e.clientX, y: e.clientY, nodeId });
  }, []);

  const handleMouseMove = useCallback((e) => {
    if (!dragNode || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setPositions(prev => prev.map(n =>
      n.id === dragNode ? { ...n, x, y } : n
    ));
  }, [dragNode]);

  const handleMouseUp = useCallback((e) => {
    // Detect click (minimal drag distance) vs drag
    if (dragStart && onNodeClick && e) {
      const dx = Math.abs(e.clientX - dragStart.x);
      const dy = Math.abs(e.clientY - dragStart.y);
      if (dx < 4 && dy < 4) {
        const clickedNode = rawNodes.find(n => n.id === dragStart.nodeId);
        if (clickedNode) onNodeClick(clickedNode);
      }
    }
    setDragNode(null);
    setDragStart(null);
  }, [dragStart, onNodeClick, rawNodes]);

  const handleNodeHover = (node, e) => {
    setHoveredNode(node.id);
    const rect = svgRef.current.getBoundingClientRect();
    setTooltip({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      node,
    });
  };

  const handleNodeLeave = () => {
    setHoveredNode(null);
    setTooltip(null);
  };

  if (!positions.length) return null;

  // Build legend from unique labels
  const uniqueLabels = [...new Set(rawNodes.map(n => n.label))];

  return (
    <div className="neo4j-graph-container">
      {title && <h3 className="neo4j-graph-title">{title}</h3>}

      <div className="neo4j-graph-legend">
        {uniqueLabels.map(label => {
          const col = LABEL_COLORS[label] || LABEL_COLORS.Default;
          return (
            <span key={label} className="legend-item">
              <span className="legend-dot" style={{ background: col.bg }} />
              {label}
            </span>
          );
        })}
      </div>

      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="neo4j-svg"
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <defs>
          <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <path d="M0,0 L8,3 L0,6 Z" fill="#888" />
          </marker>
        </defs>

        {/* Edges */}
        {(rawEdges || []).map((edge, i) => {
          const src = nodeMap[edge.source];
          const tgt = nodeMap[edge.target];
          if (!src || !tgt) return null;
          const relColor = REL_COLORS[edge.type] || '#999';
          const mx = (src.x + tgt.x) / 2;
          const my = (src.y + tgt.y) / 2;
          const highlighted = hoveredNode === edge.source || hoveredNode === edge.target;
          return (
            <g key={`e-${i}`}>
              <line
                x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                stroke={relColor}
                strokeWidth={highlighted ? 2.5 : 1.5}
                strokeOpacity={hoveredNode && !highlighted ? 0.15 : 0.7}
                markerEnd="url(#arrowhead)"
              />
              <text
                x={mx} y={my - 6}
                textAnchor="middle"
                className="edge-label"
                fill={relColor}
                opacity={hoveredNode && !highlighted ? 0.15 : 0.85}
              >
                {edge.type}
              </text>
            </g>
          );
        })}

        {/* Nodes */}
        {positions.map(node => {
          // Dynamic color: CareGap uses stage color, Action uses action type color
          let col = LABEL_COLORS[node.label] || LABEL_COLORS.Default;
          if (node.label === 'CareGap' && node.stage && STAGE_COLORS[node.stage]) {
            col = STAGE_COLORS[node.stage];
          } else if (node.label === 'Action' && node.action_type && ACTION_COLORS[node.action_type]) {
            col = { bg: ACTION_COLORS[node.action_type], text: '#fff' };
          }
          const r = LABEL_RADIUS[node.label] || 20;
          const isHovered = hoveredNode === node.id;
          const dimmed = hoveredNode && !isHovered &&
            !(rawEdges || []).some(e =>
              (e.source === hoveredNode && e.target === node.id) ||
              (e.target === hoveredNode && e.source === node.id)
            );

          return (
            <g
              key={node.id}
              onMouseDown={(e) => handleMouseDown(e, node.id)}
              onMouseEnter={(e) => handleNodeHover(node, e)}
              onMouseLeave={handleNodeLeave}
              style={{ cursor: 'grab' }}
              opacity={dimmed ? 0.2 : 1}
            >
              <circle
                cx={node.x} cy={node.y} r={r}
                fill={col.bg}
                stroke={isHovered ? '#fff' : col.bg}
                strokeWidth={isHovered ? 3 : 1.5}
                filter={isHovered ? 'url(#glow)' : undefined}
              />
              <text
                x={node.x} y={node.y + 1}
                textAnchor="middle"
                dominantBaseline="central"
                className="node-label"
                fill={col.text}
                fontSize={r > 24 ? 9 : 7}
              >
                {(node.name || node.id || '').length > 12
                  ? (node.name || node.id).slice(0, 11) + '…'
                  : (node.name || node.id)}
              </text>
              <text
                x={node.x} y={node.y + r + 12}
                textAnchor="middle"
                className="node-sublabel"
                fill="#666"
                fontSize={8}
              >
                {node.label}
              </text>
            </g>
          );
        })}

        {/* Glow filter */}
        <defs>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="neo4j-tooltip"
          style={{
            left: tooltip.x + 15,
            top: tooltip.y - 10,
          }}
        >
          <div className="tooltip-header">
            <span className="tooltip-label-badge" style={{ background: (LABEL_COLORS[tooltip.node.label] || LABEL_COLORS.Default).bg, color: (LABEL_COLORS[tooltip.node.label] || LABEL_COLORS.Default).text }}>
              {tooltip.node.label}
            </span>
            <strong>{tooltip.node.name || tooltip.node.id}</strong>
          </div>
          {tooltip.node.description && <p className="tooltip-desc">{tooltip.node.description}</p>}
          {tooltip.node.care_gap_status && <p><strong>Status:</strong> {tooltip.node.care_gap_status}</p>}
          {tooltip.node.stage && <p><strong>Stage:</strong> {tooltip.node.stage.replace(/_/g, ' ')}</p>}
          {tooltip.node.age_band && <p><strong>Age Band:</strong> {tooltip.node.age_band}</p>}
          {tooltip.node.gender && <p><strong>Gender:</strong> {tooltip.node.gender}</p>}
          {tooltip.node.age_str && <p><strong>Age:</strong> {tooltip.node.age_str}</p>}
          {tooltip.node.age && !tooltip.node.age_str && <p><strong>Age:</strong> {tooltip.node.age}</p>}
          {tooltip.node.chronic_conditions && <p><strong>Conditions:</strong> {tooltip.node.chronic_conditions}</p>}
          {tooltip.node.insurance_type && <p><strong>Insurance:</strong> {tooltip.node.insurance_type}</p>}
          {tooltip.node.specialty && <p><strong>Specialty:</strong> {tooltip.node.specialty}</p>}
          {tooltip.node.measure_id && <p><strong>Measure:</strong> {tooltip.node.measure_id}</p>}
          {tooltip.node.measure && !tooltip.node.measure_id && <p><strong>Measure:</strong> {tooltip.node.measure}</p>}
          {tooltip.node.action_type && <p><strong>Action:</strong> {tooltip.node.action_type.replace(/_/g, ' ')}</p>}
          {tooltip.node.timestamp && <p><strong>Time:</strong> {new Date(tooltip.node.timestamp).toLocaleString()}</p>}
          {tooltip.node.reasoning && <p className="tooltip-reasoning"><strong>Reasoning:</strong> {tooltip.node.reasoning}</p>}
          {tooltip.node.status && !tooltip.node.stage && <p><strong>Status:</strong> {tooltip.node.status}</p>}
        </div>
      )}
    </div>
  );
}

export default Neo4jGraph;
