## 🚀 MemoGraph Web UI - Quick Start Guide

This guide will help you get the MemoGraph web UI running in under 5 minutes!

### Step 1: Start the Backend Server

Open a terminal and run:

```bash
# Method 1: Using the helper script
python memograph/web/run_web_ui.py "C:\Users\INDIRAKUMARS\Documents\my-vault"

# Method 2: Direct command
python -c "from memograph.web.backend.server import run_dev_server; run_dev_server(r'C:\Users\INDIRAKUMARS\Documents\my-vault')"
```

You should see:
```
🧠 MemoGraph Web UI Server
============================================================
📁 Vault Path: C:\Users\INDIRAKUMARS\Documents\my-vault
🌐 API URL: http://localhost:8000
📚 API Docs: http://localhost:8000/api/docs
💚 Health Check: http://localhost:8000/api/health
============================================================

⏳ Starting server...

INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

✅ **Test it:** Open http://localhost:8000/api/health in your browser

### Step 2: Start the Frontend (Optional)

The backend serves a basic API that you can test via the Swagger docs at http://localhost:8000/api/docs

If you want the full React UI:

```bash
# Open a NEW terminal
cd memograph/web/frontend

# Install dependencies (first time only)
npm install

# Start the dev server
npm run dev
```

You should see:
```
  VITE v5.0.8  ready in 523 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
  ➜  press h + enter to show help
```

✅ **Test it:** Open http://localhost:5173 in your browser

### Step 3: Explore Your Vault

#### Using the API (Swagger UI)

1. Open http://localhost:8000/api/docs
2. Try these endpoints:
   - `GET /api/health` - Check server status
   - `GET /api/memories` - List all memories
   - `POST /api/search` - Search memories
   - `GET /api/analytics` - View statistics
   - `GET /api/graph` - Get graph data

#### Using the Web UI

1. Open http://localhost:5173
2. Navigate through:
   - **Memories** - Browse all your memories
   - **Search** - Find specific memories
   - **Graph** - Visualize connections
   - **Analytics** - See statistics

### Troubleshooting

#### Backend won't start?

```bash
# Check if port 8000 is already in use
netstat -ano | findstr :8000

# Install missing dependencies
pip install fastapi uvicorn pydantic
```

#### Frontend won't start?

```bash
# Make sure you're in the frontend directory
cd memograph/web/frontend

# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install
```

#### Can't see any memories?

Make sure your vault has `.md` files with YAML frontmatter:

```markdown
---
title: My First Memory
memory_type: fact
salience: 0.8
created: 2026-03-22T10:00:00Z
---

This is my first memory in MemoGraph!

#test #example
```

### Next Steps

1. **Create a Memory**: Use `POST /api/memories` or the "New Memory" button
2. **Search**: Try the search functionality with your vault content
3. **Explore the Graph**: See how your memories are connected
4. **Check Analytics**: View statistics about your memory vault

### Production Deployment

See the full [README.md](README.md) for:
- Docker deployment
- Production build instructions
- Security considerations
- Performance optimization

---

**Need Help?** Check the API docs at http://localhost:8000/api/docs or the main README.md
