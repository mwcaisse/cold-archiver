import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cold_archiver.utils.files import (
    get_file_checksum,
    get_file_metadata,
    get_path_relative_to,
)
from cold_archiver.utils.json_utils import json_default_handler


def test_get_file_checksum_returns_uppercase_sha256(tmp_path: Path) -> None:
    file_path = tmp_path / "example.txt"
    contents = b"cold archiver\n"
    file_path.write_bytes(contents)

    checksum = get_file_checksum(file_path)

    assert checksum == hashlib.sha256(contents).hexdigest().upper()


def test_get_file_metadata_describes_file(tmp_path: Path) -> None:
    file_path = tmp_path / "example.txt"
    file_path.write_text("contents", encoding="utf-8")

    metadata = get_file_metadata(file_path)

    assert metadata.path == file_path
    assert metadata.filename == "example.txt"
    assert metadata.size == len(b"contents")
    assert metadata.modified_ns == file_path.stat().st_mtime_ns
    assert metadata.checksum == get_file_checksum(file_path)


def test_get_path_relative_to_base_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "nested" / "example.txt"

    assert get_path_relative_to(file_path, tmp_path) == Path("nested/example.txt")


def test_json_default_handler_serializes_datetime_and_uuid() -> None:
    identifier = uuid.UUID("ed2b9b22-71cf-4e64-a932-5b4a835859c0")
    created_at = datetime(2026, 10, 24, 12, 30, tzinfo=UTC)

    encoded = json.dumps(
        {"id": identifier, "created_at": created_at},
        default=json_default_handler,
    )

    assert json.loads(encoded) == {
        "id": str(identifier),
        "created_at": "2026-10-24T12:30:00+00:00",
    }
