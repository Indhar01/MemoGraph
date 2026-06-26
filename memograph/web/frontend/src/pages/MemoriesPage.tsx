import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { memoriesApi, searchAPI } from '../lib/api';
import { Pagination } from '../components/Pagination';
import { ErrorAlert } from '../components/ErrorDisplay';
import {
  Calendar,
  Tag as TagIcon,
  Sparkles,
  LayoutGrid,
  List as ListIcon,
  Plus,
  ArrowDownAZ,
  ArrowDownWideNarrow,
  Clock,
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { getMemoryTypeColor } from '../lib/utils';
import type { Memory } from '../types';

type SortKey = 'modified_at' | 'created_at' | 'salience' | 'title';
type View = 'grid' | 'list';

const SORTS: Array<{ value: SortKey; label: string; icon: typeof Clock }> = [
  { value: 'modified_at', label: 'Recently updated', icon: Clock },
  { value: 'created_at', label: 'Recently created', icon: Calendar },
  { value: 'salience', label: 'Importance', icon: ArrowDownWideNarrow },
  { value: 'title', label: 'Title', icon: ArrowDownAZ },
];

export default function MemoriesPage() {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [view, setView] = useState<View>('grid');
  const [sortBy, setSortBy] = useState<SortKey>('modified_at');
  const [activeTag, setActiveTag] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['memories', page, pageSize, sortBy, activeTag],
    queryFn: () =>
      memoriesApi.list({
        page,
        page_size: pageSize,
        sort_by: sortBy,
        order: sortBy === 'title' ? 'asc' : 'desc',
        tags: activeTag ?? undefined,
      }),
  });

  const { data: tagList = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: () => searchAPI.getAllTags(),
    staleTime: 60_000,
  });

  const memories = data?.memories ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / pageSize);

  const topTags = useMemo(() => tagList.slice(0, 12), [tagList]);

  return (
    <div>
      <header className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4 mb-6">
        <div>
          <h1 className="text-3xl sm:text-4xl font-bold font-display text-fg">
            Your <span className="text-gradient-brand">memories</span>
          </h1>
          <p className="text-muted-fg mt-1">
            {isLoading
              ? 'Loading vault…'
              : `${total.toLocaleString()} ${total === 1 ? 'memory' : 'memories'} in your vault`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SortDropdown sortBy={sortBy} onChange={setSortBy} />
          <ViewToggle view={view} onChange={setView} />
          <Link to="/memories/new" className="btn btn-primary">
            <Plus className="w-4 h-4" />
            <span>New</span>
          </Link>
        </div>
      </header>

      {/* Tag filter rail */}
      {topTags.length > 0 && (
        <div className="mb-6 overflow-x-auto -mx-2 px-2">
          <div className="flex items-center gap-2 min-w-min">
            <button
              type="button"
              onClick={() => setActiveTag(null)}
              className={`badge ${activeTag === null ? 'badge-primary' : 'badge-secondary'} cursor-pointer transition-all hover:scale-[1.03]`}
            >
              All
            </button>
            {topTags.map((tag) => (
              <button
                key={tag}
                type="button"
                onClick={() => setActiveTag(tag === activeTag ? null : tag)}
                className={`badge ${activeTag === tag ? 'badge-accent' : 'badge-secondary'} cursor-pointer transition-all hover:scale-[1.03]`}
              >
                #{tag}
              </button>
            ))}
          </div>
        </div>
      )}

      {isLoading ? (
        <SkeletonGrid view={view} />
      ) : error ? (
        <ErrorAlert
          title="Failed to load memories"
          message={
            (error as Error).message ||
            'Make sure the backend server is running at http://localhost:8000'
          }
          onRetry={() => refetch()}
        />
      ) : memories.length === 0 ? (
        <EmptyState activeTag={activeTag} clearTag={() => setActiveTag(null)} />
      ) : (
        <>
          <div
            className={
              view === 'grid'
                ? 'grid gap-4 sm:grid-cols-2 xl:grid-cols-3'
                : 'flex flex-col gap-3'
            }
          >
            {memories.map((m) => (
              <MemoryCard key={m.id} memory={m} view={view} />
            ))}
          </div>

          {totalPages > 1 && (
            <div className="mt-8">
              <Pagination
                currentPage={page}
                totalPages={totalPages}
                totalItems={total}
                itemsPerPage={pageSize}
                onPageChange={(p) => {
                  setPage(p);
                  window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MemoryCard({ memory, view }: { memory: Memory; view: View }) {
  const salience = Math.round(memory.salience * 100);
  return (
    <Link
      to={`/memories/${memory.id}`}
      className={`card group relative overflow-hidden hover:shadow-glass-md transition-all duration-200 ease-spring hover:-translate-y-0.5 ${
        view === 'list' ? 'flex flex-col sm:flex-row gap-4 items-start' : 'flex flex-col'
      }`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3 mb-2">
          <h3 className="text-lg font-semibold text-fg line-clamp-2 group-hover:text-gradient-primary transition-colors">
            {memory.title}
          </h3>
          <span className={`badge ${getMemoryTypeColor(memory.memory_type)} shrink-0 capitalize`}>
            {memory.memory_type}
          </span>
        </div>

        <p className="text-sm text-muted-fg leading-relaxed line-clamp-3 mb-3">
          {memory.content.slice(0, 220)}
          {memory.content.length > 220 && '…'}
        </p>

        {memory.tags.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap mb-3">
            <TagIcon className="w-3.5 h-3.5 text-muted-fg" />
            {memory.tags.slice(0, 4).map((t) => (
              <span key={t} className="badge badge-secondary text-[10px]">
                #{t}
              </span>
            ))}
            {memory.tags.length > 4 && (
              <span className="text-xs text-muted-fg">+{memory.tags.length - 4}</span>
            )}
          </div>
        )}

        <div className="flex items-center justify-between gap-3 mt-auto pt-2 border-t border-border/60">
          <div className="flex items-center gap-1.5 text-xs text-muted-fg">
            <Clock className="w-3.5 h-3.5" />
            <time dateTime={memory.modified_at}>
              {formatDistanceToNow(new Date(memory.modified_at), { addSuffix: true })}
            </time>
          </div>
          <div
            className="flex items-center gap-2"
            title={`Salience ${salience}%`}
            aria-label={`Salience ${salience} percent`}
          >
            <Sparkles className="w-3.5 h-3.5 text-primary-500" />
            <div className="salience-bar w-16">
              <span style={{ width: `${salience}%` }} />
            </div>
            <span className="font-mono text-[11px] text-muted-fg">{salience}%</span>
          </div>
        </div>

        {(memory.links.length > 0 || memory.backlinks.length > 0) && (
          <div className="flex items-center gap-3 mt-2 text-[11px] text-muted-fg">
            {memory.links.length > 0 && <span>→ {memory.links.length} links</span>}
            {memory.backlinks.length > 0 && <span>← {memory.backlinks.length} backlinks</span>}
          </div>
        )}
      </div>
    </Link>
  );
}

function SortDropdown({
  sortBy,
  onChange,
}: {
  sortBy: SortKey;
  onChange: (s: SortKey) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 glass rounded-md border border-border px-3 py-1.5 text-sm text-muted-fg">
      <span className="hidden sm:inline">Sort</span>
      <select
        aria-label="Sort by"
        value={sortBy}
        onChange={(e) => onChange(e.target.value as SortKey)}
        className="bg-transparent text-fg outline-none cursor-pointer"
      >
        {SORTS.map((s) => (
          <option key={s.value} value={s.value} className="bg-surface text-fg">
            {s.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div
      role="radiogroup"
      aria-label="View"
      className="inline-flex items-center gap-0.5 p-0.5 rounded-md glass border border-border"
    >
      {(['grid', 'list'] as const).map((v) => {
        const Icon = v === 'grid' ? LayoutGrid : ListIcon;
        const selected = view === v;
        return (
          <button
            key={v}
            role="radio"
            aria-checked={selected}
            aria-label={v}
            type="button"
            onClick={() => onChange(v)}
            className={`p-1.5 rounded-[6px] transition-all ${
              selected
                ? 'bg-gradient-primary text-white shadow-glow-soft'
                : 'text-muted-fg hover:text-fg'
            }`}
          >
            <Icon className="w-4 h-4" />
          </button>
        );
      })}
    </div>
  );
}

function EmptyState({
  activeTag,
  clearTag,
}: {
  activeTag: string | null;
  clearTag: () => void;
}) {
  return (
    <div className="card text-center py-16 flex flex-col items-center gap-3">
      <span className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-brand shadow-glow-accent">
        <Sparkles className="w-7 h-7 text-white" />
      </span>
      <h3 className="text-xl font-bold font-display text-fg">
        {activeTag ? `No memories tagged #${activeTag}` : 'Your vault is empty'}
      </h3>
      <p className="text-sm text-muted-fg max-w-sm">
        {activeTag
          ? 'Try clearing the filter, or pick another tag from the list above.'
          : 'Start capturing what matters — facts, experiences, processes — and watch the graph grow.'}
      </p>
      <div className="flex items-center gap-3 mt-2">
        {activeTag && (
          <button type="button" onClick={clearTag} className="btn btn-secondary">
            Clear filter
          </button>
        )}
        <Link to="/memories/new" className="btn btn-primary">
          <Plus className="w-4 h-4" />
          Create your first memory
        </Link>
      </div>
    </div>
  );
}

function SkeletonGrid({ view }: { view: View }) {
  return (
    <div
      className={
        view === 'grid'
          ? 'grid gap-4 sm:grid-cols-2 xl:grid-cols-3'
          : 'flex flex-col gap-3'
      }
    >
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="card space-y-3">
          <div className="skeleton h-6 w-3/4" />
          <div className="skeleton h-3 w-full" />
          <div className="skeleton h-3 w-5/6" />
          <div className="skeleton h-3 w-2/3" />
          <div className="flex gap-2 mt-3">
            <div className="skeleton h-4 w-10" />
            <div className="skeleton h-4 w-14" />
          </div>
        </div>
      ))}
    </div>
  );
}
