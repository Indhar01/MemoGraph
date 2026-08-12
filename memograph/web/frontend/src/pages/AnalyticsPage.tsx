/**
 * AnalyticsPage — glassy bento grid with KPI tiles + recharts visualizations.
 *
 * Data shape comes from `GET /analytics`:
 *   - total_memories, total_links, avg_salience
 *   - memory_type_distribution: Record<type, count>
 *   - tag_distribution: Record<tag, count>
 *   - salience_distribution: Record<bucket, count>
 *   - most_connected_nodes: [{ id, title, connections, salience }]
 *   - recent_activity: [{ id, title, memory_type, modified_at, salience }]
 */

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart3,
  Brain,
  Link2,
  Sparkles,
  TrendingUp,
  AlertCircle,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
  Legend as ChartLegend,
  LabelList,
} from 'recharts';
import { analyticsAPI } from '../lib/api';
import { ErrorAlert } from '../components/ErrorDisplay';
import { formatDistanceToNow } from 'date-fns';
import { getMemoryTypeColor, MEMORY_TYPE_HEX } from '../lib/utils';

const TYPE_KEYS = ['episodic', 'semantic', 'procedural', 'fact'] as const;

export default function AnalyticsPage() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['analytics'],
    queryFn: () => analyticsAPI.getAnalytics(),
    staleTime: 30_000,
  });

  if (isLoading) return <AnalyticsSkeleton />;
  if (error) {
    return (
      <ErrorAlert
        title="Failed to load analytics"
        message={(error as Error).message}
        onRetry={() => refetch()}
      />
    );
  }
  if (!data) return null;

  if (data.total_memories === 0) {
    return <EmptyAnalytics />;
  }

  const typeData = TYPE_KEYS.map((t) => ({
    name: t,
    value: data.memory_type_distribution[t] ?? 0,
    color: MEMORY_TYPE_HEX[t]?.from ?? '#6b7280',
  })).filter((d) => d.value > 0);

  const topTags = Object.entries(data.tag_distribution)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name, value]) => ({ name, value }));

  const salienceBuckets = Object.entries(data.salience_distribution).map(([name, value]) => ({
    name,
    value,
  }));

  return (
    <div>
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-3xl sm:text-4xl font-bold font-display flex items-center gap-3">
            <span className="inline-flex items-center justify-center w-10 h-10 rounded-md bg-gradient-accent shadow-glow-accent">
              <BarChart3 className="w-5 h-5 text-white" />
            </span>
            <span>
              Vault <span className="text-gradient-brand">analytics</span>
            </span>
          </h1>
          <p className="text-muted-fg mt-1">
            A live picture of what's in your knowledge graph.
          </p>
        </div>
      </header>

      {/* KPI bento row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        <Kpi
          label="Memories"
          value={data.total_memories.toLocaleString()}
          icon={<Brain className="w-4 h-4" />}
          accent="primary"
        />
        <Kpi
          label="Connections"
          value={data.total_links.toLocaleString()}
          icon={<Link2 className="w-4 h-4" />}
          accent="primary"
        />
        <Kpi
          label="Avg salience"
          value={`${Math.round(data.avg_salience * 100)}%`}
          icon={<Sparkles className="w-4 h-4" />}
          accent="accent"
        />
        <Kpi
          label="Tag variety"
          value={Object.keys(data.tag_distribution).length.toLocaleString()}
          icon={<TrendingUp className="w-4 h-4" />}
          accent="accent"
        />
      </div>

      {/* Charts bento */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        {/* Memory type distribution */}
        <div className="card lg:col-span-1">
          <ChartHeader title="Memory types" subtitle="How knowledge is encoded" />
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie
                data={typeData}
                dataKey="value"
                nameKey="name"
                innerRadius={48}
                outerRadius={86}
                paddingAngle={3}
                stroke="rgba(0,0,0,0)"
              >
                {typeData.map((d) => (
                  <Cell key={d.name} fill={d.color} />
                ))}
              </Pie>
              <ChartTooltip
                contentStyle={chartTooltipStyle}
                formatter={(value: number, name: string) => [value, name]}
              />
              <ChartLegend
                verticalAlign="bottom"
                iconType="circle"
                wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                formatter={(v) => <span className="capitalize text-muted-fg">{v}</span>}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Top tags */}
        <div className="card lg:col-span-2">
          <ChartHeader title="Top tags" subtitle={`${topTags.length} of ${Object.keys(data.tag_distribution).length}`} />
          {topTags.length === 0 ? (
            <EmptyChart label="No tags yet" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={topTags} layout="vertical" margin={{ top: 4, left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                <XAxis type="number" tick={{ fill: 'rgb(var(--muted-fg))', fontSize: 11 }} />
                <YAxis
                  dataKey="name"
                  type="category"
                  width={110}
                  tick={{ fill: 'rgb(var(--muted-fg))', fontSize: 11 }}
                  tickFormatter={(t) => `#${t}`}
                />
                <ChartTooltip contentStyle={chartTooltipStyle} cursor={{ fill: 'rgba(14,165,233,0.08)' }} />
                <Bar dataKey="value" radius={[0, 6, 6, 0]} fill="url(#gradPrimary)" />
                <defs>
                  <linearGradient id="gradPrimary" x1="0" x2="1" y1="0" y2="0">
                    <stop offset="0%" stopColor="#0ea5e9" />
                    <stop offset="100%" stopColor="#06b6d4" />
                  </linearGradient>
                </defs>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        {/* Salience histogram */}
        <div className="card lg:col-span-2">
          <ChartHeader title="Salience distribution" subtitle="Importance buckets" />
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={salienceBuckets} margin={{ top: 4, left: -8, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: 'rgb(var(--muted-fg))', fontSize: 11 }} />
              <YAxis tick={{ fill: 'rgb(var(--muted-fg))', fontSize: 11 }} />
              <ChartTooltip contentStyle={chartTooltipStyle} cursor={{ fill: 'rgba(168,85,247,0.08)' }} />
              <Bar dataKey="value" radius={[8, 8, 0, 0]} fill="url(#gradAccent)">
                <LabelList
                  dataKey="value"
                  position="top"
                  style={{ fill: 'rgb(var(--muted-fg))', fontSize: 10 }}
                />
              </Bar>
              <defs>
                <linearGradient id="gradAccent" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#a855f7" />
                  <stop offset="100%" stopColor="#ec4899" />
                </linearGradient>
              </defs>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Recent activity */}
        <div className="card lg:col-span-1">
          <ChartHeader title="Recent activity" subtitle="Latest modifications" />
          {data.recent_activity.length === 0 ? (
            <EmptyChart label="No activity yet" />
          ) : (
            <ul className="space-y-2 mt-2">
              {data.recent_activity.slice(0, 6).map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/memories/${r.id}`}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-surface/70 transition-colors"
                  >
                    <span
                      className={`badge ${getMemoryTypeColor(r.memory_type)} capitalize shrink-0 text-[10px]`}
                    >
                      {r.memory_type}
                    </span>
                    <span className="text-sm text-fg flex-1 truncate">{r.title}</span>
                    <span className="text-[11px] text-muted-fg font-mono">
                      {formatDistanceToNow(new Date(r.modified_at), { addSuffix: false })}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Most-connected table */}
      <div className="card">
        <ChartHeader title="Most-connected memories" subtitle="Hubs in your knowledge graph" />
        {data.most_connected_nodes.length === 0 ? (
          <EmptyChart label="No connected memories yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-muted-fg border-b border-border">
                  <th className="py-2 pr-4 font-semibold">Title</th>
                  <th className="py-2 pr-4 font-semibold">Connections</th>
                  <th className="py-2 pr-4 font-semibold">Salience</th>
                </tr>
              </thead>
              <tbody>
                {data.most_connected_nodes.slice(0, 10).map((n) => (
                  <tr key={n.id} className="border-b border-border/60 last:border-0">
                    <td className="py-2 pr-4">
                      <Link
                        to={`/memories/${n.id}`}
                        className="text-fg hover:text-primary-500 transition-colors"
                      >
                        {n.title}
                      </Link>
                    </td>
                    <td className="py-2 pr-4 font-mono">{n.connections}</td>
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <div className="salience-bar w-24">
                          <span style={{ width: `${Math.round(n.salience * 100)}%` }} />
                        </div>
                        <span className="font-mono text-xs text-muted-fg">
                          {Math.round(n.salience * 100)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ----------- subcomponents ----------- */

const chartTooltipStyle = {
  background: 'rgb(var(--surface-elevated))',
  border: '1px solid rgb(var(--border))',
  borderRadius: 8,
  fontSize: 12,
  color: 'rgb(var(--fg))',
  boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
} as const;

function Kpi({
  label,
  value,
  icon,
  accent,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  accent: 'primary' | 'accent';
}) {
  return (
    <div className="card relative overflow-hidden">
      <div
        className={`absolute -top-8 -right-8 w-24 h-24 rounded-full blur-2xl opacity-25 ${
          accent === 'primary' ? 'bg-primary-500' : 'bg-accent-500'
        }`}
      />
      <div className="relative">
        <div className="flex items-center gap-2 text-muted-fg text-xs uppercase tracking-wider font-semibold mb-2">
          {icon}
          {label}
        </div>
        <div
          className={`text-3xl font-bold font-display ${
            accent === 'primary' ? 'text-gradient-primary' : 'text-gradient-brand'
          }`}
        >
          {value}
        </div>
      </div>
    </div>
  );
}

function ChartHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-sm font-semibold text-fg">{title}</h2>
      {subtitle && <span className="text-xs text-muted-fg">{subtitle}</span>}
    </div>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-[220px] text-sm text-muted-fg">
      <AlertCircle className="w-4 h-4 mr-2" />
      {label}
    </div>
  );
}

function EmptyAnalytics() {
  return (
    <div className="card text-center py-16 flex flex-col items-center gap-3">
      <span className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-brand shadow-glow-accent">
        <BarChart3 className="w-7 h-7 text-white" />
      </span>
      <h3 className="text-xl font-bold font-display">No analytics yet</h3>
      <p className="text-sm text-muted-fg max-w-sm">
        Once you add memories, you'll see distributions, top tags, hubs, and trends here.
      </p>
      <Link to="/memories/new" className="btn btn-primary mt-2">
        Create your first memory
      </Link>
    </div>
  );
}

function AnalyticsSkeleton() {
  return (
    <div>
      <div className="skeleton h-10 w-64 mb-2" />
      <div className="skeleton h-4 w-80 mb-6" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card">
            <div className="skeleton h-4 w-20 mb-3" />
            <div className="skeleton h-8 w-24" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="card h-[280px]">
            <div className="skeleton h-4 w-32 mb-4" />
            <div className="skeleton w-full h-[200px]" />
          </div>
        ))}
      </div>
    </div>
  );
}
