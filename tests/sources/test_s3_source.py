"""Tests for :class:`memograph.sources.s3.S3Source`.

We stub at ``boto3.client`` rather than using moto so the tests
work without an extra dev dependency. The fake client returns
deterministic responses for ``list_objects_v2``, ``get_object``,
``put_object`` shaped exactly like the real AWS responses (the
shape is the contract; without it we'd be testing against our own
imagination).
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from memograph.sources.base import (
    Document,
    DocumentEncoding,
    DocumentRef,
    SourceAuthError,
    SourceConfig,
    SourceError,
    SourceHealthStatus,
    SourceKind,
    SourceNotFoundError,
)
from memograph.sources.s3 import S3Source


def _config(
    bucket: str = "test-bucket",
    prefix: str = "",
    **extras: Any,
) -> SourceConfig:
    params: dict[str, Any] = {"bucket": bucket, **extras}
    if prefix:
        params["prefix"] = prefix
    return SourceConfig(
        source_id="s3-test",
        kind=SourceKind.S3,
        display_name="S3 Test",
        params=params,
    )


class _FakeS3:
    """Minimal in-memory S3-like store. Returns response dicts in the
    shape boto3 hands back, so the adapter doesn't need to know it's
    talking to a fake."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.mtimes: dict[str, datetime] = {}

    def list_objects_v2(self, **kwargs):
        prefix = kwargs.get("Prefix", "") or ""
        keys = sorted(k for k in self.objects if k.startswith(prefix))
        # ContinuationToken pagination would normally split — we
        # return everything in one page so tests stay simple.
        contents = [
            {
                "Key": k,
                "LastModified": self.mtimes[k],
                "Size": len(self.objects[k]),
                "ETag": f'"etag-{k}"',
            }
            for k in keys
        ]
        return {
            "Contents": contents,
            "KeyCount": len(contents),
            "IsTruncated": False,
        }

    def get_object(self, Bucket, Key, **kwargs):
        if Key not in self.objects:
            err = type("ClientError", (Exception,), {})
            exc = err("not found")
            exc.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
            raise exc
        return {
            "Body": io.BytesIO(self.objects[Key]),
            "LastModified": self.mtimes[Key],
            "ContentLength": len(self.objects[Key]),
            "ETag": f'"etag-{Key}"',
        }

    def put_object(self, Bucket, Key, Body, **kwargs):
        body = Body if isinstance(Body, bytes) else Body.read()
        self.objects[Key] = body
        self.mtimes[Key] = datetime.now(timezone.utc)
        return {"ETag": f'"etag-{Key}"'}


@pytest.fixture
def fake_s3():
    return _FakeS3()


@pytest.fixture
def patch_boto3(fake_s3, monkeypatch):
    """Patch ``boto3.client`` to return our fake S3."""
    import boto3

    def _client(service_name, **kwargs):
        assert service_name == "s3"
        return fake_s3

    monkeypatch.setattr(boto3, "client", _client)
    return fake_s3


class TestConstruction:
    def test_requires_bucket(self) -> None:
        bad = SourceConfig(
            source_id="x",
            kind=SourceKind.S3,
            display_name="x",
            params={},
        )
        with pytest.raises(SourceError, match="requires"):
            S3Source(bad)

    def test_normalises_prefix(self) -> None:
        source = S3Source(_config(prefix="memos"))
        assert source._prefix == "memos/"

    def test_empty_prefix_is_ok(self) -> None:
        source = S3Source(_config())
        assert source._prefix == ""


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_lists_with_prefix(self, patch_boto3) -> None:
        fake = patch_boto3
        fake.objects = {
            "memos/alpha.md": b"# Alpha",
            "memos/beta.md": b"# Beta",
            "other/skip.md": b"# skip",
            "memos/skip.txt": b"# skip",
        }
        fake.mtimes = {k: datetime.now(timezone.utc) for k in fake.objects}
        source = S3Source(_config(prefix="memos"))
        refs = [r async for r in source.list_documents()]
        ids = sorted(r.doc_id for r in refs)
        # Prefix-stripped, .md only.
        assert ids == ["alpha.md", "beta.md"]

    @pytest.mark.asyncio
    async def test_empty_bucket(self, patch_boto3) -> None:
        source = S3Source(_config())
        refs = [r async for r in source.list_documents()]
        assert refs == []


