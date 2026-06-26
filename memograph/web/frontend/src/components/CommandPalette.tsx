import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Command } from 'cmdk';
import { useQuery } from '@tanstack/react-query';
import {
  Brain,
  Search,
  Network,
  BarChart3,
  PlusCircle,
  Sun,
  Moon,
  Tag,
  ArrowRight,
  FileText,
} from 'lucide-react';
import { useTheme } from '../lib/theme';
import { memoriesApi, searchAPI } from '../lib/api';

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Glassy, gradient-accented command palette.
 * Surfaces: navigation, actions, recent memories, tag jumps, live search.
 */
export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { setTheme, resolvedTheme } = useTheme();
  const [query, setQuery] = useState('');

  // Recent / top memories (loaded once, fast for empty state)
  const { data: recentMemories } = useQuery({
    queryKey: ['palette-recent'],
    queryFn: () =>
      memoriesApi.list({ page: 1, page_size: 8, sort_by: 'modified_at', order: 'desc' }),
    enabled: open,
    staleTime: 60_000,
  });

  const { data: allTags } = useQuery({
    queryKey: ['tags'],
    queryFn: () => searchAPI.getAllTags(),
    enabled: open,
    staleTime: 120_000,
  });

  // Reset query on close
  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const close = () => onOpenChange(false);
  const go = (path: string) => {
    close();
    navigate(path);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center p-4 pt-[12vh] animate-fade-up"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <button
        type="button"
        aria-label="Close command palette"
        onClick={close}
        className="absolute inset-0 bg-slate-950/40 backdrop-blur-sm"
      />

      <div className="relative w-full max-w-2xl rounded-xl glass-strong shadow-glass-lg overflow-hidden border border-white/30 dark:border-white/10">
        <div className="absolute inset-x-0 -top-px h-px bg-gradient-brand opacity-80" />
        <Command label="Command Menu" className="w-full" shouldFilter={true}>
          <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
            <Search className="w-5 h-5 text-muted-fg" aria-hidden="true" />
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Jump to a memory, tag, or action…"
              className="flex-1 bg-transparent outline-none text-base text-fg placeholder:text-muted-fg"
              autoFocus
            />
            <kbd className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border bg-surface/60 text-xs text-muted-fg font-mono">
              esc
            </kbd>
          </div>

          <Command.List className="max-h-[60vh] overflow-y-auto p-2">
            <Command.Empty className="py-12 text-center text-sm text-muted-fg">
              No results for "{query}"
            </Command.Empty>

            <Command.Group
              heading="Navigate"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-fg"
            >
              <PaletteItem icon={<Brain className="w-4 h-4" />} onSelect={() => go('/memories')}>
                Memories
              </PaletteItem>
              <PaletteItem icon={<Network className="w-4 h-4" />} onSelect={() => go('/graph')}>
                Graph
              </PaletteItem>
              <PaletteItem
                icon={<BarChart3 className="w-4 h-4" />}
                onSelect={() => go('/analytics')}
              >
                Analytics
              </PaletteItem>
              <PaletteItem icon={<Search className="w-4 h-4" />} onSelect={() => go('/search')}>
                Open search
              </PaletteItem>
            </Command.Group>

            <Command.Group
              heading="Actions"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-fg [&_[cmdk-group-heading]]:mt-2"
            >
              <PaletteItem
                icon={<PlusCircle className="w-4 h-4" />}
                onSelect={() => go('/memories/new')}
                accent
              >
                Create new memory
              </PaletteItem>
              <PaletteItem
                icon={resolvedTheme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                onSelect={() => {
                  setTheme(resolvedTheme === 'dark' ? 'light' : 'dark');
                }}
              >
                Toggle theme — {resolvedTheme === 'dark' ? 'light' : 'dark'} mode
              </PaletteItem>
            </Command.Group>

            {!!recentMemories?.memories.length && (
              <Command.Group
                heading={query ? 'Memories' : 'Recent memories'}
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-fg [&_[cmdk-group-heading]]:mt-2"
              >
                {recentMemories.memories.map((m) => (
                  <PaletteItem
                    key={m.id}
                    icon={<FileText className="w-4 h-4" />}
                    onSelect={() => go(`/memories/${m.id}`)}
                    keywords={[m.title, ...m.tags, m.memory_type]}
                  >
                    <span className="flex-1 truncate">{m.title}</span>
                    <span className="ml-2 text-xs text-muted-fg font-mono">{m.memory_type}</span>
                  </PaletteItem>
                ))}
              </Command.Group>
            )}

            {!!allTags?.length && (
              <Command.Group
                heading="Tags"
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-fg [&_[cmdk-group-heading]]:mt-2"
              >
                {allTags.slice(0, 12).map((tag) => (
                  <PaletteItem
                    key={tag}
                    icon={<Tag className="w-4 h-4" />}
                    onSelect={() => go(`/search?tags=${encodeURIComponent(tag)}`)}
                    keywords={[tag, '#' + tag]}
                  >
                    #{tag}
                  </PaletteItem>
                ))}
              </Command.Group>
            )}
          </Command.List>

          <div className="flex items-center justify-between px-4 py-2 border-t border-border bg-surface/30 text-xs text-muted-fg">
            <div className="flex items-center gap-3">
              <span>
                <kbd className="font-mono">↑↓</kbd> navigate
              </span>
              <span>
                <kbd className="font-mono">↵</kbd> select
              </span>
            </div>
            <span className="text-gradient-primary font-semibold">MemoGraph</span>
          </div>
        </Command>
      </div>
    </div>
  );
}

function PaletteItem({
  children,
  icon,
  onSelect,
  keywords,
  accent,
}: {
  children: React.ReactNode;
  icon: React.ReactNode;
  onSelect: () => void;
  keywords?: string[];
  accent?: boolean;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      keywords={keywords}
      className={`flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer text-sm
        text-fg transition-colors
        data-[selected=true]:bg-primary-500/15 data-[selected=true]:text-primary-700
        dark:data-[selected=true]:text-primary-200
        ${accent ? 'font-semibold' : ''}`}
    >
      <span
        className={`flex items-center justify-center w-7 h-7 rounded-md ${
          accent
            ? 'bg-gradient-primary text-white shadow-glow-soft'
            : 'bg-surface/60 text-muted-fg border border-border'
        }`}
      >
        {icon}
      </span>
      <span className="flex-1 flex items-center min-w-0">{children}</span>
      <ArrowRight className="w-3.5 h-3.5 text-muted-fg opacity-0 group-data-[selected=true]/item:opacity-100" />
    </Command.Item>
  );
}
