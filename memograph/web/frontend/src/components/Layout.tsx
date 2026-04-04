import { ReactNode, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Brain, Search, Network, BarChart3, PlusCircle, Sun, Moon } from 'lucide-react'
import { useTheme } from '../lib/theme'
import { useKeyboardShortcuts } from '../lib/keyboardShortcuts'

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const { resolvedTheme, toggleTheme } = useTheme()
  const { registerShortcut, toggleHelp } = useKeyboardShortcuts()

  // Register global keyboard shortcuts
  useEffect(() => {
    // Navigation shortcuts
    registerShortcut({
      key: 'k',
      meta: true,
      description: 'Go to Search',
      action: () => navigate('/search'),
      category: 'Navigation'
    });

    registerShortcut({
      key: 'n',
      meta: true,
      description: 'Create New Memory',
      action: () => navigate('/memories/new'),
      category: 'Navigation'
    });

    registerShortcut({
      key: '1',
      meta: true,
      description: 'Go to Memories',
      action: () => navigate('/memories'),
      category: 'Navigation'
    });

    registerShortcut({
      key: '2',
      meta: true,
      description: 'Go to Graph',
      action: () => navigate('/graph'),
      category: 'Navigation'
    });

    registerShortcut({
      key: '3',
      meta: true,
      description: 'Go to Analytics',
      action: () => navigate('/analytics'),
      category: 'Navigation'
    });

    // UI shortcuts
    registerShortcut({
      key: 'd',
      meta: true,
      description: 'Toggle Dark Mode',
      action: toggleTheme,
      category: 'UI'
    });

    registerShortcut({
      key: '/',
      meta: true,
      description: 'Show Keyboard Shortcuts',
      action: toggleHelp,
      category: 'Help'
    });
  }, [registerShortcut, navigate, toggleTheme, toggleHelp]);

  const navItems = [
    { path: '/memories', label: 'Memories', icon: Brain },
    { path: '/search', label: 'Search', icon: Search },
    { path: '/graph', label: 'Graph', icon: Network },
    { path: '/analytics', label: 'Analytics', icon: BarChart3 },
  ]

  const isActive = (path: string) => {
    return location.pathname.startsWith(path)
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <Link to="/" className="flex items-center space-x-2">
              <Brain className="w-8 h-8 text-primary-600" />
              <span className="text-xl font-bold text-gray-900 dark:text-gray-100">MemoGraph</span>
            </Link>

            <nav className="flex space-x-1">
              {navItems.map((item) => {
                const Icon = item.icon
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={`flex items-center space-x-2 px-4 py-2 rounded-lg transition-colors ${
                      isActive(item.path)
                        ? 'bg-primary-50 dark:bg-primary-900 text-primary-700 dark:text-primary-300 font-medium'
                        : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800'
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                    <span>{item.label}</span>
                  </Link>
                )
              })}
            </nav>

            <div className="flex items-center space-x-2">
              <button
                onClick={toggleTheme}
                className="p-2 rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800 transition-colors"
                aria-label="Toggle theme"
                title={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} mode`}
              >
                {resolvedTheme === 'dark' ? (
                  <Sun className="w-5 h-5" />
                ) : (
                  <Moon className="w-5 h-5" />
                )}
              </button>

              <Link
                to="/memories/new"
                className="btn btn-primary flex items-center space-x-2"
              >
                <PlusCircle className="w-5 h-5" />
                <span>New Memory</span>
              </Link>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700 py-6">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center text-sm text-gray-500 dark:text-gray-400">
            <p>MemoGraph v1.0.0 - Production-Ready Memory Management System</p>
            <p className="mt-1">Powered by Graph Attention Memory (GAM)</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
