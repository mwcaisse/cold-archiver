
"""

Cold Archiver

* Want to upload a directory to S3 bucket/prefix path for archiving / backup
* On first run: all the files in the directory will be zipped up and uploaded
* It on later runs: It should only update files that are new or have changed
    * If no files have changed or been updated, then there are no changes

* Need to figure out how to handle deleted files
    * We don't want to modify a backup zip once it has been uploaded.
    * So deleting a file wouldn't remove it from the backup on S3
    * But we'd need a way to remove it from disc on restore / know it has been deleted

* We should have a command that can be used to restore the back up as well

"""
import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from zipfile import ZipFile, ZIP_DEFLATED


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
    return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)


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
        for file_path, file_record in manifest.items():
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


def main():
    arg_parser = argparse.ArgumentParser(
        description="Backup a directory to S3-compat storage"
    )

    arg_parser.add_argument("source", type=str, help="Directory to backup")

    args = arg_parser.parse_args()

    manifest = build_directory_manifest(args.source)

    print(json.dumps(manifest, indent=4, default=json_default_handler))

    current_time = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_zip = os.path.join(args.source, f"backup-{current_time}.zip")
    zip_directory(args.source, manifest, destination_zip)

    zip_checksum = get_file_checksum(destination_zip)

    print(f"Created zip at {destination_zip}({zip_checksum})")

if __name__ == "__main__":
    main()
