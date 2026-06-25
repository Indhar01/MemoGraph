---
title: Async pitfalls
memory_type: procedural
tags: [python, async, debugging]
salience: 0.75
---

Things that break async code in the order I keep hitting them:

1. **Calling sync I/O inside a coroutine.** `requests.get(...)` blocks the loop; use `httpx.AsyncClient` or `aiohttp`. Same trap with `time.sleep` — use `await asyncio.sleep`.
2. **Forgetting to `await`.** A bare coroutine call returns the coroutine object; nothing actually runs. Linters catch most cases; `RuntimeWarning: coroutine '...' was never awaited` is the runtime tell.
3. **Mixing event loops.** Don't `asyncio.run()` inside an already-running loop — use `asyncio.create_task` or `await` directly. FastAPI handlers are already in a loop.
4. **Unbounded concurrency.** `asyncio.gather` over 10,000 tasks DDoSes whatever you're calling. Wrap with a `Semaphore`.

See [[python-async]] for the why; [[fastapi-handlers]] for the most common context.
