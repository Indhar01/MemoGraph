---
title: Python async
memory_type: semantic
tags: [python, async, fundamentals]
salience: 0.85
---

`asyncio` is Python's standard library for writing concurrent code with `async`/`await`. It runs an event loop on a single thread; coroutines yield control at `await` points so the loop can multiplex many in-flight operations.

Use it when you're I/O-bound — many sockets, many HTTP calls, many database queries. Don't use it for CPU-bound work; that's what [[multiprocessing]] is for. The cardinal sin is calling a blocking sync function inside a coroutine — it stalls the whole loop. See [[async-pitfalls]] for the rest of the foot-guns.
