import logging

from tap import Tap

from .extract import ExtractCommand
from .list import ListCommand
from .spines import SpinesCommand

from .helpers import DECRYPTION_KEY, OLD_DECRYPTION_KEY


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

        # This is dirty, as it accesses subparser attributes directly
        # But Tap doesn't provide a way to access subparser attributes
        if self.version is not None and self.decrypt_key == DECRYPTION_KEY:
            version = tuple([int(x) for x in self.version.split('.')])
            if version <= (1, 21, 0):
                logging.info('Detected old version with new key, using old decryption key instead')
                self.decrypt_key = OLD_DECRYPTION_KEY
