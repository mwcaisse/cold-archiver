import argparse

from cold_archiver.backup import perform_backup
from cold_archiver.config import initialize_config


def main():
    arg_parser = argparse.ArgumentParser(
        description="Backup a directory to S3-compat storage"
    )
    arg_parser.add_argument(
        "--config",
        type=str,
        help="Path to config file",
        default="/opt/cold-archiver/config.yaml",
    )
    arg_parser.add_argument(
        "--target",
        type=str,
        help="The target to backup. If not specified will backup all targets",
        default=None,
    )

    args = arg_parser.parse_args()
    config = initialize_config(args.config)

    if len(config.backups) == 0:
        print("No backup targets found.")
        return

    for backup in config.backups:
        if args.target is not None and backup.name.lower() != args.target.lower():
            continue

        perform_backup(backup.local_path, backup.s3_prefix)


if __name__ == "__main__":
    main()
