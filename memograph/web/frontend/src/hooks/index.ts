/**
 * Custom React hooks for MemoGraph Web UI
 *
 * Collection of reusable hooks for common patterns:
 * - useDebounce: Debounce rapidly changing values
 * - useLocalStorage: Persist state in localStorage
 * - useMediaQuery: Responsive behavior based on media queries
 */

import { useState, useEffect, useCallback, useRef } from 'react';

// ============================================================================
// useDebounce Hook
// ============================================================================

/**
 * Debounces a value, delaying updates until the value has stopped changing
 * for the specified delay period.
 *
 * @param value - The value to debounce
 * @param delay - The delay in milliseconds (default: 500ms)
 * @returns The debounced value
 *
 * @example
 * ```tsx
 * const [searchQuery, setSearchQuery] = useState('');
 * const debouncedQuery = useDebounce(searchQuery, 300);
 *
 * // debouncedQuery will only update 300ms after the user stops typing
 * useEffect(() => {
 *   if (debouncedQuery) {
 *     performSearch(debouncedQuery);
 *   }
 * }, [debouncedQuery]);
 * ```
 */
export function useDebounce<T>(value: T, delay: number = 500): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    // Set up the timeout to update the debounced value
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    // Clean up the timeout if value changes before delay expires
    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

// ============================================================================
// useLocalStorage Hook
// ============================================================================

/**
 * Persists state in localStorage with automatic serialization/deserialization.
 * Syncs across tabs and provides type safety.
 *
 * @param key - The localStorage key
 * @param initialValue - The initial value if nothing is stored
 * @returns A tuple of [storedValue, setValue, removeValue]
 *
 * @example
 * ```tsx
 * const [theme, setTheme, removeTheme] = useLocalStorage('theme', 'light');
 *
 * // Update theme
 * setTheme('dark');
 *
 * // Remove from localStorage
 * removeTheme();
 * ```
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T
): [T, (value: T | ((val: T) => T)) => void, () => void] {
  // State to store our value
  // Pass initial state function to useState so logic is only executed once
  const [storedValue, setStoredValue] = useState<T>(() => {
    if (typeof window === 'undefined') {
      return initialValue;
    }

    try {
      const item = window.localStorage.getItem(key);
      return item ? JSON.parse(item) : initialValue;
    } catch (error) {
      console.warn(`Error reading localStorage key "${key}":`, error);
      return initialValue;
    }
  });

  // Return a wrapped version of useState's setter function that
  // persists the new value to localStorage
  const setValue = useCallback(
    (value: T | ((val: T) => T)) => {
      try {
        // Allow value to be a function so we have same API as useState
        const valueToStore = value instanceof Function ? value(storedValue) : value;

        // Save state
        setStoredValue(valueToStore);

        // Save to local storage
        if (typeof window !== 'undefined') {
          window.localStorage.setItem(key, JSON.stringify(valueToStore));

          // Dispatch custom event to sync across tabs
          window.dispatchEvent(new CustomEvent('local-storage', {
            detail: { key, value: valueToStore }
          }));
        }
      } catch (error) {
        console.warn(`Error setting localStorage key "${key}":`, error);
      }
    },
    [key, storedValue]
  );

  // Function to remove the value from localStorage
  const removeValue = useCallback(() => {
    try {
      setStoredValue(initialValue);
      if (typeof window !== 'undefined') {
        window.localStorage.removeItem(key);
        window.dispatchEvent(new CustomEvent('local-storage', {
          detail: { key, value: null }
        }));
      }
    } catch (error) {
      console.warn(`Error removing localStorage key "${key}":`, error);
    }
  }, [key, initialValue]);

  // Listen for changes from other tabs/windows
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent | CustomEvent) => {
      if ('key' in e && e.key === key && e.newValue !== null) {
        try {
          setStoredValue(JSON.parse(e.newValue));
        } catch (error) {
          console.warn(`Error parsing localStorage update for key "${key}":`, error);
        }
      } else if ('detail' in e && e.detail.key === key) {
        setStoredValue(e.detail.value ?? initialValue);
      }
    };

    window.addEventListener('storage', handleStorageChange as EventListener);
    window.addEventListener('local-storage', handleStorageChange as EventListener);

    return () => {
      window.removeEventListener('storage', handleStorageChange as EventListener);
      window.removeEventListener('local-storage', handleStorageChange as EventListener);
    };
  }, [key, initialValue]);

  return [storedValue, setValue, removeValue];
}

// ============================================================================
// useMediaQuery Hook
// ============================================================================

/**
 * Tracks whether a media query matches the current viewport.
 * Useful for responsive behavior and conditional rendering.
 *
 * @param query - The media query string to match
 * @returns Whether the media query currently matches
 *
 * @example
 * ```tsx
 * const isMobile = useMediaQuery('(max-width: 768px)');
 * const isDarkMode = useMediaQuery('(prefers-color-scheme: dark)');
 * const prefersReducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
 *
 * return (
 *   <div>
 *     {isMobile ? <MobileNav /> : <DesktopNav />}
 *   </div>
 * );
 * ```
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return window.matchMedia(query).matches;
    }
    return false;
  });

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const mediaQuery = window.matchMedia(query);

    // Set initial value
    setMatches(mediaQuery.matches);

    // Create event listener function
    const handleChange = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    // Modern browsers
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handleChange);
      return () => mediaQuery.removeEventListener('change', handleChange);
    }
    // Fallback for older browsers
    else {
      mediaQuery.addListener(handleChange);
      return () => mediaQuery.removeListener(handleChange);
    }
  }, [query]);

  return matches;
}

// ============================================================================
// useOnClickOutside Hook
// ============================================================================

/**
 * Detects clicks outside a referenced element and triggers a callback.
 * Useful for closing dropdowns, modals, and popovers.
 *
 * @param ref - The ref of the element to detect outside clicks for
 * @param handler - Callback function to execute on outside click
 *
 * @example
 * ```tsx
 * const dropdownRef = useRef<HTMLDivElement>(null);
 * const [isOpen, setIsOpen] = useState(false);
 *
 * useOnClickOutside(dropdownRef, () => setIsOpen(false));
 *
 * return (
 *   <div ref={dropdownRef}>
 *     {isOpen && <DropdownMenu />}
 *   </div>
 * );
 * ```
 */
