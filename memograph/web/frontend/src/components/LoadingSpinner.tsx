/**
 * Loading Components
 * 
 * Reusable loading indicators for various UI contexts.
 */

import { Loader2 } from 'lucide-react';
import { cn } from '../lib/utils';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  message?: string;
  className?: string;
}

/**
 * Spinning loader indicator
 */
export function LoadingSpinner({ size = 'md', message, className }: LoadingSpinnerProps) {
  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8',
  };
  
  return (
    <div className={cn('flex items-center justify-center', className)}>
      <div className="flex flex-col items-center space-y-3">
        <Loader2 className={cn('animate-spin text-primary-600', sizeClasses[size])} />
        {message && <span className="text-sm text-gray-600">{message}</span>}
      </div>
    </div>
  );
}

interface LoadingOverlayProps {
  message?: string;
}

/**
 * Full-page loading overlay
 */
export function LoadingOverlay({ message = 'Loading...' }: LoadingOverlayProps) {
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 shadow-xl">
        <LoadingSpinner size="lg" message={message} />
      </div>
    </div>
  );
}

interface LoadingCardProps {
  message?: string;
  className?: string;
}

/**
 * Card-style loading indicator
 */
export function LoadingCard({ message = 'Loading...', className }: LoadingCardProps) {
  return (
    <div className={cn('bg-white border rounded-lg p-8', className)}>
      <LoadingSpinner size="md" message={message} />
    </div>
  );
}

/**
 * Skeleton loader for content placeholders
 */
export function SkeletonLoader({ className }: { className?: string }) {
  return (
    <div className={cn('animate-pulse bg-gray-200 rounded', className)} />
  );
}

interface SkeletonCardProps {
  lines?: number;
}

/**
 * Skeleton card with multiple lines
 */
export function SkeletonCard({ lines = 3 }: SkeletonCardProps) {
  return (
    <div className="bg-white border rounded-lg p-6 space-y-4">
      <div className="flex items-center justify-between">
        <SkeletonLoader className="h-6 w-1/3" />
        <SkeletonLoader className="h-6 w-16" />
      </div>
      <SkeletonLoader className="h-4 w-full" />
      {Array.from({ length: lines - 1 }).map((_, i) => (
        <SkeletonLoader key={i} className="h-4 w-full" />
      ))}
      <div className="flex space-x-2 pt-2">
        <SkeletonLoader className="h-6 w-16 rounded-full" />
        <SkeletonLoader className="h-6 w-20 rounded-full" />
      </div>
    </div>
  );
}

/**
 * Skeleton list with multiple cards
 */
export function SkeletonList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}