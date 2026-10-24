from pathlib import Path

from sqlalchemy import select

from cold_archiver.backup import create_backup_record, create_db_backup_entries
from cold_archiver.config import DatabaseConfiguration
from cold_archiver.database.context import DatabaseContext
from cold_archiver.database.models import (
    Backup,
    BackupEntry,
    BackupSource,
    BackupSourceAssignment,
)
from cold_archiver.models import BackupManifest, FileRecord


def make_database(tmp_path: Path) -> DatabaseContext:
    return DatabaseContext(DatabaseConfiguration(path=str(tmp_path / "backups.sqlite")))


def test_database_context_creates_schema_and_enables_foreign_keys(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)

    connection = database.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        table_names = {row[0] for row in cursor.fetchall()}
        assert {
            "backup",
            "backup_archive",
            "backup_entry",
            "backup_source",
            "backup_source_assignment",
        } <= table_names
    finally:
        connection.close()
        database.close()


def test_create_backup_record_assigns_sequence_and_source(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    with database.create_session() as session:
        source = BackupSource(local_path="/srv/photos")
        session.add(source)
        session.flush()
        source_id = source.id

    first = create_backup_record(database, source_id, None)
    second = create_backup_record(database, source_id, first.id)

    with database.create_session() as session:
        backups = session.scalars(select(Backup).order_by(Backup.sequence_number)).all()
        assignments = session.scalars(select(BackupSourceAssignment)).all()

    assert [backup.sequence_number for backup in backups] == [1, 2]
    assert second.parent_id == first.id
    assert {assignment.backup_id for assignment in assignments} == {
        first.id,
        second.id,
    }
    assert {assignment.source_id for assignment in assignments} == {source_id}
    database.close()


def test_create_db_backup_entries_persists_current_manifest(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    with database.create_session() as session:
        source = BackupSource(local_path="/srv/photos")
        session.add(source)
        session.flush()
        source_id = source.id
    backup = create_backup_record(database, source_id, None)
    record = FileRecord(Path("photo.jpg"), "photo.jpg", "ABC123", 42, 123456)
    manifest = BackupManifest(
        local_directory=Path("/srv/photos"),
        current_files={record.path: record},
        file_changes=[],
        parent_backup_id=None,
    )

    create_db_backup_entries(database, backup.id, manifest)

    with database.create_session() as session:
        entry = session.scalars(select(BackupEntry)).one()
    assert entry.backup_id == backup.id
    assert entry.path == "photo.jpg"
    assert entry.sha256 == "ABC123"
    assert entry.size == 42
    assert entry.modified_ns == 123456
    database.close()
