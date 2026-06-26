import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { X, Brain, Search, Network, BarChart3, PlusCircle } from 'lucide-react';

interface MobileNavProps {
  open: boolean;
  onClose: () => void;
}

const NAV_ITEMS = [
  { path: '/memories', label: 'Memories', icon: Brain },
  { path: '/search', label: 'Search', icon: Search },
  { path: '/graph', label: 'Graph', icon: Network },
  { path: '/analytics', label: 'Analytics', icon: BarChart3 },
];

export function MobileNav({ open, onClose }: MobileNavProps) {
  const location = useLocation();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[90] md:hidden" role="dialog" aria-modal="true" aria-label="Navigation menu">
      <button
        type="button"
        aria-label="Close menu"
        onClick={onClose}
        className="absolute inset-0 bg-slate-950/40 backdrop-blur-sm"
      />
      <div className="relative ml-auto h-full w-[80%] max-w-xs glass-strong border-l border-border shadow-glass-lg p-4 animate-fade-up flex flex-col">
        <div className="flex items-center justify-between mb-6">
          <Link
            to="/"
            onClick={onClose}
            className="flex items-center gap-2"
            aria-label="MemoGraph home"
          >
            <span className="inline-flex items-center justify-center w-9 h-9 rounded-md bg-gradient-primary shadow-glow-soft">
              <Brain className="w-5 h-5 text-white" />
            </span>
            <span className="text-lg font-bold font-display text-gradient-brand">MemoGraph</span>
          </Link>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            className="btn btn-ghost p-2"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav aria-label="Primary navigation" className="flex flex-col gap-1">
          {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
            const active = location.pathname.startsWith(path);
            return (
              <Link
                key={path}
                to={path}
                onClick={onClose}
                aria-current={active ? 'page' : undefined}
                className={`flex items-center gap-3 px-3 py-3 rounded-md text-base transition-all
                  ${
                    active
                      ? 'bg-gradient-primary text-white shadow-glow-soft font-semibold'
                      : 'text-fg hover:bg-surface/70'
                  }`}
              >
                <Icon className="w-5 h-5" />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto pt-4 border-t border-border">
          <Link
            to="/memories/new"
            onClick={onClose}
            className="btn btn-primary w-full"
          >
            <PlusCircle className="w-4 h-4" />
            New memory
          </Link>
        </div>
      </div>
    </div>
  );
}
