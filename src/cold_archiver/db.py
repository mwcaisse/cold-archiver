import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import URL, BigInteger, Engine, ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class ColdArchiverBase(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


class Backup(ColdArchiverBase):
    __tablename__ = "backup"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("backup.id"), nullable=True
    )
    sequence_number: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True
    )

    date_created: Mapped[datetime] = mapped_column(nullable=False, default=utc_now)


class BackupArchive(ColdArchiverBase):
    __tablename__ = "backup_archive"

    backup_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backup.id"), primary_key=True
    )

    sha256: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)


class BackupEntry(ColdArchiverBase):
    __tablename__ = "backup_entry"

    backup_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("backup.id"), primary_key=True
    )
    path: Mapped[str] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))

    # File attributes
    #   TODO: We could add in mode n such later too? but for now just created + modified are fine
    size: Mapped[int] = mapped_column(BigInteger)
    modified_ns: Mapped[int] = mapped_column(BigInteger)


def create_database_engine() -> Engine:
    engine = create_engine(
        URL.create(
            drivername="sqlite",
            database="backups.sqlite",
        )
    )

    # TODO: eventually use alembic, but for now / first pass this works fine
    ColdArchiverBase.metadata.create_all(engine)

    return engine


@contextmanager
def create_database_session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        yield session
