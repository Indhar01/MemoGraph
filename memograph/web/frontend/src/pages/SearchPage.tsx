import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Search,
  Filter,
  X,
  Calendar,
  Tag as TagIcon,
  Loader2,
  Clock,
  AlertCircle,
  Sparkles,
} from 'lucide-react';
import { searchAPI } from '../lib/api';
import { Memory, SearchFilters } from '../types';
import { useDebounce, useLocalStorage } from '../hooks';
import { getMemoryTypeColor, cn } from '../lib/utils';

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const initialTag = params.get('tags');
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<SearchFilters>({
    tags: initialTag ? initialTag.split(',') : [],
    dateFrom: null,
    dateTo: null,
    memoryType: null,
    minSalience: 0,
  });
  const [showFilters, setShowFilters] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [history, setHistory] = useLocalStorage<string[]>('memograph-search-history', []);

  const debouncedQuery = useDebounce(query, 300);

  const { data, isLoading, error } = useQuery({
    queryKey: ['search', debouncedQuery, filters],
    queryFn: () => searchAPI.hybridSearch(debouncedQuery, filters),
    enabled: debouncedQuery.length > 0,
  });

  useEffect(() => {
    if (debouncedQuery && debouncedQuery.length > 2) {
      setHistory((prev) => [debouncedQuery, ...prev.filter((h) => h !== debouncedQuery)].slice(0, 10));
    }
  }, [debouncedQuery, setHistory]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setQuery('');
        setShowSuggestions(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const results = data?.results || [];
  const total = data?.total || 0;
  const filteredHistory = history.filter((h) => h.toLowerCase().includes(query.toLowerCase()) && h !== query).slice(0, 5);
  const showSuggestionsList = showSuggestions && query.length > 0 && filteredHistory.length > 0;

  const activeFilterCount =
    filters.tags.length +
    (filters.dateFrom ? 1 : 0) +
    (filters.dateTo ? 1 : 0) +
    (filters.memoryType ? 1 : 0) +
    (filters.minSalience > 0 ? 1 : 0);

  const clearFilters = () => {
    setFilters({ tags: [], dateFrom: null, dateTo: null, memoryType: null, minSalience: 0 });
    setParams({});
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl sm:text-4xl font-bold font-display">
          <span className="text-gradient-brand">Search</span> your vault
        </h1>
        <p className="text-muted-fg mt-1">Hybrid keyword + semantic + graph traversal.</p>
      </header>

      {/* Search bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-fg" />
          <input
            type="text"
            className="input pl-12 pr-10 py-3 text-base"
            placeholder="Try keywords, questions, or #id…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
            autoFocus
            aria-expanded={showSuggestionsList}
            aria-controls="search-suggestions"
            aria-autocomplete="list"
          />
          {query && (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setShowSuggestions(false);
              }}
              aria-label="Clear search"
              className="absolute right-3 top-1/2 -translate-y-1/2 btn btn-ghost p-1.5"
            >
              <X className="w-4 h-4" />
            </button>
          )}

          {showSuggestionsList && (
            <div
              id="search-suggestions"
              role="listbox"
              className="absolute z-30 top-full left-0 right-0 mt-2 glass-strong rounded-md border border-border shadow-glass-md overflow-hidden"
            >
              <div className="flex items-center justify-between px-3 py-2 text-xs text-muted-fg border-b border-border bg-surface/40">
                <span className="flex items-center gap-1.5 font-semibold uppercase tracking-wider">
                  <Clock className="w-3.5 h-3.5" />
                  Recent searches
                </span>
                <button
                  type="button"
                  onClick={() => setHistory([])}
                  className="hover:text-fg transition-colors"
                >
                  Clear
                </button>
              </div>
              <ul className="max-h-64 overflow-y-auto">
                {filteredHistory.map((h, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        setQuery(h);
                        setShowSuggestions(false);
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-fg hover:bg-surface/70 transition-colors"
                    >
                      <Clock className="w-3.5 h-3.5 text-muted-fg" />
                      <span className="truncate">{h}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={() => setShowFilters((s) => !s)}
          className={cn(
            'btn btn-secondary relative',
            showFilters && 'ring-2 ring-primary-500 ring-offset-2 ring-offset-transparent',
          )}
        >
          <Filter className="w-4 h-4" />
          <span>Filters</span>
          {activeFilterCount > 0 && (
            <span className="absolute -top-1 -right-1 w-5 h-5 inline-flex items-center justify-center rounded-full bg-gradient-primary text-[10px] text-white font-bold font-mono">
              {activeFilterCount}
            </span>
          )}
        </button>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className="card grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="text-sm font-semibold text-fg flex items-center gap-2 mb-2">
              <TagIcon className="w-4 h-4" /> Tags
            </label>
            <TagPicker
              selected={filters.tags}
              onChange={(t) => setFilters({ ...filters, tags: t })}
            />
          </div>
          <div>
            <label className="text-sm font-semibold text-fg flex items-center gap-2 mb-2">
              <Calendar className="w-4 h-4" /> Date range
            </label>
            <div className="flex flex-col sm:flex-row items-stretch gap-2">
              <input
                type="date"
                value={filters.dateFrom || ''}
                onChange={(e) => setFilters({ ...filters, dateFrom: e.target.value || null })}
                className="input"
              />
              <span className="text-muted-fg self-center text-sm">→</span>
              <input
                type="date"
                value={filters.dateTo || ''}
                onChange={(e) => setFilters({ ...filters, dateTo: e.target.value || null })}
                className="input"
              />
            </div>
          </div>
          <div>
            <label className="text-sm font-semibold text-fg mb-2 block">Type</label>
            <select
              value={filters.memoryType || ''}
              onChange={(e) => setFilters({ ...filters, memoryType: e.target.value || null })}
              className="input"
            >
              <option value="">All types</option>
              <option value="episodic">Episodic</option>
              <option value="semantic">Semantic</option>
              <option value="procedural">Procedural</option>
              <option value="fact">Fact</option>
            </select>
          </div>
          {activeFilterCount > 0 && (
            <div className="md:col-span-3">
              <button type="button" onClick={clearFilters} className="btn btn-ghost">
                Clear all filters
              </button>
            </div>
          )}
        </div>
      )}

      {/* Results */}
      <div>
        {debouncedQuery && (
          <p className="text-sm text-muted-fg mb-3">
            {isLoading ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Searching…
              </span>
            ) : (
              <>
                Found <strong className="text-fg font-semibold">{total}</strong> result
                {total !== 1 ? 's' : ''} for "<span className="text-fg">{debouncedQuery}</span>"
              </>
            )}
          </p>
        )}

        {!debouncedQuery && (
          <div className="card text-center py-12 flex flex-col items-center gap-3">
            <span className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-gradient-brand shadow-glow-accent">
              <Search className="w-6 h-6 text-white" />
            </span>
            <h3 className="text-lg font-bold font-display">Search your memories</h3>
            <p className="text-sm text-muted-fg max-w-sm">
              Keywords, questions, tags, or memory IDs — all work.
            </p>
            <div className="text-left mt-2 max-w-md mx-auto space-y-1 text-sm">
              <Tip code="#abc123" desc="Find memory by ID" />
              <Tip code="python api" desc="Keyword search" />
              <Tip code="What did I learn about…" desc="Ask a question" />
            </div>
          </div>
        )}

        {isLoading && debouncedQuery && (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <ResultSkeleton key={i} />
            ))}
          </div>
        )}

        {error && (
          <div className="card flex items-start gap-3 border-rose-500/40">
            <AlertCircle className="w-5 h-5 text-rose-500 mt-0.5" />
            <div>
              <p className="text-sm font-semibold">Search failed</p>
              <p className="text-sm text-muted-fg mt-1">{(error as Error).message}</p>
            </div>
          </div>
        )}

        {!isLoading && debouncedQuery && results.length > 0 && (
          <ul className="space-y-3">
            {results.map((r) => (
              <li key={r.memory.id}>
                <ResultCard memory={r.memory} score={r.score} query={debouncedQuery} />
              </li>
            ))}
          </ul>
        )}

        {!isLoading && debouncedQuery && results.length === 0 && (
          <div className="card text-center py-12">
            <Search className="w-12 h-12 text-muted-fg mx-auto mb-3" />
            <h3 className="font-bold text-fg">No results</h3>
            <p className="text-sm text-muted-fg mt-1">Try different keywords or clear filters.</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ----- helpers ----- */

function Tip({ code, desc }: { code: string; desc: string }) {
  return (
    <div className="flex items-center gap-2">
      <code className="px-1.5 py-0.5 rounded bg-surface/70 border border-border text-xs font-mono">
        {code}
      </code>
      <span className="text-muted-fg">{desc}</span>
    </div>
  );
}

function TagPicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (t: string[]) => void;
}) {
  const [input, setInput] = useState('');
  const { data: available = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: searchAPI.getAllTags,
  });
  const add = (t: string) => {
    const clean = t.trim();
    if (clean && !selected.includes(clean)) onChange([...selected, clean]);
    setInput('');
  };
  const remove = (t: string) => onChange(selected.filter((x) => x !== t));
  const suggestions = available
    .filter((t) => !selected.includes(t) && t.toLowerCase().includes(input.toLowerCase()))
    .slice(0, 5);
  return (
    <div>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selected.map((t) => (
            <span key={t} className="badge badge-primary inline-flex items-center gap-1">
              #{t}
              <button type="button" onClick={() => remove(t)} aria-label={`Remove ${t}`}>
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && input) {
              e.preventDefault();
              add(input);
            }
          }}
          placeholder="Add tag…"
          className="input"
        />
        {input && suggestions.length > 0 && (
          <ul className="absolute z-20 w-full mt-1 glass-strong rounded-md border border-border shadow-glass-md max-h-40 overflow-y-auto">
            {suggestions.map((t) => (
              <li key={t}>
                <button
                  type="button"
                  onClick={() => add(t)}
                  className="w-full text-left px-3 py-1.5 text-sm hover:bg-surface/70"
                >
                  #{t}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ResultCard({
  memory,
  score,
  query,
}: {
  memory: Memory;
  score: number;
  query: string;
}) {
  const highlight = (text: string) => {
    if (!query) return text;
    const re = new RegExp(`(${escapeRegExp(query)})`, 'gi');
    return text.split(re).map((p, i) =>
      re.test(p) ? (
        <mark key={i} className="bg-amber-400/40 text-fg rounded-sm px-0.5">
          {p}
        </mark>
      ) : (
        <span key={i}>{p}</span>
      ),
    );
  };
  const preview = memory.content.slice(0, 240);
  const pct = Math.round(score * 100);
  return (
    <Link
      to={`/memories/${memory.id}`}
      className="card block hover:shadow-glass-md hover:-translate-y-0.5 transition-all ease-spring"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0">
          <p className="text-[10px] font-mono text-muted-fg mb-1">#{memory.id}</p>
          <h3 className="text-lg font-semibold text-fg line-clamp-2">{highlight(memory.title)}</h3>
        </div>
        <div
          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-primary-500/15 text-primary-600 dark:text-primary-300 text-xs font-semibold shrink-0"
          title={`Relevance ${pct}%`}
        >
          <Sparkles className="w-3 h-3" />
          {pct}%
        </div>
      </div>
      <p className="text-sm text-muted-fg leading-relaxed line-clamp-3 mb-3">
        {highlight(preview)}
        {memory.content.length > 240 && '…'}
      </p>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          {memory.tags.slice(0, 4).map((t) => (
            <span key={t} className="badge badge-secondary text-[10px]">
              #{t}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-fg">
          <span className={cn('badge text-[10px] capitalize', getMemoryTypeColor(memory.memory_type))}>
            {memory.memory_type}
          </span>
          <span>{new Date(memory.created_at).toLocaleDateString()}</span>
        </div>
      </div>
    </Link>
  );
}

function ResultSkeleton() {
  return (
    <div className="card space-y-3">
      <div className="skeleton h-3 w-16" />
      <div className="skeleton h-6 w-3/4" />
      <div className="skeleton h-4 w-full" />
      <div className="skeleton h-4 w-5/6" />
      <div className="flex gap-2">
        <div className="skeleton h-4 w-10" />
        <div className="skeleton h-4 w-14" />
      </div>
    </div>
  );
}

function escapeRegExp(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
