import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import ForceGraph2D, { ForceGraphMethods, NodeObject, LinkObject } from 'react-force-graph-2d';
import { graphAPI, searchAPI, getErrorMessage } from '../lib/api';
import { ErrorAlert } from '../components/ErrorDisplay';
import GraphFilters, { GraphFilterState } from '../components/GraphFilters';
import {
  Network,
  AlertCircle,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Crosshair,
  Eye,
  EyeOff,
  Search as SearchIcon,
} from 'lucide-react';
import { useTheme } from '../lib/theme';
import { MEMORY_TYPE_HEX } from '../lib/utils';

// ============================================================================
// Types
// ============================================================================

interface GraphNode extends NodeObject {
  id: string;
  name: string;
  val: number;
  color: string;
  memory_type: string;
  salience: number;
  tags: string[];
  link_count: number;
  backlink_count: number;
}

interface GraphLink extends LinkObject {
  source: string | GraphNode;
  target: string | GraphNode;
  type: string;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

const DEFAULT_FILTERS: GraphFilterState = {
  minSalience: 0,
  maxSalience: 1,
  tags: [],
  memoryTypes: [],
  limit: 200,
  focusNode: '',
};

function nodeColor(type: string) {
  return MEMORY_TYPE_HEX[type]?.from ?? '#6b7280';
}

// ============================================================================
// Component
// ============================================================================

export default function GraphPage() {
  const navigate = useNavigate();
  const graphRef = useRef<ForceGraphMethods>();
  const containerRef = useRef<HTMLDivElement>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null);
  const [showLabels, setShowLabels] = useState(false);
  const { resolvedTheme } = useTheme();
  const [nodeSearch, setNodeSearch] = useState('');
  const [dimensions, setDimensions] = useState({ width: 0, height: 600 });

  // Filters from URL
  const filters = useMemo((): GraphFilterState => ({
    minSalience: parseFloat(searchParams.get('minSalience') || '0'),
    maxSalience: parseFloat(searchParams.get('maxSalience') || '1'),
    tags: searchParams.get('tags')?.split(',').filter(Boolean) || [],
    memoryTypes: searchParams.get('types')?.split(',').filter(Boolean) || [],
    limit: parseInt(searchParams.get('limit') || '200'),
    focusNode: searchParams.get('focus') || '',
  }), [searchParams]);

  const { data: availableTags = [], isLoading: isLoadingTags } = useQuery({
    queryKey: ['tags'],
    queryFn: () => searchAPI.getAllTags(),
    staleTime: 60000,
  });

  const apiParams = useMemo(() => {
    const p: any = { limit: filters.limit };
    if (filters.minSalience > 0) p.min_salience = filters.minSalience;
    if (filters.tags.length > 0) p.tags = filters.tags.join(',');
    if (filters.focusNode) p.focus_node = filters.focusNode;
    return p;
  }, [filters]);

  const { data: apiData, isLoading, error, refetch } = useQuery({
    queryKey: ['graph', apiParams],
    queryFn: () => graphAPI.getGraph(apiParams),
    staleTime: 30000,
  });

  const graphData: GraphData | null = useMemo(() => {
    if (!apiData) return null;
    let nodes = apiData.nodes.filter((n: any) => {
      if (n.salience < filters.minSalience || n.salience > filters.maxSalience) return false;
      if (filters.memoryTypes.length > 0 && !filters.memoryTypes.includes(n.memory_type)) return false;
      return true;
    });
    const ids = new Set(nodes.map((n: any) => n.id));
    const links = apiData.edges.filter((e: any) => ids.has(e.source) && ids.has(e.target));
    return {
      nodes: nodes.map((n: any) => ({
        id: n.id,
        name: n.title,
        val: n.salience * 10,
        color: nodeColor(n.memory_type),
        memory_type: n.memory_type,
        salience: n.salience,
        tags: n.tags,
        link_count: n.link_count,
        backlink_count: n.backlink_count,
      })),
      links: links.map((e: any) => ({ source: e.source, target: e.target, type: e.type })),
    };
  }, [apiData, filters.minSalience, filters.maxSalience, filters.memoryTypes]);

  // Match nodes for the "find node" combobox
  const nodeMatches = useMemo(() => {
    if (!nodeSearch || !graphData) return [];
    const q = nodeSearch.toLowerCase();
    return graphData.nodes
      .filter((n) => n.name.toLowerCase().includes(q))
      .slice(0, 6);
  }, [nodeSearch, graphData]);

