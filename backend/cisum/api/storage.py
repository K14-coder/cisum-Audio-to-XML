"""Object storage: a local folder in development, S3 (or MinIO) in production."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO, Protocol

from .config import Settings, get_settings


class Storage(Protocol):
    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None: ...
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def put_stream(self, key: str, stream: BinaryIO) -> int: ...
    def get_bytes(self, key: str) -> bytes: ...
    def download(self, key: str, path: Path) -> None: ...
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int | None: ...
    def delete(self, key: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def presign_put(self, key: str, content_type: str, expires_s: int = 3600) -> str | None: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"bad storage key {key!r}")
        return p

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dst)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)

    def put_stream(self, key: str, stream: BinaryIO) -> int:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as f:
            shutil.copyfileobj(stream, f)
        return dst.stat().st_size

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def download(self, key: str, path: Path) -> None:
        shutil.copyfile(self._path(key), path)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int | None:
        p = self._path(key)
        return p.stat().st_size if p.is_file() else None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        p = self._path(prefix)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)

    def presign_put(self, key: str, content_type: str, expires_s: int = 3600) -> str | None:
        return None  # uploads go through the API instead


class S3Storage:
    def __init__(self, settings: Settings):
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        # SigV4 everywhere (MinIO and newer AWS regions reject v2 presigned URLs);
        # path-style addressing for custom endpoints like MinIO.
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_endpoint_url else "auto"},
        )
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.s3_region, config=config)
        public = settings.s3_public_endpoint_url or settings.s3_endpoint_url
        self.presign_client = (
            boto3.client("s3", endpoint_url=public, region_name=settings.s3_region, config=config)
            if public != settings.s3_endpoint_url
            else self.client
        )

    def _k(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else None
        self.client.upload_file(str(path), self.bucket, self._k(key), ExtraArgs=extra)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        kwargs = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=self._k(key), Body=data, **kwargs)

    def put_stream(self, key: str, stream: BinaryIO) -> int:
        self.client.upload_fileobj(stream, self.bucket, self._k(key))
        return self.size(key) or 0

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self._k(key))["Body"].read()

    def download(self, key: str, path: Path) -> None:
        self.client.download_file(self.bucket, self._k(key), str(path))

    def exists(self, key: str) -> bool:
        return self.size(key) is not None

    def size(self, key: str) -> int | None:
        from botocore.exceptions import ClientError

        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=self._k(key))["ContentLength"])
        except ClientError:
            return None

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._k(key))

    def delete_prefix(self, prefix: str) -> None:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._k(prefix)):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})

    def presign_put(self, key: str, content_type: str, expires_s: int = 3600) -> str | None:
        return self.presign_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": self._k(key), "ContentType": content_type},
            ExpiresIn=expires_s,
        )


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = S3Storage(s) if s.storage == "s3" else LocalStorage(s.storage_dir)
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None
