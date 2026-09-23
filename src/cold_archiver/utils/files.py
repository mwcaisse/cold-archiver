import hashlib
import os
from pathlib import Path

from cold_archiver.models import FileRecord


def get_file_checksum(file_path: Path) -> str:
    with open(file_path, "rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest().upper()


def get_path_relative_to(file_path: Path, base_path: Path) -> Path:
    base = Path(base_path)
    file = Path(file_path)
    return file.relative_to(base)


def get_file_metadata(file_path: Path) -> FileRecord:
    stat = Path(file_path).stat()

    return FileRecord(
        path=file_path,
        filename=os.path.basename(file_path),
        checksum=get_file_checksum(file_path),
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
    )
