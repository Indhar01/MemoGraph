# MemoGraph Web UI

Production-ready web interface for the MemoGraph memory management system.

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- npm or yarn

### Backend Setup

1. **Install Python dependencies:**
```bash
# From the project root
pip install -e .
pip install fastapi uvicorn python-multipart
```

2. **Start the backend server:**
```bash
# Point to your vault
python -m memograph.web.backend.server C:\Users\INDIRAKUMARS\Documents\my-vault

# Or use the provided function
python -c "from memograph.web.backend.server import run_dev_server; run_dev_server('C:\\Users\\INDIRAKUMARS\\Documents\\my-vault')"
```

The API will be available at `http://localhost:8000`
- API Documentation: `http://localhost:8000/api/docs`
- Health Check: `http://localhost:8000/api/health`

### Frontend Setup

1. **Install Node dependencies:**
```bash
cd memograph/web/frontend
npm install
```

2. **Start the development server:**
```bash
npm run dev
```

The UI will be available at `http://localhost:5173`

## 📁 Project Structure

```
memograph/web/
├── backend/
│   ├── __init__.py
│   ├── server.py              # FastAPI application
│   ├── models/
│   │   └── __init__.py        # Pydantic models
│   └── routes/
│       ├── memories.py        # Memory CRUD endpoints
│       ├── search.py          # Search endpoints
│       ├── graph.py           # Graph visualization endpoints
│       └── analytics.py       # Analytics endpoints
├── frontend/
│   ├── src/
│   │   ├── components/        # React components
│   │   ├── pages/             # Page components
│   │   ├── lib/               # API client & utilities
│   │   ├── App.tsx            # Main app component
│   │   ├── main.tsx           # Entry point
│   │   └── index.css          # Tailwind styles
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── tailwind.config.js
└── README.md                  # This file
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file in the frontend directory:

```env
VITE_API_URL=http://localhost:8000/api
```

### Backend Configuration

The backend server can be configured via parameters:

```python
from memograph.web.backend.server import create_app

app = create_app(
    vault_path="path/to/vault",
    use_gam=True  # Enable Graph Attention Memory
)
```

## 📊 Features

### 1. Memory Management
- **List View**: Browse all memories with pagination, filtering, and sorting
- **Detail View**: View complete memory content with links and metadata
- **Create/Edit**: Add new memories or update existing ones
- **Delete**: Remove memories from the vault

### 2. Advanced Search
- **Hybrid Retrieval**: Combines keyword, semantic, and graph-based search
- **Filters**: Filter by tags, memory type, salience
- **Autocomplete**: Smart suggestions as you type

### 3. Graph Visualization
- **Interactive Graph**: Visualize memory connections
- **Focus Mode**: Center on specific memories
- **Filter & Zoom**: Filter by tags, salience, etc.

### 4. Analytics Dashboard
- **Statistics**: Total memories, types, tags, salience
- **Trends**: Recent activity, most connected nodes
- **Distribution**: Visual charts of memory patterns

## 🔨 Development

### Frontend Development

```bash
cd memograph/web/frontend

# Install dependencies
npm install

# Start dev server with hot reload
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

### Backend Development

```bash
# Run with auto-reload (for development)
uvicorn memograph.web.backend.server:app --reload --host 0.0.0.0 --port 8000

# Or use the development server function
python memograph/web/backend/server.py /path/to/vault
```

## 🐳 Docker Deployment

### Build and Run with Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports:
      - "8000:8000"
    volumes:
      - ./vault:/app/vault
    environment:
      - VAULT_PATH=/app/vault

  frontend:
    build:
      context: ./memograph/web/frontend
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    depends_on:
      - backend
```

```bash
docker-compose up -d
```

## 📦 Production Build

### Frontend

```bash
cd memograph/web/frontend
npm run build
```

The built files will be in `dist/` and can be served by any static file server (nginx, Apache, etc.).

### Backend

```bash
# Install production dependencies
pip install gunicorn

# Run with Gunicorn
gunicorn memograph.web.backend.server:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

## 🧪 Testing

### Backend Tests

```bash
pytest tests/test_web_api.py -v
```

### Frontend Tests

```bash
cd memograph/web/frontend
npm test
```

## 🔒 Security Considerations

For production deployment:

1. **CORS**: Update CORS origins in `server.py`
2. **Authentication**: Add authentication middleware
3. **HTTPS**: Use SSL/TLS certificates
4. **Rate Limiting**: Add rate limiting middleware
5. **Input Validation**: All inputs are validated via Pydantic models
6. **Environment Variables**: Use environment variables for sensitive data

## 📝 API Documentation

Once the backend is running, visit:
- **Swagger UI**: http://localhost:8000/api/docs
- **ReDoc**: http://localhost:8000/api/redoc

## 🎨 UI Components

The frontend uses:
- **React 18** with TypeScript
- **Tailwind CSS** for styling
- **React Router** for navigation
- **TanStack Query** for data fetching
- **Recharts** for analytics visualizations
- **React Force Graph** for graph visualization
- **Lucide React** for icons

## 🤝 Contributing

1. Follow the existing code style
2. Add tests for new features
3. Update documentation as needed
4. Ensure all tests pass before submitting

## 📄 License

Same as MemoGraph main project.

## 🐛 Troubleshooting

### Backend won't start
- Check Python version (3.11+ required)
- Verify vault path exists
- Check port 8000 is not in use

### Frontend won't connect to backend
- Verify backend is running
- Check CORS settings in server.py
- Verify API_URL in .env file

### Graph visualization not working
- Check browser console for errors
- Verify graph data is being returned by API
- Try clearing browser cache

## 📞 Support

For issues or questions:
1. Check the [documentation](https://github.com/yourusername/memograph)
2. Open an issue on GitHub
3. Contact the maintainers

---

**Happy Memory Management! 🧠✨**
