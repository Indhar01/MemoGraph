/**
 * Error Display Components
 *
 * Reusable error display components for various error scenarios.
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

/**
 * Inline error alert component
 */
export function ErrorAlert({
  title = 'Error',
  message,
  onRetry,
  onDismiss,
  className
}: ErrorAlertProps) {
  return (
    <div className={cn('bg-red-50 border border-red-200 rounded-lg p-4', className)}>
      <div className="flex items-start space-x-3">
        <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-red-900">{title}</h3>
          <p className="text-sm text-red-700 mt-1">{message}</p>
          {(onRetry || onDismiss) && (
            <div className="flex items-center space-x-3 mt-3">
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="inline-flex items-center space-x-1 text-sm font-medium text-red-800 hover:text-red-900"
                >
                  <RefreshCw className="w-4 h-4" />
                  <span>Try Again</span>
                </button>
              )}
              {onDismiss && (
                <button
                  onClick={onDismiss}
                  className="text-sm font-medium text-red-700 hover:text-red-800"
                >
                  Dismiss
                </button>
              )}
            </div>
          )}
        </div>
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

/**
 * Full-page error display
 */
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
        <XCircle className="w-16 h-16 text-red-500 mx-auto mb-4" />
        {statusCode && (
          <div className="text-6xl font-bold text-gray-300 mb-2">{statusCode}</div>
        )}
        <h1 className="text-2xl font-bold text-gray-900 mb-2">{title}</h1>
        <p className="text-gray-600 mb-6">{message}</p>
        <div className="flex items-center justify-center space-x-3">
          {onRetry && (
            <button
              onClick={onRetry}
              className="inline-flex items-center space-x-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Try Again</span>
            </button>
          )}
          {showHomeLink && (
            <Link
              to="/"
              className="inline-flex items-center space-x-2 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <Home className="w-4 h-4" />
              <span>Go Home</span>
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

/**
 * 404 Not Found component
 */
export function NotFound({
  resourceName = 'Page',
  backLink = '/',
  backLabel = 'Go Home',
}: NotFoundProps) {
  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="max-w-md w-full text-center px-4">
        <XCircle className="w-16 h-16 text-red-500 mx-auto mb-4" />
        <div className="text-6xl font-bold text-gray-300 mb-2">404</div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">{`${resourceName} Not Found`}</h1>
        <p className="text-gray-600 mb-6">
          {`The ${resourceName.toLowerCase()} you're looking for doesn't exist or has been moved.`}
        </p>
        <Link
          to={backLink}
          className="inline-flex items-center space-x-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
        >
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

/**
 * Card-style error display
 */
export function ErrorCard({ error, onRetry, className }: ErrorCardProps) {
  const message = typeof error === 'string' ? error : error.message;

  return (
    <div className={cn('bg-white border border-red-200 rounded-lg p-6', className)}>
      <div className="flex items-start space-x-3">
        <XCircle className="w-6 h-6 text-red-500 flex-shrink-0" />
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-900 mb-1">Error</h3>
          <p className="text-gray-700">{message}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="inline-flex items-center space-x-2 mt-4 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Try Again</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Network error component
 */
export function NetworkError({ onRetry }: { onRetry?: () => void }) {
  return (
    <ErrorAlert
      title="Connection Error"
      message="Unable to connect to the server. Please check your internet connection and try again."
      onRetry={onRetry}
    />
  );
}

/**
 * Permission error component
 */
export function PermissionError() {
  return (
    <ErrorAlert
      title="Access Denied"
      message="You don't have permission to access this resource."
    />
  );
}
