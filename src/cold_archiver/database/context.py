from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import URL, Engine, PoolProxiedConnection, create_engine, event
from sqlalchemy.orm import Session

from cold_archiver.database.config import DatabaseConfig
from cold_archiver.database.models import ColdArchiverBase


def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    previous_autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True

    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    finally:
        dbapi_connection.autocommit = previous_autocommit


class DatabaseContext:
    def __init__(self, config: DatabaseConfig):
        self._config = config

        self._engine = self._create_engine()

    def _create_engine(self) -> Engine:
        engine = create_engine(
            URL.create(
                drivername="sqlite",
                database=self._config.database_file,
            )
        )

        event.listen(engine, "connect", enable_sqlite_foreign_keys)

        # TODO: eventually use alembic, but for now / first pass this works fine
        ColdArchiverBase.metadata.create_all(engine)

        return engine

    @contextmanager
    def create_session(self) -> Iterator[Session]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield session

    def raw_connection(self) -> PoolProxiedConnection:
        return self._engine.raw_connection()

    def close(self):
        self._engine.dispose()
