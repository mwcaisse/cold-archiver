import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from cold_archiver.backup import (
    append_hash_to_zip_file_name,
    build_backup_latest_manifest,
    create_backup_archive,
    get_file_content_type,
    upload_backup_file_with_hash,
    upload_backup_latest_manifest,
)
from cold_archiver.database.models import Backup
from cold_archiver.models import BackupManifest, FileChange, FileChangeType, FileRecord


def make_file_record(path: str, *, checksum: str = "ABC123", size: int = 10):
    return FileRecord(
        path=Path(path),
        filename=Path(path).name,
        checksum=checksum,
        size=size,
        modified_ns=123,
    )


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("archive.zip", "application/zip"),
        ("archive.zip.sha256", "text/plain"),
        ("manifest.sqlite", "application/vnd.sqlite3"),
        ("latest.json", "application/json"),
    ],
)
def test_get_file_content_type(filename: str, expected: str) -> None:
    assert get_file_content_type(filename) == expected


def test_get_file_content_type_rejects_unknown_extension() -> None:
    with pytest.raises(ValueError, match="unknown file type"):
        get_file_content_type("archive.bin")


def test_append_hash_to_zip_file_name() -> None:
    assert append_hash_to_zip_file_name("backup.zip", "1234567890") == (
        "backup-12345678.zip"
    )


def test_create_backup_archive_includes_new_and_modified_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "new.txt").write_text("new contents", encoding="utf-8")
    (source / "modified.txt").write_text("modified contents", encoding="utf-8")
    new_record = make_file_record("new.txt")
    modified_record = make_file_record("modified.txt")
    deleted_record = make_file_record("deleted.txt")
    manifest = BackupManifest(
        local_directory=source,
        current_files={
            new_record.path: new_record,
            modified_record.path: modified_record,
        },
        file_changes=[
            FileChange(FileChangeType.NEW, None, new_record),
            FileChange(FileChangeType.MODIFIED, modified_record, modified_record),
            FileChange(FileChangeType.DELETED, deleted_record, None),
        ],
        parent_backup_id=None,
    )
    destination = tmp_path / "backup.zip"

    create_backup_archive(manifest, destination)

    with ZipFile(destination) as archive:
        assert set(archive.namelist()) == {"new.txt", "modified.txt"}
        assert archive.read("new.txt") == b"new contents"
        assert archive.read("modified.txt") == b"modified contents"


def test_create_backup_archive_rejects_non_file(tmp_path: Path) -> None:
    directory_record = make_file_record("directory")
    (tmp_path / "directory").mkdir()
    manifest = BackupManifest(
        local_directory=tmp_path,
        current_files={directory_record.path: directory_record},
        file_changes=[FileChange(FileChangeType.NEW, None, directory_record)],
        parent_backup_id=None,
    )

    with pytest.raises(ValueError, match="not a file"):
        create_backup_archive(manifest, tmp_path / "backup.zip")


def test_build_backup_latest_manifest() -> None:
    backup_id = uuid.uuid4()
    created_at = datetime(2026, 10, 24, 12, 30, tzinfo=UTC)
    backup = Backup(id=backup_id, sequence_number=1, date_created=created_at)
    manifest_file = make_file_record("manifest.sqlite", checksum="FEDCBA", size=42)

    result = build_backup_latest_manifest(
        backup, manifest_file, "s3://bucket/backup-id/manifest.sqlite"
    )

    assert result == {
        "version": 1,
        "backup_id": backup_id,
        "created_at": created_at,
        "manifest": {
            "key": "s3://bucket/backup-id/manifest.sqlite",
            "sha256": "FEDCBA",
            "size": 42,
        },
    }


def test_upload_backup_latest_manifest_uploads_json() -> None:
    class FakeClient:
        def upload_bytes(self, content, object_name, content_type):
            self.call = (content, object_name, content_type)
            return "s3://bucket/latest.json"

    backup_id = uuid.uuid4()
    backup = Backup(
        id=backup_id,
        sequence_number=1,
        date_created=datetime(2026, 10, 24, 12, 30, tzinfo=UTC),
    )
    manifest_file = make_file_record("manifest.sqlite", checksum="FEDCBA", size=42)
    client = FakeClient()

    result = upload_backup_latest_manifest(
        client, backup, manifest_file, "s3://bucket/id/manifest.sqlite"
    )

    content, object_name, content_type = client.call
    decoded = json.loads(content)
    assert result == "s3://bucket/latest.json"
    assert object_name == "latest.json"
    assert content_type == "application/json"
    assert decoded["backup_id"] == str(backup_id)
    assert decoded["manifest"]["sha256"] == "FEDCBA"


def test_upload_backup_file_with_hash_uploads_file_and_checksum(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self):
            self.file_calls = []
            self.byte_calls = []

        def upload_file(self, *args):
            self.file_calls.append(args)
            return "s3://bucket/id/archive.zip"

        def upload_bytes(self, *args):
            self.byte_calls.append(args)

    backup_id = uuid.uuid4()
    file_path = tmp_path / "archive.zip"
    file_path.write_bytes(b"zip")
    record = FileRecord(file_path, "archive.zip", "ABCDEF", 3, 123)
    client = FakeClient()

    result = upload_backup_file_with_hash(client, record, backup_id, "archive.zip")

    storage_key = f"{backup_id}/archive.zip"
    assert result == "s3://bucket/id/archive.zip"
    assert client.file_calls == [(file_path, storage_key, "application/zip")]
    assert client.byte_calls[0][0] == b"ABCDEF archive.zip\n"
    assert client.byte_calls[0][1] == f"{storage_key}.sha256"
