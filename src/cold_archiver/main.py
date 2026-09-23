import argparse

from cold_archiver.backup import perform_backup


def main():
    arg_parser = argparse.ArgumentParser(
        description="Backup a directory to S3-compat storage"
    )

    arg_parser.add_argument("source", type=str, help="Directory to backup")

    args = arg_parser.parse_args()

    perform_backup(args.source)


if __name__ == "__main__":
    main()
