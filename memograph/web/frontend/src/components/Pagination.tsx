/**
 * Pagination — glass-styled with gradient active page.
 */

import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import { cn } from '../lib/utils';

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  totalItems: number;
  itemsPerPage: number;
  onPageChange: (page: number) => void;
  className?: string;
  showItemCount?: boolean;
}

export function Pagination({
  currentPage,
  totalPages,
  totalItems,
  itemsPerPage,
  onPageChange,
  className,
  showItemCount = true,
}: PaginationProps) {
  const startItem = (currentPage - 1) * itemsPerPage + 1;
  const endItem = Math.min(currentPage * itemsPerPage, totalItems);

  const getPageNumbers = () => {
    const pages: (number | string)[] = [];
    const maxVisible = 5;
    if (totalPages <= maxVisible + 2) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages.push(1);
      if (currentPage > 3) pages.push('...');
      const start = Math.max(2, currentPage - 1);
      const end = Math.min(totalPages - 1, currentPage + 1);
      for (let i = start; i <= end; i++) pages.push(i);
      if (currentPage < totalPages - 2) pages.push('...');
      pages.push(totalPages);
    }
    return pages;
  };

  if (totalPages <= 1) return null;
  const pageNumbers = getPageNumbers();
  const go = (p: number) => {
    if (p >= 1 && p <= totalPages && p !== currentPage) onPageChange(p);
  };

  return (
    <nav
      aria-label="Pagination"
      className={cn('flex flex-col sm:flex-row items-center justify-between gap-4', className)}
    >
      {showItemCount && (
        <p className="text-sm text-muted-fg">
          Showing <span className="font-mono text-fg">{startItem}</span>–
          <span className="font-mono text-fg">{endItem}</span> of{' '}
          <span className="font-mono text-fg">{totalItems}</span>
        </p>
      )}

      <div className="flex items-center gap-1">
        <PageBtn onClick={() => go(1)} disabled={currentPage === 1} label="First page">
          <ChevronsLeft className="w-4 h-4" />
        </PageBtn>
        <PageBtn onClick={() => go(currentPage - 1)} disabled={currentPage === 1} label="Previous page">
          <ChevronLeft className="w-4 h-4" />
        </PageBtn>

        {pageNumbers.map((p, i) =>
          p === '...' ? (
            <span key={`e${i}`} className="px-2 text-muted-fg">
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              onClick={() => go(p as number)}
              aria-current={p === currentPage ? 'page' : undefined}
              aria-label={`Page ${p}`}
              className={cn(
                'min-w-[2.25rem] h-9 px-2 rounded-md font-medium text-sm transition-all',
                p === currentPage
                  ? 'bg-gradient-primary text-white shadow-glow-soft'
                  : 'glass text-fg hover:bg-surface/70',
              )}
            >
              {p}
            </button>
          ),
        )}

        <PageBtn onClick={() => go(currentPage + 1)} disabled={currentPage === totalPages} label="Next page">
          <ChevronRight className="w-4 h-4" />
        </PageBtn>
        <PageBtn onClick={() => go(totalPages)} disabled={currentPage === totalPages} label="Last page">
          <ChevronsRight className="w-4 h-4" />
        </PageBtn>
      </div>
    </nav>
  );
}

function PageBtn({
  children,
  onClick,
  disabled,
  label,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="inline-flex items-center justify-center w-9 h-9 rounded-md glass text-fg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface/70 transition-colors"
    >
      {children}
    </button>
  );
}
