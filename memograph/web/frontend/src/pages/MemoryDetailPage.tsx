/**
 * MemoryDetailPage — detail view with a content/main column and a
 * metadata + AI side panel on `lg:` breakpoint.
 */

import { useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Markdown from 'markdown-to-jsx';
import {
  ArrowLeft,
  Edit,
  Trash2,
  Calendar,
  Clock,
  Sparkles,
  Tag,
  Link as LinkIcon,
  Eye,
  ExternalLink,
  AlertTriangle,
  Loader2,
} from 'lucide-react';

import { memoriesApi, graphAPI } from '../lib/api';
import LinkSuggestions from '../components/ai/LinkSuggestions';
import TagSuggestions from '../components/ai/TagSuggestions';
import {
  formatDate,
  formatRelativeTime,
  getMemoryTypeColor,
  getMemoryTypeDescription,
  getSalienceLevel,
  formatSalience,
  cn,
} from '../lib/utils';

export default function MemoryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const {
    data: memory,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['memory', id],
    queryFn: () => memoriesApi.get(id!),
    enabled: !!id,
  });

  const { data: neighborsData } = useQuery({
    queryKey: ['neighbors', id],
    queryFn: () => graphAPI.getNeighbors(id!, 1),
    enabled: !!id,
  });

  const deleteMutation = useMutation({
    mutationFn: () => memoriesApi.delete(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] });
      navigate('/memories');
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3 text-muted-fg">
          <Loader2 className="w-6 h-6 animate-spin text-primary-500" />
          <span>Loading memory…</span>
        </div>
      </div>
    );
  }

  if (error || !memory) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="card border border-rose-500/30">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-6 h-6 text-rose-500 mt-0.5" />
            <div>
              <h2 className="text-lg font-semibold text-fg">Memory not found</h2>
              <p className="text-muted-fg mt-1">
                {error ? (error as Error).message : `Memory with ID "${id}" could not be found.`}
              </p>
              <Link to="/memories" className="btn btn-ghost mt-4 px-0">
                <ArrowLeft className="w-4 h-4" />
                Back to Memories
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const neighbors = neighborsData?.neighbors || [];
  const salienceLevel = getSalienceLevel(memory.salience);
  const saliencePct = Math.round(memory.salience * 100);

  return (
    <div className="max-w-7xl mx-auto">
      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-sm text-muted-fg mb-4">
        <Link to="/memories" className="hover:text-fg transition-colors">
          Memories
        </Link>
        <span aria-hidden="true">/</span>
        <span className="text-fg font-medium truncate max-w-md">{memory.title}</span>
      </nav>

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4 mb-6">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <span
              className={`badge ${getMemoryTypeColor(memory.memory_type)} capitalize shrink-0`}
            >
              {memory.memory_type}
            </span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold font-display text-fg">{memory.title}</h1>
          <p className="text-sm text-muted-fg mt-1">
            {getMemoryTypeDescription(memory.memory_type)}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => navigate('/memories/new', { state: { memory } })}
            className="btn btn-secondary"
          >
            <Edit className="w-4 h-4" />
            <span>Edit</span>
          </button>

          {showDeleteConfirm ? (
            <>
              <button
                type="button"
                onClick={() => deleteMutation.mutate()}
                disabled={deleteMutation.isPending}
                className="btn btn-danger"
              >
                {deleteMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Deleting…</span>
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    <span>Confirm delete</span>
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(false)}
                className="btn btn-ghost"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(true)}
              className="btn btn-secondary text-rose-500 hover:text-rose-600"
            >
              <Trash2 className="w-4 h-4" />
              <span>Delete</span>
            </button>
          )}
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid lg:grid-cols-[1fr_320px] gap-6">
        {/* Main column */}
        <div className="space-y-6 min-w-0">
          {/* Tags */}
          {memory.tags.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <Tag className="w-4 h-4 text-muted-fg" />
              {memory.tags.map((tag) => (
                <Link
                  key={tag}
                  to={`/search?tags=${encodeURIComponent(tag)}`}
                  className="badge badge-primary hover:scale-105 transition-transform"
                >
                  #{tag}
                </Link>
              ))}
            </div>
          )}

          {/* Content */}
          <article className="card">
            <h2 className="text-lg font-semibold font-display text-fg mb-4">Content</h2>
            <div className="markdown-content">
              <Markdown>{memory.content}</Markdown>
            </div>
          </article>

          {/* Links + Backlinks */}
          {(memory.links.length > 0 || memory.backlinks.length > 0) && (
            <div className="grid md:grid-cols-2 gap-4">
              {memory.links.length > 0 && (
                <LinkList
                  title={`Links (${memory.links.length})`}
                  icon={<LinkIcon className="w-4 h-4" />}
                  ids={memory.links}
                />
              )}
              {memory.backlinks.length > 0 && (
                <LinkList
                  title={`Backlinks (${memory.backlinks.length})`}
                  icon={<LinkIcon className="w-4 h-4 -scale-x-100" />}
                  ids={memory.backlinks}
                />
              )}
            </div>
          )}

          {/* Related */}
          {neighbors.length > 0 && (
            <div className="card">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold font-display">Related memories</h2>
                <span className="text-xs text-muted-fg font-mono">{neighbors.length}</span>
              </div>
              <p className="text-sm text-muted-fg mb-4">
                Connected through the knowledge graph
              </p>
              <div className="grid md:grid-cols-2 gap-3">
                {neighbors.map((n) => (
                  <Link
                    key={n.id}
                    to={`/memories/${n.id}`}
                    className="glass rounded-md p-3 hover:shadow-glass-md hover:-translate-y-0.5 transition-all duration-200 ease-spring"
                  >
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <h3 className="font-medium text-fg line-clamp-1">{n.title}</h3>
                      <span
                        className={cn(
                          'badge text-[10px] capitalize',
                          getMemoryTypeColor(n.memory_type),
                        )}
                      >
                        {n.memory_type}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-muted-fg">
                      <span className="flex items-center gap-1">
                        <Sparkles className="w-3 h-3" />
                        {formatSalience(n.salience)}
                      </span>
                      <span className="flex items-center gap-1">
                        <LinkIcon className="w-3 h-3" />
                        {n.link_count + n.backlink_count}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <aside className="space-y-4 lg:sticky lg:top-20 self-start">
          <div className="card space-y-3">
            <div className="text-xs uppercase tracking-wider font-semibold text-muted-fg">
              Importance
            </div>
            <div className="flex items-center gap-2">
              <Sparkles className={cn('w-4 h-4', salienceLevel.color)} />
              <span className="text-2xl font-bold font-display">{saliencePct}%</span>
              <span className={cn('text-xs', salienceLevel.color)}>({salienceLevel.label})</span>
            </div>
            <div className="salience-bar">
              <span style={{ width: `${saliencePct}%` }} />
            </div>
          </div>

          <div className="card space-y-3">
            <div className="text-xs uppercase tracking-wider font-semibold text-muted-fg">
              Access
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Eye className="w-4 h-4 text-muted-fg" />
              <span className="font-mono">{memory.access_count}</span>
              <span className="text-muted-fg">accesses</span>
            </div>
            <p className="text-xs text-muted-fg">
              Last: {formatRelativeTime(memory.last_accessed)}
            </p>
          </div>

          <div className="card space-y-2 text-sm">
            <div className="text-xs uppercase tracking-wider font-semibold text-muted-fg">
              Timeline
            </div>
            <div className="flex items-center gap-2">
              <Calendar className="w-3.5 h-3.5 text-muted-fg" />
              <span>Created {formatDate(memory.created_at)}</span>
            </div>
            <div className="flex items-center gap-2">
              <Clock className="w-3.5 h-3.5 text-muted-fg" />
              <span>{formatRelativeTime(memory.modified_at)}</span>
            </div>
          </div>

          <TagSuggestions title={memory.title} content={memory.content} existingTags={memory.tags} />
          <LinkSuggestions
            title={memory.title}
            content={memory.content}
            noteId={memory.id}
            existingLinks={memory.links}
          />
        </aside>
      </div>

      <div className="mt-8 pt-6 border-t border-border">
        <Link
          to="/memories"
          className="inline-flex items-center gap-2 text-sm text-muted-fg hover:text-fg transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to all memories
        </Link>
      </div>
    </div>
  );
}

function LinkList({
  title,
  icon,
  ids,
}: {
  title: string;
  icon: React.ReactNode;
  ids: string[];
}) {
  return (
    <div className="card">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-fg mb-3">
        {icon}
        {title}
      </h3>
      <ul className="space-y-1">
        {ids.map((linkId) => (
          <li key={linkId}>
            <Link
              to={`/memories/${linkId}`}
              className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-surface/70 transition-colors group"
            >
              <ExternalLink className="w-3.5 h-3.5 text-muted-fg group-hover:text-primary-500" />
              <span className="text-sm font-mono text-fg truncate">{linkId}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
