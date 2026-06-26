/**
 * Loading indicators — uses CSS-var tokens and the global `.skeleton` shimmer.
 */

import { Loader2 } from 'lucide-react';
import { cn } from '../lib/utils';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  message?: string;
  className?: string;
}

export function LoadingSpinner({ size = 'md', message, className }: LoadingSpinnerProps) {
  const sizeClasses = { sm: 'w-4 h-4', md: 'w-6 h-6', lg: 'w-8 h-8' };
  return (
    <div className={cn('flex items-center justify-center', className)}>
      <div className="flex flex-col items-center gap-3">
        <Loader2 className={cn('animate-spin text-primary-500', sizeClasses[size])} />
        {message && <span className="text-sm text-muted-fg">{message}</span>}
      </div>
    </div>
  );
}

export function LoadingOverlay({ message = 'Loading…' }: { message?: string }) {
  return (
    <div className="fixed inset-0 bg-slate-950/40 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="card shadow-glass-lg">
        <LoadingSpinner size="lg" message={message} />
      </div>
    </div>
  );
}

export function LoadingCard({
  message = 'Loading…',
  className,
}: {
  message?: string;
  className?: string;
}) {
  return (
    <div className={cn('card', className)}>
      <LoadingSpinner size="md" message={message} />
    </div>
  );
}

export function SkeletonLoader({ className }: { className?: string }) {
  return <div className={cn('skeleton', className)} />;
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card space-y-3">
      <div className="flex items-center justify-between">
        <SkeletonLoader className="h-6 w-1/3" />
        <SkeletonLoader className="h-6 w-16" />
      </div>
      <SkeletonLoader className="h-4 w-full" />
      {Array.from({ length: lines - 1 }).map((_, i) => (
        <SkeletonLoader key={i} className="h-4 w-full" />
      ))}
      <div className="flex gap-2 pt-2">
        <SkeletonLoader className="h-5 w-12 rounded-full" />
        <SkeletonLoader className="h-5 w-16 rounded-full" />
      </div>
    </div>
  );
}

export function SkeletonList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}