class TestReadDocument:
    @pytest.mark.asyncio
    async def test_read_round_trip(self, patch_boto3) -> None:
        fake = patch_boto3
        fake.objects["memos/alpha.md"] = "# Alpha".encode("utf-8")
        fake.mtimes["memos/alpha.md"] = datetime.now(timezone.utc)
        source = S3Source(_config(prefix="memos"))
        doc = await source.read_document("alpha.md")
        assert doc.content == "# Alpha"
        assert doc.encoding is DocumentEncoding.MARKDOWN
        assert doc.ref.doc_id == "alpha.md"

    @pytest.mark.asyncio
    async def test_missing_raises(self, patch_boto3) -> None:
        source = S3Source(_config())
        with pytest.raises(SourceNotFoundError):
            await source.read_document("nope.md")

    @pytest.mark.asyncio
    async def test_non_utf8_raises(self, patch_boto3) -> None:
        fake = patch_boto3
        fake.objects["bad.md"] = b"\xff\xfe not utf-8"
        fake.mtimes["bad.md"] = datetime.now(timezone.utc)
        source = S3Source(_config())
        with pytest.raises(SourceError, match="UTF-8"):
            await source.read_document("bad.md")


class TestWriteDocument:
    @pytest.mark.asyncio
    async def test_writes_through_to_fake(self, patch_boto3) -> None:
        fake = patch_boto3
        source = S3Source(_config(prefix="memos"))
        ref = DocumentRef(
            doc_id="alpha.md",
            title="alpha",
            modified_at=datetime.now(timezone.utc),
        )
        result = await source.write_document(Document(ref=ref, content="# A"))
        assert result.doc_id == "alpha.md"
        assert fake.objects["memos/alpha.md"] == b"# A"

    @pytest.mark.asyncio
    async def test_rejects_binary(self, patch_boto3) -> None:
        source = S3Source(_config())
        ref = DocumentRef(
            doc_id="img.png",
            title="img",
            modified_at=datetime.now(timezone.utc),
        )
        doc = Document(ref=ref, content=b"\x89PNG", encoding=DocumentEncoding.BINARY)
        with pytest.raises(SourceError, match="binary"):
            await source.write_document(doc)


class TestMaterialize:
    @pytest.mark.asyncio
    async def test_pulls_all_objects(
        self, patch_boto3, tmp_path: Path
    ) -> None:
        fake = patch_boto3
        fake.objects = {
            "memos/alpha.md": b"# Alpha",
            "memos/beta.md": b"# Beta",
        }
        now = datetime.now(timezone.utc)
        fake.mtimes = {k: now for k in fake.objects}
        source = S3Source(_config(prefix="memos"))
        cache = tmp_path / "cache"
        stats = await source.materialize_to_vault(cache)
        assert stats.documents_seen == 2
        assert stats.documents_written == 2
        assert (cache / "alpha.md").read_text(encoding="utf-8") == "# Alpha"


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok_when_list_succeeds(self, patch_boto3) -> None:
        fake = patch_boto3
        fake.objects["foo.md"] = b"# foo"
        fake.mtimes["foo.md"] = datetime.now(timezone.utc)
        source = S3Source(_config())
        health = await source.health()
        assert health.status is SourceHealthStatus.OK

    @pytest.mark.asyncio
    async def test_health_failed_when_client_explodes(
        self, monkeypatch
    ) -> None:
        # Replace boto3.client with one that always raises.
        import boto3

        def _exploder(*args, **kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(boto3, "client", _exploder)
        source = S3Source(_config())
        health = await source.health()
        assert health.status is SourceHealthStatus.FAILED


class TestAuthClassification:
    def test_no_credentials_error(self) -> None:
        from memograph.sources.s3 import _is_auth_error

        exc = type("NoCredentialsError", (Exception,), {})("no creds")
        assert _is_auth_error(exc) is True

    def test_access_denied_response(self) -> None:
        from memograph.sources.s3 import _is_auth_error

        exc = type("ClientError", (Exception,), {})("denied")
        exc.response = {"Error": {"Code": "AccessDenied"}}
        assert _is_auth_error(exc) is True

    def test_random_error_is_not_auth(self) -> None:
        from memograph.sources.s3 import _is_auth_error

        assert _is_auth_error(RuntimeError("oops")) is False


class TestMissingBoto3:
    def test_clear_error_when_boto3_missing(self, monkeypatch) -> None:
        # Force the import to fail.
        import sys

        monkeypatch.setitem(sys.modules, "boto3", None)
        source = S3Source(_config())
        with pytest.raises(SourceError, match="memograph\\[sources-s3\\]"):
            source._build_client()
