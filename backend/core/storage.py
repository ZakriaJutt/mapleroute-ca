"""Object storage for stored files (reports), through the S3 API (B2).

Local: MinIO at 127.0.0.1:9000 (region us-east-1, bucket ``mapleroute-dev``). Production: S3 in
ca-central-1 only (core.config refuses anything else outside local). The bucket is private: there
are no public URLs; a file leaves only through an authorised console endpoint or a presigned GET
link of at most five minutes for one tenant-prefixed key.

Every key is built by ``object_key`` and isolates tenant, source and purpose (R-13):
``<tenant_id>/<source>/<purpose>/<name>``. Every operation takes the tenant and refuses a key
outside that tenant's prefix, so a caller mistake cannot cross tenants.
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.config import REPORT_LINK_TTL_S, Settings
from core.logging import log_event

SOURCES = frozenset({"worker", "console"})
PURPOSES = frozenset({"report", "export"})
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StorageError(Exception):
    pass


class ForeignKey(StorageError):
    """A key outside the caller's tenant prefix."""


class ObjectMissing(StorageError):
    pass


def object_key(tenant_id: uuid.UUID, source: str, purpose: str, name: str) -> str:
    if source not in SOURCES or purpose not in PURPOSES or not _NAME.match(name) or ".." in name:
        raise StorageError("object key parts are not valid")
    return f"{tenant_id}/{source}/{purpose}/{name}"


def check_key(tenant_id: uuid.UUID, key: str) -> None:
    parts = key.split("/")
    if (len(parts) != 4 or parts[0] != str(tenant_id) or parts[1] not in SOURCES or parts[2] not in PURPOSES
            or not _NAME.match(parts[3]) or ".." in parts[3]):
        raise ForeignKey("key is not in this tenant's prefix")


class ObjectStore(Protocol):
    def put(self, tenant_id: uuid.UUID, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, tenant_id: uuid.UUID, key: str) -> bytes: ...

    def delete(self, tenant_id: uuid.UUID, key: str) -> None: ...

    def presign_get(self, tenant_id: uuid.UUID, key: str, ttl_s: int = REPORT_LINK_TTL_S) -> str: ...

    def ping(self) -> bool: ...


class S3ObjectStore:
    def __init__(self, bucket: str, region: str, endpoint_url: str | None = None,
                 access_key_id: str | None = None, secret_access_key: Any = None) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._client = boto3.client(
            "s3", region_name=region, endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key.reveal() if secret_access_key is not None else None,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 1},
                          connect_timeout=3, read_timeout=10),
        )

    @classmethod
    def from_settings(cls, cfg: Settings) -> S3ObjectStore:
        return cls(cfg.s3_bucket, cfg.s3_region, cfg.s3_endpoint_url, cfg.s3_access_key_id, cfg.s3_secret_access_key)

    def _call(self, op: str, **kw: Any) -> Any:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return getattr(self._client, op)(Bucket=self.bucket, **kw)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("NoSuchKey", "404"):
                raise ObjectMissing(op) from None
            log_event("storage_failed", reason=op, code=code)
            raise StorageError(op) from None
        except BotoCoreError as exc:
            log_event("storage_failed", reason=op, error_class=type(exc).__name__)
            raise StorageError(op) from None

    def put(self, tenant_id: uuid.UUID, key: str, data: bytes, content_type: str) -> None:
        check_key(tenant_id, key)
        self._call("put_object", Key=key, Body=data, ContentType=content_type)

    def get(self, tenant_id: uuid.UUID, key: str) -> bytes:
        check_key(tenant_id, key)
        body = self._call("get_object", Key=key)["Body"]
        try:
            return bytes(body.read())
        finally:
            body.close()

    def delete(self, tenant_id: uuid.UUID, key: str) -> None:
        check_key(tenant_id, key)
        self._call("delete_object", Key=key)

    def presign_get(self, tenant_id: uuid.UUID, key: str, ttl_s: int = REPORT_LINK_TTL_S) -> str:
        check_key(tenant_id, key)
        if not 0 < ttl_s <= REPORT_LINK_TTL_S:
            raise StorageError("link lifetime above five minutes")
        return str(self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl_s))

    def ping(self) -> bool:
        try:
            self._call("head_bucket")
            return True
        except StorageError:
            return False


@dataclass
class MemoryObjectStore:
    """Fake for unit tests and fully offline runs. Same key checks as S3."""

    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def put(self, tenant_id: uuid.UUID, key: str, data: bytes, content_type: str) -> None:
        check_key(tenant_id, key)
        with self._lock:
            self.objects[key] = (data, content_type)

    def get(self, tenant_id: uuid.UUID, key: str) -> bytes:
        check_key(tenant_id, key)
        with self._lock:
            if key not in self.objects:
                raise ObjectMissing(key)
            return self.objects[key][0]

    def delete(self, tenant_id: uuid.UUID, key: str) -> None:
        check_key(tenant_id, key)
        with self._lock:
            self.objects.pop(key, None)

    def presign_get(self, tenant_id: uuid.UUID, key: str, ttl_s: int = REPORT_LINK_TTL_S) -> str:
        check_key(tenant_id, key)
        return f"memory://{key}?ttl={ttl_s}"

    def ping(self) -> bool:
        return True
