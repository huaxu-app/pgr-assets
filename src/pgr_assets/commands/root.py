from typing import Optional

from tap import Tap

from pgr_assets.logging_setup import configure_logging
from .bundles import BundlesCommand
from .extract import ExtractCommand
from .list import ListCommand
from .spines import SpinesCommand


class Args(Tap):
    log_level: Optional[str] = None

    def __init__(self, *args, **kwargs):
        # Dashed flags across the whole CLI (--all-images, --log-level). Tap
        # propagates this to every subparser.
        kwargs.setdefault("underscores_to_dashes", True)
        super().__init__(*args, **kwargs)

    def configure(self) -> None:
        self.add_subparsers(required=True)
        self.add_subparser("list", ListCommand, help="List all available bundles")
        self.add_subparser(
            "extract", ExtractCommand, help="Extracts all regular asset bundles"
        )
        self.add_subparser("spines", SpinesCommand, help="Extracts all spine assets")
        self.add_subparser("bundles", BundlesCommand, help="Download bundles")

    def process_args(self):
        # Tap calls this automatically at the end of parse_args(), so --log-level
        # is applied for every subcommand; individual *_cmd functions must not
        # need to re-invoke it.
        if self.log_level:
            configure_logging(self.log_level)
