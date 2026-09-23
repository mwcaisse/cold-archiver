import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
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

    # Create the current manifest
    manifest = manifest_builder.build_backup_manifest(backup_directory)
    log_backup_manifest_changes(manifest)

    # If there are no changes between now and last backup, there is nothing to do
    if len(manifest.file_changes) < 1:
        print("No changes between current state and previous backup. Nothing to do.")
        return

    with TemporaryDirectory() as working_dir:
        current_time = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_archive_path = Path(working_dir).joinpath(f"backup-{current_time}.zip")
        create_backup_archive(manifest, backup_archive_path)

        zip_metadata = get_file_metadata(backup_archive_path)

        # Upload the zipfile to object store
        storage_path = upload_archive_to_object_store(zip_metadata)

        persist_backup_metadata_to_db(db_context, manifest, zip_metadata, storage_path)

        # TODO: We need to get the backup source ID
        manifest_db_file = Path(working_dir).joinpath("manifest.sqlite")
        create_backup_manifest_database(manifest_db_file, db_context, uuid.uuid4())

    print("Backup completed successfully!")


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
    backup_archive_metadata: FileRecord,
    backup_archive_storage_path: str,
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

        # Create our BackupArchive entry
        backup_archive = BackupArchive(
            backup_id=backup.id,
            sha256=backup_archive_metadata.checksum,
            name=backup_archive_metadata.filename,
            storage_key=backup_archive_storage_path,
            size=backup_archive_metadata.size,
        )
        session.add(backup_archive)


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


def create_backup_manifest_database(
    db_file: Path, db: DatabaseContext, backup_source_id: uuid.UUID
):
    """
    Given a backup_source_id and a database, it will create a sqlite database to use as the manifest for this backup archive

    :param db_file:
    :param db:
    :param backup_source_id:
    :return:
    """

    # Initializing the manifest databae, creating schema + db file
    manifest_db = DatabaseContext(DatabaseConfig(database_file=str(db_file)))
    manifest_db.close()

    connection = db.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "ATTACH DATABASE ? AS manifest",
            (str(db_file),),
        )

        cursor.execute(
            """
             CREATE TEMP TABLE backup_ids_to_copy (
                id PRIMARY KEY
            )
            """
        )

        cursor.execute(
            """
            INSERT INTO backup_ids_to_copy (id)
            SELECT bsa.backup_id
            FROM backup_source_assignment bsa
            WHERE bsa.source_id = ?;            
            """,
            (backup_source_id.hex,),
        )

        if cursor.rowcount == 0:
            raise ValueError(f"No backups found for source {backup_source_id}")

        cursor.execute(
            """          
            INSERT INTO manifest.backup(
                id,
                parent_id,
                sequence_number,
                date_created
            )
            SELECT 
                b.id,
                b.parent_id,
                b.sequence_number,
                b.date_created
            FROM backup AS b
            JOIN backup_ids_to_copy bid ON bid.id = b.id            
            """
        )

        cursor.execute(
            """ 
            INSERT INTO manifest.backup_archive(
                backup_id,
                sha256,
                name,
                storage_key,
                size
            )
            SELECT 
                ba.backup_id,
                ba.sha256,
                ba.name,
                ba.storage_key,
                ba.size
            FROM backup_archive AS ba
            JOIN backup_ids_to_copy bid ON bid.id = ba.backup_id            
            """
        )

        cursor.execute(
            """         
            INSERT INTO manifest.backup_entry(
                backup_id,
                path,
                sha256,
                size,
                modified_ns
            )
            SELECT 
                be.backup_id,
                be.path,
                be.sha256,
                be.size,
                be.modified_ns
            FROM backup_entry AS be
            JOIN backup_ids_to_copy bid ON bid.id = be.backup_id            
            """
        )

        connection.commit()
        cursor.execute("DETACH DATABASE manifest")

    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
