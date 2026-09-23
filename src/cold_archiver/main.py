import argparse
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select

from cold_archiver.backup_manifest_builder import BackupManifestBuilder
from cold_archiver.config import load_config, load_credentials
from cold_archiver.database.config import DatabaseConfig
from cold_archiver.database.context import DatabaseContext
from cold_archiver.database.models import (
    Backup,
    BackupArchive,
    BackupEntry,
    BackupSource,
    BackupSourceAssignment,
)
from cold_archiver.models import BackupManifest, FileChangeType
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


def create_backup_archive(manifest: BackupManifest, zip_file_destination: str):
    with ZipFile(zip_file_destination, "w", compression=ZIP_DEFLATED) as archive:
        for change in manifest.file_changes:
            # Only add files that have been added or modified
            if change.change_type in {FileChangeType.NEW, FileChangeType.MODIFIED}:
                absolute_path = Path(
                    os.path.join(manifest.local_directory, change.current.path)
                )

                if not absolute_path.is_file():
                    raise ValueError("Trying to archive something that is not a file!")

                archive.write(absolute_path, arcname=change.current.path)


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
    db: DatabaseContext,
    manifest: BackupManifest,
):
    with db.create_session() as session:
        parent_backup: Backup | None = None

        if manifest.parent_backup_id is not None:
            parent_backup = session.scalars(
                select(Backup).where(Backup.id == manifest.parent_backup_id)
            ).one()

        backup = Backup(
            parent_id=parent_backup.id if parent_backup is not None else None,
            sequence_number=parent_backup.sequence_number + 1
            if parent_backup is not None
            else 1,
        )
        session.add(backup)
        session.flush()

        for entry in manifest.current_files.values():
            db_entry = BackupEntry(
                backup_id=backup.id,
                path=entry.path,
                sha256=entry.checksum,
                size=entry.size,
                modified_ns=entry.modified_ns,
            )
            session.add(db_entry)

        # Create or get our backup source
        #   and create our backup source assignment

        backup_source = session.scalars(
            select(BackupSource).where(
                BackupSource.local_path == manifest.local_directory
            )
        ).one_or_none()
        if backup_source is None:
            backup_source = BackupSource(local_path=manifest.local_directory)
            session.add(backup_source)
            session.flush()

        assignment = BackupSourceAssignment(
            backup_id=backup.id, source_id=backup_source.id
        )
        session.add(assignment)


def persist_backup_archive_to_db(
    db: DatabaseContext,
    backup_id: uuid.UUID,
    backup_archive: FileRecord,
    backup_archive_storage_path: str,
):
    with db.create_session() as session:
        db_backup_archive = BackupArchive(
            backup_id=backup_id,
            sha256=backup_archive.checksum,
            name=backup_archive.filename,
            storage_key=backup_archive_storage_path,
            size=backup_archive.size,
        )
        session.add(db_backup_archive)


def main():
    arg_parser = argparse.ArgumentParser(
        description="Backup a directory to S3-compat storage"
    )

    arg_parser.add_argument("source", type=str, help="Directory to backup")

    args = arg_parser.parse_args()

    # build out the config
    db_config = DatabaseConfig(database_file="backups.sqlite")

    # Build our services n what not here
    db_context = DatabaseContext(db_config)
    manifest_builder = BackupManifestBuilder(db_context)

    manifest = manifest_builder.build_backup_manifest(args.source)

    # print(json.dumps(manifest, indent=4, default=json_default_handler))

    if manifest.parent_backup_id is not None:
        print("Detected previous backup!")
        if manifest.file_changes:
            print(
                f"Found the following changes: \n {json.dumps(manifest.file_changes, indent=4, default=json_default_handler)}"
            )
        else:
            print(
                "No changes between current state and previous backup. Nothing to do."
            )
    else:
        print("Initial backup!")
        print(
            f"Found the following files: \n {json.dumps(manifest.file_changes, indent=4, default=json_default_handler)}"
        )

    # TODO: Handle what happens when there are no changes or only changes are deletions
    #   if only changes are deletions, then we don't need to create a zipfile
    #   Honestly we could probably just skip performing the backup at that point

    persist_backup_metadata_to_db(db_context, manifest)
    print("Saved backup manifest to database")

    current_time = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    destination_zip = os.path.join(args.source, f"backup-{current_time}.zip")
    create_backup_archive(manifest, destination_zip)

    zip_metadata = get_file_metadata(destination_zip)
    print(f"Created zip at {zip_metadata.path}({zip_metadata.checksum})")

    # TODO: re-implement this, but for now this is fine
    # storage_path = upload_archive_to_object_store(zip_metadata)
    #
    # persist_backup_metadata_to_db(db_context, manifest, zip_metadata, storage_path)

    print("Persisted backup to backups.sqlite")

    # TODO: we have to push up the backups.sqlite (or a version of it, to object store)
    #   We also need to push up a latest.json or something / pointer to the latest backup file


if __name__ == "__main__":
    main()
