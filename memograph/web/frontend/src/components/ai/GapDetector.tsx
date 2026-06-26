
/**
 * GapDetector - AI-powered knowledge gap detection component
 *
 * Features:
 * - Display knowledge gaps grouped by type
 * - Visual severity indicators
 * - Actionable suggestions
 * - Filter by gap type
 * - Statistics overview
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Filter,
  Sparkles,
  TrendingUp,
  FileQuestion,
  FileX,
  Link2Off,
  FileWarning,
  CheckCircle,
  XCircle
} from 'lucide-react';
import { aiAPI } from '../../lib/api';
import type { GapType } from '../../types';

interface GapDetectorProps {
  minSeverity?: number;
  maxGaps?: number;
  autoLoad?: boolean;
}

export default function GapDetector({
  minSeverity = 0.3,
  maxGaps = 20,
  autoLoad = false,
}: GapDetectorProps) {
  const [selectedFilter, setSelectedFilter] = useState<GapType | 'all'>('all');
  const [severityFilter, setSeverityFilter] = useState<number>(minSeverity);

  // Fetch gaps
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['gaps', severityFilter, maxGaps],
    queryFn: () => aiAPI.detectGaps({ min_severity: severityFilter, max_gaps: maxGaps }),
    enabled: autoLoad,
  });

  const getGapIcon = (gapType: GapType) => {
    switch (gapType) {
      case 'missing_topic':
        return FileQuestion;
      case 'weak_coverage':
        return FileWarning;
      case 'isolated_note':
        return FileX;
      case 'missing_link':
        return Link2Off;
      default:
        return AlertTriangle;
    }
  };

  const getGapColor = (gapType: GapType): string => {
    switch (gapType) {
      case 'missing_topic':
        return 'text-red-600 dark:text-red-400';
      case 'weak_coverage':
        return 'text-yellow-600 dark:text-yellow-400';
      case 'isolated_note':
        return 'text-orange-600 dark:text-orange-400';
      case 'missing_link':
        return 'text-blue-600 dark:text-blue-400';
      default:
        return 'text-gray-600 dark:text-gray-400';
    }
  };

  const getSeverityColor = (severity: number): string => {
    if (severity >= 0.7) return 'bg-red-500';
    if (severity >= 0.5) return 'bg-orange-500';
    if (severity >= 0.3) return 'bg-yellow-500';
    return 'bg-gray-400';
  };

  const getSeverityLabel = (severity: number): string => {
    if (severity >= 0.7) return 'Critical';
    if (severity >= 0.5) return 'High';
    if (severity >= 0.3) return 'Medium';
    return 'Low';
  };

  const getGapTypeLabel = (gapType: GapType): string => {
    switch (gapType) {
      case 'missing_topic':
        return 'Missing Topic';
      case 'weak_coverage':
        return 'Weak Coverage';
      case 'isolated_note':
        return 'Isolated Note';
      case 'missing_link':
        return 'Missing Link';
      default:
        return gapType;
    }
  };

  // Filter gaps by selected type
  const filteredGaps = data?.gaps.filter(gap =>
    selectedFilter === 'all' || gap.gap_type === selectedFilter
  ) || [];

  const gapTypes: Array<{ value: GapType | 'all', label: string }> = [
    { value: 'all', label: 'All Types' },
    { value: 'missing_topic', label: 'Missing Topics' },
    { value: 'weak_coverage', label: 'Weak Coverage' },
    { value: 'isolated_note', label: 'Isolated Notes' },
    { value: 'missing_link', label: 'Missing Links' },
  ];

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-2">
          <Sparkles className="w-5 h-5 text-primary-600 dark:text-primary-400" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Knowledge Gap Detection
          </h3>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isLoading}
          className="btn btn-sm btn-primary flex items-center space-x-2"
        >
          {isLoading ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              <span>Analyzing...</span>
            </>
          ) : (
            <>
              <AlertTriangle className="w-4 h-4" />
              <span>Detect Gaps</span>
            </>
          )}
        </button>
      </div>

      {/* Error State */}
      {isError && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-start space-x-3 mb-4">
          <XCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-medium text-red-800 dark:text-red-200">
              Failed to detect gaps
            </h4>
            <p className="text-sm text-red-700 dark:text-red-300 mt-1">
              {error instanceof Error ? error.message : 'An error occurred'}
            </p>
          </div>
        </div>
      )}

      {/* Empty State */}
      {!data && !isLoading && !isError && (
        <div className="text-center py-8">
          <AlertTriangle className="w-12 h-12 text-gray-400 dark:text-gray-600 mx-auto mb-3" />
          <p className="text-gray-600 dark:text-gray-400 text-sm">
            Click "Detect Gaps" to analyze your knowledge base
          </p>
          <p className="text-gray-500 dark:text-gray-500 text-xs mt-1">
            Identify missing topics, weak coverage, and isolated notes
          </p>
        </div>
      )}

      {/* Statistics Overview */}
      {data && data.gaps.length > 0 && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-4">
              <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                {data.total}
              </div>
              <div className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                Total Gaps
              </div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-4">
              <div className="text-2xl font-bold text-orange-600 dark:text-orange-400">
                {(data.avg_severity * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                Avg Severity
              </div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-4">
              <div className="text-2xl font-bold text-red-600 dark:text-red-400">
                {data.gap_types['missing_topic'] || 0}
              </div>
              <div className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                Missing Topics
              </div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-4">
              <div className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">
                {data.gap_types['weak_coverage'] || 0}
              </div>
              <div className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                Weak Coverage
              </div>
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center space-x-4 mb-4">
            <div className="flex items-center space-x-2">
              <Filter className="w-4 h-4 text-gray-600 dark:text-gray-400" />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Filter:
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {gapTypes.map((type) => (
                <button
                  key={type.value}
                  onClick={() => setSelectedFilter(type.value)}
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                    selectedFilter === type.value
                      ? 'bg-primary-600 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
                  }`}
                >
                  {type.label}
                  {type.value !== 'all' && data.gap_types[type.value as GapType] && (
                    <span className="ml-1">({data.gap_types[type.value as GapType]})</span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Severity Filter */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              <div className="flex items-center space-x-2">
                <TrendingUp className="w-4 h-4" />
                <span>Minimum Severity: {(severityFilter * 100).toFixed(0)}%</span>
              </div>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={severityFilter}
              onChange={(e) => setSeverityFilter(parseFloat(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-gray-500 dark:text-gray-500 mt-1">
              <span>0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>
          </div>

          {/* Gaps List */}
          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm text-gray-600 dark:text-gray-400 mb-2">
              <span>{filteredGaps.length} gaps shown</span>
              <span>Sorted by severity</span>
            </div>

            {filteredGaps.map((gap, index) => {
              const Icon = getGapIcon(gap.gap_type);

              return (
                <div
                  key={index}
                  className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 hover:border-primary-300 dark:hover:border-primary-700 transition-all"
                >
                  {/* Gap Header */}
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-start space-x-3 flex-1">
                      <div className={`p-2 rounded-lg bg-gray-100 dark:bg-gray-900 ${getGapColor(gap.gap_type)}`}>
                        <Icon className="w-5 h-5" />
                      </div>
                      <div className="flex-1">
                        <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-1">
                          {gap.title}
                        </h4>
                        <div className="flex items-center space-x-2 mb-2">
                          <span className="inline-flex items-center px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded text-xs">
                            {getGapTypeLabel(gap.gap_type)}
                          </span>
                          <span
                            className={`inline-flex items-center px-2 py-1 rounded text-xs text-white ${
                              gap.severity >= 0.7
                                ? 'bg-red-600'
                                : gap.severity >= 0.5
                                ? 'bg-orange-600'
                                : 'bg-yellow-600'
                            }`}
                          >
                            {getSeverityLabel(gap.severity)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Severity Bar */}
                  <div className="mb-3">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs text-gray-600 dark:text-gray-400 min-w-[4rem]">
                        Severity:
                      </span>
                      <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-2 overflow-hidden">
                        <div
                          className={`h-full ${getSeverityColor(gap.severity)} transition-all`}
                          style={{ width: `${gap.severity * 100}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-600 dark:text-gray-400 font-mono min-w-[3rem] text-right">
                        {(gap.severity * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>

                  {/* Description */}
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                    {gap.description}
                  </p>

                  {/* Suggestions */}
                  {gap.suggestions.length > 0 && (
                    <div className="mb-3">
                      <div className="flex items-center space-x-2 mb-2">
                        <CheckCircle className="w-4 h-4 text-green-600 dark:text-green-400" />
                        <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                          Suggestions:
                        </span>
                      </div>
                      <ul className="space-y-1">
                        {gap.suggestions.map((suggestion, sIndex) => (
                          <li key={sIndex} className="text-xs text-gray-600 dark:text-gray-400 pl-4">
                            • {suggestion}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Related Notes */}
                  {gap.related_notes.length > 0 && (
                    <div>
                      <div className="flex items-center space-x-2 mb-2">
                        <FileWarning className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                        <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
                          Related Notes:
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {gap.related_notes.map((note, nIndex) => (
                          <span
                            key={nIndex}
                            className="inline-flex items-center px-2 py-1 bg-primary-50 dark:bg-primary-900/20 text-primary-700 dark:text-primary-300 rounded text-xs"
                          >
                            {note}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* No Gaps Found */}
      {data && data.gaps.length === 0 && (
        <div className="text-center py-8">
          <CheckCircle className="w-12 h-12 text-green-500 dark:text-green-400 mx-auto mb-3" />
          <p className="text-gray-600 dark:text-gray-400 text-sm font-medium">
            No knowledge gaps detected!
          </p>
          <p className="text-gray-500 dark:text-gray-500 text-xs mt-1">
            Your knowledge base appears to be well-structured
          </p>
        </div>
      )}
    </div>
  );
}
