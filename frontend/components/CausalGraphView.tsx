import React, { useState, useEffect, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
  Position,
  getBezierPath,
  EdgeProps,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Stock } from '../types';
import { useLocale } from '../i18n/context';

const API_BASE = (import.meta as unknown as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL ?? 'http://localhost:8000';

interface CausalGraphViewProps {
  tickers: Stock[];
  onSelectTicker?: (stock: Stock) => void;
}

interface CausalGraphEdgeData {
  from_ticker: string;
  to_ticker: string;
  storyline_id?: string | null;
  article_titles?: string[] | null;
}

interface CausalGraphData {
  nodes: string[];
  edges: CausalGraphEdgeData[];
}

function CausalEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, style, markerEnd }: EdgeProps) {
  const { t } = useLocale();
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });
  const titles = (data?.article_titles as string[] | undefined) ?? [];
  const label = titles.length > 0 ? titles.join(' • ') : t('causal.storyLink');
  return (
    <g>
      <title>{label}</title>
      <path
        id={id}
        className="react-flow__edge-path cursor-pointer"
        d={edgePath}
        style={style}
        strokeWidth={2}
        markerEnd={markerEnd}
      />
    </g>
  );
}

const edgeTypes = { causal: CausalEdge };

function layoutNodes(nodes: string[], _edges: Array<{ from_ticker: string; to_ticker: string }>, target: string): Node[] {
  if (nodes.length === 0) return [];
  const targetUpper = target.trim().toUpperCase();
  const width = 140;
  const height = 60;
  const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
  const targetIndex = nodes.indexOf(targetUpper);
  const ordered = targetIndex >= 0
    ? [nodes[targetIndex], ...nodes.slice(0, targetIndex), ...nodes.slice(targetIndex + 1)]
    : nodes;
  return ordered.map((id, i) => {
    const isTarget = id === targetUpper;
    const row = Math.floor(i / cols);
    const col = i % cols;
    return {
      id,
      type: 'default',
      position: { x: col * width, y: row * height },
      data: { label: id },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: isTarget
        ? { fontWeight: 700, background: 'rgba(204, 255, 0, 0.2)', border: '2px solid #CCFF00', borderRadius: 8 }
        : { borderRadius: 8 },
    };
  });
}

const CausalGraphView: React.FC<CausalGraphViewProps> = ({ tickers, onSelectTicker }) => {
  const { t } = useLocale();
  const [selectedTicker, setSelectedTicker] = useState<string>(() => (tickers[0]?.symbol || '').trim().toUpperCase());
  const [impactLevel, setImpactLevel] = useState<2 | 3>(3);
  const [data, setData] = useState<CausalGraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const first = (tickers[0]?.symbol || '').trim().toUpperCase();
    if (first && !selectedTicker) setSelectedTicker(first);
  }, [tickers]);

  useEffect(() => {
    if (!selectedTicker) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/causal-graph?ticker=${encodeURIComponent(selectedTicker)}&levels=${impactLevel}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(res.statusText))))
      .then((json: CausalGraphData) => {
        setData(json);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load causal graph');
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [selectedTicker, impactLevel]);

  const flowNodes = useMemo(() => {
    if (!data || !data.nodes.length) return [];
    return layoutNodes(data.nodes, data.edges, selectedTicker);
  }, [data, selectedTicker]);

  const flowEdges: Edge[] = useMemo(() => {
    if (!data || !data.edges.length) return [];
    return data.edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.from_ticker,
      target: e.to_ticker,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: '#666' },
    }));
  }, [data]);

  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  useEffect(() => {
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  const handleNodeClick = (_: React.MouseEvent, node: Node) => {
    const symbol = node.id;
    const stock = tickers.find((s) => (s.symbol || '').trim().toUpperCase() === symbol);
    if (stock && onSelectTicker) onSelectTicker(stock);
  };

  const handleEdgeClick = (_: React.MouseEvent, edge: Edge) => {
    const toTicker = (edge.data as { to_ticker?: string })?.to_ticker;
    if (!toTicker || !onSelectTicker) return;
    const stock = tickers.find((s) => (s.symbol || '').trim().toUpperCase() === toTicker);
    if (stock) onSelectTicker(stock);
  };

  if (tickers.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 border border-gray-800 rounded-xl bg-[#0a0a0a]">
        <p className="text-gray-500">{t('causal.addTickersHint')}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex flex-wrap items-center gap-4 mb-4">
        <div className="flex items-center gap-2">
          <label className="text-sm font-bold text-gray-400">Target ticker</label>
          <select
            value={selectedTicker}
            onChange={(e) => setSelectedTicker(e.target.value.trim().toUpperCase())}
            className="bg-[#121212] border border-gray-800 rounded-lg px-3 py-2 text-sm font-bold text-[#CCFF00] focus:outline-none focus:border-gray-600"
          >
            {tickers.map((s) => (
              <option key={s.symbol} value={(s.symbol || '').trim().toUpperCase()}>
                {s.symbol}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm font-bold text-gray-400">{t('causal.impactLevel')}</label>
          <select
            value={impactLevel}
            onChange={(e) => setImpactLevel(Number(e.target.value) as 2 | 3)}
            className="bg-[#121212] border border-gray-800 rounded-lg px-3 py-2 text-sm font-bold text-[#CCFF00] focus:outline-none focus:border-gray-600"
          >
            <option value={2}>{t('causal.level2')}</option>
            <option value={3}>{t('causal.level3')}</option>
          </select>
        </div>
      </div>
      {loading && (
        <div className="flex items-center justify-center h-96 border border-gray-800 rounded-xl bg-[#0a0a0a]">
          <p className="text-gray-500">Loading causal graph...</p>
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-gray-800 bg-[#0a0a0a] p-4 text-sm text-red-400">
          {error}
        </div>
      )}
      {!loading && !error && data && (
        <>
          {data.edges.length === 0 ? (
            <div className="flex items-center justify-center h-96 border border-gray-800 rounded-xl bg-[#0a0a0a]">
              <p className="text-gray-500">{t('causal.noImpactLinks')}</p>
            </div>
          ) : (
            <div className="h-[500px] border border-gray-800 rounded-xl bg-[#0a0a0a] overflow-hidden">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                edgeTypes={edgeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={handleNodeClick}
                onEdgeClick={handleEdgeClick}
                fitView
                fitViewOptions={{ padding: 0.2 }}
                proOptions={{ hideAttribution: true }}
                className="bg-[#0a0a0a]"
              >
                <Background color="#333" gap={16} />
                <Controls className="!bg-[#121212] !border-gray-800" />
              </ReactFlow>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default CausalGraphView;
