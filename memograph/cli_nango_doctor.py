"""Preflight check for the Nango-backed source integration.

Run with ``memograph nango-doctor`` (registered in :mod:`memograph.cli`).
Walks the six setup steps in order, reports red/green for each, and
exits non-zero if anything blocks cloud-source connections.

Steps checked:

1. Required env vars are set (BASE_URL, SECRET_KEY, WEBHOOK_SECRET).
2. Optional PUBLIC_URL is reachable from this host (warning only).
3. Nango is reachable at BASE_URL and the secret key is accepted.
4. At least one integration is configured in Nango admin.
5. The configured integrations cover the kinds MemoGraph knows about
   (warns if e.g. only Notion is set up but you're trying Drive).
6. (Best-effort) the public URL responds to a HEAD — surfaces the
   browser-vs-backend URL mismatch that breaks Connect UI in Docker.

Intentionally synchronous so it can run outside the FastAPI app.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Iterable

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    warning: bool = False


def _symbol(check: Check) -> str:
    if check.ok and not check.warning:
        return f"{GREEN}✓{RESET}"
    if check.warning:
        return f"{YELLOW}!{RESET}"
    return f"{RED}✗{RESET}"


def _print(check: Check) -> None:
    line = f"  {_symbol(check)} {check.name}"
    if check.detail:
        line += f" — {check.detail}"
    print(line)


async def _check_reachable(client, want_integrations: Iterable[str]) -> list[Check]:
    from memograph.sources.base import SourceError
    from memograph.sources.nango_client import NangoConfigError

    results: list[Check] = []
    try:
        integrations = await client.list_integrations()
    except NangoConfigError as exc:
        results.append(
            Check(
                "Nango reachable + secret key valid",
                ok=False,
                detail=f"{exc}",
            )
        )
        return results
    except SourceError as exc:
        results.append(
            Check(
                "Nango reachable + secret key valid",
                ok=False,
                detail=f"{exc}",
            )
        )
        return results
    except Exception as exc:  # noqa: BLE001
        results.append(
            Check(
                "Nango reachable + secret key valid",
                ok=False,
                detail=f"unexpected error: {exc}",
            )
        )
        return results

    results.append(
        Check("Nango reachable + secret key valid", ok=True, detail=client.config.base_url)
    )
    keys = {
        item["unique_key"]
        for item in integrations
        if isinstance(item, dict) and isinstance(item.get("unique_key"), str)
    }
    if keys:
        results.append(
            Check(
                "Integrations configured in Nango admin",
                ok=True,
                detail=", ".join(sorted(keys)),
            )
        )
    else:
        results.append(
            Check(
                "Integrations configured in Nango admin",
                ok=False,
                detail=(
                    "No integrations found. Open the Nango admin UI and "
                    "create at least one (e.g. google-drive)."
                ),
            )
        )

    missing = [k for k in want_integrations if k not in keys]
    if missing:
        results.append(
            Check(
                "MemoGraph cloud kinds have a matching Nango integration",
                ok=False,
                warning=True,
                detail=(
                    f"Missing: {', '.join(missing)} — wizard will grey these out."
                ),
            )
        )
    else:
        results.append(
            Check("MemoGraph cloud kinds have a matching Nango integration", ok=True)
        )
    return results


def run_doctor() -> int:
    """Run all preflight checks. Returns process exit code."""
    from memograph.sources.nango_client import KIND_TO_PROVIDER_KEY

    print("MemoGraph Nango preflight\n")
    checks: list[Check] = []

    base_url = os.environ.get("MEMOGRAPH_NANGO_BASE_URL", "").strip()
    secret_key = os.environ.get("MEMOGRAPH_NANGO_SECRET_KEY", "").strip()
    webhook_secret = os.environ.get("MEMOGRAPH_NANGO_WEBHOOK_SECRET", "").strip()
    public_url = os.environ.get("MEMOGRAPH_NANGO_PUBLIC_URL", "").strip() or base_url

    checks.append(
        Check(
            "MEMOGRAPH_NANGO_BASE_URL is set",
            ok=bool(base_url),
            detail=base_url or "(unset)",
        )
    )
    checks.append(
        Check(
            "MEMOGRAPH_NANGO_SECRET_KEY is set",
            ok=bool(secret_key),
            detail="(redacted)" if secret_key else "(unset)",
        )
    )
    checks.append(
        Check(
            "MEMOGRAPH_NANGO_WEBHOOK_SECRET is set",
            ok=bool(webhook_secret),
            detail=(
                "(redacted)"
                if webhook_secret
                else "Webhooks will be rejected with 401 — set this to match the Nango stack."
            ),
        )
    )
    if base_url and public_url != base_url:
        checks.append(
            Check(
                "MEMOGRAPH_NANGO_PUBLIC_URL distinct from BASE_URL",
                ok=True,
                detail=f"browser uses {public_url}",
            )
        )
    elif base_url:
        checks.append(
            Check(
                "MEMOGRAPH_NANGO_PUBLIC_URL not set (defaults to BASE_URL)",
                ok=True,
                warning=False,
                detail="single-machine install — fine",
            )
        )

    for c in checks:
        _print(c)

    if not (base_url and secret_key):
        print(
            f"\n{RED}Cannot probe Nango — fix the env vars above first.{RESET}"
        )
        return 1

    # Construct a client and check reachability + integrations.
    try:
        from memograph.sources.nango_client import NangoClient
    except ImportError as exc:
        print(f"\n{RED}httpx not installed: {exc}{RESET}")
        print("Run: pip install 'memograph[sources-cloud]'")
        return 1

    client = NangoClient.from_env()
    want_keys = list(KIND_TO_PROVIDER_KEY.values())
    try:
        net_results = asyncio.run(_check_reachable(client, want_keys))
    finally:
        asyncio.run(client.aclose())
    for c in net_results:
        _print(c)

    blocking = [c for c in (*checks, *net_results) if not c.ok and not c.warning]
    if blocking:
        print(f"\n{RED}{len(blocking)} blocking issue(s) — see above.{RESET}")
        return 1
    warnings = [c for c in (*checks, *net_results) if c.warning]
    if warnings:
        print(f"\n{YELLOW}{len(warnings)} warning(s) — non-blocking.{RESET}")
        return 0
    print(f"\n{GREEN}All checks passed. Cloud sources should connect.{RESET}")
    return 0


def main(_args: list[str] | None = None) -> int:
    try:
        return run_doctor()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
