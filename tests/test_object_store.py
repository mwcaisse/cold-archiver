from pathlib import Path

import pytest

from cold_archiver.config import ObjectStoreConfiguration, ObjectStoreCredentials
from cold_archiver.object_store import ObjectStoreClient


class FakeMinio:
    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.file_calls = []
        self.byte_calls = []

    def fput_object(self, **kwargs):
        self.file_calls.append(kwargs)

    def put_object(self, **kwargs):
        kwargs["content"] = kwargs["data"].read()
        self.byte_calls.append(kwargs)


@pytest.fixture
def minio_instances(monkeypatch):
    instances = []

    def factory(**kwargs):
        instance = FakeMinio(**kwargs)
        instances.append(instance)
        return instance

    monkeypatch.setattr("cold_archiver.object_store.Minio", factory)
    return instances


def make_client(minio_instances, prefix: str | None = "daily"):
    credentials = ObjectStoreCredentials(
        access_key="test-access", secret_key="test-secret"
    )
    config = ObjectStoreConfiguration(
        endpoint="storage.example.com",
        region="test-region",
        bucket="test-bucket",
        prefix=prefix,
    )
    client = ObjectStoreClient(credentials, config)
    return client, minio_instances[0]


def test_client_initializes_minio(minio_instances) -> None:
    client, minio = make_client(minio_instances)

    assert client.bucket == "test-bucket"
    assert client.prefix == "daily"
    assert minio.init_kwargs == {
        "endpoint": "storage.example.com",
        "access_key": "test-access",
        "secret_key": "test-secret",
        "secure": True,
        "region": "test-region",
    }


def test_upload_file_uses_prefix_and_returns_s3_path(
    tmp_path: Path, minio_instances
) -> None:
    client, minio = make_client(minio_instances)
    file_path = tmp_path / "archive.zip"
    file_path.write_bytes(b"contents")

    result = client.upload_file(file_path, "id/archive.zip", "application/zip")

    assert result == "s3://test-bucket/daily/id/archive.zip"
    assert minio.file_calls == [
        {
            "bucket_name": "test-bucket",
            "object_name": "daily/id/archive.zip",
            "file_path": str(file_path),
            "content_type": "application/zip",
        }
    ]


def test_upload_bytes_without_prefix(minio_instances) -> None:
    client, minio = make_client(minio_instances, prefix=None)

    result = client.upload_bytes(b"contents", "latest.json", "application/json")

    assert result == "s3://test-bucket/latest.json"
    assert len(minio.byte_calls) == 1
    assert minio.byte_calls[0]["bucket_name"] == "test-bucket"
    assert minio.byte_calls[0]["object_name"] == "latest.json"
    assert minio.byte_calls[0]["length"] == len(b"contents")
    assert minio.byte_calls[0]["content_type"] == "application/json"
    assert minio.byte_calls[0]["content"] == b"contents"
