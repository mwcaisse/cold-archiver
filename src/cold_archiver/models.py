import uuid
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class FileRecord:
    path: str
    filename: str
    checksum: str
    size: int
    modified_ns: int

    def __json__(self):
        return {
            "path": self.path,
            "filename": self.filename,
            "checksum": self.checksum,
            "size": self.size,
            "modified_ns": self.modified_ns,
        }


class FileChangeType(StrEnum):
    NEW = "NEW"
    DELETED = "DELETED"
    MODIFIED = "MODIFIED"
    # TODO: Do I want to have a renamed?


@dataclass(frozen=True)
class FileChange:
    change_type: FileChangeType
    previous: FileRecord | None
    current: FileRecord | None

    def __json__(self):
        return {
            "change_type": self.change_type,
            "previous": self.previous,
            "current": self.current,
        }


@dataclass(frozen=True)
class BackupManifest:
    local_directory: str
    # The current files in this backup -- i.e. the files on disc when this backup was taken
    current_files: dict[str, FileRecord]

    # The files that have changed since the last backup
    file_changes: list[FileChange]

    parent_backup_id: uuid.UUID | None

    def __json__(self):
        return {
            "current_files": self.current_files,
            "file_changes": self.file_changes,
            "parent_backup_id": str(self.parent_backup_id)
            if self.parent_backup_id
            else None,
        }
