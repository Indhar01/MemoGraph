import { ReactNode, useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Brain,
  Search,
  Network,
  BarChart3,
  PlusCircle,
  Sun,
  Moon,
  Monitor,
  Menu,
  Command as CommandIcon,
  Database,
  AlertTriangle,
} from 'lucide-react';
import { useTheme } from '../lib/theme';
import { useKeyboardShortcuts } from '../lib/keyboardShortcuts';
import { sourcesAPI } from '../lib/api';
import { CommandPalette } from './CommandPalette';
import { MobileNav } from './MobileNav';

interface LayoutProps {
  children: ReactNode;
}

const NAV_ITEMS = [
  { path: '/memories', label: 'Memories', icon: Brain },
  { path: '/search', label: 'Search', icon: Search },
  { path: '/graph', label: 'Graph', icon: Network },
  { path: '/analytics', label: 'Analytics', icon: BarChart3 },
  { path: '/sources', label: 'Sources', icon: Database },
];

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, resolvedTheme, setTheme, toggleTheme } = useTheme();
  const { registerShortcut, toggleHelp } = useKeyboardShortcuts();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Global keyboard shortcuts
  useEffect(() => {
    registerShortcut({
      key: 'k',
      meta: true,
      description: 'Open command palette',
      action: () => setPaletteOpen((p) => !p),
      category: 'Navigation',
    });
    registerShortcut({
      key: 'n',
      meta: true,
      description: 'Create new memory',
      action: () => navigate('/memories/new'),
      category: 'Navigation',
    });
    registerShortcut({
      key: '1',
      meta: true,
      description: 'Go to Memories',
      action: () => navigate('/memories'),
      category: 'Navigation',
    });
    registerShortcut({
      key: '2',
      meta: true,
      description: 'Go to Graph',
      action: () => navigate('/graph'),
      category: 'Navigation',
    });
    registerShortcut({
      key: '3',
      meta: true,
      description: 'Go to Analytics',
      action: () => navigate('/analytics'),
      category: 'Navigation',
    });
    registerShortcut({
      key: 'd',
      meta: true,
      description: 'Toggle dark mode',
      action: toggleTheme,
      category: 'UI',
    });
    registerShortcut({
      key: '/',
      meta: true,
      description: 'Show keyboard shortcuts',
      action: toggleHelp,
      category: 'Help',
    });
  }, [registerShortcut, navigate, toggleTheme, toggleHelp]);

  const { data: sourcesProbe } = useQuery({
    queryKey: ['sources-enabled-probe'],
    queryFn: sourcesAPI.probeEnabled,
    staleTime: Infinity,
    refetchOnMount: false,
    retry: false,
  });
  const sourcesDisabled = sourcesProbe?.enabled === false;
  const [showAdminHint, setShowAdminHint] = useState(false);

  const isActive = (path: string) => location.pathname.startsWith(path);

  return (
    <div className="min-h-screen flex flex-col relative">
      {/* Header */}
      <header className="sticky top-0 z-40 glass-strong border-b border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16 gap-4">
            {/* Brand */}
            <Link to="/" className="flex items-center gap-2 shrink-0" aria-label="MemoGraph home">
              <span className="inline-flex items-center justify-center w-9 h-9 rounded-md bg-gradient-primary shadow-glow-soft">
                <Brain className="w-5 h-5 text-white" />
              </span>
              <span className="text-lg font-bold font-display text-gradient-brand hidden sm:inline">
                MemoGraph
              </span>
            </Link>

            {/* Desktop nav */}
            <nav className="hidden md:flex items-center gap-1" aria-label="Primary navigation">
              {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
                const active = isActive(path);
                return (
                  <Link
                    key={path}
                    to={path}
                    aria-current={active ? 'page' : undefined}
                    className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-all
                      ${
                        active
                          ? 'bg-gradient-primary text-white shadow-glow-soft font-semibold'
                          : 'text-muted-fg hover:text-fg hover:bg-surface/60'
                      }`}
                  >
                    <Icon className="w-4 h-4" />
                    <span>{label}</span>
                  </Link>
                );
              })}
            </nav>

            {/* Right-side controls */}
            <div className="flex items-center gap-2">
              {/* Command palette trigger (desktop) */}
              <button
                type="button"
                onClick={() => setPaletteOpen(true)}
                aria-label="Open command palette"
                className="hidden md:inline-flex items-center gap-2 px-3 py-1.5 rounded-md glass border border-border text-sm text-muted-fg hover:text-fg transition-colors"
              >
                <Search className="w-4 h-4" />
                <span>Search…</span>
                <kbd className="font-mono text-xs px-1.5 py-0.5 rounded bg-surface/60 border border-border">
                  ⌘K
                </kbd>
              </button>

              {/* Segmented theme switcher */}
              <ThemeSegmented theme={theme} setTheme={setTheme} resolved={resolvedTheme} />

              {/* New memory CTA (desktop) */}
              <Link to="/memories/new" className="btn btn-primary hidden sm:inline-flex">
                <PlusCircle className="w-4 h-4" />
                <span className="hidden lg:inline">New memory</span>
                <span className="lg:hidden">New</span>
              </Link>

              {/* Mobile hamburger */}
              <button
                type="button"
                onClick={() => setMobileNavOpen(true)}
                aria-label="Open menu"
                className="md:hidden btn btn-ghost p-2"
              >
                <Menu className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </header>

      {sourcesDisabled && (
        <div
          role="alert"
          className="sticky top-16 z-30 w-full bg-amber-500/10 border-b border-amber-500/40 text-amber-900 dark:text-amber-200 text-sm px-4 py-2 flex items-start gap-3"
        >
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
          <div className="flex-1">
            Source connections are disabled on this instance.{' '}
            <button
              type="button"
              onClick={() => setShowAdminHint((v) => !v)}
              className="underline"
              aria-expanded={showAdminHint}
            >
              {showAdminHint ? 'Hide details' : 'Why?'}
            </button>
            {showAdminHint && (
              <span className="block mt-1 text-xs opacity-80">
                Admin: unset{' '}
                <code className="px-1 rounded bg-amber-500/20">
                  MEMOGRAPH_SOURCES_ENABLED
                </code>{' '}
                (or set it to <code>1</code>) and restart the backend, then
                refresh. See the docs link for the full troubleshooting list.
              </span>
            )}
          </div>
          <a
            href="https://github.com/Indhar01/MemoGraph/blob/main/docs/SOURCES.md"
            target="_blank"
            rel="noreferrer"
            className="underline shrink-0"
          >
            Docs
          </a>
        </div>
      )}

      {/* Main */}
      <main className="flex-1 relative">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 animate-fade-up">{children}</div>
      </main>

      {/* Footer */}
      <footer className="mt-auto border-t border-border glass">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-muted-fg">
            <p>
              MemoGraph{' '}
              <span className="font-mono">v{__APP_VERSION__}</span> · graph-based memory for LLMs
            </p>
            <p>
              <button
                type="button"
                onClick={toggleHelp}
                className="inline-flex items-center gap-1.5 hover:text-fg transition-colors"
              >
                <CommandIcon className="w-3 h-3" /> ⌘/ for shortcuts
              </button>
            </p>
          </div>
        </div>
      </footer>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <MobileNav open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
    </div>
  );
}

function ThemeSegmented({
  theme,
  setTheme,
  resolved,
}: {
  theme: 'light' | 'dark' | 'system';
  setTheme: (t: 'light' | 'dark' | 'system') => void;
  resolved: 'light' | 'dark';
}) {
  const items: Array<{ value: 'light' | 'dark' | 'system'; icon: typeof Sun; label: string }> = [
    { value: 'light', icon: Sun, label: 'Light' },
    { value: 'system', icon: Monitor, label: 'System' },
    { value: 'dark', icon: Moon, label: 'Dark' },
  ];
  return (
    <div
      role="radiogroup"
      aria-label={`Theme — currently ${resolved}`}
      className="hidden sm:inline-flex items-center gap-0.5 p-0.5 rounded-md glass border border-border"
    >
      {items.map(({ value, icon: Icon, label }) => {
        const selected = theme === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={label}
            title={label}
            onClick={() => setTheme(value)}
            className={`p-1.5 rounded-[6px] transition-all ${
              selected
                ? 'bg-gradient-primary text-white shadow-glow-soft'
                : 'text-muted-fg hover:text-fg'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
          </button>
        );
      })}
    </div>
  );
}
