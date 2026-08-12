/**
 * CreateMemoryPage — glassy markdown editor with live preview,
 * tag autocomplete, salience slider, and localStorage autosave.
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import Markdown from 'markdown-to-jsx';
import {
  Save,
  X,
  Tag as TagIcon,
  Sparkles,
  AlertCircle,
  Eye,
  Edit3,
  CalendarDays,
  BookOpen,
  Settings2,
  Lightbulb,
  ArrowLeft,
} from 'lucide-react';

import { memoriesApi, searchAPI } from '../lib/api';
import type { CreateMemoryRequest, MemoryType } from '../types';
import { cn } from '../lib/utils';

const STORAGE_KEY = 'memograph-draft';

const MEMORY_TYPES: Array<{
  value: MemoryType;
  label: string;
  description: string;
  Icon: typeof CalendarDays;
  gradient: string;
}> = [
  {
    value: 'episodic',
    label: 'Episodic',
    description: 'Personal experiences and events',
    Icon: CalendarDays,
    gradient: 'bg-gradient-mem-episodic',
  },
  {
    value: 'semantic',
    label: 'Semantic',
    description: 'Facts and general knowledge',
    Icon: BookOpen,
    gradient: 'bg-gradient-mem-semantic',
  },
  {
    value: 'procedural',
    label: 'Procedural',
    description: 'How-to and processes',
    Icon: Settings2,
    gradient: 'bg-gradient-mem-procedural',
  },
  {
    value: 'fact',
    label: 'Fact',
    description: 'Discrete factual information',
    Icon: Lightbulb,
    gradient: 'bg-gradient-mem-fact',
  },
];

interface Draft {
  title: string;
  content: string;
  memoryType: MemoryType;
  tags: string[];
  salience: number;
}

export default function CreateMemoryPage() {
  const navigate = useNavigate();

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [memoryType, setMemoryType] = useState<MemoryType>('fact');
  const [tags, setTags] = useState<string[]>([]);
  const [salience, setSalience] = useState(0.5);
  const [tagInput, setTagInput] = useState('');
  const [showPreview, setShowPreview] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [draftRestored, setDraftRestored] = useState(false);

  // Load draft on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const draft = JSON.parse(raw) as Draft;
      if (draft.title || draft.content) {
        setTitle(draft.title || '');
        setContent(draft.content || '');
        setMemoryType(draft.memoryType || 'fact');
        setTags(draft.tags || []);
        setSalience(typeof draft.salience === 'number' ? draft.salience : 0.5);
        setDraftRestored(true);
      }
    } catch {
      /* ignore */
    }
  }, []);

  // Autosave (debounced)
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        const draft: Draft = { title, content, memoryType, tags, salience };
        if (title || content || tags.length) {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
        }
      } catch {
        /* quota */
      }
    }, 400);
    return () => clearTimeout(t);
  }, [title, content, memoryType, tags, salience]);

  const { data: availableTags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: searchAPI.getAllTags,
  });

  const createMutation = useMutation({
    mutationFn: (m: CreateMemoryRequest) => memoriesApi.create(m),
    onSuccess: (d) => {
      localStorage.removeItem(STORAGE_KEY);
      navigate(`/memories/${d.id}`);
    },
    onError: (err: any) => {
      setErrors({ submit: err.response?.data?.detail || err.message });
    },
  });

  const validate = useCallback((): boolean => {
    const e: Record<string, string> = {};
    if (!title.trim()) e.title = 'Title is required';
    else if (title.length > 500) e.title = 'Title must be under 500 characters';
    if (!content.trim()) e.content = 'Content is required';
    setErrors(e);
    return Object.keys(e).length === 0;
  }, [title, content]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    createMutation.mutate({
      title: title.trim(),
      content: content.trim(),
      memory_type: memoryType,
      tags,
      salience,
    });
  };

  const handleAddTag = (raw: string) => {
    const tag = raw.trim().replace(/^#/, '');
    if (tag && !tags.includes(tag)) setTags([...tags, tag]);
    setTagInput('');
  };
  const handleRemoveTag = (t: string) => setTags(tags.filter((x) => x !== t));
  const tagSuggestions = availableTags
    .filter((t) => t.toLowerCase().includes(tagInput.toLowerCase()) && !tags.includes(t))
    .slice(0, 5);

  const discardDraft = () => {
    localStorage.removeItem(STORAGE_KEY);
    setTitle('');
    setContent('');
    setMemoryType('fact');
    setTags([]);
    setSalience(0.5);
    setDraftRestored(false);
  };

  return (
    <div className="max-w-4xl mx-auto">
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-2 text-sm text-muted-fg hover:text-fg mb-4 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back
      </button>

      <header className="mb-6">
        <h1 className="text-3xl sm:text-4xl font-bold font-display text-fg">
          Capture a <span className="text-gradient-brand">new memory</span>
        </h1>
        <p className="text-muted-fg mt-1">
          Markdown supported. Saved to your vault on submit; drafted locally as you type.
        </p>
      </header>

      {draftRestored && (
        <div className="card flex items-start gap-3 border-primary-500/40 mb-6">
          <Sparkles className="w-5 h-5 text-primary-500 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-medium text-fg">Draft restored</p>
            <p className="text-xs text-muted-fg">
              We found an unsaved draft from your last session.
            </p>
          </div>
          <button type="button" onClick={discardDraft} className="btn btn-ghost btn-sm text-xs">
            Discard
          </button>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {errors.submit && (
          <div className="card border-rose-500/40 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-rose-500 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-fg">Failed to create memory</p>
              <p className="text-sm text-muted-fg mt-1">{errors.submit}</p>
            </div>
          </div>
        )}

        {/* Title */}
        <div>
          <label htmlFor="title" className="block text-sm font-semibold text-fg mb-2">
            Title <span className="text-rose-500">*</span>
          </label>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={validate}
            className={cn('input text-lg', errors.title && 'border-rose-500')}
            placeholder="Give it a memorable name…"
            maxLength={500}
            aria-invalid={!!errors.title}
            aria-describedby={errors.title ? 'title-error' : undefined}
          />
          {errors.title && (
            <p id="title-error" role="alert" className="text-xs text-rose-500 mt-1">
              {errors.title}
            </p>
          )}
        </div>

        {/* Content */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label htmlFor="content" className="text-sm font-semibold text-fg">
              Content <span className="text-rose-500">*</span>
            </label>
            <button
              type="button"
              onClick={() => setShowPreview((s) => !s)}
              className="btn btn-ghost btn-sm text-xs"
            >
              {showPreview ? (
                <>
                  <Edit3 className="w-3.5 h-3.5" /> Edit
                </>
              ) : (
                <>
                  <Eye className="w-3.5 h-3.5" /> Preview
                </>
              )}
            </button>
          </div>
          {showPreview ? (
            <div className="card min-h-[300px] markdown-content">
              {content ? <Markdown>{content}</Markdown> : (
                <p className="text-muted-fg italic">Nothing to preview yet…</p>
              )}
            </div>
          ) : (
            <textarea
              id="content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              onBlur={validate}
              rows={12}
              className={cn('input font-mono text-sm leading-relaxed py-3', errors.content && 'border-rose-500')}
              placeholder="Markdown supported: # heading, **bold**, *italic*, `code`, [[wikilinks]]…"
              aria-invalid={!!errors.content}
              aria-describedby={errors.content ? 'content-error' : undefined}
            />
          )}
          {errors.content && (
            <p id="content-error" role="alert" className="text-xs text-rose-500 mt-1">
              {errors.content}
            </p>
          )}
        </div>

        {/* Memory type cards */}
        <div>
          <span className="block text-sm font-semibold text-fg mb-2">Type</span>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {MEMORY_TYPES.map(({ value, label, description, Icon, gradient }) => {
              const active = memoryType === value;
              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => setMemoryType(value)}
                  aria-pressed={active}
                  className={cn(
                    'glass rounded-md p-3 text-left transition-all',
                    active
                      ? 'ring-2 ring-primary-500 shadow-glow-soft -translate-y-0.5'
                      : 'hover:-translate-y-0.5 hover:shadow-glass-md',
                  )}
                >
                  <span
                    className={cn(
                      'inline-flex items-center justify-center w-8 h-8 rounded-md text-white shadow-sm mb-2',
                      gradient,
                    )}
                  >
                    <Icon className="w-4 h-4" />
                  </span>
                  <div className="text-sm font-semibold text-fg">{label}</div>
                  <p className="text-[11px] text-muted-fg leading-tight mt-0.5">{description}</p>
                </button>
              );
            })}
          </div>
        </div>

        {/* Salience */}
        <div>
          <label htmlFor="salience" className="text-sm font-semibold text-fg flex items-center gap-2 mb-2">
            <Sparkles className="w-4 h-4 text-primary-500" />
            Importance{' '}
            <span className="font-mono text-xs text-muted-fg">
              {(salience * 100).toFixed(0)}%
            </span>
          </label>
          <input
            id="salience"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={salience}
            onChange={(e) => setSalience(parseFloat(e.target.value))}
            className="w-full h-2 rounded-full bg-border accent-primary-500 cursor-pointer"
          />
          <div className="flex justify-between text-[11px] text-muted-fg mt-1">
            <span>Low</span>
            <span>Medium</span>
            <span>High</span>
          </div>
        </div>

        {/* Tags */}
        <div>
          <label htmlFor="tag-input" className="text-sm font-semibold text-fg flex items-center gap-2 mb-2">
            <TagIcon className="w-4 h-4" />
            Tags
          </label>
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {tags.map((t) => (
                <span key={t} className="badge badge-primary inline-flex items-center gap-1">
                  #{t}
                  <button
                    type="button"
                    onClick={() => handleRemoveTag(t)}
                    aria-label={`Remove ${t}`}
                    className="hover:scale-110 transition-transform"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="relative">
            <input
              id="tag-input"
              type="text"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleAddTag(tagInput);
                } else if (e.key === 'Backspace' && !tagInput && tags.length) {
                  handleRemoveTag(tags[tags.length - 1]);
                }
              }}
              className="input"
              placeholder="Type to add tags… (press Enter)"
              aria-expanded={tagSuggestions.length > 0}
              aria-autocomplete="list"
            />
            {tagInput && tagSuggestions.length > 0 && (
              <ul
                role="listbox"
                className="absolute z-20 w-full mt-1 glass-strong rounded-md border border-border shadow-glass-md max-h-48 overflow-y-auto"
              >
                {tagSuggestions.map((t) => (
                  <li key={t}>
                    <button
                      type="button"
                      onClick={() => handleAddTag(t)}
                      className="w-full text-left px-3 py-2 text-sm hover:bg-surface/70 transition-colors"
                    >
                      #{t}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-6 border-t border-border">
          <button
            type="button"
            onClick={() => navigate('/memories')}
            disabled={createMutation.isPending}
            className="btn btn-secondary"
          >
            Cancel
          </button>
          <button type="submit" disabled={createMutation.isPending} className="btn btn-primary">
            {createMutation.isPending ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>Creating…</span>
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                <span>Create memory</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
