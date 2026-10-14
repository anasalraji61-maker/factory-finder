"""S3-compatible storage. UNVERIFIED: never exercised against a real bucket; off by default
(``FF_MEDIA_STORAGE_BACKEND=s3`` plus bucket and credentials from the environment). Needs ``boto3`` (extra ``s3``)."""

from __future__ import annotations

import asyncio

from ff_media.storage.base import valid_key


class S3Storage:
    def __init__(
        self, bucket: str, *, prefix: str = "media/", region: str | None = None,
        endpoint_url: str | None = None, access_key_id: str | None = None,
        secret_access_key: str | None = None, client=None,
    ) -> None:  # fmt: skip
        if not bucket:
            raise ValueError("FF_MEDIA_S3_BUCKET is required for the s3 backend")
        self.bucket, self.prefix = bucket, prefix
        if client is None:
            import boto3  # lazy: optional dependency

            client = boto3.client(
                "s3", region_name=region, endpoint_url=endpoint_url,
                aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key,
            )  # fmt: skip
        self.client = client

    def _k(self, key: str) -> str:
        if not valid_key(key):
            raise ValueError("invalid storage key")
        return self.prefix + key

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=self._k(key), Body=data,
            ContentType=content_type, CacheControl="public, max-age=31536000, immutable",
        )  # fmt: skip

    async def get(self, key: str) -> bytes | None:
        def run() -> bytes | None:
            try:
                return self.client.get_object(Bucket=self.bucket, Key=self._k(key))["Body"].read()
            except self.client.exceptions.NoSuchKey:
                return None

        return await asyncio.to_thread(run)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=self._k(key))

    async def exists(self, key: str) -> bool:
        def run() -> bool:
            try:
                self.client.head_object(Bucket=self.bucket, Key=self._k(key))
                return True
            except Exception:
                return False

        return await asyncio.to_thread(run)

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)
            return True
        except Exception:
            return False
