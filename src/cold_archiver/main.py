import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import Engine, select

from cold_archiver.config import load_config, load_credentials
from cold_archiver.db import (
    Backup,
    BackupArchive,
    BackupEntry,
    create_database_engine,
    create_database_session,
)
from cold_archiver.object_store import ObjectStoreClient


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


def get_file_checksum(file_path: str) -> str:
    with open(file_path, "rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest().upper()


def get_path_relative_to(file_path: str, base_path: str) -> str:
    base = Path(base_path)
    file = Path(file_path)
    return str(file.relative_to(base))


def get_file_metadata(file_path: str) -> FileRecord:
    stat = Path(file_path).stat()

    return FileRecord(
        path=file_path,
        filename=os.path.basename(file_path),
        checksum=get_file_checksum(file_path),
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
    )


def build_directory_manifest(directory: str) -> dict[str, FileRecord]:
    results: dict[str, FileRecord] = {}

    for root, _, files in os.walk(directory):
        for filename in files:
            full_path = os.path.join(root, filename)
            relative_path = get_path_relative_to(full_path, directory)
            stat = Path(full_path).stat()

            results[relative_path] = FileRecord(
                path=relative_path,
                filename=filename,
                checksum=get_file_checksum(full_path),
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
            )

    return results


def zip_directory(directory: str, manifest: dict[str, FileRecord], destination: str):
    """

    :param directory: The directory to zip
    :param manifest: The manifest of the files in the directory to zip
    :param destination: The destination of the zipfile
    """

    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in manifest:
            absolute_path = Path(os.path.join(directory, file_path))

            if not absolute_path.is_file():
                raise ValueError("Trying to archive something that is not a file!")

            archive.write(absolute_path, arcname=file_path)


def json_default_handler(val):
    if hasattr(val, "__json__"):
        return val.__json__()

    if isinstance(val, datetime):
        return val.isoformat()

    return TypeError(f"Cannot serialize {type(val).__name__}")


def append_hash_to_zip_file_name(file_name: str, sha: str) -> str:
    return file_name.replace(".zip", f"-{sha[:8]}.zip")


def upload_archive_to_object_store(archive: FileRecord) -> str:

    # TODO: load these elsewhere? but for now this works
    credentials = load_credentials("credentials.toml")
    config = load_config("config.toml")

    client = ObjectStoreClient(credentials=credentials, config=config)

    object_store_file_name = append_hash_to_zip_file_name(
        archive.filename, archive.checksum
    )

    hash_file_name = f"{object_store_file_name}.sha256"
    hash_file_contents = f"{archive.checksum} {archive.filename}\n".encode()

    s3_archive_path = client.upload_file(
        archive.path, object_store_file_name, "application/zip"
    )
    client.upload_bytes(hash_file_contents, hash_file_name, "plain/text")

    print(f"Uploaded archive to {s3_archive_path}")

    return s3_archive_path


def persist_backup_metadata_to_db(
    db: Engine,
    manifest: dict[str, FileRecord],
    backup_archive: FileRecord,
    backup_archive_storage_path: str,
):
    with create_database_session(db) as session:
        # TODO: We need more support for incremental, but this is the base
        existing_query = select(Backup).order_by(Backup.sequence_number.desc())
        parent_backup = session.scalars(existing_query).first()

        backup = Backup(
            parent_id=parent_backup.id if parent_backup is not None else None,
            sequence_number=max(
                1, parent_backup.sequence_number if parent_backup is not None else 0
            ),
        )
        session.add(backup)
        session.flush()

        db_backup_archive = BackupArchive(
            backup_id=backup.id,
            sha256=backup_archive.checksum,
            name=backup_archive.filename,
            storage_key=backup_archive_storage_path,
            size=backup_archive.size,
        )

        session.add(db_backup_archive)

        for entry in manifest.values():
            db_entry = BackupEntry(
                backup_id=backup.id,
                path=entry.path,
                sha256=entry.checksum,
                size=entry.size,
                modified_ns=entry.modified_ns,
            )
            session.add(db_entry)


def main():
    arg_parser = argparse.ArgumentParser(
        description="Backup a directory to S3-compat storage"
    )

    arg_parser.add_argument("source", type=str, help="Directory to backup")

    args = arg_parser.parse_args()

    manifest = build_directory_manifest(args.source)

    print(json.dumps(manifest, indent=4, default=json_default_handler))

    current_time = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    destination_zip = os.path.join(args.source, f"backup-{current_time}.zip")
    zip_directory(args.source, manifest, destination_zip)

    zip_metadata = get_file_metadata(destination_zip)

    print(f"Created zip at {zip_metadata.path}({zip_metadata.checksum})")

    storage_path = upload_archive_to_object_store(zip_metadata)

    db_engine = create_database_engine()

    persist_backup_metadata_to_db(db_engine, manifest, zip_metadata, storage_path)

    print("Persisted backup to backups.sqlite")


if __name__ == "__main__":
    main()
