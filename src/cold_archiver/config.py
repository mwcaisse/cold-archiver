import tomllib
from typing import NamedTuple


class ObjectStoreCredentials(NamedTuple):
    access_key: str
    secret_key: str

class ObjectStoreConfiguration(NamedTuple):
    endpoint: str
    region: str
    bucket: str
    prefix: str | None


def load_config(config_file: str) -> ObjectStoreConfiguration:
    with open(config_file, "rb") as f:
        toml = tomllib.load(f)

    s3_config = toml["s3"]
    return ObjectStoreConfiguration(
        endpoint=s3_config["endpoint"],
        region=s3_config["region"],
        bucket=s3_config["bucket"],
        prefix=s3_config["prefix"],
    )


def load_credentials(credentials_file: str) -> ObjectStoreCredentials:
    with open(credentials_file, "rb") as f:
        toml = tomllib.load(f)

    return ObjectStoreCredentials(
        access_key=toml["access_key"],
        secret_key=toml["secret_key"],
    )

