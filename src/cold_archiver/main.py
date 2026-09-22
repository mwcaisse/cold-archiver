import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from cold_archiver.config import load_config, load_credentials
from cold_archiver.object_store import ObjectStoreClient


@dataclass(frozen=True)
class FileRecord:
    path: str
    checksum: str
    last_modified: datetime

    def __json__(self):
        return {
            "path": self.path,
            "checksum": self.checksum,
            "last_modified": self.last_modified,
        }


def get_file_modified_date(file_path: str) -> datetime:
    path = Path(file_path)
    stat = path.stat()
    return datetime.fromtimestamp(stat.st_mtime, tz=UTC)


def get_file_checksum(file_path: str) -> str:
    with open(file_path, "rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest().upper()


def get_path_relative_to(file_path: str, base_path: str) -> str:
    base = Path(base_path)
    file = Path(file_path)
    return str(file.relative_to(base))


def build_directory_manifest(directory: str) -> dict[str, FileRecord]:
    results: dict[str, FileRecord] = {}

    for root, _, files in os.walk(directory):
        for filename in files:
            full_path = os.path.join(root, filename)
            relative_path = get_path_relative_to(full_path, directory)

            results[relative_path] = FileRecord(
                path=relative_path,
                checksum=get_file_checksum(full_path),
                last_modified=get_file_modified_date(full_path),
            )

    return results


def zip_directory(directory: str, manifest: dict[str, FileRecord], destination: str):
    """

    :param directory: The directory to zip
    :param manifest: The manifest of the files in the directory to zip
    :param destination: The destination of the zipfile
    """

    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in manifest:
            absolute_path = Path(os.path.join(directory, file_path))

            if not absolute_path.is_file():
                raise ValueError("Trying to archive something that is not a file!")

            archive.write(absolute_path, arcname=file_path)


def json_default_handler(val):
    if hasattr(val, "__json__"):
        return val.__json__()

    if isinstance(val, datetime):
        return val.isoformat()

    return TypeError(f"Cannot serialize {type(val).__name__}")


def append_hash_to_zip_file_name(file_name: str, sha: str) -> str:
    return file_name.replace(".zip", f"-{sha[:8]}.zip")


def upload_archive_to_object_store(archive_path: str):
    """
    Uploads
    :param archive_path:
    :return:
    """

    # TODO: load these elsewhere? but for now this works
    credentials = load_credentials("credentials.toml")
    config = load_config("config.toml")

    client = ObjectStoreClient(credentials=credentials, config=config)

    archive_hash = get_file_checksum(archive_path)
    object_store_file_name = append_hash_to_zip_file_name(
        os.path.basename(archive_path), archive_hash
    )

    hash_file_name = f"{object_store_file_name}.sha256"
    hash_file_contents = f"{archive_hash} {Path(archive_path).name}\n".encode()

    s3_archive_path = client.upload_file(
        archive_path, object_store_file_name, "application/zip"
    )
    client.upload_bytes(hash_file_contents, hash_file_name, "plain/text")

    print(f"Uploaded archive to {s3_archive_path}")


def main():
    arg_parser = argparse.ArgumentParser(
        description="Backup a directory to S3-compat storage"
    )

    arg_parser.add_argument("source", type=str, help="Directory to backup")

    args = arg_parser.parse_args()

    manifest = build_directory_manifest(args.source)

    print(json.dumps(manifest, indent=4, default=json_default_handler))

    current_time = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    destination_zip = os.path.join(args.source, f"backup-{current_time}.zip")
    zip_directory(args.source, manifest, destination_zip)

    zip_checksum = get_file_checksum(destination_zip)

    print(f"Created zip at {destination_zip}({zip_checksum})")

    upload_archive_to_object_store(destination_zip)


if __name__ == "__main__":
    main()
