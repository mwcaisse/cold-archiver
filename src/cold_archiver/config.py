from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource


class ObjectStoreCredentials(BaseSettings):
    model_config = SettingsConfigDict(yaml_file=None)

    access_key: str
    secret_key: str


class ObjectStoreConfiguration(BaseModel):
    endpoint: str
    region: str
    bucket: str
    prefix: str | None


class BackupDirectoryConfiguration(BaseModel):
    """
    Configures which folders you want to be backed up on your system
    """

    # Path to the local directory to backup
    local_path: str
    # Prefix of where to upload the backups to S3
    s3_prefix: str


class DatabaseConfiguration(BaseModel):
    path: str = "/opt/cold-archiver/database.sqlite"


class ColdArchiverConfiguration(BaseSettings):
    model_config = SettingsConfigDict(yaml_file=None)

    s3: ObjectStoreConfiguration = Field(alias="s3")
    database: DatabaseConfiguration = Field(alias="database")
    backups: list[BackupDirectoryConfiguration] = Field(alias="backups")

    credentials_path: str = "/opt/cold-archiver/credentials.yaml"
    s3_credentials: ObjectStoreCredentials | None = None


def load_config(config_file: str) -> ColdArchiverConfiguration:
    config_path = Path(config_file).expanduser().resolve()
    config_base_dir = config_path.parent

    source = YamlConfigSettingsSource(
        ColdArchiverConfiguration,
        yaml_file=config_path,
    )
    config = ColdArchiverConfiguration(**source())

    config.credentials_path = resolve_config_path(
        config.credentials_path, config_base_dir
    )
    config.database.path = resolve_config_path(config.database.path, config_base_dir)

    # load in s3 credentials
    config.s3_credentials = load_credentials(config.credentials_path)

    return config


def load_credentials(credentials_file: str) -> ObjectStoreCredentials:
    source = YamlConfigSettingsSource(
        ObjectStoreCredentials,
        yaml_file=credentials_file,
    )
    return ObjectStoreCredentials(**source())


def resolve_config_path(path: str, base_path: Path) -> str:
    """
    Takes the given path and resolves it to the given base_path
    :param path:
    :param base_path:
    :return:
    """
    path_path = Path(path).expanduser()
    if not path_path.is_absolute():
        path_path = base_path.joinpath(path_path)

    return str(path_path.resolve())
