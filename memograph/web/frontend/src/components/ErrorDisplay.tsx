/**
 * Error display components — glass-aware, theme-correct.
 */

import { AlertTriangle, XCircle, RefreshCw, Home } from 'lucide-react';
import { Link } from 'react-router-dom';
import { cn } from '../lib/utils';

interface ErrorAlertProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export function ErrorAlert({
  title = 'Error',
  message,
  onRetry,
  onDismiss,
  className,
}: ErrorAlertProps) {
  return (
    <div
      role="alert"
      className={cn(
        'card flex items-start gap-3 border border-rose-500/40 bg-rose-500/10 backdrop-blur-md',
        className,
      )}
    >
      <AlertTriangle className="w-5 h-5 text-rose-500 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        <p className="text-sm text-muted-fg mt-1">{message}</p>
        {(onRetry || onDismiss) && (
          <div className="flex items-center gap-3 mt-3">
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="inline-flex items-center gap-1 text-sm font-medium text-rose-500 hover:text-rose-600"
              >
                <RefreshCw className="w-4 h-4" />
                <span>Try again</span>
              </button>
            )}
            {onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                className="text-sm font-medium text-muted-fg hover:text-fg"
              >
                Dismiss
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

interface ErrorPageProps {
  title?: string;
  message?: string;
  statusCode?: number;
  onRetry?: () => void;
  showHomeLink?: boolean;
}

export function ErrorPage({
  title = 'Something went wrong',
  message = 'An unexpected error occurred. Please try again.',
  statusCode,
  onRetry,
  showHomeLink = true,
}: ErrorPageProps) {
  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="max-w-md w-full text-center px-4">
        <XCircle className="w-16 h-16 text-rose-500 mx-auto mb-4" />
        {statusCode && (
          <div className="text-6xl font-bold font-display text-muted-fg/40 mb-2">
            {statusCode}
          </div>
        )}
        <h1 className="text-2xl font-bold font-display text-fg mb-2">{title}</h1>
        <p className="text-muted-fg mb-6">{message}</p>
        <div className="flex items-center justify-center gap-3">
          {onRetry && (
            <button type="button" onClick={onRetry} className="btn btn-primary">
              <RefreshCw className="w-4 h-4" />
              <span>Try again</span>
            </button>
          )}
          {showHomeLink && (
            <Link to="/" className="btn btn-secondary">
              <Home className="w-4 h-4" />
              <span>Go home</span>
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

interface NotFoundProps {
  resourceName?: string;
  backLink?: string;
  backLabel?: string;
}

export function NotFound({
  resourceName = 'Page',
  backLink = '/',
  backLabel = 'Go home',
}: NotFoundProps) {
  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="max-w-md w-full text-center px-4">
        <XCircle className="w-16 h-16 text-rose-500 mx-auto mb-4" />
        <div className="text-6xl font-bold font-display text-muted-fg/40 mb-2">404</div>
        <h1 className="text-2xl font-bold font-display text-fg mb-2">{`${resourceName} not found`}</h1>
        <p className="text-muted-fg mb-6">{`The ${resourceName.toLowerCase()} you're looking for doesn't exist or has been moved.`}</p>
        <Link to={backLink} className="btn btn-primary">
          <Home className="w-4 h-4" />
          <span>{backLabel}</span>
        </Link>
      </div>
    </div>
  );
}

interface ErrorCardProps {
  error: Error | string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorCard({ error, onRetry, className }: ErrorCardProps) {
  const message = typeof error === 'string' ? error : error.message;
  return (
    <div className={cn('card flex items-start gap-3 border-rose-500/40', className)}>
      <XCircle className="w-6 h-6 text-rose-500 shrink-0" />
      <div className="flex-1">
        <h3 className="text-lg font-semibold font-display text-fg mb-1">Error</h3>
        <p className="text-muted-fg">{message}</p>
        {onRetry && (
          <button type="button" onClick={onRetry} className="btn btn-primary mt-4">
            <RefreshCw className="w-4 h-4" />
            <span>Try again</span>
          </button>
        )}
      </div>
    </div>
  );
}

export function NetworkError({ onRetry }: { onRetry?: () => void }) {
  return (
    <ErrorAlert
      title="Connection error"
      message="Unable to connect to the server. Please check your internet connection and try again."
      onRetry={onRetry}
    />
  );
}

export function PermissionError() {
  return (
    <ErrorAlert
      title="Access denied"
      message="You don't have permission to access this resource."
    />
  );
}
