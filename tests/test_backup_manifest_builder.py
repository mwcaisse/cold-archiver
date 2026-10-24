import uuid
from pathlib import Path
from types import SimpleNamespace

from cold_archiver.backup_manifest_builder import BackupManifestBuilder
from cold_archiver.models import FileChangeType, FileRecord


def make_file_record(path: str, checksum: str) -> FileRecord:
    return FileRecord(
        path=Path(path),
        filename=Path(path).name,
        checksum=checksum,
        size=10,
        modified_ns=123,
    )


def test_build_initial_manifest_marks_every_file_as_new(
    tmp_path: Path, monkeypatch
) -> None:
    current_files = {
        Path("one.txt"): make_file_record("one.txt", "ONE"),
        Path("nested/two.txt"): make_file_record("nested/two.txt", "TWO"),
    }
    builder = BackupManifestBuilder(SimpleNamespace())
    monkeypatch.setattr(builder, "_build_directory_manifest", lambda _: current_files)
    monkeypatch.setattr(builder, "_get_latest_backup_for_directory", lambda _: None)

    manifest = builder.build_backup_manifest(tmp_path)

    assert manifest.local_directory == tmp_path
    assert manifest.current_files == current_files
    assert manifest.parent_backup_id is None
    assert {change.change_type for change in manifest.file_changes} == {
        FileChangeType.NEW
    }
    assert {change.current.path for change in manifest.file_changes} == set(
        current_files
    )


def test_build_manifest_detects_new_modified_and_deleted_files(
    tmp_path: Path, monkeypatch
) -> None:
    backup_id = uuid.uuid4()
    previous_files = {
        Path("unchanged.txt"): make_file_record("unchanged.txt", "SAME"),
        Path("modified.txt"): make_file_record("modified.txt", "OLD"),
        Path("deleted.txt"): make_file_record("deleted.txt", "DELETED"),
    }
    current_files = {
        Path("unchanged.txt"): make_file_record("unchanged.txt", "SAME"),
        Path("modified.txt"): make_file_record("modified.txt", "NEW"),
        Path("created.txt"): make_file_record("created.txt", "CREATED"),
    }
    existing_backup = SimpleNamespace(id=backup_id)
    builder = BackupManifestBuilder(SimpleNamespace())
    monkeypatch.setattr(builder, "_build_directory_manifest", lambda _: current_files)
    monkeypatch.setattr(
        builder, "_get_latest_backup_for_directory", lambda _: existing_backup
    )
    monkeypatch.setattr(builder, "_get_manifest_for_backup", lambda _: previous_files)

    manifest = builder.build_backup_manifest(tmp_path)

    changes = {
        (change.current or change.previous).path: change
        for change in manifest.file_changes
    }
    assert manifest.parent_backup_id == backup_id
    assert set(changes) == {
        Path("modified.txt"),
        Path("deleted.txt"),
        Path("created.txt"),
    }
    assert changes[Path("modified.txt")].change_type is FileChangeType.MODIFIED
    assert (
        changes[Path("modified.txt")].previous == previous_files[Path("modified.txt")]
    )
    assert changes[Path("modified.txt")].current == current_files[Path("modified.txt")]
    assert changes[Path("deleted.txt")].change_type is FileChangeType.DELETED
    assert changes[Path("deleted.txt")].current is None
    assert changes[Path("created.txt")].change_type is FileChangeType.NEW
    assert changes[Path("created.txt")].previous is None


def test_build_directory_manifest_reads_nested_files(tmp_path: Path) -> None:
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    (tmp_path / "one.txt").write_text("one", encoding="utf-8")
    (nested_dir / "two.txt").write_text("two", encoding="utf-8")

    manifest = BackupManifestBuilder._build_directory_manifest(tmp_path)

    assert set(manifest) == {Path("one.txt"), Path("nested/two.txt")}
    assert manifest[Path("one.txt")].filename == "one.txt"
    assert manifest[Path("one.txt")].size == 3
    assert manifest[Path("nested/two.txt")].filename == "two.txt"
    assert manifest[Path("nested/two.txt")].size == 3
