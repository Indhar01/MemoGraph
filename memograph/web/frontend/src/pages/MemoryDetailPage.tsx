/**
 * MemoryDetailPage - Detailed view of a single memory
 * 
 * Features:
 * - Full markdown rendering of content
 * - Metadata display (type, salience, dates, tags)
 * - Links and backlinks sections
 * - Edit/delete actions
 * - Related memories via graph neighbors
 * - Navigation breadcrumbs
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
  TrendingUp,
  Tag,
  Link as LinkIcon,
  Eye,
  ExternalLink,
  AlertTriangle,
  Loader2,
} from 'lucide-react';

import { memoriesApi, graphAPI } from '../lib/api';
import {
  formatDate,
  formatRelativeTime,
  getMemoryTypeColor,
  getMemoryTypeIcon,
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
  
  // Fetch memory data
  const { data: memory, isLoading, error } = useQuery({
    queryKey: ['memory', id],
    queryFn: () => memoriesApi.get(id!),
    enabled: !!id,
  });
  
  // Fetch related memories (neighbors)
  const { data: neighborsData } = useQuery({
    queryKey: ['neighbors', id],
    queryFn: () => graphAPI.getNeighbors(id!, 1),
    enabled: !!id,
  });
  
  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: () => memoriesApi.delete(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] });
      navigate('/memories');
    },
  });
  
  const handleDelete = () => {
    if (showDeleteConfirm) {
      deleteMutation.mutate();
    } else {
      setShowDeleteConfirm(true);
    }
  };
  
  const handleEdit = () => {
    // For now, navigate back to create page (could be enhanced with edit mode)
    navigate(`/memories/new`, { state: { memory } });
  };
  
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center space-x-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary-600" />
          <span className="text-gray-600">Loading memory...</span>
        </div>
      </div>
    );
  }
  
  if (error || !memory) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <div className="flex items-start space-x-3">
            <AlertTriangle className="w-6 h-6 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <h2 className="text-lg font-semibold text-red-900">Memory not found</h2>
              <p className="text-red-700 mt-1">
                {error ? (error as Error).message : `Memory with ID "${id}" could not be found.`}
              </p>
              <Link
                to="/memories"
                className="inline-flex items-center space-x-2 mt-4 text-red-800 hover:text-red-900 font-medium"
              >
                <ArrowLeft className="w-4 h-4" />
                <span>Back to Memories</span>
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }
  
  const neighbors = neighborsData?.neighbors || [];
  const salienceLevel = getSalienceLevel(memory.salience);
  
  return (
    <div className="max-w-5xl mx-auto">
      {/* Breadcrumbs */}
      <nav className="flex items-center space-x-2 text-sm text-gray-600 mb-6">
        <Link to="/memories" className="hover:text-gray-900">
          Memories
        </Link>
        <span>/</span>
        <span className="text-gray-900 font-medium truncate max-w-md">
          {memory.title}
        </span>
      </nav>
      
      {/* Header with Actions */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex-1">
          <div className="flex items-center space-x-3 mb-2">
            <span className="text-2xl">{getMemoryTypeIcon(memory.memory_type)}</span>
            <h1 className="text-3xl font-bold text-gray-900">{memory.title}</h1>
          </div>
          <p className="text-gray-600">{getMemoryTypeDescription(memory.memory_type)}</p>
        </div>
        
        <div className="flex items-center space-x-2">
          <button
            onClick={handleEdit}
            className="flex items-center space-x-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <Edit className="w-4 h-4" />
            <span>Edit</span>
          </button>
          
          {showDeleteConfirm ? (
            <div className="flex items-center space-x-2">
              <button
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
              >
                {deleteMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Deleting...</span>
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    <span>Confirm Delete</span>
                  </>
                )}
              </button>
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="px-4 py-2 text-gray-600 hover:text-gray-900"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="flex items-center space-x-2 px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              <span>Delete</span>
            </button>
          )}
        </div>
      </div>
      
      {/* Metadata Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        {/* Memory Type */}
        <div className="bg-white border rounded-lg p-4">
          <div className="text-xs text-gray-500 mb-1">Type</div>
          <span className={cn('inline-block px-3 py-1 rounded-full text-sm font-medium', getMemoryTypeColor(memory.memory_type))}>
            {memory.memory_type}
          </span>
        </div>
        
        {/* Salience */}
        <div className="bg-white border rounded-lg p-4">
          <div className="text-xs text-gray-500 mb-1">Importance</div>
          <div className="flex items-center space-x-2">
            <TrendingUp className={cn('w-4 h-4', salienceLevel.color)} />
            <span className="text-lg font-semibold">{formatSalience(memory.salience)}</span>
            <span className={cn('text-xs', salienceLevel.color)}>({salienceLevel.label})</span>
          </div>
        </div>
        
        {/* Access Count */}
        <div className="bg-white border rounded-lg p-4">
          <div className="text-xs text-gray-500 mb-1">Accessed</div>
          <div className="flex items-center space-x-2">
            <Eye className="w-4 h-4 text-gray-400" />
            <span className="text-lg font-semibold">{memory.access_count} times</span>
          </div>
          <div className="text-xs text-gray-500 mt-1">
            Last: {formatRelativeTime(memory.last_accessed)}
          </div>
        </div>
        
        {/* Dates */}
        <div className="bg-white border rounded-lg p-4">
          <div className="text-xs text-gray-500 mb-1">Dates</div>
          <div className="space-y-1">
            <div className="flex items-center space-x-2 text-sm">
              <Calendar className="w-3 h-3 text-gray-400" />
              <span className="text-gray-700">{formatDate(memory.created_at)}</span>
            </div>
            <div className="flex items-center space-x-2 text-sm">
              <Clock className="w-3 h-3 text-gray-400" />
              <span className="text-gray-700">{formatRelativeTime(memory.modified_at)}</span>
            </div>
          </div>
        </div>
      </div>
      
      {/* Tags */}
      {memory.tags.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center space-x-2 mb-3">
            <Tag className="w-4 h-4 text-gray-500" />
            <h2 className="text-lg font-semibold text-gray-900">Tags</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {memory.tags.map((tag: string) => (
              <Link
                key={tag}
                to={`/search?tags=${encodeURIComponent(tag)}`}
                className="inline-flex items-center px-3 py-1 bg-primary-100 text-primary-800 rounded-full text-sm hover:bg-primary-200 transition-colors"
              >
                #{tag}
              </Link>
            ))}
          </div>
        </div>
      )}
      
      {/* Content */}
      <div className="bg-white border rounded-lg p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Content</h2>
        <div className="prose prose-sm max-w-none">
          <Markdown>{memory.content}</Markdown>
        </div>
      </div>
      
      {/* Links Section */}
      {(memory.links.length > 0 || memory.backlinks.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          {/* Outgoing Links */}
          {memory.links.length > 0 && (
            <div className="bg-white border rounded-lg p-6">
              <div className="flex items-center space-x-2 mb-4">
                <LinkIcon className="w-5 h-5 text-gray-500" />
                <h2 className="text-lg font-semibold text-gray-900">
                  Links ({memory.links.length})
                </h2>
              </div>
              <div className="space-y-2">
                {memory.links.map((linkId: string) => (
                  <Link
                    key={linkId}
                    to={`/memories/${linkId}`}
                    className="flex items-center space-x-2 p-2 rounded hover:bg-gray-50 transition-colors group"
                  >
                    <ExternalLink className="w-4 h-4 text-gray-400 group-hover:text-primary-600" />
                    <span className="text-gray-700 group-hover:text-primary-600 font-medium">
                      {linkId}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
          
          {/* Backlinks */}
          {memory.backlinks.length > 0 && (
            <div className="bg-white border rounded-lg p-6">
              <div className="flex items-center space-x-2 mb-4">
                <LinkIcon className="w-5 h-5 text-gray-500 transform rotate-180" />
                <h2 className="text-lg font-semibold text-gray-900">
                  Backlinks ({memory.backlinks.length})
                </h2>
              </div>
              <div className="space-y-2">
                {memory.backlinks.map((backlinkId: string) => (
                  <Link
                    key={backlinkId}
                    to={`/memories/${backlinkId}`}
                    className="flex items-center space-x-2 p-2 rounded hover:bg-gray-50 transition-colors group"
                  >
                    <ExternalLink className="w-4 h-4 text-gray-400 group-hover:text-primary-600" />
                    <span className="text-gray-700 group-hover:text-primary-600 font-medium">
                      {backlinkId}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      
      {/* Related Memories (Graph Neighbors) */}
      {neighbors.length > 0 && (
        <div className="bg-white border rounded-lg p-6">
          <div className="flex items-center space-x-2 mb-4">
            <ExternalLink className="w-5 h-5 text-gray-500" />
            <h2 className="text-lg font-semibold text-gray-900">
              Related Memories ({neighbors.length})
            </h2>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Memories connected through the knowledge graph
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {neighbors.map((neighbor: any) => (
              <Link
                key={neighbor.id}
                to={`/memories/${neighbor.id}`}
                className="border rounded-lg p-4 hover:border-primary-300 hover:bg-primary-50 transition-colors group"
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="font-medium text-gray-900 group-hover:text-primary-700">
                    {neighbor.title}
                  </h3>
                  <span className={cn('text-xs px-2 py-1 rounded', getMemoryTypeColor(neighbor.memory_type))}>
                    {neighbor.memory_type}
                  </span>
                </div>
                <div className="flex items-center space-x-4 text-xs text-gray-500">
                  <span className="flex items-center">
                    <TrendingUp className="w-3 h-3 mr-1" />
                    {formatSalience(neighbor.salience)}
                  </span>
                  <span className="flex items-center">
                    <LinkIcon className="w-3 h-3 mr-1" />
                    {neighbor.link_count + neighbor.backlink_count} connections
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
      
      {/* Back to List Button */}
      <div className="mt-8 pt-6 border-t">
        <Link
          to="/memories"
          className="inline-flex items-center space-x-2 text-gray-600 hover:text-gray-900"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to all memories</span>
        </Link>
      </div>
    </div>
  );
}