  // Track container width
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      setDimensions({ width: r.width, height: 600 });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Theme-aware colors
  const themeColors = useMemo(() => {
    if (resolvedTheme === 'dark') {
      return {
        bg: 'rgba(2, 6, 23, 0)',
        link: 'rgba(148, 163, 184, 0.35)',
        labelBg: 'rgba(15, 23, 42, 0.92)',
        labelFg: '#f8fafc',
        ring: '#38bdf8',
      };
    }
    return {
      bg: 'rgba(255, 255, 255, 0)',
      link: 'rgba(100, 116, 139, 0.30)',
      labelBg: 'rgba(255, 255, 255, 0.96)',
      labelFg: '#0f172a',
      ring: '#0284c7',
    };
  }, [resolvedTheme]);

  const handleFiltersChange = useCallback((nf: GraphFilterState) => {
    const p = new URLSearchParams();
    if (nf.minSalience > 0) p.set('minSalience', nf.minSalience.toString());
    if (nf.maxSalience < 1) p.set('maxSalience', nf.maxSalience.toString());
    if (nf.tags.length > 0) p.set('tags', nf.tags.join(','));
    if (nf.memoryTypes.length > 0) p.set('types', nf.memoryTypes.join(','));
    if (nf.limit !== DEFAULT_FILTERS.limit) p.set('limit', nf.limit.toString());
    if (nf.focusNode) p.set('focus', nf.focusNode);
    setSearchParams(p);
  }, [setSearchParams]);

  const handleResetFilters = useCallback(() => setSearchParams(new URLSearchParams()), [setSearchParams]);

  const handleNodeClick = useCallback((node: GraphNode) => {
    navigate(`/memories/${node.id}`);
  }, [navigate]);

  const handleNodeHover = useCallback((node: GraphNode | null) => {
    setHoveredNode(node);
    if (!node) setCursorPos(null);
  }, []);

