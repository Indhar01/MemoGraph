import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import MemoriesPage from './pages/MemoriesPage'
import MemoryDetailPage from './pages/MemoryDetailPage'
import SearchPage from './pages/SearchPage'
import GraphPage from './pages/GraphPage'
import AnalyticsPage from './pages/AnalyticsPage'
import CreateMemoryPage from './pages/CreateMemoryPage'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/memories" replace />} />
        <Route path="/memories" element={<MemoriesPage />} />
        <Route path="/memories/:id" element={<MemoryDetailPage />} />
        <Route path="/memories/new" element={<CreateMemoryPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
      </Routes>
    </Layout>
  )
}

export default App
