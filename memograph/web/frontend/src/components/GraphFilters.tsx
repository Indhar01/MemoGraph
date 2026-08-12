import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, X, Search, Filter, Sparkles } from 'lucide-react';
import { MEMORY_TYPE_HEX } from '../lib/utils';

export interface GraphFilterState {
  minSalience: number;
  maxSalience: number;
  tags: string[];
  memoryTypes: string[];
  limit: number;
  focusNode: string;
}

interface GraphFiltersProps {
  filters: GraphFilterState;
  availableTags: string[];
  onFiltersChange: (filters: GraphFilterState) => void;
  onReset: () => void;
  isLoadingTags?: boolean;
}

const MEMORY_TYPES = [
  { value: 'episodic', label: 'Episodic' },
  { value: 'semantic', label: 'Semantic' },
  { value: 'procedural', label: 'Procedural' },
  { value: 'fact', label: 'Fact' },
] as const;

const LIMIT_OPTIONS = [50, 100, 200, 500];

export default function GraphFilters({
  filters,
  availableTags,
  onFiltersChange,
  onReset,
  isLoadingTags = false,
}: GraphFiltersProps) {
  const [expanded, setExpanded] = useState(true);
  const [tagSearch, setTagSearch] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);

  const filtered = availableTags.filter(
    (t) => t.toLowerCase().includes(tagSearch.toLowerCase()) && !filters.tags.includes(t),
  );

  const update = <K extends keyof GraphFilterState>(key: K, value: GraphFilterState[K]) =>
    onFiltersChange({ ...filters, [key]: value });

  const toggleType = (t: string) => {
    const next = filters.memoryTypes.includes(t)
      ? filters.memoryTypes.filter((x) => x !== t)
      : [...filters.memoryTypes, t];
    update('memoryTypes', next);
  };

  const addTag = (t: string) => {
    if (!filters.tags.includes(t)) update('tags', [...filters.tags, t]);
    setTagSearch('');
    setShowDropdown(false);
  };
  const removeTag = (t: string) => update('tags', filters.tags.filter((x) => x !== t));

  const hasActive =
    filters.minSalience > 0 ||
    filters.maxSalience < 1 ||
    filters.tags.length > 0 ||
    filters.memoryTypes.length > 0 ||
    filters.limit !== 200 ||
    filters.focusNode !== '';

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest('.tag-picker')) setShowDropdown(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  return (
    <aside className="card">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between"
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-primary-500" />
          <span className="text-sm font-semibold font-display text-fg">Filters</span>
          {hasActive && (
            <span className="badge badge-accent text-[10px]">Active</span>
          )}
        </span>
        <span className="flex items-center gap-2">
          {hasActive && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                onReset();
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.stopPropagation();
                  onReset();
                }
              }}
              className="text-xs text-muted-fg hover:text-fg transition-colors"
            >
              Reset
            </span>
          )}
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-muted-fg" />
          ) : (
            <ChevronDown className="w-4 h-4 text-muted-fg" />
          )}
        </span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-5 pt-4 border-t border-border">
          {/* Salience range */}
          <div>
            <label className="flex items-center gap-2 text-xs uppercase tracking-wider font-semibold text-muted-fg mb-2">
              <Sparkles className="w-3.5 h-3.5" />
              Salience range
            </label>
            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-[11px] text-muted-fg mb-1">
                  <span>Min</span>
                  <span className="font-mono">{(filters.minSalience * 100).toFixed(0)}%</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={filters.minSalience}
                  onChange={(e) => update('minSalience', parseFloat(e.target.value))}
                  className="w-full h-1.5 rounded-full bg-border accent-primary-500 cursor-pointer"
                  aria-label="Minimum salience"
                />
              </div>
              <div>
                <div className="flex justify-between text-[11px] text-muted-fg mb-1">
                  <span>Max</span>
                  <span className="font-mono">{(filters.maxSalience * 100).toFixed(0)}%</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={filters.maxSalience}
                  onChange={(e) => update('maxSalience', parseFloat(e.target.value))}
                  className="w-full h-1.5 rounded-full bg-border accent-primary-500 cursor-pointer"
                  aria-label="Maximum salience"
                />
              </div>
            </div>
          </div>

          {/* Memory types */}
          <div>
            <label className="block text-xs uppercase tracking-wider font-semibold text-muted-fg mb-2">
              Memory types
            </label>
            <div className="grid grid-cols-2 gap-1.5">
              {MEMORY_TYPES.map(({ value, label }) => {
                const selected = filters.memoryTypes.includes(value);
                const swatch = MEMORY_TYPE_HEX[value];
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => toggleType(value)}
                    aria-pressed={selected}
                    className={`flex items-center gap-2 px-2 py-1.5 rounded-md text-xs transition-all ${
                      selected
                        ? 'glass-strong ring-1 ring-primary-500/50 text-fg'
                        : 'glass text-muted-fg hover:text-fg'
                    }`}
                  >
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0"
                      style={{
                        background: `linear-gradient(135deg, ${swatch.from}, ${swatch.to})`,
                      }}
                    />
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-xs uppercase tracking-wider font-semibold text-muted-fg mb-2">
              Tags {isLoadingTags && <span className="ml-1 normal-case">(loading…)</span>}
            </label>
            {filters.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {filters.tags.map((t) => (
                  <span key={t} className="badge badge-primary inline-flex items-center gap-1 text-[10px]">
                    #{t}
                    <button type="button" onClick={() => removeTag(t)} aria-label={`Remove ${t}`}>
                      <X className="w-2.5 h-2.5" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="tag-picker relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-fg" />
              <input
                type="text"
                value={tagSearch}
                onChange={(e) => {
                  setTagSearch(e.target.value);
                  setShowDropdown(true);
                }}
                onFocus={() => setShowDropdown(true)}
                placeholder="Search tags…"
                className="input pl-9 py-1.5 text-sm"
                disabled={isLoadingTags}
              />
              {showDropdown && tagSearch && filtered.length > 0 && (
                <ul className="absolute z-20 w-full mt-1 glass-strong rounded-md border border-border shadow-glass-md max-h-48 overflow-y-auto">
                  {filtered.slice(0, 8).map((t) => (
                    <li key={t}>
                      <button
                        type="button"
                        onClick={() => addTag(t)}
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

          {/* Node limit */}
          <div>
            <label htmlFor="node-limit" className="block text-xs uppercase tracking-wider font-semibold text-muted-fg mb-2">
              Node limit
            </label>
            <select
              id="node-limit"
              value={filters.limit}
              onChange={(e) => update('limit', parseInt(e.target.value))}
              className="input py-1.5 text-sm"
            >
              {LIMIT_OPTIONS.map((l) => (
                <option key={l} value={l}>
                  {l} nodes
                </option>
              ))}
            </select>
          </div>

          {/* Focus node */}
          <div>
            <label htmlFor="focus-node" className="block text-xs uppercase tracking-wider font-semibold text-muted-fg mb-2">
              Focus node ID
            </label>
            <input
              id="focus-node"
              type="text"
              value={filters.focusNode}
              onChange={(e) => update('focusNode', e.target.value)}
              placeholder="Node ID…"
              className="input py-1.5 text-sm font-mono"
            />
          </div>
        </div>
      )}
    </aside>
  );
}