  // Track mouse for floating tooltip
  const onCanvasMouseMove = useCallback((e: React.MouseEvent) => {
    if (!hoveredNode || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setCursorPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  }, [hoveredNode]);

  const paintNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const size = Math.sqrt(node.val || 1) * 4;
      const isHover = hoveredNode?.id === node.id;
      const fontSize = 11 / globalScale;

      // Soft glow
      ctx.shadowBlur = isHover ? 14 : 6;
      ctx.shadowColor = node.color;
      ctx.beginPath();
      ctx.arc(node.x!, node.y!, size, 0, Math.PI * 2);
      ctx.fillStyle = node.color;
      ctx.fill();
      ctx.shadowBlur = 0;

      if (isHover) {
        ctx.beginPath();
        ctx.arc(node.x!, node.y!, size + 2, 0, Math.PI * 2);
        ctx.strokeStyle = themeColors.ring;
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }

      // Labels: when in labeled mode OR on hover. Skip when text would be illegible
      if ((showLabels && globalScale > 0.8) || isHover) {
        const label = node.name.length > 30 ? node.name.slice(0, 28) + '…' : node.name;
        ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
        const width = ctx.measureText(label).width;
        const pad = 4 / globalScale;
        ctx.fillStyle = themeColors.labelBg;
        ctx.fillRect(
          node.x! - width / 2 - pad,
          node.y! - size - fontSize - pad * 2,
          width + pad * 2,
          fontSize + pad * 2,
        );
        ctx.fillStyle = themeColors.labelFg;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(label, node.x!, node.y! - size - fontSize / 2 - pad);
      }
    },
    [hoveredNode, showLabels, themeColors],
  );

  // Graph controls
  const zoomIn = () => graphRef.current?.zoom((graphRef.current.zoom() ?? 1) * 1.4, 200);
  const zoomOut = () => graphRef.current?.zoom((graphRef.current.zoom() ?? 1) / 1.4, 200);
  const fit = () => graphRef.current?.zoomToFit(400, 60);
  const center = () => graphRef.current?.centerAt(0, 0, 400);

  // Focus a specific node (used by node search)
  const focusOnNode = useCallback((node: GraphNode) => {
    if (graphRef.current && node.x !== undefined && node.y !== undefined) {
      graphRef.current.centerAt(node.x, node.y, 600);
      graphRef.current.zoom(2.5, 600);
    }
    setNodeSearch('');
  }, []);

  // Loading
  if (isLoading) {
    return (
      <div>
        <PageHeader nodes={0} links={0} loading />
        <div className="card flex flex-col items-center justify-center min-h-[600px]">
          <div className="skeleton w-full h-full rounded-lg" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageHeader nodes={0} links={0} />
        <ErrorAlert
          title="Failed to load graph"
          message={getErrorMessage(error)}
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div>
        <PageHeader nodes={0} links={0} />
        <div className="card text-center py-16 flex flex-col items-center gap-3">
          <span className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-brand shadow-glow-accent">
            <AlertCircle className="w-7 h-7 text-white" />
          </span>
          <h3 className="text-xl font-bold font-display">No graph data yet</h3>
          <p className="text-sm text-muted-fg max-w-sm">
            Create some memories with <code className="font-mono">[[wikilinks]]</code> and watch
            the graph come alive.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader nodes={graphData.nodes.length} links={graphData.links.length} />

      <div className="grid lg:grid-cols-[280px_1fr] gap-4 items-start">
        {/* Filters sidebar */}
        <GraphFilters
          filters={filters}
          availableTags={availableTags}
          onFiltersChange={handleFiltersChange}
          onReset={handleResetFilters}
          isLoadingTags={isLoadingTags}
        />

        {/* Canvas + overlays */}
        <div
          ref={containerRef}
          onMouseMove={onCanvasMouseMove}
          className="card p-0 overflow-hidden relative"
          style={{ height: '600px' }}
        >
          {/* Top-left node search */}
          <div className="absolute top-3 left-3 z-10 w-64">
            <div className="relative">
              <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-fg" />
              <input
                type="text"
                value={nodeSearch}
                onChange={(e) => setNodeSearch(e.target.value)}
                placeholder="Find a node…"
                aria-label="Find a node"
                className="input pl-9 py-1.5 text-sm"
              />
            </div>
            {nodeMatches.length > 0 && (
              <ul
                role="listbox"
                className="mt-1 glass-strong rounded-md border border-border shadow-glass-md overflow-hidden"
              >
                {nodeMatches.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => focusOnNode(n)}
                      className="w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 hover:bg-surface/70"
                    >
                      <span
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: n.color }}
                      />
                      <span className="truncate">{n.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Top-right: density toggle + legend toggle */}
          <div className="absolute top-3 right-3 z-10 flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowLabels((s) => !s)}
              aria-pressed={showLabels}
              aria-label={showLabels ? 'Hide labels' : 'Show labels'}
              className={`btn ${showLabels ? 'btn-primary' : 'btn-secondary'} btn-sm px-2 py-1.5`}
              title={showLabels ? 'Hide labels' : 'Show labels'}
            >
              {showLabels ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>

          {/* Bottom-right controls */}
          <div className="absolute bottom-3 right-3 z-10 flex flex-col gap-1 glass-strong rounded-md border border-border p-1">
            <CanvasIconButton onClick={zoomIn} label="Zoom in"><ZoomIn className="w-4 h-4" /></CanvasIconButton>
            <CanvasIconButton onClick={zoomOut} label="Zoom out"><ZoomOut className="w-4 h-4" /></CanvasIconButton>
            <CanvasIconButton onClick={fit} label="Fit to view"><Maximize2 className="w-4 h-4" /></CanvasIconButton>
            <CanvasIconButton onClick={center} label="Center"><Crosshair className="w-4 h-4" /></CanvasIconButton>
          </div>

          {/* Bottom-left legend */}
          <Legend />

          {/* Floating tooltip */}
          {hoveredNode && cursorPos && (
            <div
              role="tooltip"
              className="absolute z-20 pointer-events-none glass-strong rounded-md p-3 shadow-glass-md border border-border text-xs animate-fade-up"
              style={{
                left: Math.min(cursorPos.x + 12, dimensions.width - 240),
                top: Math.min(cursorPos.y + 12, 600 - 140),
                width: 220,
              }}
            >
              <div className="font-semibold text-fg mb-1 truncate">{hoveredNode.name}</div>
              <div className="text-muted-fg capitalize mb-1.5">{hoveredNode.memory_type}</div>
              <div className="flex items-center gap-2 mb-1">
                <div className="salience-bar flex-1">
                  <span style={{ width: `${Math.round(hoveredNode.salience * 100)}%` }} />
                </div>
                <span className="font-mono">{Math.round(hoveredNode.salience * 100)}%</span>
              </div>
              <div className="text-muted-fg">
                → {hoveredNode.link_count} · ← {hoveredNode.backlink_count}
              </div>
            </div>
          )}

          {/* The canvas */}
          {dimensions.width > 0 && (
            <ForceGraph2D
              ref={graphRef as any}
              width={dimensions.width}
              height={dimensions.height}
              graphData={graphData}
              nodeLabel={() => ''}
              nodeCanvasObject={paintNode}
              nodeVal="val"
              linkColor={() => themeColors.link}
              linkWidth={1.4}
              linkDirectionalParticles={1.5}
              linkDirectionalParticleWidth={1.6}
              linkDirectionalParticleSpeed={0.0028}
              onNodeClick={handleNodeClick}
              onNodeHover={handleNodeHover}
              cooldownTicks={120}
              d3AlphaDecay={0.025}
              d3VelocityDecay={0.32}
              enableNodeDrag
              enableZoomInteraction
              enablePanInteraction
              minZoom={0.4}
              maxZoom={10}
              backgroundColor={themeColors.bg}
            />
          )}
        </div>
      </div>

      <StatsFooter graphData={graphData} />
    </div>
  );
}

function PageHeader({
  nodes,
  links,
  loading,
}: {
  nodes: number;
  links: number;
  loading?: boolean;
}) {
  return (
    <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-3 mb-5">
      <div>
        <h1 className="text-3xl sm:text-4xl font-bold font-display flex items-center gap-3">
          <span className="inline-flex items-center justify-center w-10 h-10 rounded-md bg-gradient-accent shadow-glow-accent">
            <Network className="w-5 h-5 text-white" />
          </span>
          <span>
            Knowledge <span className="text-gradient-brand">graph</span>
          </span>
        </h1>
        <p className="text-muted-fg mt-1">
          {loading
            ? 'Loading…'
            : `${nodes.toLocaleString()} nodes · ${links.toLocaleString()} connections`}
        </p>
      </div>
    </header>
  );
}

function CanvasIconButton({
  onClick,
  label,
  children,
}: {
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="w-8 h-8 rounded inline-flex items-center justify-center text-muted-fg hover:text-fg hover:bg-surface/70 transition-colors"
    >
      {children}
    </button>
  );
}

function Legend() {
  return (
    <div className="absolute bottom-3 left-3 z-10 glass-strong rounded-md border border-border p-3 text-xs">
      <div className="font-semibold mb-2 text-fg">Memory types</div>
      <div className="space-y-1.5">
        {(Object.keys(MEMORY_TYPE_HEX) as Array<keyof typeof MEMORY_TYPE_HEX>).map((t) => (
          <div key={t} className="flex items-center gap-2">
            <div
              className="w-3 h-3 rounded-full shadow-sm"
              style={{
                background: `linear-gradient(135deg, ${MEMORY_TYPE_HEX[t].from}, ${MEMORY_TYPE_HEX[t].to})`,
              }}
            />
            <span className="capitalize text-muted-fg">{t}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 pt-2 border-t border-border text-[10px] text-muted-fg">
        Size = salience
      </div>
    </div>
  );
}

function StatsFooter({ graphData }: { graphData: GraphData }) {
  const avgSal =
    graphData.nodes.length > 0
      ? (graphData.nodes.reduce((s, n) => s + n.salience, 0) / graphData.nodes.length) * 100
      : 0;
  const avgConn = graphData.nodes.length > 0 ? graphData.links.length / graphData.nodes.length : 0;
  return (
    <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
      {[
        { label: 'Total nodes', value: graphData.nodes.length.toLocaleString() },
        { label: 'Total edges', value: graphData.links.length.toLocaleString() },
        { label: 'Avg connections', value: avgConn.toFixed(1) },
        { label: 'Avg salience', value: `${avgSal.toFixed(0)}%` },
      ].map((s) => (
        <div key={s.label} className="card flex flex-col items-start py-4">
          <div className="text-2xl font-bold font-display text-gradient-primary">{s.value}</div>
          <div className="text-xs text-muted-fg">{s.label}</div>
        </div>
      ))}
    </div>
  );
}
