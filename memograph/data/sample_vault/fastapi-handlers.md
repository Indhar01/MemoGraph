---
title: FastAPI handlers
memory_type: semantic
tags: [python, fastapi, web, async]
salience: 0.8
---

FastAPI route handlers can be either `def` or `async def`. The framework dispatches each correctly: `async def` handlers run on the event loop directly, `def` handlers are pushed to a threadpool so they don't block the loop.

Practical rule: if your handler awaits anything (DB driver, HTTP client, async file I/O), use `async def`. If it's purely synchronous CPU/IO with sync libraries, `def` is fine and FastAPI will threadpool it for you. Mixing is allowed — pick per route.

[[async-pitfalls]] applies inside any `async def` handler. For dependency injection patterns see [[fastapi-dependencies]].
