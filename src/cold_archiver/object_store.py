import os
from io import BytesIO
from pathlib import Path

from minio import Minio, S3Error

from cold_archiver.config import ObjectStoreConfiguration, ObjectStoreCredentials


class ObjectStoreClient:
    def __init__(
        self, credentials: ObjectStoreCredentials, config: ObjectStoreConfiguration
    ):
        self._client = Minio(
            endpoint=config.endpoint,
            access_key=credentials.access_key,
            secret_key=credentials.secret_key,
            secure=True,
            region=config.region,
        )

        self.bucket = config.bucket
        self.prefix = config.prefix

    def upload_file(self, local_path: Path, object_name: str, content_type: str):
        object_key = self._create_object_path(object_name)

        try:
            self._client.fput_object(
                bucket_name=self.bucket,
                object_name=object_key,
                file_path=str(local_path),
                content_type=content_type,
            )

            return self._s3_path(object_key)
        except S3Error as e:
            raise RuntimeError(
                f"Failed to upload {local_path} to {self.bucket}/{object_key}"
            ) from e

    def upload_bytes(self, content: bytes, object_name: str, content_type: str):
        object_key = self._create_object_path(object_name)

        try:
            self._client.put_object(
                bucket_name=self.bucket,
                object_name=object_key,
                data=BytesIO(content),
                length=len(content),
                content_type=content_type,
            )

            return self._s3_path(object_key)
        except S3Error as e:
            raise RuntimeError(
                f"Failed to upload bytes to {self.bucket}/{object_key}"
            ) from e

    def _create_object_path(self, object_name: str) -> str:
        if self.prefix is None or len(self.prefix) == 0:
            return object_name

        return os.path.join(self.prefix, object_name)

    def _s3_path(self, object_key: str) -> str:
        return f"s3://{self.bucket}/{object_key}"
