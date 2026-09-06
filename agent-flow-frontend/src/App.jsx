import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  useNodesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import manifest from './data/architecture_manifest.generated.json';

const TYPE_META = {
  user: { label: 'USER', index: '01', className: 'node-user', color: '#6f6d67' },
  orchestrator: { label: 'ORCHESTRATOR', index: '02', className: 'node-orchestrator', color: '#536164' },
  agent: { label: 'AGENT', index: '03', className: 'node-agent', color: '#697161' },
  memory: { label: 'MEMORY', index: '04', className: 'node-memory', color: '#82735c' },
  audit: { label: 'AUDIT', index: '05', className: 'node-audit', color: '#815f57' },
  data: { label: 'DATA', index: '06', className: 'node-data', color: '#66645f' },
};

const SYSTEM_ORDER = [
  'system:user_interface',
  'system:local_orchestration',
  'system:framework_planning',
  'system:script_assets',
  'system:conflict_production',
  'system:script_production',
  'system:script_audit',
  'system:character_visual',
  'system:persistence',
];

const HIGH_WARNINGS = new Map(
  manifest.configuration_warnings
    .filter((warning) => warning.severity === 'HIGH')
    .map((warning) => [warning.node_id, warning]),
);

const NODE_BY_ID = new Map(manifest.nodes.map((node) => [node.id, node]));

const CHILDREN_BY_PARENT = manifest.nodes.reduce((result, node) => {
  if (!node.parent_id) return result;
  if (!result[node.parent_id]) result[node.parent_id] = [];
  result[node.parent_id].push(node);
  return result;
}, {});

const sortNodes = (nodes) => [...nodes].sort((left, right) => {
  const leftSystemIndex = SYSTEM_ORDER.indexOf(left.id);
  const rightSystemIndex = SYSTEM_ORDER.indexOf(right.id);
  if (leftSystemIndex >= 0 || rightSystemIndex >= 0) return leftSystemIndex - rightSystemIndex;
  return manifest.nodes.indexOf(left) - manifest.nodes.indexOf(right);
});

const sortWorkflowNodes = (nodes) => {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = manifest.edges.filter((edge) => (
    edge.edge_type === 'platform_data_flow'
    && nodeIds.has(edge.source)
    && nodeIds.has(edge.target)
  ));
  const incomingCount = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, []]));
  edges.forEach((edge) => {
    incomingCount.set(edge.target, (incomingCount.get(edge.target) || 0) + 1);
    outgoing.get(edge.source)?.push(edge.target);
  });
  const queue = nodes
    .filter((node) => incomingCount.get(node.id) === 0)
    .sort((left, right) => Number(right.node_type === 'START') - Number(left.node_type === 'START'));
  const ordered = [];
  while (queue.length) {
    const node = queue.shift();
    ordered.push(node);
    (outgoing.get(node.id) || []).forEach((targetId) => {
      incomingCount.set(targetId, incomingCount.get(targetId) - 1);
      if (incomingCount.get(targetId) === 0) queue.push(NODE_BY_ID.get(targetId));
    });
  }
  const orderedIds = new Set(ordered.map((node) => node.id));
  return [...ordered, ...nodes.filter((node) => !orderedIds.has(node.id))];
};

const displayTitleForNode = (node) => {
  const platformTitle = String(node.title || '').trim();
  const genericLlmTitle = /^(?:大模型\s*\d*|LLM\s*\d*)$/i.test(platformTitle);
  if (node.node_type === 'LLM' && !genericLlmTitle) return platformTitle;
  return node.display_title || platformTitle || node.node_type || 'UNKNOWN';
};

const formatPort = (port) => {
  if (typeof port === 'string') return port;
  if (!port || typeof port !== 'object') return String(port ?? 'UNKNOWN');
  const field = port.field || 'UNKNOWN';
  const type = port.type ? ` : ${String(port.type).toLowerCase()}` : '';
  const reference = port.reference_path ? ` ← ${port.reference_path}` : '';
  return `${field}${type}${reference}`;
};

