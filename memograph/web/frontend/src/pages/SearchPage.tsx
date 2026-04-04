import { useState, useEffect } from 'react'
import { Search, Filter, X, Calendar, Tag, Loader2, Clock } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { searchAPI } from '../lib/api'
import { Memory, SearchFilters } from '../types'
import { useDebounce, useLocalStorage } from '../hooks'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<SearchFilters>({
    tags: [],
    dateFrom: null,
    dateTo: null,
    memoryType: null,
    minSalience: 0,
  })
  const [showFilters, setShowFilters] = useState(false)
  const [showSuggestions, setShowSuggestions] = useState(false)
  
  // Search history stored in localStorage
  const [searchHistory, setSearchHistory] = useLocalStorage<string[]>('memograph-search-history', [])
  
  // Debounce search query using custom hook
  const debouncedQuery = useDebounce(query, 300)

  // Fetch search results
  const { data, isLoading, error } = useQuery({
    queryKey: ['search', debouncedQuery, filters],
    queryFn: () => searchAPI.hybridSearch(debouncedQuery, filters),
    enabled: debouncedQuery.length > 0,
  })

  // Add to search history when search is performed
  useEffect(() => {
    if (debouncedQuery && debouncedQuery.length > 2) {
      setSearchHistory(prev => {
        const newHistory = [debouncedQuery, ...prev.filter(h => h !== debouncedQuery)].slice(0, 10)
        return newHistory
      })
    }
  }, [debouncedQuery, setSearchHistory])

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setQuery('')
        setShowSuggestions(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const results = data?.results || []
  const totalResults = data?.total || 0
  
  // Filter search history based on current query
  const filteredHistory = searchHistory
    .filter(h => h.toLowerCase().includes(query.toLowerCase()) && h !== query)
    .slice(0, 5)
  
  // Show suggestions when there's input and user is focused on input
  const shouldShowSuggestions = showSuggestions && query.length > 0 && (filteredHistory.length > 0)
  
  const handleSelectSuggestion = (suggestion: string) => {
    setQuery(suggestion)
    setShowSuggestions(false)
  }
  
  const clearHistory = () => {
    setSearchHistory([])
  }

  return (
    <div className="search-page">
      {/* Search Header */}
      <div className="search-header">
        <div className="search-bar-container">
          <div className="search-input-wrapper">
            <Search className="search-icon" size={20} />
            <input
              type="text"
              className="search-input"
              placeholder="Search memories... (try #id, keywords, or questions)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              autoFocus
            />
            {query && (
              <button
                className="clear-button"
                onClick={() => {
                  setQuery('')
                  setShowSuggestions(false)
                }}
                aria-label="Clear search"
              >
                <X size={16} />
              </button>
            )}
            
            {/* Search Suggestions Dropdown */}
            {shouldShowSuggestions && (
              <div className="search-suggestions">
                <div className="suggestions-header">
                  <div className="flex items-center gap-2">
                    <Clock size={14} />
                    <span>Recent Searches</span>
                  </div>
                  {searchHistory.length > 0 && (
                    <button
                      onClick={clearHistory}
                      className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300"
                    >
                      Clear
                    </button>
                  )}
                </div>
                <div className="suggestions-list">
                  {filteredHistory.map((item, index) => (
                    <button
                      key={index}
                      className="suggestion-item"
                      onClick={() => handleSelectSuggestion(item)}
                    >
                      <Clock size={14} />
                      <span>{item}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <button
            className={`filter-toggle ${showFilters ? 'active' : ''}`}
            onClick={() => setShowFilters(!showFilters)}
          >
            <Filter size={18} />
            Filters
            {Object.values(filters).some(v => v && (Array.isArray(v) ? v.length > 0 : v !== 0)) && (
              <span className="filter-badge"></span>
            )}
          </button>
        </div>

        {/* Filter Panel */}
        {showFilters && (
          <div className="filter-panel">
            <div className="filter-row">
              <label>
                <Tag size={16} />
                Tags
              </label>
              <TagFilter
                selected={filters.tags}
                onChange={(tags) => setFilters({ ...filters, tags })}
              />
            </div>

            <div className="filter-row">
              <label>
                <Calendar size={16} />
                Date Range
              </label>
              <div className="date-inputs">
                <input
                  type="date"
                  value={filters.dateFrom || ''}
                  onChange={(e) => setFilters({ ...filters, dateFrom: e.target.value })}
                  placeholder="From"
                />
                <span>to</span>
                <input
                  type="date"
                  value={filters.dateTo || ''}
                  onChange={(e) => setFilters({ ...filters, dateTo: e.target.value })}
                  placeholder="To"
                />
              </div>
            </div>

            <div className="filter-row">
              <label>Memory Type</label>
              <select
                value={filters.memoryType || ''}
                onChange={(e) => setFilters({ ...filters, memoryType: e.target.value || null })}
              >
                <option value="">All Types</option>
                <option value="episodic">Episodic</option>
                <option value="semantic">Semantic</option>
                <option value="procedural">Procedural</option>
                <option value="fact">Fact</option>
              </select>
            </div>

            <button
              className="clear-filters"
              onClick={() => setFilters({
                tags: [],
                dateFrom: null,
                dateTo: null,
                memoryType: null,
                minSalience: 0,
              })}
            >
              Clear All Filters
            </button>
          </div>
        )}
      </div>

      {/* Results Section */}
      <div className="search-results">
        {/* Status Bar */}
        {debouncedQuery && (
          <div className="results-status">
            {isLoading ? (
              <span className="loading">
                <Loader2 className="spin" size={16} />
                Searching...
              </span>
            ) : (
              <span>
                Found <strong>{totalResults}</strong> result{totalResults !== 1 ? 's' : ''} for "{debouncedQuery}"
              </span>
            )}
          </div>
        )}

        {/* Empty State */}
        {!debouncedQuery && (
          <div className="empty-state">
            <Search size={48} />
            <h3>Search your memories</h3>
            <p>Try searching by keywords, #id, tags, or ask questions</p>
            <div className="search-tips">
              <h4>Search Tips:</h4>
              <ul>
                <li><code>#123</code> - Find memory by ID</li>
                <li><code>python api</code> - Keyword search</li>
                <li><code>What did I learn about...</code> - Ask questions</li>
                <li>Use filters to narrow results by tags, date, or type</li>
              </ul>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoading && debouncedQuery && (
          <div className="results-list">
            {[...Array(5)].map((_, i) => (
              <ResultCardSkeleton key={i} />
            ))}
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="error-state">
            <div className="error-icon">⚠️</div>
            <h3>Search failed</h3>
            <p>{(error as Error).message}</p>
            <button onClick={() => window.location.reload()}>Try Again</button>
          </div>
        )}

        {/* Results List */}
        {!isLoading && debouncedQuery && results.length > 0 && (
          <div className="results-list">
            {results.map((result) => (
              <ResultCard
                key={result.memory.id}
                memory={result.memory}
                score={result.score}
                searchQuery={debouncedQuery}
              />
            ))}
          </div>
        )}

        {/* No Results */}
        {!isLoading && debouncedQuery && results.length === 0 && (
          <div className="no-results">
            <Search size={48} />
            <h3>No results found</h3>
            <p>Try different keywords, adjust filters, or check spelling</p>
          </div>
        )}
      </div>
    </div>
  )
}

// Tag Filter Component
function TagFilter({ selected, onChange }: { selected: string[], onChange: (tags: string[]) => void }) {
  const [input, setInput] = useState('')
  const { data: availableTags } = useQuery({
    queryKey: ['tags'],
    queryFn: searchAPI.getAllTags,
  })

  const handleAdd = (tag: string) => {
    if (tag && !selected.includes(tag)) {
      onChange([...selected, tag])
      setInput('')
    }
  }

  const handleRemove = (tag: string) => {
    onChange(selected.filter(t => t !== tag))
  }

  const filteredSuggestions = (availableTags || [])
    .filter(tag => !selected.includes(tag) && tag.toLowerCase().includes(input.toLowerCase()))
    .slice(0, 5)

  return (
    <div className="tag-filter">
      <div className="selected-tags">
        {selected.map(tag => (
          <span key={tag} className="tag">
            {tag}
            <button onClick={() => handleRemove(tag)}>
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      <div className="tag-input-container">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && input) {
              handleAdd(input)
            }
          }}
          placeholder="Add tag..."
        />
        {input && filteredSuggestions.length > 0 && (
          <div className="tag-suggestions">
            {filteredSuggestions.map(tag => (
              <button key={tag} onClick={() => handleAdd(tag)}>
                {tag}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Result Card Component
function ResultCard({ memory, score, searchQuery }: { memory: Memory, score: number, searchQuery: string }) {
  const navigate = (path: string) => {
    window.location.href = path
  }

  const highlightText = (text: string, query: string) => {
    if (!query) return text
    const regex = new RegExp(`(${query})`, 'gi')
    const parts = text.split(regex)
    return parts.map((part, i) =>
      regex.test(part) ? <mark key={i}>{part}</mark> : part
    )
  }

  const preview = memory.content.substring(0, 300)

  return (
    <div className="result-card" onClick={() => navigate(`/graph?focus=${memory.id}`)}>
      <div className="result-header">
        <div className="result-title">
          <span className="memory-id">#{memory.id}</span>
          <h3>{highlightText(memory.title, searchQuery)}</h3>
        </div>
        <div className="result-score" title={`Relevance score: ${(score * 100).toFixed(1)}%`}>
          {(score * 100).toFixed(0)}%
        </div>
      </div>

      <div className="result-content">
        {highlightText(preview, searchQuery)}
        {memory.content.length > 300 && '...'}
      </div>

      <div className="result-footer">
        <div className="result-tags">
          {memory.tags.map(tag => (
            <span key={tag} className="tag">{tag}</span>
          ))}
        </div>
        <div className="result-meta">
          <span className="memory-type">{memory.memory_type}</span>
          <span className="memory-date">{new Date(memory.created_at).toLocaleDateString()}</span>
        </div>
      </div>
    </div>
  )
}

// Skeleton Loading Component
function ResultCardSkeleton() {
  return (
    <div className="result-card skeleton">
      <div className="skeleton-header">
        <div className="skeleton-title"></div>
        <div className="skeleton-score"></div>
      </div>
      <div className="skeleton-content"></div>
      <div className="skeleton-footer"></div>
    </div>
  )
}
