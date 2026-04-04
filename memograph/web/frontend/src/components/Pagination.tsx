/**
 * Pagination Component
 * 
 * Reusable pagination controls with page numbers and navigation.
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
  // Calculate the range of items being displayed
  const startItem = (currentPage - 1) * itemsPerPage + 1;
  const endItem = Math.min(currentPage * itemsPerPage, totalItems);

  // Generate page numbers to display
  const getPageNumbers = () => {
    const pages: (number | string)[] = [];
    const maxVisible = 5; // Maximum number of page buttons to show

    if (totalPages <= maxVisible + 2) {
      // Show all pages if total is small
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i);
      }
    } else {
      // Always show first page
      pages.push(1);

      if (currentPage > 3) {
        pages.push('...');
      }

      // Show pages around current page
      const start = Math.max(2, currentPage - 1);
      const end = Math.min(totalPages - 1, currentPage + 1);

      for (let i = start; i <= end; i++) {
        pages.push(i);
      }

      if (currentPage < totalPages - 2) {
        pages.push('...');
      }

      // Always show last page
      pages.push(totalPages);
    }

    return pages;
  };

  const pageNumbers = getPageNumbers();

  const handlePageChange = (page: number) => {
    if (page >= 1 && page <= totalPages && page !== currentPage) {
      onPageChange(page);
    }
  };

  if (totalPages <= 1) {
    return null; // Don't show pagination if there's only one page
  }

  return (
    <div className={cn('flex flex-col sm:flex-row items-center justify-between gap-4', className)}>
      {/* Item count */}
      {showItemCount && (
        <div className="text-sm text-gray-600">
          Showing <span className="font-medium">{startItem}</span> to{' '}
          <span className="font-medium">{endItem}</span> of{' '}
          <span className="font-medium">{totalItems}</span> results
        </div>
      )}

      {/* Page controls */}
      <div className="flex items-center space-x-2">
        {/* First page */}
        <button
          onClick={() => handlePageChange(1)}
          disabled={currentPage === 1}
          className={cn(
            'p-2 rounded-lg border transition-colors',
            currentPage === 1
              ? 'border-gray-200 text-gray-400 cursor-not-allowed'
              : 'border-gray-300 text-gray-700 hover:bg-gray-50'
          )}
          aria-label="Go to first page"
        >
          <ChevronsLeft className="w-4 h-4" />
        </button>

        {/* Previous page */}
        <button
          onClick={() => handlePageChange(currentPage - 1)}
          disabled={currentPage === 1}
          className={cn(
            'p-2 rounded-lg border transition-colors',
            currentPage === 1
              ? 'border-gray-200 text-gray-400 cursor-not-allowed'
              : 'border-gray-300 text-gray-700 hover:bg-gray-50'
          )}
          aria-label="Go to previous page"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>

        {/* Page numbers */}
        <div className="flex items-center space-x-1">
          {pageNumbers.map((page, index) => {
            if (page === '...') {
              return (
                <span key={`ellipsis-${index}`} className="px-2 text-gray-400">
                  ...
                </span>
              );
            }

            const pageNum = page as number;
            const isActive = pageNum === currentPage;

            return (
              <button
                key={pageNum}
                onClick={() => handlePageChange(pageNum)}
                className={cn(
                  'min-w-[2.5rem] h-10 px-3 rounded-lg border font-medium transition-colors',
                  isActive
                    ? 'border-primary-600 bg-primary-600 text-white'
                    : 'border-gray-300 text-gray-700 hover:bg-gray-50'
                )}
                aria-label={`Go to page ${pageNum}`}
                aria-current={isActive ? 'page' : undefined}
              >
                {pageNum}
              </button>
            );
          })}
        </div>

        {/* Next page */}
        <button
          onClick={() => handlePageChange(currentPage + 1)}
          disabled={currentPage === totalPages}
          className={cn(
            'p-2 rounded-lg border transition-colors',
            currentPage === totalPages
              ? 'border-gray-200 text-gray-400 cursor-not-allowed'
              : 'border-gray-300 text-gray-700 hover:bg-gray-50'
          )}
          aria-label="Go to next page"
        >
          <ChevronRight className="w-4 h-4" />
        </button>

        {/* Last page */}
        <button
          onClick={() => handlePageChange(totalPages)}
          disabled={currentPage === totalPages}
          className={cn(
            'p-2 rounded-lg border transition-colors',
            currentPage === totalPages
              ? 'border-gray-200 text-gray-400 cursor-not-allowed'
              : 'border-gray-300 text-gray-700 hover:bg-gray-50'
          )}
          aria-label="Go to last page"
        >
          <ChevronsRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}