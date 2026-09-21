
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


def build_directory_manifest(directory: str) -> dict[str, FileRecord]:
    results: dict[str, FileRecord] = {}

    for root, _, files in os.walk(directory):
        for filename in files:
            full_path = os.path.join(root, filename)

            results[full_path] = FileRecord(
                path=full_path,
                checksum=get_file_checksum(full_path),
                last_modified=get_file_modified_date(full_path),
            )

    return results


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

if __name__ == "__main__":
    main()
