import os
import sys
from typing import List

from .helpers import build_source_set, filter_bundles, highlight, BaseArgs


class ListCommand(BaseArgs):
    patterns: List[str]  # case-insensitive substring filters, AND-combined

    def configure(self) -> None:
        self.add_argument(
            "patterns",
            nargs="*",
            help="Only print bundles containing all of these (case-insensitive substring)",
        )
        self.set_defaults(func=list_cmd)


def list_cmd(args: ListCommand):
    ss = build_source_set(args).sources

    # Color matches only on a TTY (like grep --color=auto), so piping stays clean.
    use_color = bool(args.patterns) and sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    for bundle in filter_bundles(ss.list_all_bundles(), args.patterns):
        print(highlight(bundle, args.patterns) if use_color else bundle)
