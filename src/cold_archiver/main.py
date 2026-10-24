import argparse

from cold_archiver.config import load_config


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

    args = arg_parser.parse_args()
    print(f"Config from {args.config}")
    config = load_config(args.config)

    print("Loaded config!")
    print(config.model_dump_json(indent=4))

    # perform_backup("AAAH")


if __name__ == "__main__":
    main()
