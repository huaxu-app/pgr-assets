from tap import Tap

from cmd.extract import ExtractCommand
from cmd.list import ListCommand


class Args(Tap):
    def configure(self) -> None:
        self.add_subparsers(required=True)
        self.add_subparser('list', ListCommand, help='List all available bundles')
        self.add_subparser('extract', ExtractCommand, help='Extracts all regular asset bundles')
