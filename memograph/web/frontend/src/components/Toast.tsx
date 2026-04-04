/**
 * Toast Component
 *
 * Individual toast notification with animations and icons.
 * Supports success, error, info, and warning types.
 */

import { useEffect, useState } from 'react';
import { X, CheckCircle, AlertCircle, Info, AlertTriangle } from 'lucide-react';
import { useToastStore, type Toast as ToastType } from '../lib/toast';
import { cn } from '../lib/utils';

interface ToastProps {
  toast: ToastType;
}

export function Toast({ toast }: ToastProps) {
  const { removeToast } = useToastStore();
  const [isExiting, setIsExiting] = useState(false);

  // Handle exit animation before removing
  const handleClose = () => {
    setIsExiting(true);
    setTimeout(() => {
      removeToast(toast.id);
    }, 300); // Match animation duration
  };

  // Auto-dismiss progress bar
  const [progress, setProgress] = useState(100);

  useEffect(() => {
    if (toast.duration <= 0) return;

    const interval = 50; // Update every 50ms
    const decrement = (interval / toast.duration) * 100;

    const timer = setInterval(() => {
      setProgress((prev) => {
        const next = prev - decrement;
        return next <= 0 ? 0 : next;
      });
    }, interval);

    return () => clearInterval(timer);
  }, [toast.duration]);

  // Get icon and colors based on type
  const getTypeStyles = () => {
    switch (toast.type) {
      case 'success':
        return {
          icon: <CheckCircle className="w-5 h-5" />,
          className: 'bg-green-50 border-green-200 text-green-900',
          iconColor: 'text-green-600',
          progressColor: 'bg-green-500',
        };
      case 'error':
        return {
          icon: <AlertCircle className="w-5 h-5" />,
          className: 'bg-red-50 border-red-200 text-red-900',
          iconColor: 'text-red-600',
          progressColor: 'bg-red-500',
        };
      case 'warning':
        return {
          icon: <AlertTriangle className="w-5 h-5" />,
          className: 'bg-yellow-50 border-yellow-200 text-yellow-900',
          iconColor: 'text-yellow-600',
          progressColor: 'bg-yellow-500',
        };
      case 'info':
      default:
        return {
          icon: <Info className="w-5 h-5" />,
          className: 'bg-blue-50 border-blue-200 text-blue-900',
          iconColor: 'text-blue-600',
          progressColor: 'bg-blue-500',
        };
    }
  };

  const styles = getTypeStyles();

  return (
    <div
      className={cn(
        'relative flex items-start space-x-3 p-4 rounded-lg border shadow-lg min-w-[320px] max-w-md',
        'transition-all duration-300 ease-out',
        isExiting ? 'opacity-0 translate-x-full' : 'opacity-100 translate-x-0',
        styles.className
      )}
      role="alert"
      aria-live="polite"
    >
      {/* Icon */}
      <div className={cn('flex-shrink-0 mt-0.5', styles.iconColor)}>
        {styles.icon}
      </div>

      {/* Message */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium">{toast.message}</p>
      </div>

      {/* Close button */}
      <button
        onClick={handleClose}
        className="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors"
        aria-label="Close notification"
      >
        <X className="w-4 h-4" />
      </button>

      {/* Progress bar */}
      {toast.duration > 0 && (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-gray-200 bg-opacity-30 rounded-b-lg overflow-hidden">
          <div
            className={cn('h-full transition-all ease-linear', styles.progressColor)}
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  );
}

/**
 * ToastContainer Component
 *
 * Renders all active toasts in a fixed position on the screen.
 * Place this component once at the root of your app.
 */
export function ToastContainer() {
  const { toasts } = useToastStore();

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed top-4 right-4 z-50 flex flex-col space-y-2"
      aria-live="polite"
      aria-atomic="false"
    >
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} />
      ))}
    </div>
  );
}
