---
title: Concurrency decision tree
memory_type: procedural
tags: [python, concurrency, decision]
salience: 0.9
---

Quick decision for "which Python concurrency primitive should I use":

- **CPU-bound, single machine** → [[multiprocessing]] (or `concurrent.futures.ProcessPoolExecutor`).
- **I/O-bound, modern code** → [[python-async]] with `async`/`await`.
- **I/O-bound, can't rewrite legacy sync code** → `concurrent.futures.ThreadPoolExecutor`. Threads still help here because the GIL releases on I/O.
- **CPU-bound, distributed across machines** → out of scope for this rule of thumb — reach for Ray, Dask, or a job queue (see [[task-queues]]).

The mistake people make is using threads for CPU work (the GIL still serializes) or async for CPU work (one slow coroutine stalls everything).
