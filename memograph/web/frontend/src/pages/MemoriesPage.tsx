import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { memoriesApi } from '@/lib/api'
import { Calendar, Tag, TrendingUp, ExternalLink } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export default function MemoriesPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['memories'],
    queryFn: () => memoriesApi.list({ page: 1, page_size: 20, sort_by: 'modified_at', order: 'desc' }),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-gray-500">Loading memories...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card bg-red-50 border-red-200">
        <p className="text-red-800">Error loading memories: {(error as Error).message}</p>
        <p className="text-sm text-red-600 mt-2">
          Make sure the backend server is running at http://localhost:8000
        </p>
      </div>
    )
  }

  const memories = data?.memories || []
  const total = data?.total || 0

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Memories</h1>
          <p className="text-gray-600 mt-1">
            {total} {total === 1 ? 'memory' : 'memories'} in your vault
          </p>
        </div>
      </div>

      {memories.length === 0 ? (
        <div className="card text-center py-12">
          <h3 className="text-lg font-medium text-gray-900 mb-2">No memories yet</h3>
          <p className="text-gray-600 mb-4">Get started by creating your first memory</p>
          <Link to="/memories/new" className="btn btn-primary inline-flex items-center">
            Create Memory
          </Link>
        </div>
      ) : (
        <div className="grid gap-4">
          {memories.map((memory) => (
            <Link
              key={memory.id}
              to={`/memories/${memory.id}`}
              className="card hover:shadow-md transition-shadow cursor-pointer"
            >
              <div className="flex justify-between items-start mb-3">
                <div className="flex-1">
                  <h3 className="text-xl font-semibold text-gray-900 mb-1">
                    {memory.title}
                  </h3>
                  <div className="flex items-center space-x-4 text-sm text-gray-500">
                    <span className="flex items-center">
                      <Calendar className="w-4 h-4 mr-1" />
                      {formatDistanceToNow(new Date(memory.modified_at), { addSuffix: true })}
                    </span>
                    <span className="badge badge-secondary">{memory.memory_type}</span>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <div className="flex items-center text-sm text-gray-600">
                    <TrendingUp className="w-4 h-4 mr-1" />
                    {(memory.salience * 100).toFixed(0)}%
                  </div>
                  <ExternalLink className="w-4 h-4 text-gray-400" />
                </div>
              </div>

              <p className="text-gray-700 line-clamp-2 mb-3">
                {memory.content.slice(0, 200)}
                {memory.content.length > 200 && '...'}
              </p>

              {memory.tags.length > 0 && (
                <div className="flex items-center flex-wrap gap-2">
                  <Tag className="w-4 h-4 text-gray-400" />
                  {memory.tags.map((tag) => (
                    <span key={tag} className="badge badge-primary">
                      #{tag}
                    </span>
                  ))}
                </div>
              )}

              {(memory.links.length > 0 || memory.backlinks.length > 0) && (
                <div className="mt-3 pt-3 border-t text-sm text-gray-500">
                  {memory.links.length > 0 && (
                    <span className="mr-4">→ {memory.links.length} outgoing links</span>
                  )}
                  {memory.backlinks.length > 0 && (
                    <span>← {memory.backlinks.length} backlinks</span>
                  )}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
