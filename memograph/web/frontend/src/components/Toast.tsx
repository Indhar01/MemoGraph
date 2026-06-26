/**
 * Toast notification — glass-styled, theme-aware.
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
  const [exiting, setExiting] = useState(false);
  const [progress, setProgress] = useState(100);

  const handleClose = () => {
    setExiting(true);
    setTimeout(() => removeToast(toast.id), 200);
  };

  useEffect(() => {
    if (toast.duration <= 0) return;
    const tick = 50;
    const dec = (tick / toast.duration) * 100;
    const t = setInterval(() => {
      setProgress((p) => Math.max(0, p - dec));
    }, tick);
    return () => clearInterval(t);
  }, [toast.duration]);

  const styles = (() => {
    switch (toast.type) {
      case 'success':
        return { Icon: CheckCircle, ring: 'border-emerald-500/40', tint: 'text-emerald-500', bar: 'bg-emerald-500' };
      case 'error':
        return { Icon: AlertCircle, ring: 'border-rose-500/40', tint: 'text-rose-500', bar: 'bg-rose-500' };
      case 'warning':
        return { Icon: AlertTriangle, ring: 'border-amber-500/40', tint: 'text-amber-500', bar: 'bg-amber-500' };
      case 'info':
      default:
        return { Icon: Info, ring: 'border-primary-500/40', tint: 'text-primary-500', bar: 'bg-primary-500' };
    }
  })();
  const { Icon } = styles;

  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        'relative flex items-start gap-3 p-4 rounded-md glass-strong border shadow-glass-md min-w-[320px] max-w-md transition-all duration-200',
        styles.ring,
        exiting ? 'opacity-0 translate-x-6' : 'opacity-100 translate-x-0',
      )}
    >
      <Icon className={cn('w-5 h-5 shrink-0 mt-0.5', styles.tint)} />
      <p className="flex-1 text-sm text-fg font-medium">{toast.message}</p>
      <button
        type="button"
        onClick={handleClose}
        aria-label="Close notification"
        className="text-muted-fg hover:text-fg transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
      {toast.duration > 0 && (
        <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-border rounded-b-md overflow-hidden">
          <div
            className={cn('h-full transition-all ease-linear', styles.bar)}
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  );
}

export function ToastContainer() {
  const { toasts } = useToastStore();
  if (toasts.length === 0) return null;
  return (
    <div
      className="fixed top-20 right-4 z-[110] flex flex-col gap-2 pointer-events-none"
      aria-live="polite"
      aria-atomic="false"
    >
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto animate-fade-up">
          <Toast toast={t} />
        </div>
      ))}
    </div>
  );
}
