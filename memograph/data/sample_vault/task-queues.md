---
title: Task queues
memory_type: semantic
tags: [python, distributed, infrastructure]
salience: 0.65
---

When a job needs to outlive a single web request, you reach for a task queue.

- **Celery** — battle-tested, brokered by Redis or RabbitMQ. Heavyweight; great when you already have ops capacity for it.
- **Dramatiq** — Celery's spiritual successor. Smaller surface, saner defaults, same broker model.
- **RQ** — simplest of the three; Redis-only; perfect for "I just need a background job, stop overthinking it".
- **arq** — async-native; pairs with [[python-async]] codebases naturally.

The decision split: small project → RQ or arq. Large project with complex routing/retries → Celery or Dramatiq. Don't reach for distributed workers (Ray, Dask) until you've felt actual queue pain.

Related: [[concurrency-decision]], [[fastapi-handlers]] (for kicking off jobs from handlers).