const asList = (value) => {
  if (Array.isArray(value)) return value.map(formatPort);
  if (value === undefined || value === null || value === '') return [];
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}: ${JSON.stringify(item)}`);
  return [String(value)];
};

const typeForNode = (node) => {
  if (HIGH_WARNINGS.has(node.id)) return 'audit';
  if (node.node_type === 'User') return 'user';
  if (node.node_type === 'AuditSystem' || node.stage_key === 'hot_review') return 'audit';
  if (node.stage_key === '11_02' || node.stage_key === '12_02') return 'audit';
  if (node.stage_key === '11_04' || node.stage_key === '12_04') return 'memory';
  if (node.node_type === 'Data' || node.node_type === 'DataSystem') return 'data';
  if (['Orchestrator', 'Gateway', 'Validator'].includes(node.node_type)) return 'orchestrator';
  return 'agent';
};

const nodeStageLabel = (node) => {
  if (node.node_level === 1) return `LEVEL 1 / ${node.node_type}`;
  if (node.node_level === 2 && node.stage_key) return `LEVEL 2 / WORKFLOW ${node.stage_key}`;
  if (node.node_level === 2) return `LEVEL 2 / ${node.node_type}`;
  return `LEVEL 3 / TENCENT ${node.node_type}`;
};

const createFlowNode = (node, position, isExpanded) => {
  const children = CHILDREN_BY_PARENT[node.id] || [];
  const warning = HIGH_WARNINGS.get(node.id);
  return {
    id: node.id,
    type: typeForNode(node),
    position,
    draggable: true,
    data: {
      title: displayTitleForNode(node),
      platformTitle: node.title,
      subtitle: node.responsibility || 'UNKNOWN',
      stage: nodeStageLabel(node),
      nodeLevel: node.node_level,
      nodeType: node.node_type,
      parentId: node.parent_id,
      inputs: asList(node.input),
      outputs: asList(node.output),
      saves: asList(node.save_state),
      evidence: (node.source_evidence || []).map((item) => `${item.path}:${item.line} · ${item.symbol}`),
      model: node.model || '',
      modelParams: node.model_params || {},
      workflowStatus: node.workflow_id_status || '',
      responseStatus: node.response_field_status || '',
      childCount: children.length,
      hasChildren: children.length > 0,
      isExpanded,
      warning,
    },
  };
};

const createLayerMarker = (id, title, subtitle, position) => ({
  id: `layer:${id}`,
  type: 'layerLabel',
  position,
  draggable: false,
  selectable: false,
  focusable: false,
  data: { title, subtitle },
});

function buildLayout(activeSystemId, activeWorkflowId) {
  const systems = sortNodes(manifest.nodes.filter((node) => node.node_level === 1));
  const laneX = { level1: 80, level2: 480, level3: 880 };
  const systemStartY = 40;
  const systemGapY = 202;
  const positions = new Map();
  systems.forEach((node, index) => positions.set(node.id, { x: laneX.level1, y: systemStartY + index * systemGapY }));

  const visible = systems.map((node) => createFlowNode(
    node,
    positions.get(node.id),
    node.id === activeSystemId,
  ));
  const activeChildren = activeSystemId ? sortNodes(CHILDREN_BY_PARENT[activeSystemId] || []) : [];
  const selectedSystemIndex = Math.max(0, systems.findIndex((node) => node.id === activeSystemId));
  const childGapY = 196;
  const childStartY = Math.max(40, systemStartY + selectedSystemIndex * systemGapY - Math.floor(activeChildren.length / 2) * childGapY);

  activeChildren.forEach((node, index) => {
    positions.set(node.id, { x: laneX.level2, y: childStartY + index * childGapY });
    visible.push(createFlowNode(node, positions.get(node.id), node.id === activeWorkflowId));
  });

  const activeWorkflow = activeChildren.find((node) => node.id === activeWorkflowId);
  const workflowChildren = activeWorkflow ? sortWorkflowNodes(CHILDREN_BY_PARENT[activeWorkflow.id] || []) : [];
  const activeWorkflowIndex = Math.max(0, activeChildren.findIndex((node) => node.id === activeWorkflowId));
  const level3GapY = 196;
  const level3StartY = Math.max(40, childStartY + activeWorkflowIndex * childGapY - Math.floor(workflowChildren.length / 2) * level3GapY);

  workflowChildren.forEach((node, index) => {
    positions.set(node.id, { x: laneX.level3, y: level3StartY + index * level3GapY });
    visible.push(createFlowNode(node, positions.get(node.id), false));
  });

  return [
    createLayerMarker('level1', 'LEVEL 1', 'SYSTEM MODULES', { x: laneX.level1, y: -86 }),
    createLayerMarker('level2', 'LEVEL 2', activeSystemId ? 'WORKFLOWS / LOCAL MODULES' : 'SELECT A SYSTEM', { x: laneX.level2, y: -86 }),
    createLayerMarker('level3', 'LEVEL 3', activeWorkflowId ? 'TENCENT INTERNAL AGENTS' : 'SELECT A WORKFLOW', { x: laneX.level3, y: -86 }),
    ...visible,
  ];
}

const parentVisibleFor = (nodeId, visibleIds) => {
  let cursor = NODE_BY_ID.get(nodeId);
  while (cursor) {
    if (visibleIds.has(cursor.id)) return cursor.id;
    cursor = cursor.parent_id ? NODE_BY_ID.get(cursor.parent_id) : null;
  }
  return null;
};

const EDGE_CHANNELS = {
  hierarchy: { label: 'HIERARCHY', stroke: '#514f49', dash: '5 7' },
  creative: { label: 'CREATIVE FLOW', stroke: '#2f523c' },
  invoke: { label: 'ORCHESTRATION', stroke: '#285064' },
  audit: { label: 'REVIEW LOOP', stroke: '#793d34' },
  memory: { label: 'MEMORY RETURN', stroke: '#71500f', dash: '7 4' },
  persistence: { label: 'PERSISTENCE', stroke: '#3d4d63', dash: '4 4' },
  platform: { label: 'PLATFORM INTERNAL', stroke: '#172e39' },
};

const edgeVisual = (group) => {
  if (group.edgeType === 'contains') return { ...EDGE_CHANNELS.hierarchy, kind: 'hierarchy' };
  if (group.edgeType === 'platform_data_flow') return { ...EDGE_CHANNELS.platform, kind: 'platform' };
  const signal = `${group.source} ${group.target} ${group.names.join(' ')} ${group.fields.join(' ')}`.toLowerCase();
  if (/audit|review|审核|blocking|rewrite/.test(signal)) return { ...EDGE_CHANNELS.audit, kind: 'audit' };
  if (/memory|记忆/.test(signal)) return { ...EDGE_CHANNELS.memory, kind: 'memory' };
  if (/data:|snapshot|store|sqlite|debug|persist|保存|project snapshot/.test(signal)) return { ...EDGE_CHANNELS.persistence, kind: 'persistence' };
  if (/api|gateway|request|invoke|workflow client|用户操作/.test(signal)) return { ...EDGE_CHANNELS.invoke, kind: 'invoke' };
  return { ...EDGE_CHANNELS.creative, kind: 'creative' };
};

const stableRouteIndex = (value) => [...String(value)].reduce(
  (total, character) => (total * 31 + character.charCodeAt(0)) % 997,
  0,
);

const connectionRoute = (group, flowNodeById) => {
  const sourceNode = flowNodeById.get(group.source);
  const targetNode = flowNodeById.get(group.target);
  if (!sourceNode || !targetNode) return {};
  const deltaX = targetNode.position.x - sourceNode.position.x;
  const deltaY = targetNode.position.y - sourceNode.position.y;
  const routeIndex = stableRouteIndex(group.id);
  const offset = 30 + (routeIndex % 5) * 16;

  if (Math.abs(deltaX) > 150) {
    const direction = deltaX > 0 ? 'right' : 'left';
    return {
      sourceHandle: `source-${direction}`,
      targetHandle: `target-${direction === 'right' ? 'left' : 'right'}`,
      pathOptions: { offset, borderRadius: 6 },
    };
  }

  if (deltaY < -40) {
    const side = sourceNode.position.x < 300 ? 'left' : 'right';
    return {
      sourceHandle: `source-${side}`,
      targetHandle: `target-${side}`,
      pathOptions: { offset, borderRadius: 8 },
    };
  }

  return {
    sourceHandle: 'source-bottom',
    targetHandle: 'target-top',
    pathOptions: { offset: 22 + (routeIndex % 3) * 8, borderRadius: 6 },
  };
};

function buildProjectedEdges(flowNodes, selectedId) {
  const visibleIds = new Set(flowNodes.map((node) => node.id));
  const flowNodeById = new Map(flowNodes.map((node) => [node.id, node]));
  const grouped = new Map();

  manifest.edges.forEach((edge) => {
    let source;
    let target;
    if (edge.edge_type === 'contains') {
      if (!visibleIds.has(edge.source) || !visibleIds.has(edge.target)) return;
      source = edge.source;
      target = edge.target;
    } else {
      source = parentVisibleFor(edge.source, visibleIds);
      target = parentVisibleFor(edge.target, visibleIds);
    }
    if (!source || !target || source === target) return;

    const groupKey = `${edge.edge_type}:${source}:${target}`;
    const existing = grouped.get(groupKey) || {
      id: `projected:${groupKey}`,
      source,
      target,
      edgeType: edge.edge_type,
      names: [],
      fields: [],
      animated: false,
      originals: [],
    };
    if (edge.data_name && !existing.names.includes(edge.data_name)) existing.names.push(edge.data_name);
    (edge.fields || []).forEach((field) => {
      if (field !== 'UNKNOWN' && !existing.fields.includes(field)) existing.fields.push(field);
    });
    existing.animated ||= edge.animation_type === 'animated';
    existing.originals.push(edge);
    grouped.set(groupKey, existing);
  });

  return [...grouped.values()].map((group) => {
    const visual = edgeVisual(group);
    const route = connectionRoute(group, flowNodeById);
    const primary = group.names.slice(0, 2).join(' · ') || 'DATA FLOW';
    const extra = group.names.length > 2 ? ` +${group.names.length - 2}` : '';
    const related = group.source === selectedId || group.target === selectedId;
    const fullLabel = `${primary}${extra}`;
    const label = group.edgeType === 'contains' || !related
      ? ''
      : fullLabel.length > 46 ? `${fullLabel.slice(0, 43)}...` : fullLabel;
    return {
      id: group.id,
      source: group.source,
      target: group.target,
      sourceHandle: route.sourceHandle,
      targetHandle: route.targetHandle,
      label,
      type: 'smoothstep',
      pathOptions: route.pathOptions,
      animated: group.edgeType !== 'contains',
      className: `edge-channel-${visual.kind}${related ? ' is-related' : ''}`,
      data: { ...group, kind: visual.kind, related },
      markerEnd: group.edgeType === 'contains' ? undefined : {
        type: MarkerType.ArrowClosed,
        width: 17,
        height: 17,
        color: visual.stroke,
      },
      style: {
        stroke: visual.stroke,
        strokeWidth: related ? 4.2 : group.edgeType === 'contains' ? 2.7 : 3.1,
        strokeDasharray: visual.dash,
        opacity: related || group.edgeType === 'contains' ? 1 : 0.94,
      },
      labelStyle: { fill: '#252522', fontSize: 10, fontWeight: 680 },
      labelBgStyle: { fill: '#faf8f1', fillOpacity: 1 },
      labelBgPadding: [7, 5],
      labelBgBorderRadius: 0,
    };
  });
}

function EyeIcon({ active }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M2.6 12s3.25-5.35 9.4-5.35S21.4 12 21.4 12 18.15 17.35 12 17.35 2.6 12 2.6 12Z" />
      <circle cx="12" cy="12" r={active ? 2.8 : 2.25} />
    </svg>
  );
}

function ArchitectureNode({ data }) {
  const meta = TYPE_META[data.kind] || TYPE_META.agent;
  return (
    <article className={`architecture-node ${meta.className} level-${data.nodeLevel} ${data.warning ? 'has-warning' : ''} ${data.isFlowFocused ? 'is-flow-focused' : ''}`}>
      <Handle id="target-top" type="target" position={Position.Top} className="node-handle" />
      <Handle id="target-left" type="target" position={Position.Left} className="node-handle node-handle-side" />
      <Handle id="target-right" type="target" position={Position.Right} className="node-handle node-handle-side" />
      <div className="node-kicker">
        <span>{data.stage}</span>
        <div className="node-tools">
          <span>{String(data.nodeLevel).padStart(2, '0')} / 03</span>
          <button
            type="button"
            className="node-visibility-button nodrag nopan"
            aria-label={data.isFlowFocused ? `显示全部节点，退出 ${data.title} 数据流聚焦` : `只显示 ${data.title} 的相关数据流`}
            aria-pressed={data.isFlowFocused}
            title={data.isFlowFocused ? '显示全部节点' : '仅查看此节点数据流'}
            onClick={(event) => {
              event.stopPropagation();
              data.onToggleFlowFocus?.();
            }}
          >
            <EyeIcon active={data.isFlowFocused} />
          </button>
        </div>
      </div>
      {data.warning && <span className="warning-flag">CONFIG WARNING</span>}
      <h3>{data.title}</h3>
      <p>{data.subtitle}</p>
      <footer>
        <span>{data.inputs.length} IN</span>
        <span>{data.outputs.length} OUT</span>
        <span>{data.hasChildren ? `${data.isExpanded ? '−' : '+'} ${data.childCount} NODES` : meta.label}</span>
      </footer>
      <Handle id="source-bottom" type="source" position={Position.Bottom} className="node-handle" />
      <Handle id="source-left" type="source" position={Position.Left} className="node-handle node-handle-side" />
      <Handle id="source-right" type="source" position={Position.Right} className="node-handle node-handle-side" />
    </article>
  );
}

function LayerLabelNode({ data }) {
  return (
    <div className="layer-label-node" aria-hidden="true">
      <strong>{data.title}</strong>
      <span>{data.subtitle}</span>
    </div>
  );
}

const UserNode = memo((props) => <ArchitectureNode {...props} data={{ ...props.data, kind: 'user' }} />);
const OrchestratorNode = memo((props) => <ArchitectureNode {...props} data={{ ...props.data, kind: 'orchestrator' }} />);
const AgentNode = memo((props) => <ArchitectureNode {...props} data={{ ...props.data, kind: 'agent' }} />);
const MemoryNode = memo((props) => <ArchitectureNode {...props} data={{ ...props.data, kind: 'memory' }} />);
const AuditNode = memo((props) => <ArchitectureNode {...props} data={{ ...props.data, kind: 'audit' }} />);
const DataNode = memo((props) => <ArchitectureNode {...props} data={{ ...props.data, kind: 'data' }} />);

const nodeTypes = {
  user: UserNode,
  orchestrator: OrchestratorNode,
  agent: AgentNode,
  memory: MemoryNode,
  audit: AuditNode,
  data: DataNode,
  layerLabel: memo(LayerLabelNode),
};

function DetailSection({ index, title, items, empty = 'UNKNOWN' }) {
  return (
    <section className="detail-section">
      <div className="detail-section-title"><span>{index}</span><h3>{title}</h3></div>
      {items?.length ? <ul>{items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{item}</li>)}</ul> : <p className="unknown-value">{empty}</p>}
    </section>
  );
}

function App() {
  const [activeSystemId, setActiveSystemId] = useState(null);
  const [activeWorkflowId, setActiveWorkflowId] = useState(null);
  const [selectedId, setSelectedId] = useState('system:script_production');
  const [focusNodeId, setFocusNodeId] = useState(null);
  const [isDetailOpen, setIsDetailOpen] = useState(true);
  const [flowInstance, setFlowInstance] = useState(null);

  const layoutNodes = useMemo(() => buildLayout(activeSystemId, activeWorkflowId), [activeSystemId, activeWorkflowId]);
  const [nodes, setNodes, onNodesChange] = useNodesState(layoutNodes);
  useEffect(() => setNodes(layoutNodes), [layoutNodes, setNodes]);

  const projectedEdges = useMemo(() => buildProjectedEdges(nodes, selectedId), [nodes, selectedId]);
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selectedNode = selectedId ? NODE_BY_ID.get(selectedId) : null;
  const selectedFlowNode = selectedId ? nodeById.get(selectedId) : null;

  useEffect(() => {
    if (focusNodeId && !nodeById.has(focusNodeId)) setFocusNodeId(null);
  }, [focusNodeId, nodeById]);

  const handleToggleFlowFocus = useCallback((nodeId) => {
    setSelectedId(nodeId);
    setIsDetailOpen(true);
    setFocusNodeId((current) => current === nodeId ? null : nodeId);
  }, []);

  const focusedNodeIds = useMemo(() => {
    if (!focusNodeId || !nodeById.has(focusNodeId)) return null;
    const branchIds = new Set([focusNodeId]);

    nodes.forEach((node) => {
      let cursor = NODE_BY_ID.get(node.id);
      while (cursor?.parent_id) {
        if (cursor.parent_id === focusNodeId) {
          branchIds.add(node.id);
          break;
        }
        cursor = NODE_BY_ID.get(cursor.parent_id);
      }
    });

    const keepIds = new Set(branchIds);
    projectedEdges.forEach((edge) => {
      if (edge.data.edgeType === 'contains') return;
      if (branchIds.has(edge.source) || branchIds.has(edge.target)) {
        keepIds.add(edge.source);
        keepIds.add(edge.target);
      }
    });

    [...keepIds].forEach((nodeId) => {
      let cursor = NODE_BY_ID.get(nodeId);
      while (cursor?.parent_id) {
        if (nodeById.has(cursor.parent_id)) keepIds.add(cursor.parent_id);
        cursor = NODE_BY_ID.get(cursor.parent_id);
      }
    });
    return keepIds;
  }, [focusNodeId, nodeById, nodes, projectedEdges]);

  const flowNodes = useMemo(() => nodes.map((node) => {
    if (node.type === 'layerLabel') return { ...node, hidden: false };
    const isFlowFocused = node.id === focusNodeId;
    return {
      ...node,
      hidden: Boolean(focusedNodeIds && !focusedNodeIds.has(node.id)),
      data: {
        ...node.data,
        isFlowFocused,
        onToggleFlowFocus: () => handleToggleFlowFocus(node.id),
      },
    };
  }), [focusNodeId, focusedNodeIds, handleToggleFlowFocus, nodes]);

  const edges = useMemo(() => projectedEdges.map((edge) => {
    const visibleInFocus = !focusedNodeIds
      || (focusedNodeIds.has(edge.source) && focusedNodeIds.has(edge.target));
    if (!focusedNodeIds) return edge;
    const isHierarchy = edge.data.edgeType === 'contains';
    const primary = edge.data.names.slice(0, 2).join(' · ') || 'DATA FLOW';
    const extra = edge.data.names.length > 2 ? ` +${edge.data.names.length - 2}` : '';
    const fullLabel = `${primary}${extra}`;
    return {
      ...edge,
      hidden: !visibleInFocus,
      label: visibleInFocus && !isHierarchy
        ? fullLabel.length > 46 ? `${fullLabel.slice(0, 43)}...` : fullLabel
        : '',
      className: `${edge.className || ''}${visibleInFocus ? ' is-focus-flow' : ''}`,
      markerEnd: edge.markerEnd ? { ...edge.markerEnd, width: 19, height: 19 } : undefined,
      style: {
        ...edge.style,
        strokeWidth: isHierarchy ? 3.4 : 4.8,
        opacity: visibleInFocus ? 1 : 0,
      },
    };
  }), [focusedNodeIds, projectedEdges]);

  const relations = useMemo(() => {
    if (!selectedFlowNode) return [];
    return edges.flatMap((edge) => {
      if (edge.target === selectedFlowNode.id) {
        return [`IN  ${nodeById.get(edge.source)?.data.title || edge.source} → ${edge.data.names.join(' · ') || 'CONTAINS'}`];
      }
      if (edge.source === selectedFlowNode.id) {
        return [`OUT ${edge.data.names.join(' · ') || 'CONTAINS'} → ${nodeById.get(edge.target)?.data.title || edge.target}`];
      }
      return [];
    });
  }, [edges, nodeById, selectedFlowNode]);

  const handleNodeClick = useCallback((_, node) => {
    setSelectedId(node.id);
    setIsDetailOpen(true);
    const rawNode = NODE_BY_ID.get(node.id);
    if (!rawNode) return;
    const children = CHILDREN_BY_PARENT[node.id] || [];
    if (!children.length) return;
    if (rawNode.node_level === 1) {
      setActiveSystemId((current) => current === node.id ? null : node.id);
      setActiveWorkflowId(null);
    } else if (rawNode.node_level === 2 && rawNode.node_type === 'Workflow') {
      setActiveWorkflowId((current) => current === node.id ? null : node.id);
    }
  }, []);

  const collapseAll = useCallback(() => {
    setActiveSystemId(null);
    setActiveWorkflowId(null);
    setSelectedId('system:script_production');
    setFocusNodeId(null);
  }, []);

  const resetPositions = useCallback(() => {
    setNodes(layoutNodes);
    window.setTimeout(() => flowInstance?.fitView({ padding: 0.1, duration: 420, maxZoom: 1.04 }), 30);
  }, [flowInstance, layoutNodes, setNodes]);

  const selectedChildren = selectedNode ? (CHILDREN_BY_PARENT[selectedNode.id] || []) : [];
  const modelItems = selectedNode?.model ? [
    selectedNode.model,
    ...Object.entries(selectedNode.model_params || {}).map(([key, value]) => `${key}: ${value}`),
  ] : [];
  const evidenceItems = selectedNode?.source_evidence?.map((item) => `${item.path}:${item.line} · ${item.symbol}`) || [];
  const warning = selectedNode ? HIGH_WARNINGS.get(selectedNode.id) : null;

  return (
    <main className="architecture-app">
      <style>{APP_STYLES}</style>
      <header className="app-header">
        <div className="brand-block">
          <div className="brand-index">ITS / ARCHIVE 001</div>
          <div><h1>Idea to Scripts</h1><p>Code-driven Agent Runtime Architecture</p></div>
        </div>
        <div className="header-stats" aria-label="架构统计">
          <span><strong>{manifest.nodes.length}</strong> NODES</span>
          <span><strong>{manifest.edges.length}</strong> EDGES</span>
          <span><strong>{manifest.scan_scope.workflow_export_count}</strong> WORKFLOWS</span>
          <span className="warning-stat"><strong>{manifest.configuration_warnings.filter((item) => item.severity === 'HIGH').length}</strong> HIGH WARN</span>
          {focusNodeId && <button type="button" className="focus-exit-button" onClick={() => setFocusNodeId(null)}>SHOW ALL</button>}
          <button type="button" onClick={collapseAll}>LEVEL 1</button>
          <button type="button" onClick={resetPositions}>RESET POS</button>
          <button type="button" onClick={() => setIsDetailOpen((open) => !open)}>{isDetailOpen ? 'HIDE DETAIL' : 'SHOW DETAIL'}</button>
        </div>
      </header>

      <section className={`flow-workspace ${isDetailOpen ? 'detail-visible' : ''}`} aria-label="Idea to Scripts 真实数据流架构">
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onInit={setFlowInstance}
          onNodesChange={onNodesChange}
          onNodeClick={handleNodeClick}
          onPaneClick={() => setIsDetailOpen(false)}
          nodesConnectable={false}
          nodesDraggable
          edgesReconnectable={false}
          deleteKeyCode={null}
          minZoom={0.18}
          maxZoom={1.45}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Lines} color="#d2cec3" gap={32} size={1} />
          <MiniMap nodeColor={(node) => TYPE_META[node.type]?.color || '#77746d'} maskColor="rgba(239,236,226,.78)" pannable zoomable />
          <Controls showInteractive={false} position="bottom-left" />
          <Panel position="top-left" className="canvas-guide">
            <span>CLICK → EXPAND / DETAIL</span><span>EYE → ISOLATE FLOW</span><span>DRAG NODE → ADJUST</span><span>SCROLL / PAN</span>
          </Panel>
          <Panel position="top-center" className="breadcrumb-panel">
            <span>LEVEL 1</span>
            {activeSystemId && <><b>→</b><span>{NODE_BY_ID.get(activeSystemId)?.title}</span></>}
            {activeWorkflowId && <><b>→</b><span>{NODE_BY_ID.get(activeWorkflowId)?.title}</span></>}
            {focusNodeId && <><b>/</b><span className="focus-mode-label">FOCUS · {displayTitleForNode(NODE_BY_ID.get(focusNodeId))}</span></>}
          </Panel>
          <Panel position="top-right" className="legend-panel">
            {Object.entries(TYPE_META).map(([type, meta]) => <span key={type}><i style={{ background: meta.color }} />{meta.label}</span>)}
          </Panel>
          <Panel position="bottom-center" className="edge-legend-panel">
            {Object.entries(EDGE_CHANNELS).filter(([key]) => key !== 'hierarchy').map(([key, meta]) => (
              <span key={key}><i style={{ background: meta.stroke }} />{meta.label}</span>
            ))}
          </Panel>
        </ReactFlow>

        {isDetailOpen && selectedNode && (
          <aside className="detail-drawer" aria-label={`${selectedNode.title} 节点详情`}>
            <div className="detail-header">
              <div><span>{nodeStageLabel(selectedNode)}</span><h2>{displayTitleForNode(selectedNode)}</h2><p>{selectedNode.responsibility}</p></div>
              <button type="button" aria-label="关闭详情" onClick={() => setIsDetailOpen(false)}>×</button>
            </div>
            <div className="detail-scroll">
              <div className="detail-status-row">
                <span>NODE ID</span><code>{selectedNode.id}</code><span className="status-chip">L{selectedNode.node_level}</span>
              </div>
              {warning && <section className="warning-note"><span>HIGH / CONFIGURATION</span><p>{warning.observed}</p><p>{warning.impact}</p></section>}
              <DetailSection index="01" title="输入字段 / INPUT" items={asList(selectedNode.input)} />
              <DetailSection index="02" title="输出字段 / OUTPUT" items={asList(selectedNode.output)} />
              <DetailSection index="03" title="调用关系 / RELATIONS" items={relations} />
              <DetailSection index="04" title="保存状态 / PERSISTENCE" items={asList(selectedNode.save_state)} />
              <DetailSection index="05" title="模型参数 / MODEL" items={modelItems} empty="NOT AN LLM NODE" />
              <DetailSection index="06" title="下级节点 / CHILDREN" items={selectedChildren.map((item) => `${item.id} · ${displayTitleForNode(item)}`)} empty="LEAF NODE" />
              <DetailSection index="07" title="代码证据 / EVIDENCE" items={evidenceItems} />
            </div>
          </aside>
        )}
      </section>
    </main>
  );
}

const APP_STYLES = `
  :root { color-scheme: light; }
  .architecture-app { width:100%; height:100%; overflow:hidden; color:#242421; background:#f2efe6; }
  .app-header { position:relative; z-index:20; display:flex; min-height:74px; align-items:center; justify-content:space-between; padding:0 22px; border-bottom:1px solid #c8c4b9; background:#f6f3ea; }
  .brand-block,.header-stats,.detail-status-row,.node-kicker,.architecture-node footer,.canvas-guide,.legend-panel,.breadcrumb-panel,.edge-legend-panel { display:flex; align-items:center; }
  .brand-block { gap:17px; }
  .brand-index { padding:7px 9px; border:1px solid #2d2d29; font:600 9px/1.1 "SFMono-Regular",Consolas,monospace; letter-spacing:.12em; }
  .brand-block h1 { margin:0 0 3px; font-size:17px; font-weight:650; letter-spacing:-.02em; }
  .brand-block p { margin:0; color:#76736d; font:500 9px/1.2 "SFMono-Regular",Consolas,monospace; letter-spacing:.14em; text-transform:uppercase; }
  .header-stats { gap:16px; color:#77746d; font:500 9px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.1em; }
  .header-stats span { white-space:nowrap; }
  .header-stats strong { margin-right:5px; color:#252522; font-size:13px; }
  .header-stats .warning-stat,.header-stats .warning-stat strong { color:#775047; }
  .header-stats button,.detail-header button { border:1px solid #2d2d29; border-radius:0; color:#f6f3ea; background:#242421; cursor:pointer; }
  .header-stats button { padding:9px 12px; font:600 9px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.09em; }
  .header-stats button:hover,.header-stats button:focus-visible,.detail-header button:hover,.detail-header button:focus-visible { color:#242421; background:#f6f3ea; }
  .header-stats .focus-exit-button { border-color:#6f5740; color:#201f1c; background:#d9c9aa; }
  .header-stats .focus-exit-button:hover,.header-stats .focus-exit-button:focus-visible { border-color:#242421; color:#f6f3ea; background:#242421; }
  .flow-workspace { position:relative; width:100%; height:calc(100% - 74px); }
  .flow-workspace .react-flow { width:100%; background:radial-gradient(circle at 24% 18%,rgba(55,55,50,.035) 0 1px,transparent 1.5px) 0 0/23px 23px,#f2efe6; transition:width .22s ease; }
  .detail-visible .react-flow { width:calc(100% - 390px); }
  .architecture-node { position:relative; width:224px; min-height:122px; padding:14px 15px 12px; border:1.5px solid #77746d; border-radius:0; color:#20201e; background:#f7f4ec; box-shadow:0 6px 18px rgba(45,44,39,.075); transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease; cursor:grab; }
  .architecture-node:active { cursor:grabbing; }
  .architecture-node.level-1 { min-height:136px; border-top:4px solid #292925; }
  .architecture-node.level-3 { background:#f4f1e9; }
  .architecture-node.node-user { background:#f8f5ed; border-color:#595751; }
  .architecture-node.node-orchestrator { background:#dde7e7; border-color:#536e72; }
  .architecture-node.node-agent { background:#e5eadf; border-color:#65775b; }
  .architecture-node.node-memory { background:#eee4d3; border-color:#8a6f3e; }
  .architecture-node.node-audit { background:#efe0db; border-color:#8d5e54; }
  .architecture-node.node-data { background:#e3e4e1; border-color:#646762; }
  .architecture-node.has-warning { border-color:#7c4e45; border-top:3px solid #7c4e45; }
  .architecture-node.is-flow-focused { border-color:#171715; box-shadow:0 0 0 2px #171715,0 12px 30px rgba(31,30,27,.18); }
  .react-flow__node.selected .architecture-node { border-color:#1e1e1b; box-shadow:0 0 0 1px #1e1e1b,0 10px 28px rgba(38,37,33,.13); transform:translateY(-2px); }
  .node-kicker { justify-content:space-between; gap:10px; padding-bottom:9px; border-bottom:1px solid rgba(45,45,41,.28); color:#55534e; font:700 8.5px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.1em; }
  .node-tools { display:flex; flex:0 0 auto; align-items:center; gap:7px; }
  .node-visibility-button { display:grid; width:23px; height:20px; place-items:center; padding:0; border:1px solid rgba(48,48,44,.48); border-radius:0; color:#4f4e49; background:rgba(248,246,239,.45); cursor:pointer; transition:color .14s ease,background .14s ease,border-color .14s ease; }
  .node-visibility-button svg { width:15px; height:15px; overflow:visible; fill:none; stroke:currentColor; stroke-width:1.65; vector-effect:non-scaling-stroke; }
  .node-visibility-button:hover,.node-visibility-button:focus-visible,.node-visibility-button[aria-pressed="true"] { border-color:#20201d; color:#f7f4ec; background:#20201d; outline:none; }
  .node-visibility-button[aria-pressed="true"] circle { fill:currentColor; }
  .warning-flag { display:inline-block; margin-top:9px; padding:4px 5px; color:#71463e; border:1px solid #a58279; font:700 7px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.08em; }
  .architecture-node h3 { margin:12px 0 6px; font-size:15px; font-weight:720; line-height:1.28; letter-spacing:-.012em; }
  .architecture-node p { display:-webkit-box; min-height:32px; margin:0 0 13px; overflow:hidden; color:#595751; font-size:10.8px; font-weight:480; line-height:1.5; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
  .architecture-node footer { gap:8px; color:#5f5d57; font:700 7.5px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.08em; }
  .architecture-node footer span:last-child { margin-left:auto; color:#363632; }
  .node-handle { width:7px; height:7px; border:1px solid #f2efe6; background:#53534d; }
  .react-flow__edge-path { vector-effect:non-scaling-stroke; }
  .react-flow__edge.animated path { stroke-dasharray:8 6; animation-duration:1.35s; animation-timing-function:linear; }
  .react-flow__edge.animated.is-related path { stroke-dasharray:9 5; animation-duration:.72s; }
  .react-flow__edge.animated.is-focus-flow path { animation-duration:.52s; }
  .react-flow__edge.edge-channel-memory path { stroke-dasharray:10 6; }
  .react-flow__edge.edge-channel-persistence path { stroke-dasharray:5 5; }
  .react-flow__edge-text { font-family:"SFMono-Regular",Consolas,monospace; letter-spacing:.015em; paint-order:stroke; stroke:#faf8f1; stroke-width:3px; stroke-linejoin:round; }
  .react-flow__controls,.react-flow__minimap,.canvas-guide,.legend-panel,.breadcrumb-panel,.edge-legend-panel { border:1px solid #aaa69b; border-radius:0; box-shadow:none; }
  .react-flow__controls { overflow:hidden; }
  .react-flow__controls-button { width:30px; height:30px; border-bottom-color:#c9c5ba; color:#30302c; background:#f6f3ea; }
  .react-flow__controls-button:hover { background:#e7e3d9; }
  .react-flow__minimap { right:18px; bottom:18px; width:170px; height:110px; background:#ebe8df; }
  .canvas-guide,.legend-panel,.breadcrumb-panel,.edge-legend-panel { gap:13px; padding:9px 11px; color:#5c5a54; background:rgba(250,248,241,.96); font:700 7px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.1em; pointer-events:none; }
  .breadcrumb-panel { max-width:42vw; overflow:hidden; }
  .breadcrumb-panel span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .breadcrumb-panel .focus-mode-label { color:#3e3326; font-weight:800; }
  .legend-panel { flex-wrap:wrap; max-width:405px; justify-content:flex-end; }
  .legend-panel span { display:inline-flex; align-items:center; gap:5px; }
  .legend-panel i { width:6px; height:6px; }
  .edge-legend-panel { flex-wrap:wrap; justify-content:center; max-width:640px; }
  .edge-legend-panel span { display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }
  .edge-legend-panel i { width:18px; height:3px; }
  .layer-label-node { width:224px; padding:0 0 10px; border-bottom:2px solid #343431; color:#262623; background:transparent; pointer-events:none; }
  .layer-label-node strong { display:block; font:750 15px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.08em; }
  .layer-label-node span { display:block; margin-top:7px; color:#6a6760; font:650 8px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.13em; }
  .react-flow__node-layerLabel { z-index:0!important; }
  .detail-drawer { position:absolute; z-index:15; top:0; right:0; display:grid; grid-template-rows:auto 1fr; width:min(390px,92vw); height:100%; border-left:1px solid #77746c; color:#292925; background:#f7f4ec; box-shadow:-16px 0 38px rgba(40,39,35,.08); }
  .detail-header { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding:22px 22px 19px; border-bottom:1px solid #c7c3b8; }
  .detail-header span,.warning-note span { color:#77746e; font:600 8px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.12em; }
  .detail-header h2 { margin:10px 0 7px; font-size:20px; line-height:1.25; letter-spacing:-.025em; }
  .detail-header p { margin:0; color:#6c6963; font-size:11px; line-height:1.5; }
  .detail-header button { flex:0 0 auto; width:28px; height:28px; padding:0 0 2px; font-size:21px; line-height:1; }
  .detail-scroll { min-height:0; overflow-y:auto; scrollbar-width:thin; scrollbar-color:#aaa69b transparent; }
  .detail-status-row { gap:9px; padding:12px 22px; border-bottom:1px solid #d2cec3; color:#77746e; font:600 8px/1 "SFMono-Regular",Consolas,monospace; letter-spacing:.09em; }
  .detail-status-row code { overflow:hidden; color:#373732; font-size:9px; letter-spacing:0; text-overflow:ellipsis; }
  .status-chip { margin-left:auto; padding:5px 6px; border:1px solid #aaa69b; color:#44433e; white-space:nowrap; }
  .warning-note { margin:18px 22px 0; padding:14px; border:1px solid #9a7168; border-left:3px solid #7c4e45; background:#eee2de; }
  .warning-note span { color:#71463e; }
  .warning-note p { margin:9px 0 0; color:#5f4b46; font-size:10px; line-height:1.6; }
  .detail-section { padding:18px 22px 19px; border-bottom:1px solid #d2cec3; }
  .detail-section-title { display:grid; grid-template-columns:25px 1fr; align-items:baseline; margin-bottom:13px; }
  .detail-section-title span { color:#8b877d; font:500 8px/1 "SFMono-Regular",Consolas,monospace; }
  .detail-section-title h3 { margin:0; font-size:10px; font-weight:700; letter-spacing:.08em; }
  .detail-section ul { display:grid; gap:8px; margin:0; padding:0; list-style:none; }
  .detail-section li { position:relative; padding-left:13px; color:#52514c; font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace; font-size:9px; line-height:1.55; overflow-wrap:anywhere; }
  .detail-section li::before { position:absolute; top:.62em; left:0; width:4px; height:4px; border:1px solid #74716a; content:''; }
  .unknown-value { margin:0; color:#8b877f; font:500 9px/1.4 "SFMono-Regular",Consolas,monospace; }
  @media (max-width:1100px) { .header-stats span { display:none; } .legend-panel,.breadcrumb-panel,.edge-legend-panel { display:none; } }
  @media (max-width:760px) { .detail-visible .react-flow { width:100%; } }
  @media (max-width:640px) { .app-header { min-height:66px; padding:0 12px; } .flow-workspace { height:calc(100% - 66px); } .brand-index { display:none; } .brand-block h1 { font-size:15px; } .header-stats { gap:5px; } .header-stats button:nth-last-of-type(2) { display:none; } .canvas-guide,.react-flow__minimap { display:none; } .detail-drawer { width:100%; } }
`;

export default App;
