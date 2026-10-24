import sys
from types import SimpleNamespace

import cold_archiver.main


def test_main_initializes_config_and_runs_each_backup(monkeypatch) -> None:
    backups = [
        SimpleNamespace(local_path="/srv/photos", s3_prefix="photos"),
        SimpleNamespace(local_path="/srv/documents", s3_prefix="documents"),
    ]
    initialized_with = []
    backup_calls = []
    monkeypatch.setattr(
        cold_archiver.main,
        "initialize_config",
        lambda path: initialized_with.append(path) or SimpleNamespace(backups=backups),
    )
    monkeypatch.setattr(
        cold_archiver.main,
        "perform_backup",
        lambda local_path, prefix: backup_calls.append((local_path, prefix)),
    )
    monkeypatch.setattr(sys, "argv", ["cold-archiver", "--config", "/tmp/config.yaml"])

    cold_archiver.main.main()

    assert initialized_with == ["/tmp/config.yaml"]
    assert backup_calls == [
        ("/srv/photos", "photos"),
        ("/srv/documents", "documents"),
    ]


def test_main_skips_backup_when_no_targets(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cold_archiver.main,
        "initialize_config",
        lambda _: SimpleNamespace(backups=[]),
    )
    monkeypatch.setattr(
        cold_archiver.main,
        "perform_backup",
        lambda *_: raise_unexpected_backup_call(),
    )
    monkeypatch.setattr(sys, "argv", ["cold-archiver"])

    cold_archiver.main.main()

    assert capsys.readouterr().out == "No backup targets found.\n"


def raise_unexpected_backup_call() -> None:
    raise AssertionError("perform_backup should not have been called")
