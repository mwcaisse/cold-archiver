from pathlib import Path

import pytest
from pydantic import ValidationError

from cold_archiver.config import load_config, load_credentials, resolve_config_path


def write_credentials(credentials_path: Path) -> None:
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    credentials_path.write_text(
        "access_key: test-access-key\nsecret_key: test-secret-key\n",
        encoding="utf-8",
    )


def write_config(
    config_path: Path,
    *,
    credentials_path: str,
    database_path: str,
) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"""\
s3:
  endpoint: storage.example.com
  region: test-region
  bucket: test-bucket
  prefix: archives

credentials_path: "{credentials_path}"

database:
  path: "{database_path}"

backups:
  - local_path: /srv/photos
    s3_prefix: photos
  - local_path: /srv/documents
    s3_prefix: documents
""",
        encoding="utf-8",
    )


def test_load_config_parses_yaml_and_resolves_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "settings"
    config_path = config_dir / "config.yaml"
    credentials_path = config_dir / "secrets" / "credentials.yaml"
    write_credentials(credentials_path)
    write_config(
        config_path,
        credentials_path="secrets/credentials.yaml",
        database_path="data/backups.sqlite",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config("settings/config.yaml")

    assert config.s3.endpoint == "storage.example.com"
    assert config.s3.region == "test-region"
    assert config.s3.bucket == "test-bucket"
    assert config.s3.prefix == "archives"
    assert config.credentials_path == str(credentials_path.resolve())
    assert config.database.path == str((config_dir / "data/backups.sqlite").resolve())
    assert config.s3_credentials is not None
    assert config.s3_credentials.access_key == "test-access-key"
    assert config.s3_credentials.secret_key == "test-secret-key"
    assert [backup.local_path for backup in config.backups] == [
        "/srv/photos",
        "/srv/documents",
    ]
    assert [backup.s3_prefix for backup in config.backups] == [
        "photos",
        "documents",
    ]


def test_load_config_preserves_absolute_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    credentials_path = tmp_path / "absolute-secrets" / "credentials.yaml"
    database_path = tmp_path / "absolute-data" / "backups.sqlite"
    write_credentials(credentials_path)
    write_config(
        config_path,
        credentials_path=str(credentials_path),
        database_path=str(database_path),
    )

    config = load_config(str(config_path))

    assert config.credentials_path == str(credentials_path)
    assert config.database.path == str(database_path)


def test_load_credentials_parses_yaml(tmp_path: Path) -> None:
    credentials_path = tmp_path / "credentials.yaml"
    write_credentials(credentials_path)

    credentials = load_credentials(str(credentials_path))

    assert credentials.access_key == "test-access-key"
    assert credentials.secret_key == "test-secret-key"


def test_load_config_rejects_missing_required_sections(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """\
database:
  path: backups.sqlite
backups: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="s3"):
        load_config(str(config_path))


def test_resolve_config_path_normalizes_parent_segments(tmp_path: Path) -> None:
    base_path = tmp_path / "config" / "nested"

    resolved_path = resolve_config_path("../backups.sqlite", base_path)

    assert resolved_path == str((tmp_path / "config" / "backups.sqlite").resolve())
