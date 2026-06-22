---
title: FastAPI dependencies
memory_type: semantic
tags: [python, fastapi, web, patterns]
salience: 0.7
---

`Depends(...)` is FastAPI's dependency injection. A dependency is just a callable; FastAPI calls it for each request, caches the result within that request, and injects it into your handler.

Three patterns I use constantly:

1. **Auth/identity** — `Depends(get_current_user)` returns the authenticated `User` or raises 401. Every authenticated route uses this; it keeps auth logic out of the handler.
2. **Resource resolution** — `Depends(kernel_for_request)` resolves the right backend object based on request context (e.g. picking the right tenant kernel). See [[fastapi-handlers]] for how this composes with `async`.
3. **Validation** — heavy validators that need DB access can live in a dependency rather than in the Pydantic model.

Cached per-request, so calling `Depends(get_current_user)` on five sub-dependencies of the same handler runs the function once.
