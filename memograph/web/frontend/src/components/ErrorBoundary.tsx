/**
 * Error Boundary Component
 *
 * React error boundary that catches JavaScript errors anywhere in the child
 * component tree and displays a fallback UI instead of crashing the entire app.
 *
 * Usage:
 * ```tsx
 * <ErrorBoundary>
 *   <YourComponent />
 * </ErrorBoundary>
 * ```
 */

import { Component, ReactNode, ErrorInfo } from 'react';
import { RefreshCw, Home, AlertTriangle } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Error Boundary class component
 *
 * Must be a class component because React error boundaries
 * require the componentDidCatch lifecycle method.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    // Update state so the next render will show the fallback UI
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Log error to console in development
    if (import.meta.env.DEV) {
      console.error('Error Boundary caught an error:', error, errorInfo);
    }

    // Update state with error info
    this.setState({
      error,
      errorInfo,
    });

    // Call optional onError callback
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }

    // In production, you might want to log to an error reporting service
    // e.g., Sentry, LogRocket, etc.
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback UI provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen flex items-center justify-center px-4">
          <div className="max-w-lg w-full card-elevated">
            <div className="flex items-center gap-3 mb-4">
              <span className="inline-flex items-center justify-center w-11 h-11 rounded-md bg-rose-500/15 text-rose-500">
                <AlertTriangle className="w-6 h-6" />
              </span>
              <h1 className="text-2xl font-bold font-display text-fg">Something went wrong</h1>
            </div>

            <p className="text-muted-fg mb-4">
              The application encountered an unexpected error. We apologize for the inconvenience.
            </p>

            {import.meta.env.DEV && this.state.error && (
              <details className="mb-4">
                <summary className="cursor-pointer text-sm font-medium text-muted-fg hover:text-fg">
                  Error details (dev only)
                </summary>
                <div className="mt-2 p-4 rounded-md glass overflow-auto">
                  <p className="text-sm font-mono text-rose-500 mb-2">
                    {this.state.error.toString()}
                  </p>
                  {this.state.errorInfo && (
                    <pre className="text-xs text-muted-fg whitespace-pre-wrap">
                      {this.state.errorInfo.componentStack}
                    </pre>
                  )}
                </div>
              </details>
            )}

            <div className="flex flex-col sm:flex-row gap-3">
              <button onClick={this.handleReset} className="btn btn-primary flex-1">
                <RefreshCw className="w-4 h-4" />
                <span>Try again</span>
              </button>
              <button onClick={this.handleReload} className="btn btn-secondary flex-1">
                <Home className="w-4 h-4" />
                <span>Reload page</span>
              </button>
            </div>

            <p className="text-xs text-muted-fg mt-4 text-center">
              If this problem persists, please contact support or try clearing your browser cache.
            </p>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

/**
 * Hook-based wrapper for functional components
 * Note: This doesn't catch errors within the component itself,
 * only in its children. Use ErrorBoundary for that.
 */
export function withErrorBoundary<P extends object>(
  Component: React.ComponentType<P>,
  fallback?: ReactNode
) {
  return function WithErrorBoundaryWrapper(props: P) {
    return (
      <ErrorBoundary fallback={fallback}>
        <Component {...props} />
      </ErrorBoundary>
    );
  };
}
