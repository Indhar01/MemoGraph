/**
 * CreateMemoryPage - Memory creation form with markdown editor
 *
 * Features:
 * - Title and content inputs
 * - Markdown editor with live preview
 * - Memory type selector
 * - Tag input with autocomplete
 * - Salience slider
 * - Form validation
 * - Save/cancel actions
 */

import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import Markdown from 'markdown-to-jsx';
import {
  Save,
  X,
  Tag,
  TrendingUp,
  AlertCircle,
  Eye,
  Edit3,
} from 'lucide-react';

import { memoriesApi, searchAPI } from '../lib/api';
import type { CreateMemoryRequest, MemoryType } from '../types';
import { getMemoryTypeIcon, cn } from '../lib/utils';

export default function CreateMemoryPage() {
  const navigate = useNavigate();

  // Form state
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [memoryType, setMemoryType] = useState<MemoryType>('fact');
  const [tags, setTags] = useState<string[]>([]);
  const [salience, setSalience] = useState(0.5);
  const [tagInput, setTagInput] = useState('');
  const [showPreview, setShowPreview] = useState(false);

  // Validation state
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Fetch available tags for autocomplete
  const { data: availableTags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: searchAPI.getAllTags,
  });

  // Create memory mutation
  const createMutation = useMutation({
    mutationFn: (memory: CreateMemoryRequest) => memoriesApi.create(memory),
    onSuccess: (data) => {
      navigate(`/memories/${data.id}`);
    },
    onError: (error: any) => {
      setErrors({ submit: error.response?.data?.detail || error.message });
    },
  });

  // Validate form
  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {};

    if (!title.trim()) {
      newErrors.title = 'Title is required';
    } else if (title.length > 500) {
      newErrors.title = 'Title must be less than 500 characters';
    }

    if (!content.trim()) {
      newErrors.content = 'Content is required';
    }

    if (salience < 0 || salience > 1) {
      newErrors.salience = 'Salience must be between 0 and 1';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [title, content, salience]);

  // Handle form submission
  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();

    if (!validate()) {
      return;
    }

    const memory: CreateMemoryRequest = {
      title: title.trim(),
      content: content.trim(),
      memory_type: memoryType,
      tags,
      salience,
    };

    createMutation.mutate(memory);
  }, [title, content, memoryType, tags, salience, validate, createMutation]);

  // Handle tag input
  const handleAddTag = useCallback((tag: string) => {
    const cleanTag = tag.trim().replace(/^#/, '');
    if (cleanTag && !tags.includes(cleanTag)) {
      setTags([...tags, cleanTag]);
      setTagInput('');
    }
  }, [tags]);

  const handleRemoveTag = useCallback((tagToRemove: string) => {
    setTags(tags.filter(t => t !== tagToRemove));
  }, [tags]);

  const handleTagInputKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddTag(tagInput);
    } else if (e.key === 'Backspace' && !tagInput && tags.length > 0) {
      handleRemoveTag(tags[tags.length - 1]);
    }
  }, [tagInput, tags, handleAddTag, handleRemoveTag]);

  // Filter autocomplete suggestions
  const tagSuggestions = availableTags
    .filter((tag: string) =>
      tag.toLowerCase().includes(tagInput.toLowerCase()) &&
      !tags.includes(tag)
    )
    .slice(0, 5);

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Create Memory</h1>
        <p className="text-gray-600 mt-1">
          Add a new memory to your vault
        </p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Global error */}
        {errors.submit && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start space-x-3">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-medium text-red-800">Failed to create memory</h3>
              <p className="text-sm text-red-700 mt-1">{errors.submit}</p>
            </div>
          </div>
        )}

        {/* Title */}
        <div>
          <label htmlFor="title" className="block text-sm font-medium text-gray-700 mb-2">
            Title <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            id="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={cn(
              'w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent',
              errors.title ? 'border-red-300' : 'border-gray-300'
            )}
            placeholder="Enter memory title..."
            maxLength={500}
          />
          {errors.title && (
            <p className="text-sm text-red-600 mt-1">{errors.title}</p>
          )}
        </div>

        {/* Content with Preview Toggle */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label htmlFor="content" className="text-sm font-medium text-gray-700">
              Content <span className="text-red-500">*</span>
            </label>
            <button
              type="button"
              onClick={() => setShowPreview(!showPreview)}
              className="flex items-center space-x-2 text-sm text-gray-600 hover:text-gray-900"
            >
              {showPreview ? (
                <>
                  <Edit3 className="w-4 h-4" />
                  <span>Edit</span>
                </>
              ) : (
                <>
                  <Eye className="w-4 h-4" />
                  <span>Preview</span>
                </>
              )}
            </button>
          </div>

          {showPreview ? (
            <div className="w-full min-h-[300px] px-4 py-3 border border-gray-300 rounded-lg bg-gray-50 prose prose-sm max-w-none">
              {content ? (
                <Markdown>{content}</Markdown>
              ) : (
                <p className="text-gray-400 italic">No content to preview</p>
              )}
            </div>
          ) : (
            <textarea
              id="content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className={cn(
                'w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm',
                errors.content ? 'border-red-300' : 'border-gray-300'
              )}
              rows={12}
              placeholder="Enter memory content (markdown supported)..."
            />
          )}
          {errors.content && (
            <p className="text-sm text-red-600 mt-1">{errors.content}</p>
          )}
          <p className="text-xs text-gray-500 mt-1">
            Markdown formatting supported. Use **bold**, *italic*, `code`, etc.
          </p>
        </div>

        {/* Memory Type and Salience Row */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Memory Type */}
          <div>
            <label htmlFor="memoryType" className="block text-sm font-medium text-gray-700 mb-2">
              Memory Type
            </label>
            <select
              id="memoryType"
              value={memoryType}
              onChange={(e) => setMemoryType(e.target.value as MemoryType)}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            >
              <option value="episodic">{getMemoryTypeIcon('episodic')} Episodic</option>
              <option value="semantic">{getMemoryTypeIcon('semantic')} Semantic</option>
              <option value="procedural">{getMemoryTypeIcon('procedural')} Procedural</option>
              <option value="fact">{getMemoryTypeIcon('fact')} Fact</option>
            </select>
            <p className="text-xs text-gray-500 mt-1">
              {memoryType === 'episodic' && 'Personal experiences and events'}
              {memoryType === 'semantic' && 'Facts and general knowledge'}
              {memoryType === 'procedural' && 'How-to knowledge and processes'}
              {memoryType === 'fact' && 'Discrete factual information'}
            </p>
          </div>

          {/* Salience */}
          <div>
            <label htmlFor="salience" className="block text-sm font-medium text-gray-700 mb-2">
              <div className="flex items-center space-x-2">
                <TrendingUp className="w-4 h-4" />
                <span>Importance: {(salience * 100).toFixed(0)}%</span>
              </div>
            </label>
            <input
              type="range"
              id="salience"
              min="0"
              max="1"
              step="0.1"
              value={salience}
              onChange={(e) => setSalience(parseFloat(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>Low</span>
              <span>Medium</span>
              <span>High</span>
            </div>
          </div>
        </div>

        {/* Tags */}
        <div>
          <label htmlFor="tags" className="block text-sm font-medium text-gray-700 mb-2">
            <div className="flex items-center space-x-2">
              <Tag className="w-4 h-4" />
              <span>Tags</span>
            </div>
          </label>

          {/* Selected tags */}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center space-x-1 px-3 py-1 bg-primary-100 text-primary-800 rounded-full text-sm"
                >
                  <span>#{tag}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveTag(tag)}
                    className="hover:text-primary-900"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* Tag input */}
          <div className="relative">
            <input
              type="text"
              id="tags"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={handleTagInputKeyDown}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              placeholder="Type to add tags... (press Enter)"
            />

            {/* Autocomplete suggestions */}
            {tagInput && tagSuggestions.length > 0 && (
              <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg">
                {tagSuggestions.map((tag: string) => (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => handleAddTag(tag)}
                    className="w-full px-4 py-2 text-left hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg"
                  >
                    #{tag}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end space-x-4 pt-6 border-t">
          <button
            type="button"
            onClick={() => navigate('/memories')}
            className="px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
            disabled={createMutation.isPending}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="flex items-center space-x-2 px-6 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {createMutation.isPending ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>Creating...</span>
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                <span>Create Memory</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
