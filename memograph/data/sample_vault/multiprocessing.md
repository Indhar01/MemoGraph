---
title: multiprocessing
memory_type: semantic
tags: [python, parallelism, fundamentals]
salience: 0.7
---

`multiprocessing` runs Python code on multiple OS processes, sidestepping the GIL. Pick it for CPU-bound work — image processing, ML inference without GPU, parsing big files.

Tradeoffs vs. [[python-async]]: heavier per-task (process creation isn't free), workers can't share Python objects directly (pickle overhead at every boundary), and stack traces are harder to read across the IPC seam. Use `concurrent.futures.ProcessPoolExecutor` rather than raw `Process` unless you have a specific reason.

For mixed workloads see [[concurrency-decision]].
