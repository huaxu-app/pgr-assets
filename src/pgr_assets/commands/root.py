import logging

from tap import Tap

from .extract import ExtractCommand
from .list import ListCommand
from .spines import SpinesCommand

class Args(Tap):
    log_level: str = None

    def configure(self) -> None:
        self.add_subparsers(required=True)
        self.add_subparser('list', ListCommand, help='List all available bundles')
        self.add_subparser('extract', ExtractCommand, help='Extracts all regular asset bundles')
        self.add_subparser('spines', SpinesCommand, help='Extracts all spine assets')

    def process_args(self):
        if self.log_level:
            logging.getLogger().setLevel(self.log_level.upper())
