import json
import uuid
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
from cold_archiver.models import BackupManifest, FileChangeType, FileRecord
from cold_archiver.object_store import ObjectStoreClient
from cold_archiver.utils.files import get_file_metadata
from cold_archiver.utils.json_utils import json_default_handler


def perform_backup(directory: str):
    """
    Performs the backup on the given directory

    :param directory:
    :return:
    """

    backup_directory = normalize_path(directory)

    if not backup_directory.is_dir():
        raise ValueError(f"Given backup directory does not exist ({backup_directory}")

    # Construct our config
    db_config = DatabaseConfig(database_file="backups.sqlite")

    # Build our services n what not here
    db_context = DatabaseContext(db_config)
    manifest_builder = BackupManifestBuilder(db_context)

    manifest = manifest_builder.build_backup_manifest(backup_directory)
    log_backup_manifest_changes(manifest)

    persist_backup_metadata_to_db(db_context, manifest)
    print("Saved backup manifest to database")

    current_time = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    destination_zip = Path.joinpath(backup_directory, f"backup-{current_time}.zip")
    create_backup_archive(manifest, destination_zip)

    zip_metadata = get_file_metadata(destination_zip)
    print(f"Created zip at {zip_metadata.path}({zip_metadata.checksum})")

    # TODO: re-implement this, but for now this is fine
    # storage_path = upload_archive_to_object_store(zip_metadata)
    #
    # persist_backup_metadata_to_db(db_context, manifest, zip_metadata, storage_path)

    print("Persisted backup to backups.sqlite")


def normalize_path(path: str) -> Path:
    """
    Gets the absolute path of the given path.

    To normalize home directory, relative paths, to absolute paths so they are the same regardless of how they are passed.

    :param path:
    :return:
    """

    return Path(path).expanduser().absolute()


def log_backup_manifest_changes(manifest: BackupManifest):
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
                path=str(entry.path),
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
            backup_source = BackupSource(local_path=str(manifest.local_directory))
            session.add(backup_source)
            session.flush()

        assignment = BackupSourceAssignment(
            backup_id=backup.id, source_id=backup_source.id
        )
        session.add(assignment)


def create_backup_archive(manifest: BackupManifest, zip_file_destination: Path):
    with ZipFile(zip_file_destination, "w", compression=ZIP_DEFLATED) as archive:
        for change in manifest.file_changes:
            # Only add files that have been added or modified
            if change.change_type in {FileChangeType.NEW, FileChangeType.MODIFIED}:
                absolute_path = Path.joinpath(
                    manifest.local_directory, change.current.path
                )

                if not absolute_path.is_file():
                    raise ValueError("Trying to archive something that is not a file!")

                archive.write(absolute_path, arcname=change.current.path)


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
