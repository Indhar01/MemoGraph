/**
 * TypeScript type definitions for MemoGraph Web UI
 * 
 * These types match the Pydantic models from the backend API
 * and provide type safety throughout the frontend application.
 */

// ============================================================================
// Memory Types
// ============================================================================

export type MemoryType = 'episodic' | 'semantic' | 'procedural' | 'fact';

export interface Memory {
  id: string;
  title: string;
  content: string;
  memory_type: MemoryType;
  tags: string[];
  salience: number;
  access_count: number;
  last_accessed: string;
  created_at: string;
  modified_at: string;
  links: string[];
  backlinks: string[];
  source_path: string | null;
}

export interface MemoryListResponse {
  memories: Memory[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface CreateMemoryRequest {
  title: string;
  content: string;
  memory_type: MemoryType;
  tags: string[];
  salience: number;
  meta?: Record<string, any>;
}

export interface UpdateMemoryRequest {
  content?: string;
  tags?: string[];
  salience?: number;
  meta?: Record<string, any>;
}

// ============================================================================
// Search Types
// ============================================================================

export interface SearchFilters {
  tags: string[];
  dateFrom: string | null;
  dateTo: string | null;
  memoryType: string | null;
  minSalience: number;
}

export type SearchStrategy = 'keyword' | 'semantic' | 'hybrid' | 'graph';

export interface SearchRequest {
  query: string;
  tags?: string[];
  memory_type?: string;
  min_salience?: number;
  depth?: number;
  top_k?: number;
  strategy?: SearchStrategy;
  boost_recent?: boolean;
}

export interface SearchResult {
  memory: Memory;
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  total: number;
  execution_time_ms: number;
}

export interface AutocompleteSuggestion {
  type: 'memory' | 'tag';
  value: string;
  id?: string;
  salience?: number;
}

// ============================================================================
// Graph Types
// ============================================================================

export interface GraphNode {
  id: string;
  title: string;
  memory_type: string;
  salience: number;
  tags: string[];
  link_count: number;
  backlink_count: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_nodes: number;
  total_edges: number;
}

export interface NeighborNode {
  id: string;
  title: string;
  memory_type: string;
  salience: number;
  tags: string[];
  link_count: number;
  backlink_count: number;
}

export interface NeighborsResponse {
  node_id: string;
  depth: number;
  neighbors: NeighborNode[];
  total: number;
}

// ============================================================================
// Analytics Types
// ============================================================================

export interface ConnectedNode {
  id: string;
  title: string;
  connections: number;
  salience: number;
}

export interface RecentActivity {
  id: string;
  title: string;
  memory_type: string;
  modified_at: string;
  salience: number;
}

export interface AnalyticsResponse {
  total_memories: number;
  memory_type_distribution: Record<string, number>;
  tag_distribution: Record<string, number>;
  avg_salience: number;
  total_links: number;
  most_connected_nodes: ConnectedNode[];
  recent_activity: RecentActivity[];
  salience_distribution: Record<string, number>;
}

// ============================================================================
// System Types
// ============================================================================

export interface HealthResponse {
  status: string;
  version: string;
  vault_path: string;
  total_memories: number;
  total_entities: number;
  gam_enabled: boolean;
  timestamp: number;
}

export interface ErrorResponse {
  error: string;
  detail?: string;
  code?: string;
}

// ============================================================================
// UI State Types
// ============================================================================

export interface GraphFilters {
  minSalience: number;
  tags: string[];
  memoryType: string | null;
  limit: number;
  focusNode: string | null;
}

export interface PaginationParams {
  page: number;
  page_size: number;
  sort_by?: 'salience' | 'created_at' | 'modified_at' | 'title';
  order?: 'asc' | 'desc';
}

export interface ToastNotification {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  message: string;
  duration?: number;
}