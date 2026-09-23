from typing import NamedTuple


class DatabaseConfig(NamedTuple):
    database_file: str = "backups.sqlite"
