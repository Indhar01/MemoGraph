import { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Brain, Search, Network, BarChart3, PlusCircle } from 'lucide-react'

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation()

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
      <header className="bg-white border-b sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <Link to="/" className="flex items-center space-x-2">
              <Brain className="w-8 h-8 text-primary-600" />
              <span className="text-xl font-bold text-gray-900">MemoGraph</span>
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
                        ? 'bg-primary-50 text-primary-700 font-medium'
                        : 'text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                    <span>{item.label}</span>
                  </Link>
                )
              })}
            </nav>

            <Link
              to="/memories/new"
              className="btn btn-primary flex items-center space-x-2"
            >
              <PlusCircle className="w-5 h-5" />
              <span>New Memory</span>
            </Link>
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
      <footer className="bg-white border-t py-6">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center text-sm text-gray-500">
            <p>MemoGraph v1.0.0 - Production-Ready Memory Management System</p>
            <p className="mt-1">Powered by Graph Attention Memory (GAM)</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
