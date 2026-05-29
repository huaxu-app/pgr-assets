from pgr_assets.commands.root import Args
from pgr_assets.logging_setup import configure_logging


def main() -> None:
    configure_logging()
    args = Args().parse_args()
    args.func(args)  # pyright: ignore[reportAttributeAccessIssue]  # func is set via Tap set_defaults


if __name__ == "__main__":
    main()
