"""``S3Source`` — S3 (and S3-compatible) bucket as a Markdown vault.

Phase 2 adapter. Treats a bucket-prefix as a flat namespace of
``.md`` objects: ``list_documents`` paginates ``ListObjectsV2``,
``read_document`` is ``GetObject``, ``write_document`` is
``PutObject``. The key is the doc id, with a configurable
``prefix`` stripped on read / re-added on write so the local cache
sees clean relative paths.

Supports S3-compatible backends (MinIO, Backblaze B2, Wasabi,
Cloudflare R2, DigitalOcean Spaces) through the standard boto3
``endpoint_url`` override. Auth is whatever boto3 already supports:
explicit access-key/secret in the source config, ambient AWS
credentials via env / instance profile, or assumed roles. The
adapter does not embed credentials — operators choose the auth
chain at deploy time.

Optional dependency: ``boto3``. The adapter imports lazily so the
default ``pip install memograph`` does not pull AWS SDKs.

Config shape (in ``SourceConfig.params``):

.. code-block:: json

    {
      "bucket": "my-bucket",
      "prefix": "memograph/",       // optional, default ""
      "region": "us-east-1",        // optional
      "endpoint_url": "https://...", // optional (MinIO, R2, etc.)
      "access_key_id": "...",       // optional
      "secret_access_key": "...",   // optional
      "session_token": "..."        // optional (STS)
    }

Tokens passed via ``params`` are not encrypted by this adapter —
the operator should prefer the ambient AWS credential chain
(env / instance profile / SSO) and reserve ``params`` for
configuration that's safe to keep in a JSON file. The encrypted
token store in :mod:`memograph.sources.oauth.token_store` is for
OAuth refresh tokens (GDrive, OneDrive) — Phase 3+.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from memograph.sources.base import (
    ChangeEvent,
    Document,
    DocumentEncoding,
    DocumentRef,
    Source,
    SourceAuthError,
    SourceConfig,
    SourceError,
    SourceHealth,
    SourceHealthStatus,
    SourceNotFoundError,
    SyncMode,
    SyncStats,
    WriteResult,
)

logger = logging.getLogger(__name__)

DEFAULT_MARKDOWN_SUFFIX = ".md"


class S3Source(Source):
    """S3 / S3-compatible bucket as a Markdown source.

    Construction is cheap. The boto3 client is built lazily on the
    first I/O call so a registry warm-up of many sources does not
    fan out parallel TLS handshakes to S3.
    """

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        bucket = config.params.get("bucket")
        if not bucket or not isinstance(bucket, str):
            raise SourceError(
                f"S3Source {config.source_id!r} requires "
                "params['bucket']; got empty/missing value"
            )
        self._bucket: str = bucket
        # Prefix can be empty (whole bucket = vault) or a folder
        # path. Normalise to always end with "/" when non-empty so
        # key construction is unambiguous.
        prefix = str(config.params.get("prefix", "") or "")
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"
        self._prefix: str = prefix
        self._suffix: str = str(
            config.params.get("suffix", DEFAULT_MARKDOWN_SUFFIX) or DEFAULT_MARKDOWN_SUFFIX
        )
        self._client: Any = None  # lazy boto3 client

    # --- lazy boto3 wiring ---

    def _build_client(self) -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise SourceError(
                "S3Source requires boto3. "
                "Install with: pip install 'memograph[sources-s3]'"
            ) from exc
        params = self.config.params
        kwargs: dict[str, Any] = {}
        if region := params.get("region"):
            kwargs["region_name"] = region
        if endpoint := params.get("endpoint_url"):
            kwargs["endpoint_url"] = endpoint
        # Explicit creds only if both are present. Otherwise fall
        # back to boto3's default chain (env, profile, instance role).
        ak = params.get("access_key_id")
        sk = params.get("secret_access_key")
        if ak and sk:
            kwargs["aws_access_key_id"] = ak
            kwargs["aws_secret_access_key"] = sk
            if st := params.get("session_token"):
                kwargs["aws_session_token"] = st
        return boto3.client("s3", **kwargs)

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _doc_id_from_key(self, key: str) -> str:
        """S3 key minus prefix = stable doc id used by callers.

        Keys outside the prefix should not appear (the ListObjectsV2
        call is prefix-scoped) but the guard is defensive against
        future code paths that pass arbitrary keys.
        """
        if self._prefix and key.startswith(self._prefix):
            return key[len(self._prefix):]
        return key

    def _key_from_doc_id(self, doc_id: str) -> str:
        # The opposite direction: add the prefix back. We do not
        # resolve the path against the filesystem here — S3 keys are
        # opaque to the local FS and treating ``..`` segments as
        # traversal would prevent legitimate keys like
        # ``versions/..backup`` (yes, those exist in real buckets).
        # Validation is at registration time: the prefix is operator-
        # configured and trusted.
        return f"{self._prefix}{doc_id}"

    # --- document ops ---

    async def list_documents(self) -> AsyncIterator[DocumentRef]:
        import asyncio

        client = self._ensure_client()

        def _list_page(continuation_token: str | None) -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": self._prefix,
                "MaxKeys": 1000,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            return client.list_objects_v2(**kwargs)

        token: str | None = None
        while True:
            try:
                page = await asyncio.to_thread(_list_page, token)
            except Exception as exc:  # noqa: BLE001 — boto3 wraps many error types
                # Auth-y errors get a specific subclass so the worker
                # can pause retries; everything else is generic.
                if _is_auth_error(exc):
                    raise SourceAuthError(str(exc)) from exc
                raise SourceError(f"S3 list failed: {exc}") from exc
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if self._suffix and not key.endswith(self._suffix):
                    continue
                yield DocumentRef(
                    doc_id=self._doc_id_from_key(key),
                    title=Path(key).stem,
                    modified_at=obj["LastModified"].astimezone(timezone.utc),
                    size_bytes=obj.get("Size"),
                    metadata={
                        "key": key,
                        "etag": obj.get("ETag", "").strip('"'),
                        "storage_class": obj.get("StorageClass"),
                    },
                )
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
            # Yield to the event loop between pages so a 100k-object
            # bucket doesn't starve other coroutines.
            await asyncio.sleep(0)

    async def read_document(self, doc_id: str) -> Document:
        import asyncio

        client = self._ensure_client()
        key = self._key_from_doc_id(doc_id)

        def _read() -> tuple[bytes, dict[str, Any]]:
            try:
                resp = client.get_object(Bucket=self._bucket, Key=key)
            except Exception as exc:  # noqa: BLE001
                if _is_not_found_error(exc):
                    raise SourceNotFoundError(
                        f"S3 object not found: {key}"
                    ) from exc
                if _is_auth_error(exc):
                    raise SourceAuthError(str(exc)) from exc
                raise SourceError(f"S3 get failed: {exc}") from exc
            body = resp["Body"].read()
            return body, resp

        body, resp = await asyncio.to_thread(_read)
        # We assume Markdown content is utf-8; raise loudly otherwise
        # rather than silently corrupt the local vault with mojibake.
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceError(
                f"S3 object {key} is not valid UTF-8 Markdown"
            ) from exc
        return Document(
            ref=DocumentRef(
                doc_id=doc_id,
                title=Path(key).stem,
                modified_at=resp["LastModified"].astimezone(timezone.utc),
                size_bytes=resp.get("ContentLength"),
                metadata={
                    "key": key,
                    "etag": resp.get("ETag", "").strip('"'),
                },
            ),
            content=content,
            encoding=DocumentEncoding.MARKDOWN,
        )

    async def write_document(self, doc: Document) -> WriteResult:
        import asyncio

        if doc.encoding is DocumentEncoding.BINARY:
            raise SourceError(
                f"S3Source does not write binary documents in Phase 2 "
                f"(doc_id={doc.ref.doc_id!r})"
            )
        client = self._ensure_client()
        key = self._key_from_doc_id(doc.ref.doc_id)
        assert isinstance(doc.content, str)
        body = doc.content.encode("utf-8")

        def _put() -> dict[str, Any]:
            try:
                return client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=body,
                    ContentType="text/markdown; charset=utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                if _is_auth_error(exc):
                    raise SourceAuthError(str(exc)) from exc
                raise SourceError(f"S3 put failed: {exc}") from exc

        resp = await asyncio.to_thread(_put)
        return WriteResult(
            doc_id=doc.ref.doc_id,
            version=str(resp.get("ETag", "")).strip('"') or None,
            written_at=datetime.now(timezone.utc),
        )

    async def watch(self) -> AsyncIterator[ChangeEvent]:
        # S3 push notifications require EventBridge / SNS wiring on
        # the AWS side, which the adapter can't bootstrap itself.
        # Phase 2 ships polling-only; Phase 3+ can add a webhook
        # receiver that the operator points an SNS subscription at.
        if False:  # pragma: no cover
            yield ChangeEvent.__new__(ChangeEvent)  # type: ignore[call-arg]
        return

    async def materialize_to_vault(self, vault_path: Path) -> SyncStats:
        """Pull every ``*.md`` under the prefix into ``vault_path``.

        Skips objects whose local copy is already up to date by
        size + mtime — cheap heuristic that avoids re-downloading
        on every sync cycle. ETag-based comparison would be more
        accurate but requires HEAD per object before deciding to
        skip; the size/mtime check is sufficient for typical vault
        workloads where edits change both.
        """
        started = perf_counter()
        vault = Path(vault_path).expanduser()
        vault.mkdir(parents=True, exist_ok=True)

        seen = written = 0
        async for ref in self.list_documents():
            seen += 1
            dst = vault / ref.doc_id
            if dst.exists():
                dst_stat = dst.stat()
                if (
                    ref.size_bytes is not None
                    and dst_stat.st_size == ref.size_bytes
                    and datetime.fromtimestamp(
                        dst_stat.st_mtime, tz=timezone.utc
                    ) >= ref.modified_at
                ):
                    continue
            doc = await self.read_document(ref.doc_id)
            dst.parent.mkdir(parents=True, exist_ok=True)
            assert isinstance(doc.content, str)
            dst.write_text(doc.content, encoding="utf-8")
            written += 1

        return SyncStats(
            mode=SyncMode.FULL,
            documents_seen=seen,
            documents_written=written,
            documents_deleted=0,
            duration_seconds=perf_counter() - started,
        )

    async def health(self) -> SourceHealth:
        import asyncio

        try:
            client = self._ensure_client()
        except SourceError as exc:
            # Missing boto3 / bad credentials. Surface as FAILED
            # rather than 500 the health endpoint.
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            # Any other construction error (e.g. boto3.client raised
            # because of bad config or transient network issue).
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )

        def _head() -> int | None:
            try:
                resp = client.list_objects_v2(
                    Bucket=self._bucket,
                    Prefix=self._prefix,
                    MaxKeys=1,
                )
                # Approximate document total via KeyCount on a small
                # page. Accurate counting requires walking the whole
                # listing and is too expensive for a health probe.
                # Documented as "as of last successful list" rather
                # than precise total.
                return resp.get("KeyCount", 0) if resp else 0
            except Exception:  # noqa: BLE001
                return None

        try:
            count = await asyncio.to_thread(_head)
        except Exception as exc:  # noqa: BLE001
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error=str(exc),
            )
        if count is None:
            return SourceHealth(
                status=SourceHealthStatus.FAILED,
                checked_at=datetime.now(timezone.utc),
                last_error="list_objects_v2 failed; check credentials and bucket access",
            )
        return SourceHealth(
            status=SourceHealthStatus.OK,
            checked_at=datetime.now(timezone.utc),
            last_successful_sync_at=datetime.now(timezone.utc),
            documents_total=count if count > 0 else None,
        )

    @property
    def supports_watch(self) -> bool:
        # Phase 2 is poll-only. EventBridge wiring is Phase 3+.
        return False


# --- error classification helpers ---


def _is_auth_error(exc: BaseException) -> bool:
    """True if a boto3 exception looks like an auth failure.

    We sniff on the exception's response error code where present;
    this is robust across ClientError / NoCredentialsError /
    SSO-token-expired without importing botocore exception classes
    at module load time (would break the optional-dep guarantee).
    """
    cls_name = type(exc).__name__
    if cls_name in {
        "NoCredentialsError",
        "PartialCredentialsError",
        "SSOTokenLoadError",
        "TokenRetrievalError",
    }:
        return True
    code = _error_code(exc)
    return code in {
        "AccessDenied",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "ExpiredToken",
        "TokenRefreshRequired",
    }


def _is_not_found_error(exc: BaseException) -> bool:
    return _error_code(exc) in {"NoSuchKey", "404"}


def _error_code(exc: BaseException) -> str | None:
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        err = resp.get("Error", {})
        if isinstance(err, dict):
            code = err.get("Code")
            if isinstance(code, str):
                return code
    return None


__all__ = ["S3Source"]