export function useOnClickOutside<T extends HTMLElement = HTMLElement>(
  ref: React.RefObject<T>,
  handler: (event: MouseEvent | TouchEvent) => void
): void {
  useEffect(() => {
    const listener = (event: MouseEvent | TouchEvent) => {
      const el = ref?.current;

      // Do nothing if clicking ref's element or descendent elements
      if (!el || el.contains(event.target as Node)) {
        return;
      }

      handler(event);
    };

    document.addEventListener('mousedown', listener);
    document.addEventListener('touchstart', listener);

    return () => {
      document.removeEventListener('mousedown', listener);
      document.removeEventListener('touchstart', listener);
    };
  }, [ref, handler]);
}

// ============================================================================
// useKeyPress Hook
// ============================================================================

/**
 * Detects when a specific key or key combination is pressed.
 * Supports modifier keys (Ctrl, Alt, Shift, Meta).
 *
 * @param targetKey - The key to detect (e.g., 'Enter', 'Escape', 'k')
 * @param modifiers - Optional modifier keys
 * @returns Whether the key (with modifiers) is currently pressed
 *
 * @example
 * ```tsx
 * const searchPressed = useKeyPress('k', { meta: true }); // Cmd+K
 * const escapePressed = useKeyPress('Escape');
 *
 * useEffect(() => {
 *   if (searchPressed) {
 *     openSearchModal();
 *   }
 * }, [searchPressed]);
 * ```
 */
export function useKeyPress(
  targetKey: string,
  modifiers?: { ctrl?: boolean; alt?: boolean; shift?: boolean; meta?: boolean }
): boolean {
  const [keyPressed, setKeyPressed] = useState(false);

  useEffect(() => {
    const downHandler = (event: KeyboardEvent) => {
      const modifiersMatch =
        (!modifiers?.ctrl || event.ctrlKey) &&
        (!modifiers?.alt || event.altKey) &&
        (!modifiers?.shift || event.shiftKey) &&
        (!modifiers?.meta || event.metaKey);

      if (event.key === targetKey && modifiersMatch) {
        setKeyPressed(true);
      }
    };

    const upHandler = (event: KeyboardEvent) => {
      if (event.key === targetKey) {
        setKeyPressed(false);
      }
    };

    window.addEventListener('keydown', downHandler);
    window.addEventListener('keyup', upHandler);

    return () => {
      window.removeEventListener('keydown', downHandler);
      window.removeEventListener('keyup', upHandler);
    };
  }, [targetKey, modifiers]);

  return keyPressed;
}

// ============================================================================
// usePrevious Hook
// ============================================================================

/**
 * Returns the previous value of a state or prop.
 * Useful for detecting changes and animations.
 *
 * @param value - The value to track
 * @returns The previous value
 *
 * @example
 * ```tsx
 * const [count, setCount] = useState(0);
 * const prevCount = usePrevious(count);
 *
 * console.log(`Count changed from ${prevCount} to ${count}`);
 * ```
 */
export function usePrevious<T>(value: T): T | undefined {
  const ref = useRef<T>();

  useEffect(() => {
    ref.current = value;
  }, [value]);

  return ref.current;
}

// ============================================================================
// useInterval Hook
// ============================================================================

/**
 * Declarative setInterval with automatic cleanup.
 * Can be paused by passing null as the delay.
 *
 * @param callback - Function to call on each interval
 * @param delay - Delay in milliseconds, or null to pause
 *
 * @example
 * ```tsx
 * const [count, setCount] = useState(0);
 * const [isRunning, setIsRunning] = useState(true);
 *
 * useInterval(
 *   () => setCount(c => c + 1),
 *   isRunning ? 1000 : null
 * );
 * ```
 */
export function useInterval(callback: () => void, delay: number | null): void {
  const savedCallback = useRef<() => void>();

  // Remember the latest callback
  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  // Set up the interval
  useEffect(() => {
    if (delay === null) {
      return;
    }

    const tick = () => {
      savedCallback.current?.();
    };

    const id = setInterval(tick, delay);
    return () => clearInterval(id);
  }, [delay]);
}
