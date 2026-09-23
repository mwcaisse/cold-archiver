import os
from pathlib import Path

from sqlalchemy import select

from cold_archiver.database.context import DatabaseContext
from cold_archiver.database.models import (
    Backup,
    BackupEntry,
    BackupSource,
    BackupSourceAssignment,
)
from cold_archiver.models import BackupManifest, FileChange, FileChangeType, FileRecord
from cold_archiver.utils import get_file_checksum, get_path_relative_to


class BackupManifestBuilder:
    """
    Builds the manifest for what a backup should contain
    """

    def __init__(self, db: DatabaseContext):
        self._db = db

    def build_backup_manifest(self, directory: str) -> BackupManifest:
        """
        Given a directory, builds the manifest for the given directory
        :param directory:
        :return:
        """

        current_directory_manifest = self._build_directory_manifest(directory)

        # determine if there is an existing backup
        existing_backup = self._get_latest_backup_for_directory(directory)
        if existing_backup is not None:
            existing_manifest = self._get_manifest_for_backup(existing_backup)

            # Now we need to diff out the current vs the old
            all_file_paths = (
                current_directory_manifest.keys() | existing_manifest.keys()
            )

            changes: list[FileChange] = []
            for file_path in all_file_paths:
                prev = existing_manifest.get(file_path)
                current = current_directory_manifest.get(file_path)

                if current is None:
                    # file was deleted
                    changes.append(
                        FileChange(
                            change_type=FileChangeType.DELETED,
                            previous=prev,
                            current=None,
                        )
                    )
                elif prev is None:
                    # file as added
                    changes.append(
                        FileChange(
                            change_type=FileChangeType.NEW,
                            previous=None,
                            current=current,
                        )
                    )
                else:
                    # They are both not null (they can't both be null)
                    #   so they exist in both the backup, and the current directory, its only a change if their checksums are different
                    if prev.checksum != current.checksum:
                        changes.append(
                            FileChange(
                                change_type=FileChangeType.MODIFIED,
                                previous=prev,
                                current=current,
                            )
                        )

            return BackupManifest(
                local_directory=directory,
                current_files=current_directory_manifest,
                file_changes=changes,
                parent_backup_id=existing_backup.id,
            )

        else:
            return BackupManifest(
                local_directory=directory,
                current_files=current_directory_manifest,
                file_changes=[
                    FileChange(
                        change_type=FileChangeType.NEW,
                        previous=None,
                        current=file_record,
                    )
                    for file_record in current_directory_manifest.values()
                ],
                parent_backup_id=None,
            )

    def _get_latest_backup_for_directory(self, directory: str) -> Backup | None:
        with self._db.create_session() as session:
            backup_source = session.scalars(
                select(BackupSource).where(BackupSource.local_path == directory)
            ).one_or_none()

            # No backup for this directory
            if backup_source is None:
                return None

            return session.scalars(
                select(Backup)
                .outerjoin(
                    BackupSourceAssignment,
                    BackupSourceAssignment.backup_id == Backup.id,
                )
                .where(BackupSourceAssignment.source_id == backup_source.id)
                .order_by(Backup.date_created.desc())
            ).first()

    def _get_manifest_for_backup(self, backup: Backup) -> dict[str, FileRecord]:
        with self._db.create_session() as session:
            backup_entries = session.scalars(
                select(BackupEntry).where(BackupEntry.backup_id == backup.id)
            ).all()

            return {
                entry.path: FileRecord(
                    path=entry.path,
                    filename=os.path.basename(entry.path),
                    checksum=entry.sha256,
                    size=entry.size,
                    modified_ns=entry.modified_ns,
                )
                for entry in backup_entries
            }

    @staticmethod
    def _build_directory_manifest(directory: str) -> dict[str, FileRecord]:
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
